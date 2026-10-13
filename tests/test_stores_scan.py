"""ADR-0050 acceptance criteria for the read-only ``stores scan``."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from an_kla.canonical import canonical_json
from an_kla.custody import POINTER_SCHEMA, custody_fingerprint, pointer_path
from an_kla.export_restore import create_export
from an_kla.identity import read_binding
from an_kla.stores_scan import ScanError, scan
from an_kla.store import MemoryStore
from tests.test_custody_root import _commit_fact


ROOT = Path(__file__).resolve().parents[1]


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    out = {}
    for directory, subdirs, files in os.walk(root, followlinks=False):
        for name in subdirs + files:
            path = Path(directory) / name
            info = path.lstat()
            out[str(path)] = (info.st_mtime_ns, info.st_size)
    return out


def _by_class(result: dict) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for entry in result["entries"]:
        grouped.setdefault(entry["class"], []).append(entry)
    return grouped


class StoresScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name).resolve()
        self.scan_root = self.base / "www"
        # Project-local vault.
        self.local_project = self.scan_root / "local"
        self.local_project.mkdir(parents=True)
        local = MemoryStore(self.local_project)
        local.initialize()
        _commit_fact(local, "f-local")
        self.local_fp = custody_fingerprint(read_binding(local))
        # External vault bound by a pointer.
        self.bound_project = self.scan_root / "bound"
        self.bound_project.mkdir()
        self.bound_vault = self.scan_root / "vaults" / "bound"
        MemoryStore(self.bound_project, store_root=self.bound_vault).initialize()
        # External vault whose checkout is gone.
        gone = self.scan_root / "gone"
        gone.mkdir()
        self.orphan_vault = self.scan_root / "vaults" / "orphan"
        orphan = MemoryStore(gone, store_root=self.orphan_vault)
        orphan.initialize()
        self.orphan_fp = custody_fingerprint(read_binding(orphan))
        shutil.rmtree(gone)
        # A copy of the local vault in another directory (moved + copy).
        shutil.copytree(self.local_project / ".an-kla", self.scan_root / "backup" / ".an-kla")
        # An export bundle of the local vault.
        (self.scan_root / "exports").mkdir()
        create_export(local, self.scan_root / "exports" / "bundle")

    def test_fixtures_are_classified_by_bytes(self) -> None:
        result = scan([self.scan_root])
        self.assertEqual(result["schema"], "an-kla/stores-scan-v1")
        self.assertFalse(result["verify_run"])
        groups = _by_class(result)
        self.assertEqual(result["counts"]["active"], 2)  # local and its backup copy
        active = groups["active"]
        self.assertEqual(sorted(entry["custody_fingerprint"] for entry in active).count(self.local_fp), 2)
        self.assertEqual(
            sorted(entry["flags"] for entry in active if entry["custody_fingerprint"] == self.local_fp),
            [["copy"], ["copy", "moved"]],
        )
        self.assertEqual(len(groups["external_bound"]), 1)
        self.assertEqual(groups["orphan_uncertain"][0]["custody_fingerprint"], self.orphan_fp)
        self.assertEqual(len(groups["export_bundle"]), 1)
        self.assertEqual(len(groups["pointer_only"]), 1)
        self.assertEqual(groups["pointer_only"][0]["flags"], [])

    def test_scan_writes_nothing(self) -> None:
        before = _snapshot(self.scan_root)
        scan([self.scan_root], show_paths=True)
        self.assertEqual(_snapshot(self.scan_root), before)

    def test_depth_and_symlinks_with_positive_control(self) -> None:
        deep = self.base / "deep"
        project = deep / "a" / "b" / "c"
        project.mkdir(parents=True)
        MemoryStore(project).initialize()
        self.assertEqual(scan([deep], max_depth=3)["counts"]["active"], 1)  # positive control
        self.assertEqual(scan([deep], max_depth=2)["counts"]["active"], 0)
        linked = self.base / "linked"
        linked.mkdir()
        (linked / "via-link").symlink_to(deep / "a", target_is_directory=True)
        result = scan([linked], max_depth=6)
        self.assertEqual(result["counts"]["active"], 0)
        self.assertEqual(result["symlinks_not_followed"], 1)
        with self.assertRaises(ScanError):
            scan([linked / "via-link"])
        with self.assertRaises(ScanError):
            scan(["relative/path"])

    def test_no_paths_by_default(self) -> None:
        text = json.dumps(scan([self.scan_root]))
        self.assertNotIn(str(self.base), text)
        self.assertIn(str(self.local_project), json.dumps(scan([self.scan_root], show_paths=True)))

    def test_fake_pointer_never_changes_identity_classes(self) -> None:
        honest = scan([self.scan_root])
        liar = self.scan_root / "liar"
        liar.mkdir()
        fake = {
            "schema": POINTER_SCHEMA,
            "store_root": str(self.orphan_vault),
            "custody_fingerprint": "sha256:" + "0" * 64,
        }
        pointer_path(liar).parent.mkdir(parents=True)
        pointer_path(liar).write_bytes(canonical_json(fake))
        result = scan([self.scan_root])
        groups = _by_class(result)
        self.assertEqual(groups["orphan_uncertain"][0]["custody_fingerprint"], self.orphan_fp)
        self.assertEqual(result["flags"]["pointer_divergent"], 1)
        for name in ("active", "external_bound", "orphan_uncertain", "export_bundle"):
            self.assertEqual(result["counts"][name], honest["counts"][name], name)

    def test_cli_scan(self) -> None:
        env = {key: value for key, value in os.environ.items() if key != "AN_KLA_STORE_ROOT"}
        env["AN_KLA_NO_UPDATE_CHECK"] = "1"
        completed = subprocess.run(
            [
                sys.executable, "-m", "an_kla", "--project-root", str(self.base),
                "stores", "scan", "--root", str(self.scan_root), "--max-depth", "4",
            ],
            capture_output=True, text=True, cwd=str(ROOT), env=env,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["counts"]["orphan_uncertain"], 1)
        self.assertFalse((self.base / ".an-kla").exists())


if __name__ == "__main__":
    unittest.main()
