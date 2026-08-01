from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from an_kla.store import MemoryStore


class ContextAssemblyCliTests(unittest.TestCase):
    def test_cli_exposes_globally_budgeted_assembly(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = MemoryStore(root)
            initial = store.initialize()
            store.commit(
                expected_current_hash=initial,
                checkpoint_patch={"goal": "probar CLI"},
                facts=[{"id": "f-001", "payload": {"text": "memoria CLI"}}],
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "an_kla",
                    "--project-root",
                    root,
                    "assemble-context",
                    "--query",
                    "memoria",
                    "--new-information",
                    "entrada ñ",
                    "--budget",
                    "800",
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                timeout=30,
                check=True,
            )
            payload = json.loads(completed.stdout)
            self.assertEqual(
                payload["used_bytes"], len(completed.stdout)
            )
            self.assertLessEqual(payload["used_bytes"], 800)


if __name__ == "__main__":
    unittest.main()
