from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CiMetadataTests(unittest.TestCase):
    def test_node24_actions_are_pinned_to_reviewed_commits(self) -> None:
        payload = (ROOT / ".github" / "workflows" / "test.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1",
            payload,
        )
        self.assertIn(
            "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0",
            payload,
        )
        self.assertNotIn("actions/checkout@v4", payload)
        self.assertNotIn("actions/setup-python@v5", payload)


if __name__ == "__main__":
    unittest.main()
