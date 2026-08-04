from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

from an_kla import VERSION


ROOT = Path(__file__).resolve().parents[1]


class ReleaseMetadataTests(unittest.TestCase):
    def test_runtime_and_pyproject_versions_match(self) -> None:
        payload = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'^version = "([^"]+)"$', payload, re.MULTILINE)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), VERSION)

    def test_cli_reports_installed_version_without_project_state(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "an_kla", "--version"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(completed.stdout.strip(), f"an-kla-memory {VERSION}")

    def test_pep639_license_metadata_uses_supported_backend(self) -> None:
        payload = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('requires = ["setuptools>=77"]', payload)
        self.assertIn('license = "Apache-2.0"', payload)
        self.assertIn('license-files = ["LICENSE"]', payload)
        self.assertNotIn("license = {", payload)

    def test_readme_covers_reproducible_consumer_lifecycle(self) -> None:
        payload = (ROOT / "README.md").read_text(encoding="utf-8")
        required = (
            "python3.12 -m venv .venv",
            "git+https://github.com/kristhianmanue1/an-kla-memory.git@v0.1.0-beta.4",
            "-m an_kla --version",
            "context plan --operation install",
            "context plan --operation update",
            "context plan --operation uninstall",
            "pip uninstall an-kla-memory",
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, payload)

        self.assertNotIn(
            "git+https://github.com/kristhianmanue1/an-kla-memory.git@main",
            payload,
        )


if __name__ == "__main__":
    unittest.main()
