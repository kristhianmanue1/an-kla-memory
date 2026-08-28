"""El arranque sin memoria produce señal estable, no traceback (issue #76)."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STARTUP_COMMANDS = (
    ["status"],
    ["doctor"],
    ["checkpoint", "show"],
    ["resume", "--budget", "12000"],
)


try:
    import fcntl  # noqa: F401
    _FCNTL = True
except ImportError:
    _FCNTL = False


@unittest.skipUnless(_FCNTL, "reader gate requiere fcntl (no disponible en Windows)")
class StartupWithoutMemoryTest(unittest.TestCase):
    def _run(self, project_root: str, command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "an_kla", "--project-root", project_root,
             "--no-update-check", *command],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

    def test_startup_commands_report_reader_gate_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as project_root:
            for command in STARTUP_COMMANDS:
                with self.subTest(command=command):
                    completed = self._run(project_root, command)
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertEqual(completed.stdout, "")
                    self.assertEqual(
                        completed.stderr,
                        "an-kla error: reader_gate_unavailable\n",
                    )
                    self.assertNotIn("Traceback", completed.stderr)
                    self.assertNotIn(str(ROOT), completed.stderr)

    def test_identity_status_still_classifies_absence(self) -> None:
        with tempfile.TemporaryDirectory() as project_root:
            completed = self._run(project_root, ["identity", "status"])
            self.assertEqual(completed.returncode, 0)
            self.assertIn('"identity_status":"absent"', completed.stdout)


if __name__ == "__main__":
    unittest.main()
