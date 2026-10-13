"""Regressions from the beta.30 release adversarial round (reviewer: Muse
CLI, a different model family).  H-01..H-04 reproduce its findings."""

from __future__ import annotations

import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from an_kla import relocate
from an_kla.custody import CustodyError, read_pointer
from an_kla.identity import IdentityError
from an_kla.relocate import SimulatedCrash, commit_relocation, plan_relocation
from an_kla.relocate_attach import AttachError, attach_store
from an_kla.store import MemoryStore
from an_kla.store_resolution import open_resolved_store
from an_kla.stores_scan import scan
from tests.test_custody_root import _commit_fact


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
