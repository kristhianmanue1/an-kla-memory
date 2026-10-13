"""Regressions from the beta.30 release adversarial rounds (reviewer: Muse
CLI, a different model family).  H-01..H-04 (round 1), N-01..N-03
(round 2) and R3-02..R3-04 (round 3) reproduce its findings."""

from __future__ import annotations

import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from an_kla import relocate
from an_kla.canonical import canonical_json
from an_kla.custody import CustodyError, read_pointer
from an_kla.identity import IdentityError, read_binding
from an_kla.relocate import (
    RelocateError, SimulatedCrash, commit_relocation, plan_relocation, reconcile_relocation,
)
from an_kla.relocate_back import plan_back
from an_kla.relocate_attach import AttachError, attach_store, bound_project_root
from an_kla.store import MemoryStore
from an_kla.store_resolution import open_resolved_store
from an_kla.stores_scan import scan
from tests.test_custody_root import _commit_fact


def _fault_at(point: str):
    def fault(name: str) -> None:
        if name == point:
            raise SimulatedCrash(name)

    return fault


class CopiedVaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name).resolve()
        self.project = self.base / "project"
        self.project.mkdir()
        self.vault_a = self.base / "vaults" / "a"
        self.vault_b = self.base / "vaults" / "b"
        created = MemoryStore(self.project, store_root=self.vault_a)
        created.initialize()
        self.revision = _commit_fact(created, "f-a")

    def test_h01_copy_opened_by_flag_cannot_write_while_original_lives(self) -> None:
        shutil.copytree(self.vault_a, self.vault_b)
        copy = MemoryStore(self.project, store_root=self.vault_b)
        with self.assertRaises((CustodyError, IdentityError)) as caught:
            _commit_fact(copy, "f-b")
        self.assertEqual(str(caught.exception), "store_root_divergence")
        self.assertEqual(_commit_fact(MemoryStore(self.project, store_root=self.vault_a), "f-a2")[:7], "sha256:")
        warnings = io.StringIO()
        open_resolved_store(self.project, flag=str(self.vault_b), warnings=warnings, environ={})
        self.assertIn("pointer_stale_locator", warnings.getvalue())

    def test_h01_positive_control_moved_vault_stays_writable(self) -> None:
        # A stale locator (vault moved, nothing left at the old path) is the
        # legitimate case the H-01 check must not break.
        os.rename(self.vault_a, self.vault_b)
        moved = MemoryStore(self.project, store_root=self.vault_b)
        revision = _commit_fact(moved, "f-moved")
        result = attach_store(MemoryStore(self.project, store_root=self.vault_b), revision)
        self.assertTrue(result["replayed"])
        self.assertEqual(read_pointer(self.project)["store_root"], str(self.vault_b))
        self.assertEqual(open_resolved_store(self.project, environ={}).verify()["revision"], revision)

    def test_h02_attach_replay_needs_exact_current_and_live_locator(self) -> None:
        with self.assertRaises(AttachError) as caught:
            attach_store(MemoryStore(self.project, store_root=self.vault_a), "sha256:" + "0" * 64)
        self.assertEqual(str(caught.exception), "relocate_attach_base_changed")
        shutil.copytree(self.vault_a, self.vault_b)
        before = read_pointer(self.project)
        with self.assertRaises((AttachError, CustodyError, IdentityError)) as caught:
            attach_store(MemoryStore(self.project, store_root=self.vault_b), self.revision)
        self.assertEqual(str(caught.exception), "store_root_divergence")
        self.assertEqual(read_pointer(self.project), before)


class AttachRoundTwoTests(unittest.TestCase):
    """Round 2 (N-01..N-03): attach and the locator check, with controls."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name).resolve()
        self.p1 = self.base / "p1"
        self.p2 = self.base / "p2"
        self.p1.mkdir()
        self.p2.mkdir()
        self.vault_a = self.base / "vaults" / "a"
        self.vault_b = self.base / "vaults" / "b"
        created = MemoryStore(self.p1, store_root=self.vault_a)
        created.initialize()
        self.revision = _commit_fact(created, "f-a")

    def test_n01_attach_copy_refused_while_old_checkout_holds_original(self) -> None:
        shutil.copytree(self.vault_a, self.vault_b)
        with self.assertRaises(AttachError) as caught:
            attach_store(MemoryStore(self.p2, store_root=self.vault_b), self.revision)
        self.assertEqual(str(caught.exception), "relocate_attach_source_live")
        self.assertIsNone(read_pointer(self.p2))
        self.assertFalse((self.vault_b / "relocation-receipts").exists())

    def test_n01_positive_control_old_checkout_gone(self) -> None:
        # The legitimate re-clone: the old checkout (and its pointer) is gone.
        shutil.copytree(self.vault_a, self.vault_b)
        shutil.rmtree(self.p1)
        result = attach_store(MemoryStore(self.p2, store_root=self.vault_b), self.revision)
        self.assertFalse(result["replayed"])
        self.assertIsNotNone(result["relocation_receipt"])
        self.assertEqual(read_pointer(self.p2)["store_root"], str(self.vault_b))

    def test_n02_copied_pointer_is_not_a_replay(self) -> None:
        (self.p2 / ".an-kla").mkdir()
        shutil.copy(self.p1 / ".an-kla" / "store-root.txt", self.p2 / ".an-kla" / "store-root.txt")
        store = MemoryStore(self.p2, store_root=self.vault_a)
        result = attach_store(store, self.revision)
        self.assertFalse(result["replayed"])
        self.assertIsNotNone(result["relocation_receipt"])
        self.assertEqual(bound_project_root(store, read_binding(store)), str(self.p2))
        again = attach_store(MemoryStore(self.p2, store_root=self.vault_a), self.revision)
        self.assertTrue(again["replayed"])
        self.assertIsNone(again["relocation_receipt"])

    def test_n03_locator_spelled_with_dotdot_is_the_same_vault(self) -> None:
        pointer = read_pointer(self.p1)
        alias = str(self.vault_a / ".." / "a")
        (self.p1 / ".an-kla" / "store-root.txt").write_bytes(canonical_json({**pointer, "store_root": alias}))
        self.assertEqual(_commit_fact(MemoryStore(self.p1, store_root=self.vault_a), "f-a2")[:7], "sha256:")
        warnings = io.StringIO()
        open_resolved_store(self.p1, warnings=warnings, environ={})
        self.assertNotIn("pointer_stale_locator", warnings.getvalue())
        # Control: a real copy at another path is still refused (H-01).
        shutil.copytree(self.vault_a, self.vault_b)
        with self.assertRaises((CustodyError, IdentityError)):
            _commit_fact(MemoryStore(self.p1, store_root=self.vault_b), "f-b")


def _crash_before_journal(stage: str):
    """Process death after a stage's filesystem change, before its journal."""

    original = relocate._write_journal

    def write(project_root, journal, name):
        if name == stage:
            raise SimulatedCrash(stage)
        return original(project_root, journal, name)

    return mock.patch.object(relocate, "_write_journal", side_effect=write)


class RoundThreeTests(unittest.TestCase):
    """Round 3 (R3-02..R3-04): abort after the commit point, FIFO in scan."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name).resolve()
        self.project = self.base / "project"
        self.project.mkdir()
        self.vault = self.base / "vault"

    def _local(self) -> tuple[MemoryStore, str]:
        local = MemoryStore(self.project)
        local.initialize()
        return local, _commit_fact(local, "f-local")

    def test_r3_02_abort_after_pointer_before_journal_is_too_late(self) -> None:
        local, revision = self._local()
        plan = plan_relocation(local, self.vault)
        with _crash_before_journal("pointer_written"):
            with self.assertRaises(SimulatedCrash):
                commit_relocation(local, plan, revision)
        txid = plan["core"]["transaction_id"]
        with self.assertRaises(RelocateError) as caught:
            reconcile_relocation(self.project, txid, abort=True)
        self.assertEqual(str(caught.exception), "relocate_abort_too_late")
        self.assertTrue((self.vault / "memory" / "refs" / "CURRENT").is_file())
        self.assertEqual(reconcile_relocation(self.project, txid)["stage"], "cleaned")
        self.assertEqual(open_resolved_store(self.project, environ={}).verify()["revision"], revision)

    def test_r3_02_positive_control_abort_before_pointer_still_aborts(self) -> None:
        local, revision = self._local()
        plan = plan_relocation(local, self.vault)
        relocate._fault = _fault_at("after_publish")
        try:
            with self.assertRaises(SimulatedCrash):
                commit_relocation(local, plan, revision)
        finally:
            relocate._fault = None
        txid = plan["core"]["transaction_id"]
        self.assertEqual(reconcile_relocation(self.project, txid, abort=True)["stage"], "aborted")
        self.assertFalse(self.vault.exists())
        self.assertEqual(MemoryStore(self.project).verify()["revision"], revision)

    def test_r3_03_back_abort_after_pointer_removal_is_too_late(self) -> None:
        local, revision = self._local()
        plan = plan_relocation(local, self.vault)
        commit_relocation(local, plan, revision)
        external = MemoryStore(self.project, store_root=self.vault)
        revision = _commit_fact(external, "f-external")
        back = plan_back(external)
        with _crash_before_journal("pointer_removed"):
            with self.assertRaises(SimulatedCrash):
                commit_relocation(external, back, revision)
        txid = back["core"]["transaction_id"]
        with self.assertRaises(RelocateError) as caught:
            reconcile_relocation(self.project, txid, abort=True)
        self.assertEqual(str(caught.exception), "relocate_abort_too_late")
        self.assertEqual(reconcile_relocation(self.project, txid)["stage"], "cleaned")
        self.assertEqual(MemoryStore(self.project).verify()["revision"], revision)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "needs mkfifo")
    def test_r3_04_scan_never_blocks_on_a_fifo(self) -> None:
        MemoryStore(self.project, store_root=self.vault).initialize()
        root = self.base / "scanroot"
        anchor = root / "proj" / ".an-kla"
        (anchor / "memory" / "refs").mkdir(parents=True)
        shutil.copy(self.vault / "project-identity.json", anchor / "project-identity.json")
        shutil.copy(self.vault / "memory" / "identity.json", anchor / "memory" / "identity.json")
        os.mkfifo(anchor / "memory" / "refs" / "CURRENT")
        result = scan([root])
        self.assertEqual(result["counts"]["unreadable"], 1)
        self.assertEqual(result["entries"][0]["code"], "non_regular_file_in_vault")


class LongLivedSnapshotTests(unittest.TestCase):
    def test_h03_explicit_revision_snapshot_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            project = base / "project"
            project.mkdir()
            local = MemoryStore(project)
            local.initialize()
            revision = _commit_fact(local, "f-local")
            long_lived = MemoryStore(project)
            plan = plan_relocation(local, base / "vault")

            def fault(name: str) -> None:
                if name == "after_pointer":
                    raise SimulatedCrash(name)

            relocate._fault = fault
            try:
                with self.assertRaises(SimulatedCrash):
                    commit_relocation(local, plan, revision)
            finally:
                relocate._fault = None
            with self.assertRaises(CustodyError) as caught:
                long_lived.snapshot(revision)
            self.assertEqual(str(caught.exception), "store_root_divergence")


class ScanSymlinkTests(unittest.TestCase):
    def test_h04_scan_never_reads_through_a_symlinked_component(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            project = base / "p0"
            project.mkdir()
            outside = base / "outside-vault"
            MemoryStore(project, store_root=outside).initialize()
            root = base / "scanroot"
            anchor = root / "proj" / ".an-kla"
            anchor.mkdir(parents=True)
            shutil.copy(outside / "project-identity.json", anchor / "project-identity.json")
            os.symlink(outside / "memory", anchor / "memory")
            result = scan([root])
            self.assertEqual(result["counts"]["active"], 0)
            self.assertEqual(result["counts"]["unreadable"], 1)
            self.assertEqual(result["entries"][0]["code"], "symlink_in_vault")
            self.assertIsNone(result["entries"][0]["custody_fingerprint"])


if __name__ == "__main__":
    unittest.main()
