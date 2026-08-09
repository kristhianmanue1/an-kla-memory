from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from an_kla.store import MemoryStore


ROOT = Path(__file__).resolve().parents[1]


class RetiredLegacyWriteCliTests(unittest.TestCase):
    def test_public_write_command_is_absent_and_creates_no_state(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            project = Path(root) / "consumer"
            project.mkdir()
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "an_kla",
                    "--project-root",
                    str(project),
                    "write",
                ],
                cwd=ROOT,
                env={**os.environ, "AN_KLA_NO_UPDATE_CHECK": "1"},
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("invalid choice: 'write'", completed.stderr)
            self.assertFalse((project / ".an-kla").exists())

    def test_help_lists_only_governed_public_write_flow(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "an_kla", "--help"],
            cwd=ROOT,
            env={**os.environ, "AN_KLA_NO_UPDATE_CHECK": "1"},
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        self.assertIn("plan-write", completed.stdout)
        self.assertIn("commit-write-plan", completed.stdout)
        self.assertNotIn("API alfa heredada", completed.stdout)
        self.assertNotIn("--allow-legacy-unguarded-write", completed.stdout)

    def test_memory_store_commit_remains_internal_maintenance_api(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = MemoryStore(root)
            parent = store.initialize()
            child = store.commit(
                expected_current_hash=parent,
                checkpoint_patch={},
                facts=[{"id": "internal", "payload": {"text": "maintenance"}}],
            )
            self.assertEqual(store.read_current(), child)


if __name__ == "__main__":
    unittest.main()
