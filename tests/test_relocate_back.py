"""G3 R2b: relocate-back by subtree, roundtrip and recovery after the
checkout is recreated (ADR-0048 §3.5-6)."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from an_kla import relocate
from an_kla.canonical import digest_bytes
from an_kla.export_restore import create_export
from an_kla.custody import CustodyError, custody_fingerprint, pointer_path, read_pointer
from an_kla.identity import IdentityError, read_binding
from an_kla.relocation_receipts import chain_head, load_relocation_receipt
from an_kla.relocate import (
    RelocateError, SimulatedCrash, commit_relocation, plan_relocation, reconcile_relocation,
)
from an_kla.relocate_back import plan_back
from an_kla.startup import startup_diagnostic
from an_kla.store import MemoryStore
from tests.test_custody_root import _commit_fact


def _crash_at(point: str):
    def fault(name: str) -> None:
        if name == point:
            raise SimulatedCrash(name)

    return fault


class RelocateBackTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name).resolve()
        self.project = self.base / "project"
        self.project.mkdir()
        self.vault = self.base / "vaults" / "vault"
        local = MemoryStore(self.project)
        local.initialize()
        _commit_fact(local, "f-local")
        self.context = self.project / ".an-kla" / "context" / "note.txt"
        self.context.parent.mkdir(parents=True, exist_ok=True)
        self.context.write_bytes(b"project-side")
        plan = plan_relocation(local, self.vault)
        commit_relocation(local, plan, plan["core"]["base_revision"])
        self.external = MemoryStore(self.project, store_root=self.vault)
        self.revision = _commit_fact(self.external, "f-external")
        self.fingerprint = custody_fingerprint(read_binding(self.external))
        self.addCleanup(setattr, relocate, "_fault", None)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _back(self) -> dict:
        return plan_back(self.external)

    def _assert_back(self, result: dict, plan: dict) -> None:
        self.assertEqual(result["stage"], "cleaned")
        self.assertIsNone(read_pointer(self.project))
        local = MemoryStore(self.project)
        self.assertEqual(local.verify()["revision"], self.revision)
        self.assertEqual(custody_fingerprint(read_binding(local)), self.fingerprint)
        anchor = self.project / ".an-kla"
        for entry in plan["core"]["entries"]:
            relative = entry["path"].removeprefix("anchor/")
            self.assertEqual(digest_bytes((anchor / relative).read_bytes()), entry["content_sha256"])
            self.assertFalse((self.vault / relative).exists(), relative)
        self.assertEqual(self.context.read_bytes(), b"project-side")
        head = chain_head(local, read_binding(local)["store_identity"], "store_root")
        receipt = load_relocation_receipt(local, head)
        self.assertEqual(receipt["to_root_observed"], str(anchor))
        self.assertEqual(receipt["from_root_observed"], str(self.vault))
        self.assertIsNotNone(receipt["predecessor_receipt"])
        self.assertFalse(any(path.name.startswith(".an-kla.staging-") for path in self.project.iterdir()))

    def _assert_still_external(self) -> None:
        self.assertEqual(read_pointer(self.project)["custody_fingerprint"], self.fingerprint)
        self.assertEqual(self.external.verify()["revision"], self.revision)
        anchor = self.project / ".an-kla"
        for gone in ("project-identity.json", "memory/refs", "attest.key", "relocation-receipts"):
            self.assertFalse((anchor / gone).exists(), gone)

    def test_roundtrip_back_and_forth_keeps_bytes_identity_and_receipts(self) -> None:
        plan = self._back()
        self.assertEqual(plan["core"]["direction"], "external_to_project_local")
        result = commit_relocation(self.external, plan, self.revision)
        self._assert_back(result, plan)
        replay = commit_relocation(MemoryStore(self.project), plan, self.revision)
        self.assertTrue(replay["replayed"])
        local = MemoryStore(self.project)
        # Back in the project, plain export works again (journals excluded,
        # relocation receipts travel with the vault).
        exported = create_export(local, self.base / "bundle")
        self.assertEqual(exported["current_revision"], self.revision)
        manifest = json.loads((self.base / "bundle" / "manifest.json").read_bytes())
        paths = {entry["path"] for entry in manifest["core"]["entries"]}
        self.assertTrue(any(path.startswith("anchor/relocation-receipts/") for path in paths))
        after = _commit_fact(local, "f-back")
        # The emptied vault keeps only lock files: going out again needs a
        # fresh destination (rename_noreplace never reuses a directory).
        self.assertEqual(result["cleanup"]["residue"], [])
        second = self.base / "vaults" / "second"
        again = plan_relocation(local, second)
        forward = commit_relocation(local, again, after)
        self.assertEqual(forward["stage"], "cleaned")
        receipt = load_relocation_receipt(
            MemoryStore(self.project, store_root=second), forward["relocation_receipt"]
        )
        self.assertEqual(receipt["from_root_observed"], str(self.project / ".an-kla"))

    def test_occupied_destination_fails_closed(self) -> None:
        late = self.project / ".an-kla" / "relocation-receipts"
        late.mkdir()
        with self.assertRaises(RelocateError) as caught:
            self._back()
        self.assertEqual(str(caught.exception), "relocate_destination_occupied")
        late.rmdir()
        plan = self._back()
        late.mkdir()
        (late / "x").write_bytes(b"x")
        with self.assertRaises(RelocateError) as caught:
            commit_relocation(self.external, plan, self.revision)
        self.assertEqual(str(caught.exception), "relocate_destination_occupied")
        self.assertEqual((late / "x").read_bytes(), b"x")
        shutil.rmtree(late)
        self._assert_still_external()

    def test_crash_between_subtrees_rolls_forward_or_aborts(self) -> None:
        for abort in (False, True):
            with self.subTest(abort=abort):
                self.tearDown()
                self.setUp()
                plan = self._back()
                relocate._fault = _crash_at("published:memory/refs")
                with self.assertRaises(SimulatedCrash):
                    commit_relocation(self.external, plan, self.revision)
                relocate._fault = None
                # Some subtrees are already in the project, the pointer still
                # names the vault: reads keep going to the vault.
                self.assertTrue((self.project / ".an-kla" / "memory" / "refs").exists())
                self.assertEqual(self.external.verify()["revision"], self.revision)
                txid = plan["core"]["transaction_id"]
                result = reconcile_relocation(self.project, txid, abort=abort)
                if abort:
                    self.assertEqual(result["stage"], "aborted")
                    self._assert_still_external()
                else:
                    self._assert_back(result, plan)

    def test_crash_after_pointer_removal_only_rolls_forward(self) -> None:
        plan = self._back()
        relocate._fault = _crash_at("after_pointer")
        with self.assertRaises(SimulatedCrash):
            commit_relocation(self.external, plan, self.revision)
        relocate._fault = None
        txid = plan["core"]["transaction_id"]
        with self.assertRaises(RelocateError) as caught:
            reconcile_relocation(self.project, txid, abort=True)
        self.assertEqual(str(caught.exception), "relocate_abort_too_late")
        self._assert_back(reconcile_relocation(self.project, txid), plan)

    def test_recreated_checkout_recovers_the_vault_without_a_new_store(self) -> None:
        shutil.rmtree(self.project)
        self.project.mkdir()
        bare = startup_diagnostic(MemoryStore(self.project))
        self.assertEqual(bare["store_presence"], "absent")
        self.assertFalse((self.project / ".an-kla").exists())
        recovered = MemoryStore(self.project, store_root=self.vault)
        self.assertEqual(recovered.initialize(), self.revision)
        self.assertEqual(read_pointer(self.project)["custody_fingerprint"], self.fingerprint)
        self.assertEqual(MemoryStore(self.project, store_root=self.vault).verify()["revision"], self.revision)

        # Negative: a pointer naming another project's vault never resolves
        # to it for writes.
        other = self.base / "other"
        other.mkdir()
        foreign_root = self.base / "foreign"
        MemoryStore(other, store_root=foreign_root).initialize()
        foreign = MemoryStore(self.project, store_root=foreign_root)
        with self.assertRaises((CustodyError, IdentityError)) as caught:
            _commit_fact(foreign, "f-foreign")
        self.assertEqual(str(caught.exception), "store_root_divergence")

    def test_external_init_never_forks_a_project_local_vault(self) -> None:
        project = self.base / "local-only"
        project.mkdir()
        MemoryStore(project).initialize()
        twin_root = self.base / "twin"
        with self.assertRaises(CustodyError) as caught:
            MemoryStore(project, store_root=twin_root).initialize()
        self.assertEqual(str(caught.exception), "store_root_divergence")
        self.assertFalse((twin_root / "project-identity.json").exists())
        self.assertFalse(pointer_path(project).exists())

    def test_after_commit_point_the_external_copy_is_inert_and_local_may_advance(self) -> None:
        # Adversarial round M1/M2: crash after the pointer is removed.
        plan = self._back()
        relocate._fault = _crash_at("after_pointer")
        with self.assertRaises(SimulatedCrash):
            commit_relocation(self.external, plan, self.revision)
        relocate._fault = None
        stale = MemoryStore(self.project, store_root=self.vault)
        with self.assertRaises((CustodyError, IdentityError)) as caught:
            _commit_fact(stale, "f-stale-external")
        self.assertEqual(str(caught.exception), "store_root_divergence")
        local = MemoryStore(self.project)
        self.assertEqual(local.doctor()["custody_divergence"]["relocations_unfinished"], 1)
        self.revision = _commit_fact(local, "f-local-after-commit")
        result = reconcile_relocation(self.project, plan["core"]["transaction_id"])
        self.assertEqual(result["stage"], "cleaned")
        self.assertEqual(result["cleanup"]["changed_kept"], [])
        self.assertEqual(MemoryStore(self.project).verify()["revision"], self.revision)
        self.assertFalse((self.vault / "memory" / "refs" / "CURRENT").exists())

    def test_init_never_binds_another_projects_vault(self) -> None:
        # Adversarial round M3: --store-root init over a foreign vault.
        other = self.base / "other"
        other.mkdir()
        with self.assertRaises(CustodyError) as caught:
            MemoryStore(other, store_root=self.vault).initialize()
        self.assertEqual(str(caught.exception), "store_root_project_mismatch")
        self.assertFalse(pointer_path(other).exists())
        self.assertEqual(self.external.verify()["revision"], self.revision)


if __name__ == "__main__":
    unittest.main()
