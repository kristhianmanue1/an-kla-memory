"""G3 R3: plain and sealed export from external custody, restored to the
project-local destination the current contract admits (ADR-0048 §3,
Enmienda 1 §3)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from an_kla.canonical import canonical_json, digest_json
from an_kla.custody import custody_fingerprint, pointer_path
from an_kla.export_io import ExportIOError
from an_kla.export_restore import create_export, restore_export, verify_export
from an_kla.identity import read_binding
from an_kla.relocate import commit_relocation, plan_relocation
from an_kla.store import MemoryStore
from tests.test_custody_root import _commit_fact

try:
    from an_kla.sealed import bundle as sb
    from tests.test_sealed_bundle import FakeAdapter, _cryptography_importable

    _SEALED = _cryptography_importable()
except Exception:  # pragma: no cover
    _SEALED = False


class CustodyExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name).resolve()
        self.project = self.base / "project"
        self.project.mkdir()
        self.vault = self.base / "vaults" / "vault"
        local = MemoryStore(self.project)
        local.initialize()
        _commit_fact(local, "f-local")
        plan = plan_relocation(local, self.vault)
        commit_relocation(local, plan, plan["core"]["base_revision"])
        self.store = MemoryStore(self.project, store_root=self.vault)
        self.revision = _commit_fact(self.store, "f-external")
        self.fingerprint = custody_fingerprint(read_binding(self.store))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _assert_restored(self, target: Path) -> None:
        restored = MemoryStore(target)
        verified = restored.verify()
        self.assertEqual(verified["revision"], self.revision)
        self.assertEqual(custody_fingerprint(read_binding(restored)), self.fingerprint)
        self.assertFalse(pointer_path(target).exists())
        self.assertFalse((target / ".an-kla" / "attest.key").exists())

    def test_plain_export_from_external_custody_restores_project_local(self) -> None:
        bundle = self.base / "bundle"
        created = create_export(self.store, bundle)
        self.assertEqual(created["current_revision"], self.revision)
        manifest = json.loads((bundle / "manifest.json").read_bytes())
        paths = {entry["path"] for entry in manifest["core"]["entries"]}
        self.assertIn("anchor/memory/refs/CURRENT", paths)
        self.assertTrue(any(path.startswith("anchor/relocation-receipts/") for path in paths))
        for excluded in ("anchor/attest.key", "anchor/store-root.txt"):
            self.assertNotIn(excluded, paths)
        self.assertFalse(any(path.startswith("anchor/relocations/") for path in paths))
        self.assertTrue(verify_export(bundle)["verified"])
        restored = self.base / "restored"
        restored.mkdir()
        restore_export(bundle, restored)
        self._assert_restored(restored)

    def test_export_negative_controls(self) -> None:
        # Bundle inside the vault, existing destination and a divergent
        # pointer all fail closed without writing a bundle.
        with self.assertRaises(ExportIOError) as caught:
            create_export(self.store, self.vault / "bundle")
        self.assertEqual(str(caught.exception), "export_destination_inside_source")
        occupied = self.base / "occupied"
        occupied.mkdir()
        with self.assertRaises(ExportIOError):
            create_export(self.store, occupied)
        other = self.base / "other"
        other.mkdir()
        foreign_root = self.base / "foreign"
        MemoryStore(other, store_root=foreign_root).initialize()
        foreign = MemoryStore(self.project, store_root=foreign_root)
        with self.assertRaises(Exception) as caught:
            create_export(foreign, self.base / "foreign-bundle")
        self.assertEqual(str(caught.exception), "store_root_divergence")
        self.assertFalse((self.base / "foreign-bundle").exists())
        # Restore never publishes into a checkout that already holds a
        # custody anchor (the pointer lives in .an-kla).
        bundle = self.base / "bundle"
        create_export(self.store, bundle)
        with self.assertRaises(ExportIOError):
            restore_export(bundle, self.project)
        self.assertEqual(self.store.verify()["revision"], self.revision)

    def test_tampered_bundle_cannot_escape_the_destination(self) -> None:
        bundle = self.base / "bundle"
        create_export(self.store, bundle)
        manifest_path = bundle / "manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        entry = manifest["core"]["entries"][0]
        original = entry["path"]
        entry["path"] = "anchor/../../escape.json"
        # Re-seal the manifest digest so the path rule, not the digest, is
        # what must reject the entry.
        manifest["manifest_sha256"] = digest_json(manifest["core"])
        manifest_path.write_bytes(canonical_json(manifest))
        restored = self.base / "restored"
        restored.mkdir()
        with self.assertRaises(ExportIOError) as caught:
            restore_export(bundle, restored)
        self.assertEqual(str(caught.exception), "export_entries_invalid")
        self.assertFalse((self.base / "escape.json").exists())
        self.assertFalse((restored / ".an-kla").exists())
        self.assertTrue(original.startswith("anchor/"))

    @unittest.skipUnless(_SEALED, "cryptography not installed")
    def test_sealed_export_from_external_custody(self) -> None:
        adapter = FakeAdapter()
        bundle = self.base / "sealed"
        sb.create_sealed_bundle(self.store, bundle, adapter)
        restored = self.base / "restored"
        restored.mkdir()
        sb.restore_sealed_bundle(bundle, restored, runner=adapter)
        self._assert_restored(restored)


if __name__ == "__main__":
    unittest.main()
