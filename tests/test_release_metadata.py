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
        project = re.search(
            r"^\[project\]\n(.*?)(?=^\[)", payload, re.MULTILINE | re.DOTALL
        )
        self.assertIsNotNone(project)
        self.assertIn('dynamic = ["version"]', project.group(1))
        self.assertIsNone(
            re.search(r"^version\s*=", project.group(1), re.MULTILINE),
            "version duplicated",
        )
        self.assertIn(
            'version = {attr = "an_kla.version.VERSION"}', payload
        )

    def test_console_entrypoint_is_declared(self) -> None:
        payload = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('[project.scripts]', payload)
        self.assertIn('an-kla = "an_kla.__main__:main"', payload)

    def test_release_documents_match_the_runtime_candidate(self) -> None:
        match = re.fullmatch(r"(\d+\.\d+\.\d+)b(\d+)", VERSION)
        self.assertIsNotNone(match)
        display = f"{match.group(1)}-beta.{match.group(2)}"
        tag = f"v{display}"
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
        self.assertIn(f"`{VERSION}`", readme)
        self.assertIn(tag, readme)
        self.assertIn(f"| `{tag}` | ✅ |", security)
        self.assertIn(f'version: "{display}"', citation)
        self.assertTrue((ROOT / "docs" / "releases" / f"{tag}.md").is_file())
        self.assertTrue(
            (ROOT / "docs" / "releases" / f"{tag}-adversarial.md").is_file()
        )

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
            "git+https://github.com/kristhianmanue1/an-kla-memory.git@v0.1.0-beta.9",
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
