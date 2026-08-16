"""Regression tests for the startup diagnostic (ADR-0036, issue #76)."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from an_kla.schemas import schema_document
from an_kla.startup import startup_diagnostic
from an_kla.store import MemoryStore


ROOT = Path(__file__).resolve().parents[1]

try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator = None  # type: ignore[assignment,misc]


def initialized(path: str) -> MemoryStore:
    store = MemoryStore(path)
    store.initialize()
    return store


class StartupDiagnosticTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = self.temp.name

    def tearDown(self) -> None:
        # Restore any mode change so cleanup never fails on a read-only tree.
        for path in Path(self.root).rglob("*"):
            try:
                path.chmod(path.stat().st_mode | stat.S_IRWXU)
            except OSError:
                pass
        self.temp.cleanup()

    def assertValid(self, result: dict) -> None:
        if Draft202012Validator is None:
            self.skipTest("jsonschema unavailable")
        Draft202012Validator(schema_document("startup-diagnostic-v1")).validate(result)

    def test_absent_memory_is_a_result_not_an_error(self) -> None:
        result = startup_diagnostic(MemoryStore(self.root))
        self.assertEqual(result["store_presence"], "absent")
        self.assertEqual(result["store_integrity"], "not_evaluated")
        self.assertValid(result)

    def test_intact_memory_is_verified(self) -> None:
        result = startup_diagnostic(initialized(self.root))
        self.assertEqual(result["store_presence"], "present")
        self.assertEqual(result["store_integrity"], "verified")
        self.assertIsNone(result["integrity_detail"])
        self.assertValid(result)

    def test_present_but_broken_store_is_representable(self) -> None:
        """The state the four-state enum could not name: present and broken."""
        store = initialized(self.root)
        shutil.rmtree(store.root / "revisions")
        result = startup_diagnostic(store)
        self.assertEqual(result["store_presence"], "present")
        self.assertEqual(result["store_integrity"], "failed")
        self.assertIsNotNone(result["integrity_detail"])
        self.assertValid(result)

    @unittest.skipIf(os.name == "nt", "POSIX mode semantics")
    @unittest.skipIf(os.geteuid() == 0, "root ignores mode bits")
    def test_read_only_tree_is_not_evaluated_never_failed(self) -> None:
        """An intact store whose gate cannot be taken is not a broken store."""
        store = initialized(self.root)
        for path in sorted(store.root.rglob("*"), reverse=True):
            path.chmod(path.stat().st_mode & ~stat.S_IWUSR)
        store.root.chmod(store.root.stat().st_mode & ~stat.S_IWUSR)
        result = startup_diagnostic(store)
        self.assertEqual(result["store_presence"], "present")
        self.assertEqual(result["store_integrity"], "not_evaluated")
        self.assertEqual(result["integrity_detail"], "reader_gate_unavailable")
        self.assertValid(result)

    @unittest.skipIf(os.name == "nt", "POSIX mode semantics")
    @unittest.skipIf(os.geteuid() == 0, "root ignores mode bits")
    def test_unreadable_store_never_leaks_absolute_paths(self) -> None:
        store = initialized(self.root)
        store.root.chmod(0o000)
        result = startup_diagnostic(store)
        self.assertEqual(result["store_presence"], "unreadable")
        self.assertEqual(result["store_integrity"], "not_evaluated")
        self.assertEqual(result["identity"]["error_code"], "store_unreadable")
        self.assertNotIn(self.root, json.dumps(result))
        self.assertValid(result)

    @unittest.skipIf(os.name == "nt", "POSIX mode semantics")
    @unittest.skipIf(os.geteuid() == 0, "root ignores mode bits")
    def test_unreadable_object_reports_a_code_not_a_path(self) -> None:
        """OSError stringifies with the absolute path; only its type may travel."""
        store = initialized(self.root)
        (store.root / "revisions").chmod(0o000)
        result = startup_diagnostic(store)
        (store.root / "revisions").chmod(0o700)
        self.assertEqual(result["store_integrity"], "failed")
        self.assertEqual(result["integrity_detail"], "PermissionError")
        self.assertNotIn(self.root, json.dumps(result))
        self.assertNotIn("/", json.dumps(result["identity"]))
        self.assertValid(result)

    def test_copied_store_exposes_root_relocated(self) -> None:
        source = initialized(self.root)
        with tempfile.TemporaryDirectory() as other:
            shutil.copytree(Path(self.root) / ".an-kla", Path(other) / ".an-kla")
            result = startup_diagnostic(MemoryStore(other))
            self.assertTrue(result["identity"]["root_relocated"])
            self.assertValid(result)
        self.assertEqual(startup_diagnostic(source)["identity"]["root_relocated"], False)

    def test_linked_worktree_is_distinguishable_from_a_new_project(self) -> None:
        """The acceptance criterion of issue #76."""
        main = Path(self.root) / "main"
        main.mkdir()
        for command in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "base"]):
            subprocess.run(
                ["git", *command], cwd=main, check=True,
                env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                     "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
            )
        linked = Path(self.root) / "linked"
        subprocess.run(
            ["git", "worktree", "add", "-q", str(linked), "-b", "wt"],
            cwd=main, check=True, capture_output=True,
        )

        main_result = startup_diagnostic(MemoryStore(main))
        linked_result = startup_diagnostic(MemoryStore(linked))
        self.assertEqual(main_result["repo_context"], "main_checkout")
        self.assertEqual(linked_result["repo_context"], "linked_worktree")
        # Both lack memory, and that alone would be indistinguishable.
        self.assertEqual(main_result["store_presence"], "absent")
        self.assertEqual(linked_result["store_presence"], "absent")
        self.assertValid(linked_result)

    def test_plain_directory_is_not_a_repo(self) -> None:
        self.assertEqual(
            startup_diagnostic(MemoryStore(self.root))["repo_context"], "not_a_repo"
        )

    def test_schema_is_closed_and_rejects_unknown_fields(self) -> None:
        if Draft202012Validator is None:
            self.skipTest("jsonschema unavailable")
        validator = Draft202012Validator(schema_document("startup-diagnostic-v1"))
        result = startup_diagnostic(MemoryStore(self.root))
        self.assertFalse(validator.is_valid({**result, "unexpected": 1}))
        self.assertFalse(validator.is_valid({**result, "store_presence": "local_valid"}))

    def test_cli_reports_every_axis_with_exit_zero(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "an_kla", "--project-root", self.root,
             "--no-update-check", "startup-diagnostic"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 0)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["schema"], "an-kla/startup-diagnostic-v1")
        self.assertTrue(payload["untrusted_memory_data"])
        self.assertFalse(payload["external_memory_evaluated"])


if __name__ == "__main__":
    unittest.main()
