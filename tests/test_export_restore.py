from __future__ import annotations

import json
import io
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from an_kla.canonical import canonical_json, digest_bytes, digest_json
from an_kla.export_restore import ExportError, create_export, restore_export, verify_export
from an_kla.export_io import rename_noreplace
from an_kla.store import MemoryStore

#: ADR-0027: sin O_NOFOLLOW/O_DIRECTORY/dir_fd (Windows) el camino
#: funcional de export falla cerrado con export_platform_unsafe. Los
#: tests que ejercitan ese camino sólo corren donde la plataforma lo
#: ofrece; el fail-closed en sí lo cubre test_export_io.
_EXPORT_CAPABLE = (
    getattr(os, "O_NOFOLLOW", None) is not None
    and getattr(os, "O_DIRECTORY", None) is not None
    and os.open in os.supports_dir_fd
)


@unittest.skipUnless(_EXPORT_CAPABLE, "plataforma sin export descriptor-relative (ADR-0027)")
class ExportRestoreTests(unittest.TestCase):
    def _source_bundle(self, root: str) -> tuple[Path, Path, str]:
        source = Path(root) / "source"
        source.mkdir()
        store = MemoryStore(source)
        initial = store.initialize()
        current = store.commit(
            expected_current_hash=initial, checkpoint_patch={},
            facts=[{"id": "f-export", "payload": {"text": "backup"}}],
        )
        bundle = Path(root) / "bundle"
        create_export(store, bundle)
        return source, bundle, current

    def test_export_with_host_managed_artifacts_issue119(self) -> None:
        # Issue #119 / ADR-0048 §3 (H3): hook-runs viaja con la bóveda;
        # host-hooks.json es del proyecto y queda excluido. Antes del
        # fix, cualquier proyecto host-managed no podía exportar
        # (export_unrecognized_durable_path).
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source"
            store = MemoryStore(source)
            store.initialize()
            anchor = source / ".an-kla"
            hook_run = anchor / "hook-runs" / "runs" / "sha256" / ("a" * 64 + ".json")
            hook_run.parent.mkdir(parents=True, exist_ok=True)
            hook_run.write_text('{"schema": "an-kla/hook-run-v1"}', encoding="utf-8")
            (anchor / "host-hooks.json").write_text("{}", encoding="utf-8")

            bundle = Path(root) / "bundle"
            create_export(store, bundle)
            verified = verify_export(bundle)
            self.assertIs(verified["verified"], True)
            manifest = json.loads(
                (bundle / "manifest.json").read_text(encoding="utf-8")
            )
            names = {entry["path"] for entry in manifest["core"]["entries"]}
            self.assertTrue(any("hook-runs" in name for name in names))
            self.assertFalse(any("host-hooks" in name for name in names))

    def test_roundtrip_and_tamper_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source"
            bundle = Path(root) / "bundle"
            restored = Path(root) / "restored"
            source.mkdir()
            store = MemoryStore(source)
            initial = store.initialize()
            current = store.commit(
                expected_current_hash=initial, checkpoint_patch={},
                facts=[{"id": "f-export", "payload": {"text": "backup"}}],
            )
            created = create_export(store, bundle)
            self.assertTrue(created["created"])
            self.assertTrue(verify_export(bundle)["verified"])
            result = restore_export(bundle, restored)
            self.assertTrue(result["published"])
            self.assertEqual(MemoryStore(restored).read_current(), current)
            self.assertEqual(MemoryStore(restored).snapshot().records["facts"][0]["id"], "f-export")
            self.assertNotIn("root_relocated", verify_export(bundle)["warnings"])

            manifest = json.loads((bundle / "manifest.json").read_text())
            entry = manifest["core"]["entries"][0]
            path = bundle / "entries" / entry["path"]
            path.write_bytes(path.read_bytes() + b"x")
            with self.assertRaisesRegex(ExportError, "export_content_mismatch"):
                verify_export(bundle)

    def test_semantically_invalid_but_rehashed_bundle_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            _source, bundle, current = self._source_bundle(root)
            manifest_path = bundle / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            revision_entry = next(
                item for item in manifest["core"]["entries"]
                if item["path"].endswith(current.removeprefix("sha256:") + ".json")
            )
            revision_path = bundle / "entries" / revision_entry["path"]
            revision = json.loads(revision_path.read_text())
            revision["revision"] += 100
            payload = canonical_json(revision)
            revision_path.write_bytes(payload)
            revision_entry["size"] = len(payload)
            revision_entry["content_sha256"] = digest_bytes(payload)
            manifest["core"]["total_bytes"] = sum(
                item["size"] for item in manifest["core"]["entries"]
            )
            manifest["manifest_sha256"] = digest_json(manifest["core"])
            manifest_path.write_bytes(canonical_json(manifest))
            with self.assertRaises(Exception):
                verify_export(bundle)

    def test_bundle_inside_source_and_symlink_directory_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source"
            source.mkdir()
            store = MemoryStore(source)
            store.initialize()
            with self.assertRaisesRegex(ExportError, "export_destination_inside_source"):
                create_export(store, source / ".an-kla" / "bundle")
            bundle = Path(root) / "bundle"
            create_export(store, bundle)
            (bundle / "entries" / "escape").symlink_to(Path(root))
            with self.assertRaisesRegex(ExportError, "export_unsafe_link"):
                verify_export(bundle)

    def test_restore_outcomes_race_and_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            _source, bundle, _current = self._source_bundle(root)
            pre = Path(root) / "pre"
            with patch("an_kla.export_restore.rename_noreplace", side_effect=OSError("rename-EIO")):
                result = restore_export(bundle, pre)
            self.assertEqual(result["state"], "not_published")
            self.assertFalse((pre / ".an-kla").exists())

            after = Path(root) / "after"

            def rename_then_error(source: Path, destination: Path) -> None:
                rename_noreplace(source, destination)
                raise OSError("post-rename-EIO")

            with patch("an_kla.export_restore.rename_noreplace", side_effect=rename_then_error):
                result = restore_export(bundle, after)
            self.assertEqual(result["state"], "published_durability_incomplete")
            self.assertTrue(result["published"])
            self.assertTrue(MemoryStore(after).verify()["ok"])

            raced = Path(root) / "raced"
            raced.mkdir()

            def race(source: Path, destination: Path) -> None:
                destination.mkdir()
                rename_noreplace(source, destination)

            with patch("an_kla.export_restore.rename_noreplace", side_effect=race):
                result = restore_export(bundle, raced)
            self.assertEqual(result["state"], "not_published")
            self.assertTrue((raced / ".an-kla").is_dir())

            degraded = Path(root) / "degraded"
            original_sync = __import__("an_kla.export_restore", fromlist=["fsync_directory"]).fsync_directory

            def fail_project(path: Path) -> None:
                if path == degraded.resolve():
                    raise OSError("dir-EIO")
                original_sync(path)

            with patch("an_kla.export_restore.fsync_directory", side_effect=fail_project):
                result = restore_export(bundle, degraded)
            self.assertEqual(result["state"], "published_durability_incomplete")
            self.assertTrue((degraded / ".an-kla").exists())

            restored = Path(root) / "permissions"
            result = restore_export(bundle, restored)
            self.assertEqual(result["state"], "published")
            for path in (restored / ".an-kla").rglob("*"):
                self.assertEqual(path.stat().st_mode & 0o777, 0o700 if path.is_dir() else 0o600)

    def test_staged_bytes_are_rehashed_and_cli_degraded_restore_exits_three(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            _source, bundle, _current = self._source_bundle(root)
            destination = Path(root) / "corrupt-stage"
            original_write = Path.write_bytes
            changed = {"done": False}

            def corrupt_write(path: Path, payload: bytes) -> int:
                result = original_write(path, payload)
                if (
                    not changed["done"]
                    and ".an-kla-restore-" in str(path)
                    and "transactions" in path.parts
                    and path.suffix == ".json"
                ):
                    original_write(path, payload + b"x")
                    changed["done"] = True
                return result

            with patch.object(Path, "write_bytes", new=corrupt_write):
                outcome = restore_export(bundle, destination)
            self.assertEqual(outcome["state"], "not_published")
            self.assertFalse((destination / ".an-kla").exists())

            class Capture:
                def __init__(self) -> None:
                    self.buffer = io.BytesIO()

            cli_destination = Path(root) / "cli"
            argv = [
                "an-kla", "--project-root", str(cli_destination),
                "--no-update-check", "export", "restore", "--bundle", str(bundle),
            ]
            with patch.object(sys, "argv", argv), patch.object(sys, "stdout", Capture()), patch(
                "an_kla.export_restore.rename_noreplace", side_effect=OSError("rename-EIO")
            ), self.assertRaises(SystemExit) as raised:
                __import__("an_kla.__main__", fromlist=["_run"])._run()
            self.assertEqual(raised.exception.code, 3)

    def test_restore_same_canonical_root_does_not_warn_relocated(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            source, bundle, _current = self._source_bundle(root)
            shutil.rmtree(source / ".an-kla")
            result = restore_export(bundle, source)
            self.assertEqual(result["state"], "published")
            self.assertNotIn("root_relocated", result["warnings"])

    def test_existing_anchor_and_extra_bundle_file_fail(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source"
            source.mkdir()
            store = MemoryStore(source)
            store.initialize()
            (store.root / ".reader-gate").touch(mode=0o600)
            bundle = Path(root) / "bundle"
            create_export(store, bundle)
            extra = bundle / "extra"
            extra.write_text("x")
            with self.assertRaisesRegex(ExportError, "export_extra_or_missing_entry"):
                verify_export(bundle)
            extra.unlink()
            destination = Path(root) / "destination"
            (destination / ".an-kla").mkdir(parents=True)
            with self.assertRaisesRegex(ExportError, "restore_destination_conflict"):
                restore_export(bundle, destination)


if __name__ == "__main__":
    unittest.main()
