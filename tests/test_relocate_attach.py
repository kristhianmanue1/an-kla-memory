"""G3: ``relocate attach`` binds an external vault created at another
project root, with a ``project_root`` relocation receipt (ADR-0048
Enmienda 5)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from an_kla import relocate_attach
from an_kla.custody import CustodyError, custody_fingerprint, pointer_path, read_pointer
from an_kla.identity import read_binding
from an_kla.relocate_attach import AttachError, attach_store, bound_project_root
from an_kla.relocation_receipts import load_relocation_receipt, receipts_dir
from an_kla.store import MemoryStore
from an_kla.store_resolution import open_resolved_store
from tests.test_custody_root import _commit_fact


ROOT = Path(__file__).resolve().parents[1]


def _receipts(vault: Path) -> list[str]:
    directory = vault / "relocation-receipts" / "sha256"
    return sorted(path.name for path in directory.glob("*.json")) if directory.exists() else []


class RelocateAttachTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name).resolve()
        self.vault = self.base / "vaults" / "vault"
        old = self.base / "old-checkout"
        old.mkdir()
        created = MemoryStore(old, store_root=self.vault)
        created.initialize()
        self.revision = _commit_fact(created, "f-old")
        self.fingerprint = custody_fingerprint(read_binding(created))
        self.old = old
        # The checkout is deleted and cloned again elsewhere; the vault stays.
        shutil.rmtree(old)
        self.project = self.base / "new-checkout"
        self.project.mkdir()

    def _store(self, project: Path | None = None) -> MemoryStore:
        return MemoryStore(project or self.project, store_root=self.vault)

    def test_attach_binds_recreated_checkout_with_receipt(self) -> None:
        with self.assertRaises(CustodyError) as caught:
            self._store().initialize()
        self.assertEqual(str(caught.exception), "store_root_project_mismatch")
        result = attach_store(self._store(), self.revision)
        self.assertEqual(result["schema"], "an-kla/relocate-attach-result-v1")
        self.assertEqual(result["custody_fingerprint"], self.fingerprint)
        self.assertFalse(result["replayed"])
        receipt = load_relocation_receipt(self._store(), result["relocation_receipt"])
        self.assertEqual(receipt["kind"], "project_root")
        self.assertEqual(receipt["from_root_observed"], str(self.old))
        self.assertEqual(receipt["to_root_observed"], str(self.project))
        self.assertEqual(receipt["current_observed"], self.revision)
        self.assertEqual(read_pointer(self.project)["custody_fingerprint"], self.fingerprint)
        # A bare invocation now resolves through the pointer and can write.
        resolved = open_resolved_store(self.project, environ={})
        self.assertTrue(resolved.store_external)
        revision = _commit_fact(resolved, "f-new")
        self.assertEqual(self._store().verify()["revision"], revision)
        self.assertEqual(bound_project_root(resolved, read_binding(resolved)), str(self.project))
        # The receipt moved the bound root: init accepts this checkout now.
        pointer_path(self.project).unlink()
        self.assertEqual(self._store().initialize(), revision)
        self.assertTrue(pointer_path(self.project).exists())

    def test_attach_is_idempotent_and_requires_exact_current(self) -> None:
        with self.assertRaises(AttachError) as caught:
            attach_store(self._store(), "sha256:" + "0" * 64)
        self.assertEqual(str(caught.exception), "relocate_attach_base_changed")
        self.assertIsNone(read_pointer(self.project))
        self.assertEqual(_receipts(self.vault), [])
        first = attach_store(self._store(), self.revision)
        again = attach_store(self._store(), self.revision)
        self.assertTrue(again["replayed"])
        self.assertIsNone(again["relocation_receipt"])
        self.assertEqual(len(_receipts(self.vault)), 1)
        self.assertIsNotNone(first["relocation_receipt"])

    def test_crash_between_receipt_and_pointer_recovers_without_new_receipt(self) -> None:
        with mock.patch.object(relocate_attach, "write_pointer", side_effect=OSError("crash")):
            with self.assertRaises(OSError):
                attach_store(self._store(), self.revision)
        self.assertIsNone(read_pointer(self.project))
        self.assertEqual(len(_receipts(self.vault)), 1)
        result = attach_store(self._store(), self.revision)
        self.assertIsNone(result["relocation_receipt"])
        self.assertFalse(result["replayed"])
        self.assertEqual(len(_receipts(self.vault)), 1)
        self.assertEqual(read_pointer(self.project)["custody_fingerprint"], self.fingerprint)

    def test_second_move_chains_receipts(self) -> None:
        first = attach_store(self._store(), self.revision)["relocation_receipt"]
        third = self.base / "third-checkout"
        third.mkdir()
        second = attach_store(self._store(third), self.revision)["relocation_receipt"]
        receipt = load_relocation_receipt(self._store(third), second)
        self.assertEqual(receipt["predecessor_receipt"], first)
        self.assertEqual(receipt["from_root_observed"], str(self.project))
        self.assertEqual(receipt["to_root_observed"], str(third))

    def test_refuses_project_local_vault_divergent_pointer_and_local_store(self) -> None:
        local = MemoryStore(self.project)
        local.initialize()
        with self.assertRaises(CustodyError) as caught:
            attach_store(self._store(), self.revision)
        self.assertEqual(str(caught.exception), "store_root_divergence")
        self.assertEqual(_receipts(self.vault), [])
        with self.assertRaises(AttachError) as caught:
            attach_store(local, local.read_current())
        self.assertEqual(str(caught.exception), "relocate_attach_not_external")
        # A pointer to another vault is never replaced.
        other_project = self.base / "other"
        other_project.mkdir()
        other_vault = self.base / "vaults" / "other"
        MemoryStore(other_project, store_root=other_vault).initialize()
        before = pointer_path(other_project).read_bytes()
        with self.assertRaises(AttachError) as caught:
            attach_store(self._store(other_project), self.revision)
        self.assertEqual(str(caught.exception), "store_root_divergence")
        self.assertEqual(pointer_path(other_project).read_bytes(), before)
        self.assertEqual(_receipts(self.vault), [])

    def test_cli_attach(self) -> None:
        env = {key: value for key, value in os.environ.items() if key != "AN_KLA_STORE_ROOT"}
        env["AN_KLA_NO_UPDATE_CHECK"] = "1"
        completed = subprocess.run(
            [
                sys.executable, "-m", "an_kla", "--project-root", str(self.project),
                "relocate", "attach", "--store-root", str(self.vault),
                "--expected-current", self.revision,
            ],
            capture_output=True, text=True, cwd=str(ROOT), env=env,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["custody_fingerprint"], self.fingerprint)
        status = subprocess.run(
            [sys.executable, "-m", "an_kla", "--project-root", str(self.project), "status"],
            capture_output=True, text=True, cwd=str(ROOT), env=env,
        )
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(json.loads(status.stdout)["revision"], self.revision)
        self.assertTrue(receipts_dir(self._store()).is_dir())


if __name__ == "__main__":
    unittest.main()
