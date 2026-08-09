from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from an_kla.__main__ import _run
from an_kla.store import MemoryStore


ROOT = Path(__file__).resolve().parents[1]


class LegacyWriteCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = MemoryStore(self.root)
        self.revision = self.store.initialize()
        self.checkpoint = self.root / "checkpoint.json"
        self.facts = self.root / "facts.json"
        self.checkpoint.write_text("{}", encoding="utf-8")
        self.facts.write_text(
            json.dumps([{"id": "f-legacy", "payload": {"text": "legacy"}}]),
            encoding="utf-8",
        )

    def _command(self, *, allow: bool) -> list[str]:
        command = [
            sys.executable,
            "-m",
            "an_kla",
            "--project-root",
            str(self.root),
            "write",
            "--expected-current",
            self.revision,
            "--checkpoint-patch",
            str(self.checkpoint),
            "--facts",
            str(self.facts),
        ]
        if allow:
            command.append("--allow-legacy-unguarded-write")
        return command

    def _run(self, *, allow: bool) -> subprocess.CompletedProcess:
        return subprocess.run(
            self._command(allow=allow),
            cwd=ROOT,
            env={**os.environ, "AN_KLA_NO_UPDATE_CHECK": "1"},
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_write_without_explicit_opt_in_fails_before_mutation(self) -> None:
        before = {
            str(path.relative_to(self.root)): path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file()
        }
        completed = self._run(allow=False)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("legacy_unguarded_write_requires_opt_in", completed.stderr)
        after = {
            str(path.relative_to(self.root)): path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file()
        }
        self.assertEqual(after, before)
        self.assertEqual(self.store.read_current(), self.revision)

    def test_explicit_opt_in_commits_and_emits_stable_warning(self) -> None:
        completed = self._run(allow=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["deprecation"], "legacy_write_bypasses_write_policy")
        self.assertEqual(payload["warning"], "legacy_unguarded_write_enabled")
        self.assertEqual(
            completed.stderr,
            "an-kla warning: legacy_unguarded_write_enabled; "
            "bypasses_write_policy_v1; removal=v0.1.0-beta.10\n",
        )
        self.assertNotEqual(payload["revision"], self.revision)
        self.assertEqual(self.store.read_current(), payload["revision"])

    def test_opt_in_cannot_mutate_checkpoint_or_create_transaction(self) -> None:
        self.checkpoint.write_text(
            json.dumps({"goal": "legacy mutation"}), encoding="utf-8"
        )
        transactions = self.store.root / "transactions"
        before = set(transactions.rglob("*")) if transactions.exists() else set()
        completed = self._run(allow=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("governed_checkpoint_update_required", completed.stderr)
        after = set(transactions.rglob("*")) if transactions.exists() else set()
        self.assertEqual(after, before)
        self.assertEqual(self.store.read_current(), self.revision)

    def test_abbreviated_opt_in_flags_are_rejected_without_mutation(self) -> None:
        before = {
            str(path.relative_to(self.root)): path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file()
        }
        for option in ("--allow", "--allow-legacy", "--allow-legacy-unguarded"):
            with self.subTest(option=option):
                completed = subprocess.run(
                    self._command(allow=False) + [option],
                    cwd=ROOT,
                    env={**os.environ, "AN_KLA_NO_UPDATE_CHECK": "1"},
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(completed.returncode, 2)
                self.assertNotIn("legacy_unguarded_write_enabled", completed.stderr)
                self.assertEqual(self.store.read_current(), self.revision)
        after = {
            str(path.relative_to(self.root)): path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file()
        }
        self.assertEqual(after, before)

    def test_opt_in_guard_precedes_update_hook_and_input_reads(self) -> None:
        argv = [
            "an-kla",
            "--project-root",
            str(self.root / "does-not-exist"),
            "write",
            "--expected-current",
            "not-a-revision",
            "--checkpoint-patch",
            str(self.root / "missing.json"),
        ]
        with patch.object(sys, "argv", argv), patch(
            "an_kla.__main__.check_for_update",
            side_effect=AssertionError("update_check_must_not_run"),
        ), self.assertRaisesRegex(
            ValueError, "^legacy_unguarded_write_requires_opt_in$"
        ):
            _run()


if __name__ == "__main__":
    unittest.main()
