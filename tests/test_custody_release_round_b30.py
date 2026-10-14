"""Regressions from the beta.30 release adversarial rounds (reviewer: Muse
CLI, a different model family).  H-01..H-04 (round 1), N-01..N-03
(round 2), R3-02..R3-04 (round 3), R4-01..R4-02 (round 4) and
R5-01..R5-03 (round 5, Muse), R6-01..R6-03 (round 6) and R7-01 (round 7,
both opencode with GLM 5.3) reproduce their findings."""

from __future__ import annotations

import contextlib
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
    RelocateError, SimulatedCrash, commit_relocation, inspect_relocation, plan_relocation,
    reconcile_relocation, unfinished_relocations,
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


class _VaultCase(unittest.TestCase):
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


class RoundThreeTests(_VaultCase):
    """Round 3 (R3-02..R3-04): abort after the commit point, FIFO in scan."""

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

    def test_r4_01_reconcile_finishes_after_the_live_vault_advanced(self) -> None:
        local, revision = self._local()
        plan = plan_relocation(local, self.vault)
        with _crash_before_journal("pointer_written"):
            with self.assertRaises(SimulatedCrash):
                commit_relocation(local, plan, revision)
        advanced = _commit_fact(MemoryStore(self.project, store_root=self.vault), "f-live")
        txid = plan["core"]["transaction_id"]
        self.assertEqual(reconcile_relocation(self.project, txid)["stage"], "cleaned")
        self.assertEqual(open_resolved_store(self.project, environ={}).verify()["revision"], advanced)
        external = MemoryStore(self.project, store_root=self.vault)
        back = plan_back(external)
        with _crash_before_journal("pointer_removed"):
            with self.assertRaises(SimulatedCrash):
                commit_relocation(external, back, advanced)
        local_advanced = _commit_fact(MemoryStore(self.project), "f-local-live")
        back_txid = back["core"]["transaction_id"]
        self.assertEqual(reconcile_relocation(self.project, back_txid)["stage"], "cleaned")
        self.assertEqual(MemoryStore(self.project).verify()["revision"], local_advanced)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "needs mkfifo")
    def test_r4_02_scan_never_blocks_on_a_fifo_receipt(self) -> None:
        MemoryStore(self.project, store_root=self.vault).initialize()
        receipts = self.vault / "relocation-receipts" / "sha256"
        receipts.mkdir(parents=True, exist_ok=True)
        os.mkfifo(receipts / ("0" * 64 + ".json"))
        result = scan([self.base])
        codes = [entry.get("code") for entry in result["entries"]]
        self.assertIn("relocation_receipt_chain_invalid", codes)


def _crash_on_second(stage: str):
    """Process death on the second journal write of ``stage``."""

    original = relocate._write_journal
    seen = []

    def write(project_root, journal, name):
        if name == stage:
            seen.append(name)
            if len(seen) == 2:
                raise SimulatedCrash(stage)
        return original(project_root, journal, name)

    return mock.patch.object(relocate, "_write_journal", side_effect=write)


class RoundFiveTests(_VaultCase):
    """Round 5 (R5-01..R5-03): a pointer this transaction did not write or
    remove is not its commit point; a non-directory receipts tree."""

    def _point_pointer_at(self, store_root: Path) -> None:
        pointer = read_pointer(self.project)
        (self.project / ".an-kla" / "store-root.txt").write_bytes(
            canonical_json({**pointer, "store_root": str(store_root)})
        )

    def test_r5_01_foreign_locator_with_same_custody_fails_closed(self) -> None:
        local, revision = self._local()
        plan = plan_relocation(local, self.vault)
        with _crash_before_journal("pointer_written"):
            with self.assertRaises(SimulatedCrash):
                commit_relocation(local, plan, revision)
        copy = self.base / "copy"
        shutil.copytree(self.vault, copy)
        self._point_pointer_at(copy)
        txid = plan["core"]["transaction_id"]
        with self.assertRaises(RelocateError) as caught:
            reconcile_relocation(self.project, txid)
        self.assertEqual(str(caught.exception), "relocate_pointer_unrecognized")
        self.assertTrue((self.project / ".an-kla" / "memory" / "refs" / "CURRENT").exists())
        self.assertTrue((self.vault / "memory" / "refs" / "CURRENT").exists())

    def test_r5_01_positive_control_locator_spelled_differently(self) -> None:
        local, revision = self._local()
        plan = plan_relocation(local, self.vault)
        with _crash_before_journal("pointer_written"):
            with self.assertRaises(SimulatedCrash):
                commit_relocation(local, plan, revision)
        self._point_pointer_at(self.base / "project" / ".." / "vault")
        txid = plan["core"]["transaction_id"]
        self.assertEqual(reconcile_relocation(self.project, txid)["stage"], "cleaned")

    def _crashed_back(self) -> tuple[MemoryStore, str]:
        local, revision = self._local()
        commit_relocation(local, plan_relocation(local, self.vault), revision)
        external = MemoryStore(self.project, store_root=self.vault)
        return external, plan_back(external)

    def test_r5_02_pointer_removed_by_hand_is_not_the_commit_point(self) -> None:
        external, back = self._crashed_back()
        revision = external.verify()["revision"]
        with _crash_on_second("published"):
            with self.assertRaises(SimulatedCrash):
                commit_relocation(external, back, revision)
        (self.project / ".an-kla" / "store-root.txt").unlink()
        txid = back["core"]["transaction_id"]
        with self.assertRaises(RelocateError) as caught:
            reconcile_relocation(self.project, txid)
        self.assertEqual(str(caught.exception), "relocate_pointer_unrecognized")
        self.assertTrue((self.vault / "memory" / "refs" / "CURRENT").exists())

    def test_r5_02_positive_control_crash_before_removal_finishes(self) -> None:
        external, back = self._crashed_back()
        revision = external.verify()["revision"]
        relocate._fault = _fault_at("before_pointer_removal")
        try:
            with self.assertRaises(SimulatedCrash):
                commit_relocation(external, back, revision)
        finally:
            relocate._fault = None
        self.assertIsNotNone(read_pointer(self.project))
        txid = back["core"]["transaction_id"]
        self.assertEqual(reconcile_relocation(self.project, txid)["stage"], "cleaned")
        self.assertIsNone(read_pointer(self.project))

    def _scan_codes_with(self, make) -> list:
        MemoryStore(self.project, store_root=self.vault).initialize()
        make(self.vault / "relocation-receipts")
        return [entry.get("code") for entry in scan([self.base])["entries"]]

    def test_r5_03_receipts_leaf_as_regular_file_is_a_broken_chain(self) -> None:
        def make(receipts: Path) -> None:
            receipts.mkdir(parents=True, exist_ok=True)
            (receipts / "sha256").write_bytes(b"")

        self.assertIn("relocation_receipt_chain_invalid", self._scan_codes_with(make))

    @unittest.skipUnless(hasattr(os, "mkfifo"), "needs mkfifo")
    def test_r5_03_receipts_root_as_fifo_is_a_broken_chain(self) -> None:
        def make(receipts: Path) -> None:
            if receipts.exists():
                shutil.rmtree(receipts)
            os.mkfifo(receipts)

        self.assertIn("relocation_receipt_chain_invalid", self._scan_codes_with(make))


class RoundSixTests(_VaultCase):
    """Round 6 (R6-01..R6-03): the back direction never removes a pointer
    to another vault; journals that are not regular files fail closed."""

    def _crashed_back_to_copy(self, crash) -> tuple[str, Path, str]:
        local, revision = self._local()
        commit_relocation(local, plan_relocation(local, self.vault), revision)
        external = MemoryStore(self.project, store_root=self.vault)
        back = plan_back(external)
        with crash():
            with self.assertRaises(SimulatedCrash):
                commit_relocation(external, back, external.verify()["revision"])
        copy = self.base / "copy"
        shutil.copytree(self.vault, copy)
        pointer = read_pointer(self.project)
        (self.project / ".an-kla" / "store-root.txt").write_bytes(
            canonical_json({**pointer, "store_root": str(copy)})
        )
        advanced = _commit_fact(open_resolved_store(self.project, environ={}), "f-copy")
        return back["core"]["transaction_id"], copy, advanced

    def _assert_copy_kept(self, txid: str, copy: Path, advanced: str) -> None:
        with self.assertRaises(RelocateError) as caught:
            reconcile_relocation(self.project, txid)
        self.assertEqual(str(caught.exception), "relocate_pointer_unrecognized")
        self.assertEqual(Path(read_pointer(self.project)["store_root"]), copy)
        self.assertEqual(MemoryStore(self.project, store_root=copy).verify()["revision"], advanced)

    def test_r6_03_back_never_removes_a_pointer_to_a_live_copy(self) -> None:
        @contextlib.contextmanager
        def crash():
            relocate._fault = _fault_at("before_pointer_removal")
            try:
                yield
            finally:
                relocate._fault = None

        self._assert_copy_kept(*self._crashed_back_to_copy(crash))

    def test_r6_03_back_without_mark_never_removes_a_pointer_to_a_copy(self) -> None:
        self._assert_copy_kept(*self._crashed_back_to_copy(lambda: _crash_on_second("published")))

    def _journal_slot(self) -> tuple[str, Path]:
        local, _ = self._local()
        txid = plan_relocation(local, self.vault)["core"]["transaction_id"]
        directory = self.project / ".an-kla" / "relocations"
        directory.mkdir(exist_ok=True)
        return txid, directory / f"{txid}.json"

    @unittest.skipUnless(hasattr(os, "mkfifo"), "needs mkfifo")
    def test_r6_01_fifo_journal_never_blocks(self) -> None:
        txid, slot = self._journal_slot()
        os.mkfifo(slot)
        with self.assertRaises(RelocateError) as caught:
            inspect_relocation(self.project, txid)
        self.assertEqual(str(caught.exception), "relocate_journal_invalid")
        self.assertEqual(unfinished_relocations(self.project), 1)

    def test_r6_02_directory_journal_is_a_stable_error(self) -> None:
        txid, slot = self._journal_slot()
        slot.mkdir()
        with self.assertRaises(RelocateError) as caught:
            inspect_relocation(self.project, txid)
        self.assertEqual(str(caught.exception), "relocate_journal_invalid")


class RoundSevenTests(_VaultCase):
    """Round 7 (R7-01): a long-lived reader of an external origin stops
    serving it once ``relocate back`` passes its commit point."""

    def _external_reader(self) -> tuple[MemoryStore, MemoryStore, str]:
        local, revision = self._local()
        commit_relocation(local, plan_relocation(local, self.vault), revision)
        reader = open_resolved_store(self.project, environ={})
        self.assertEqual(reader.read_current(), revision)
        return reader, MemoryStore(self.project, store_root=self.vault), revision

    def test_r7_01_long_lived_external_reader_stops_after_back(self) -> None:
        reader, external, revision = self._external_reader()
        back = plan_back(external)
        relocate._fault = _fault_at("after_pointer")
        try:
            with self.assertRaises(SimulatedCrash):
                commit_relocation(external, back, revision)
        finally:
            relocate._fault = None
        for read in (reader.read_current, reader.snapshot):
            with self.assertRaises(CustodyError) as caught:
                read()
            self.assertEqual(str(caught.exception), "store_root_divergence")
        reconcile_relocation(self.project, back["core"]["transaction_id"])
        with self.assertRaises(CustodyError) as caught:
            reader.read_current()
        self.assertEqual(str(caught.exception), "store_root_divergence")

    def test_r7_01_positive_control_external_reader_serves_while_live(self) -> None:
        reader, external, revision = self._external_reader()
        back = plan_back(external)
        relocate._fault = _fault_at("before_pointer_removal")
        try:
            with self.assertRaises(SimulatedCrash):
                commit_relocation(external, back, revision)
        finally:
            relocate._fault = None
        # Units published, pointer still names the external root: still live.
        self.assertEqual(reader.read_current(), revision)
        self.assertEqual(reader.snapshot().revision_id, revision)


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
