from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from an_kla.store import MemoryStore


class ContextAssemblyCliTests(unittest.TestCase):
    @staticmethod
    def _initialize(root: str) -> None:
        store = MemoryStore(root)
        initial = store.initialize()
        store.commit(
            expected_current_hash=initial,
            checkpoint_patch={},
            facts=[{
                "id": "f-001",
                "verified_at": "2026-08-01T00:00:00Z",
                "payload": {"text": "memoria CLI"},
            }],
        )

    def test_cli_exposes_globally_budgeted_assembly(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            self._initialize(root)
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

    def test_cli_exposes_temporal_retrieval_and_assembly_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            self._initialize(root)
            base = [
                sys.executable,
                "-m",
                "an_kla",
                "--project-root",
                root,
            ]
            temporal = [
                "--freshness-profile",
                "computed-age/v1",
                "--now",
                "2026-08-08T00:00:00Z",
                "--stale-after-days",
                "3",
            ]
            retrieved = subprocess.run(
                base + ["retrieve", "--query", "memoria", "--budget", "1200"] + temporal,
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                timeout=30,
                check=True,
            )
            retrieval_payload = json.loads(retrieved.stdout)
            self.assertEqual(retrieval_payload["schema"], "an-kla/retrieval-result-v2")
            self.assertTrue(retrieval_payload["selected"][0]["stale"])

            assembled = subprocess.run(
                base + ["assemble-context", "--query", "memoria", "--budget", "1200"] + temporal,
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                timeout=30,
                check=True,
            )
            assembly_payload = json.loads(assembled.stdout)
            self.assertEqual(assembly_payload["schema"], "an-kla/context-assembly-v2")
            self.assertTrue(
                assembly_payload["sections"]["retrieved_records"][0]["stale"]
            )

    def test_cli_rejects_temporal_options_without_profile(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            self._initialize(root)
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "an_kla",
                    "--project-root",
                    root,
                    "retrieve",
                    "--query",
                    "memoria",
                    "--budget",
                    "800",
                    "--now",
                    "2026-08-08T00:00:00Z",
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                timeout=30,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(b"freshness_profile_required", completed.stderr)


if __name__ == "__main__":
    unittest.main()
