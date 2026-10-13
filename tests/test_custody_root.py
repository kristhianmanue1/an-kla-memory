"""G3 R1a: custody root resolution, pointer and relocation receipts (ADR-0048)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import uuid

from an_kla.attest import attest_run, ensure_attest_files
from an_kla.canonical import canonical_json, digest_json
from an_kla.custody import (
    CustodyError,
    custody_fingerprint,
    pointer_path,
    read_pointer,
    resolve_store_root,
)
from an_kla.export_restore import create_export
from an_kla.hook_runs import mint_hook_run
from an_kla.identity import (
    IdentityError,
    adopt,
    identity_status,
    plan_adoption,
    read_binding,
)
from an_kla.identity_relocation import record_project_relocation
from an_kla.initialization import initialize_locked
from an_kla.store import MemoryStore, StoreError
from tests.test_identity import _authority, _proposal


def _commit_fact(store: MemoryStore, record_id: str) -> str:
    base = store.read_current()
    proposal = _proposal(base, record_id)
    authority = _authority(proposal)
    planning = store.plan_write(proposal, authority)
    return store.commit_write_plan(
        expected_current_hash=base,
        proposal=proposal,
        authority=authority,
        decision=planning["decision"],
        plan=planning["plan"],
    )["revision"]


def _tree(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))


class DefaultLayoutTests(unittest.TestCase):
    def test_default_custody_is_byte_compatible_project_local(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            store = MemoryStore(project)
            resolved = Path(project).resolve()
            self.assertEqual(store.store_root, resolved / ".an-kla")
            self.assertEqual(store.custody_walk_root, resolved)
            self.assertEqual(store.root, resolved / ".an-kla" / "memory")
            self.assertFalse(store.store_external)
            result = store.initialize_with_outcome()
            self.assertEqual(result["identity"]["identity_state"], "complete")
            self.assertTrue((resolved / ".an-kla" / "project-identity.json").exists())
            self.assertTrue((resolved / ".an-kla" / "attest.key").exists())
            self.assertFalse(pointer_path(project).exists())

    def test_store_root_inside_project_anchor_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            for bad in (
                Path(project) / ".an-kla" / "vault",
                Path(project),
                Path(project).parent,
            ):
                with self.assertRaisesRegex(StoreError, "store_root_invalid"):
                    MemoryStore(project, store_root=bad)


class ExternalCustodyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name).resolve()
        self.project = base / "project"
        self.project.mkdir()
        self.vault = base / "vaults" / "project-vault"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _init_external(self) -> MemoryStore:
        store = MemoryStore(self.project, store_root=self.vault)
        result = store.initialize_with_outcome()
        self.assertEqual(result["identity"]["identity_state"], "complete")
        return store

    def test_fresh_external_init_writes_identity_in_vault_and_pointer(self) -> None:
        store = self._init_external()
        self.assertTrue(store.store_external)
        self.assertTrue((self.vault / "project-identity.json").exists())
        self.assertTrue((self.vault / "memory" / "refs" / "CURRENT").exists())
        self.assertEqual(_tree(self.project / ".an-kla"), ["store-root.txt"])
        pointer = read_pointer(self.project)
        self.assertEqual(pointer["store_root"], str(self.vault))
        self.assertEqual(
            pointer["custody_fingerprint"], custody_fingerprint(read_binding(store))
        )
        self.assertNotIn(str(self.vault), pointer["custody_fingerprint"])
        self.assertTrue(store.verify()["ok"])
        self.assertEqual(identity_status(store)["identity_status"], "complete")

    def test_legacy_receipts_resolve_against_moved_custody_root(self) -> None:
        # H9: receipt paths say `.an-kla/...`; that prefix is the custody
        # root, so receipts minted project-local still verify after a move.
        local = MemoryStore(self.project)
        local.initialize()
        revision = local.read_current()
        self.vault.parent.mkdir(parents=True)
        shutil.move(str(self.project / ".an-kla"), str(self.vault))
        moved = MemoryStore(self.project, store_root=self.vault)
        self.assertEqual(identity_status(moved)["identity_status"], "complete")
        self.assertEqual(moved.read_current(), revision)
        self.assertTrue(moved.verify()["ok"])

    def test_external_init_creates_attest_material_in_vault(self) -> None:
        store = MemoryStore(self.project, store_root=self.vault)
        result = store.initialize_with_outcome()
        self.assertEqual(result["attestation"]["created"], ["attest.key", "attest-whitelist.json"])
        self.assertTrue((self.vault / "attest.key").exists())
        self.assertFalse((self.project / ".an-kla" / "attest.key").exists())

    def test_reinit_is_idempotent_and_keeps_pointer(self) -> None:
        store = self._init_external()
        first = store.read_current()
        pointer = pointer_path(self.project).read_bytes()
        again = MemoryStore(self.project, store_root=self.vault).initialize()
        self.assertEqual(again, first)
        self.assertEqual(pointer_path(self.project).read_bytes(), pointer)

    def test_pointer_resolution_opens_same_identity_and_revision(self) -> None:
        store = self._init_external()
        revision = _commit_fact(store, "f-external")
        resolution = resolve_store_root(self.project, environ={})
        self.assertEqual(resolution.source, "pointer")
        reopened = MemoryStore(self.project, store_root=resolution.store_root)
        self.assertEqual(reopened.read_current(), revision)
        self.assertEqual(
            read_binding(reopened)["store_identity"],
            read_binding(store)["store_identity"],
        )

    def test_precedence_flag_env_pointer_project_local(self) -> None:
        other = self.vault.parent / "other"
        self.assertEqual(
            resolve_store_root(self.project, environ={}).source, "project_local"
        )
        self._init_external()
        env = {"AN_KLA_STORE_ROOT": str(other)}
        self.assertEqual(resolve_store_root(self.project, environ=env).source, "env")
        flagged = resolve_store_root(self.project, self.vault, environ=env)
        self.assertEqual(flagged.source, "flag")
        self.assertEqual(flagged.store_root, self.vault)
        self.assertEqual(flagged.warnings, ("store_root_flag_env_divergence",))
        same = resolve_store_root(
            self.project, self.vault, environ={"AN_KLA_STORE_ROOT": str(self.vault)}
        )
        self.assertEqual(same.warnings, ())

    def test_pointer_blocks_project_local_init_without_twin(self) -> None:
        self._init_external()
        local = MemoryStore(self.project)
        with self.assertRaisesRegex(IdentityError, "store_root_divergence"):
            local.initialize()
        self.assertEqual(_tree(self.project / ".an-kla"), ["store-root.txt"])

    def test_pointer_blocks_fresh_vault_elsewhere(self) -> None:
        self._init_external()
        elsewhere = self.vault.parent / "twin"
        with self.assertRaisesRegex(IdentityError, "store_root_divergence"):
            MemoryStore(self.project, store_root=elsewhere).initialize()
        self.assertFalse((elsewhere / "memory").exists())

    def test_pointer_blocks_mutation_on_foreign_vault(self) -> None:
        self._init_external()
        foreign_project = self.vault.parent / "foreign-project"
        foreign_project.mkdir()
        foreign_vault = self.vault.parent / "foreign-vault"
        MemoryStore(foreign_project, store_root=foreign_vault).initialize()
        swapped = MemoryStore(self.project, store_root=foreign_vault)
        before = swapped.read_current()
        with self.assertRaisesRegex(IdentityError, "store_root_divergence"):
            _commit_fact(swapped, "f-wrong-vault")
        self.assertEqual(swapped.read_current(), before)

    def test_copied_project_local_twin_cannot_mutate(self) -> None:
        # Crash-like leftover: identity bytes match the pointer, but the
        # project-local root is never a valid custody once a pointer exists.
        store = self._init_external()
        shutil.copytree(self.vault, self.project / ".an-kla", dirs_exist_ok=True)
        local = MemoryStore(self.project)
        self.assertTrue(local.custody_pointer_present)
        self.assertEqual(
            custody_fingerprint(read_binding(local)),
            read_pointer(self.project)["custody_fingerprint"],
        )
        with self.assertRaises(StoreError) as caught:
            _commit_fact(local, "f-twin")
        self.assertIn("store_root_divergence", str(caught.exception))
        with self.assertRaisesRegex(CustodyError, "store_root_divergence"):
            local.snapshot()
        self.assertTrue(store.verify()["ok"])

    def test_moved_vault_with_matching_bytes_keeps_working(self) -> None:
        store = self._init_external()
        moved = self.vault.parent / "moved-vault"
        shutil.move(str(self.vault), str(moved))
        reopened = MemoryStore(self.project, store_root=moved)
        _commit_fact(reopened, "f-after-move")
        self.assertTrue(reopened.verify()["ok"])
        self.assertNotEqual(read_pointer(self.project)["store_root"], str(moved))
        del store

    def test_invalid_pointer_fails_closed(self) -> None:
        anchor = self.project / ".an-kla"
        anchor.mkdir()
        for payload in (
            b"not json",
            b'{"schema":"an-kla/store-root-pointer-v1"}',
            canonical_json(
                {
                    "schema": "an-kla/store-root-pointer-v1",
                    "store_root": "relative/path",
                    "custody_fingerprint": "sha256:" + "0" * 64,
                }
            ),
        ):
            pointer_path(self.project).write_bytes(payload)
            with self.assertRaisesRegex(CustodyError, "store_root_pointer_invalid"):
                resolve_store_root(self.project, environ={})
            with self.assertRaisesRegex(IdentityError, "store_root_pointer_invalid"):
                MemoryStore(self.project).initialize()
        self.assertFalse((anchor / "memory").exists())

    def test_symlinked_pointer_fails_closed(self) -> None:
        self._init_external()
        real = self.vault.parent / "pointer-copy.txt"
        shutil.copyfile(pointer_path(self.project), real)
        pointer_path(self.project).unlink()
        os.symlink(real, pointer_path(self.project))
        with self.assertRaisesRegex(CustodyError, "store_root_pointer_invalid"):
            resolve_store_root(self.project, environ={})

    def test_hostile_symlink_inside_vault_is_rejected(self) -> None:
        store = self._init_external()
        identity = self.vault / "memory" / "identity.json"
        copy = self.vault.parent / "identity-copy.json"
        shutil.copyfile(identity, copy)
        identity.unlink()
        os.symlink(copy, identity)
        with self.assertRaisesRegex(IdentityError, "store_identity_invalid"):
            read_binding(store)

    def test_symlinked_vault_receipts_are_not_followed(self) -> None:
        store = self._init_external()
        receipts = self.vault / "identity-receipts"
        outside = self.vault.parent / "receipts-outside"
        shutil.move(str(receipts), str(outside))
        os.symlink(outside, receipts)
        self.assertNotEqual(identity_status(store)["identity_status"], "complete")

    def test_custody_entries_use_vault_and_export_fails_closed(self) -> None:
        store = self._init_external()
        with self.assertRaisesRegex(CustodyError, "store_root_external_unsupported"):
            create_export(store, self.vault.parent / "bundle")
        self.assertFalse((self.vault.parent / "bundle").exists())
        minted = mint_hook_run(
            store,
            hook_id="pre-commit",
            trigger="before_task",
            action="status",
            exit_code=0,
            subject={"k": "v"},
        )
        self.assertTrue(
            (self.vault / "hook-runs" / "runs" / "sha256"
             / (minted["digest"].removeprefix("sha256:") + ".json")).exists()
        )
        receipt = attest_run(self.project, ["git", "diff"], store_root=self.vault)
        self.assertTrue(receipt["receipt_path"].startswith(".an-kla/receipts/"))
        self.assertTrue(
            (self.vault / receipt["receipt_path"].removeprefix(".an-kla/")).exists()
        )
        self.assertEqual(_tree(self.project / ".an-kla"), ["store-root.txt"])

    def test_custody_entries_refuse_a_disowned_vault(self) -> None:
        self._init_external()
        other_project = self.vault.parent / "other-project"
        other_project.mkdir()
        foreign = self.vault.parent / "foreign"
        MemoryStore(other_project, store_root=foreign).initialize()
        wrong = MemoryStore(self.project, store_root=foreign)
        with self.assertRaisesRegex(CustodyError, "store_root_divergence"):
            mint_hook_run(
                wrong, hook_id="pre-commit", trigger="before_task",
                action="status", exit_code=0, subject={},
            )
        with self.assertRaisesRegex(CustodyError, "store_root_divergence"):
            attest_run(self.project, ["true"], store_root=foreign)
        with self.assertRaisesRegex(CustodyError, "store_root_divergence"):
            ensure_attest_files(self.project)
        self.assertFalse((foreign / "hook-runs").exists())
        self.assertFalse((foreign / "receipts").exists())
        self.assertEqual(_tree(self.project / ".an-kla"), ["store-root.txt"])


class RelocationReceiptAdoptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name).resolve()
        self.original = base / "original"
        self.moved = base / "moved"
        self.original.mkdir()
        store = MemoryStore(self.original)
        store._make_layout()
        with store.write_lock():
            root, outcome = initialize_locked(store, transaction_id=str(uuid.uuid4()))
        assert root is not None and outcome["committed"] is True
        self.root = root
        self.plan = plan_adoption(store)
        shutil.move(str(self.original), str(self.moved))
        self.store = MemoryStore(self.moved)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_moved_project_without_receipt_fails_closed(self) -> None:
        with self.assertRaisesRegex(IdentityError, "identity_adoption_base_changed"):
            adopt(self.store, self.plan, self.root)
        self.assertEqual(
            identity_status(self.store)["identity_status"], "legacy_unadopted"
        )

    def test_recorded_relocation_allows_adoption(self) -> None:
        recorded = record_project_relocation(self.store, self.plan, self.root)
        receipt = recorded["relocation_receipt"]
        result = adopt(self.store, self.plan, self.root, receipt)
        self.assertEqual(result["identity_state"], "complete")
        self.assertTrue(self.store.verify()["ok"])
        self.assertTrue(self.store.verify()["root_relocated"])
        _commit_fact(self.store, "f-after-relocated-adoption")

    def test_receipt_for_another_plan_is_rejected(self) -> None:
        other = plan_adoption(self.store)
        receipt = record_project_relocation(self.store, self.plan, self.root)[
            "relocation_receipt"
        ]
        # `other` was observed at the new root: same-root plans refuse receipts.
        with self.assertRaisesRegex(IdentityError, "relocation_receipt_not_required"):
            adopt(self.store, other, self.root, receipt)
        forged = dict(self.plan)
        forged["store_identity"] = {
            **self.plan["store_identity"],
            "store_uuid": str(uuid.uuid4()),
        }
        core = {key: forged[key] for key in forged if key != "plan_fingerprint"}
        forged["plan_fingerprint"] = digest_json(core)
        with self.assertRaisesRegex(IdentityError, "relocation_receipt_mismatch"):
            adopt(self.store, forged, self.root, receipt)
        self.assertEqual(
            identity_status(self.store)["identity_status"], "legacy_unadopted"
        )

    def test_missing_or_tampered_receipt_is_rejected(self) -> None:
        with self.assertRaisesRegex(IdentityError, "relocation_receipt_missing"):
            adopt(self.store, self.plan, self.root, "sha256:" + "3" * 64)
        receipt = record_project_relocation(self.store, self.plan, self.root)[
            "relocation_receipt"
        ]
        path = (
            self.store.store_root
            / "relocation-receipts"
            / "sha256"
            / (receipt.removeprefix("sha256:") + ".json")
        )
        value = json.loads(path.read_bytes())
        value["to_root_observed"] = "/elsewhere"
        path.write_bytes(canonical_json(value))
        with self.assertRaisesRegex(IdentityError, "relocation_receipt_invalid"):
            adopt(self.store, self.plan, self.root, receipt)

    def test_relocation_receipt_travels_in_export(self) -> None:
        receipt = record_project_relocation(self.store, self.plan, self.root)[
            "relocation_receipt"
        ]
        adopt(self.store, self.plan, self.root, receipt)
        bundle = self.moved.parent / "bundle"
        create_export(self.store, bundle)
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        names = {entry["path"] for entry in manifest["core"]["entries"]}
        self.assertIn(
            "anchor/relocation-receipts/sha256/"
            + receipt.removeprefix("sha256:") + ".json",
            names,
        )

    def test_symlinked_receipt_directory_is_rejected(self) -> None:
        receipt = record_project_relocation(self.store, self.plan, self.root)[
            "relocation_receipt"
        ]
        directory = self.store.store_root / "relocation-receipts"
        outside = self.moved.parent / "outside-receipts"
        shutil.move(str(directory), str(outside))
        os.symlink(outside, directory)
        with self.assertRaisesRegex(IdentityError, "relocation_receipt_invalid"):
            adopt(self.store, self.plan, self.root, receipt)

    def test_receipt_requires_exact_current(self) -> None:
        with self.assertRaisesRegex(IdentityError, "identity_adoption_base_changed"):
            record_project_relocation(self.store, self.plan, "sha256:" + "4" * 64)

    def test_same_root_plan_needs_no_receipt(self) -> None:
        plan = plan_adoption(self.store)
        with self.assertRaisesRegex(IdentityError, "relocation_receipt_not_required"):
            record_project_relocation(self.store, plan, self.root)
        self.assertEqual(adopt(self.store, plan, self.root)["identity_state"], "complete")


if __name__ == "__main__":
    unittest.main()
