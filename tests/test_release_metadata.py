from __future__ import annotations

import re
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

    def test_pep639_license_metadata_uses_supported_backend(self) -> None:
        payload = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('requires = ["setuptools>=77"]', payload)
        self.assertIn('license = "Apache-2.0"', payload)
        self.assertIn('license-files = ["LICENSE"]', payload)
        self.assertNotIn("license = {", payload)


if __name__ == "__main__":
    unittest.main()
