"""Tests for the read-only managed-template exposure used by issue #11."""

from __future__ import annotations

import unittest

from an_kla.context_package import (
    COMPACT_PAYLOAD,
    DETAILED_CONTRACT,
    TEMPLATE_VERSION,
    _KNOWN_CONTEXT_TEMPLATES,
    get_template,
    managed_payload_sha256,
)


class GetTemplateTests(unittest.TestCase):
    def test_current_returns_full_text(self):
        result = get_template()
        self.assertEqual(result["schema"], "an-kla/context-template-v1")
        self.assertEqual(result["version"], TEMPLATE_VERSION)
        self.assertTrue(result["current"])
        self.assertEqual(result["compact_payload"], COMPACT_PAYLOAD)
        self.assertEqual(result["detailed_contract"], DETAILED_CONTRACT)
        self.assertEqual(result["content_sha256"], managed_payload_sha256())

    def test_known_old_version_returns_hashes_only(self):
        old_version = next(iter(_KNOWN_CONTEXT_TEMPLATES))
        result = get_template(old_version)
        self.assertFalse(result["current"])
        self.assertEqual(result["version"], old_version)
        self.assertNotIn("compact_payload", result)
        self.assertNotIn("detailed_contract", result)
        self.assertEqual(
            result["content_sha256"],
            _KNOWN_CONTEXT_TEMPLATES[old_version]["content_sha256"],
        )

    def test_unknown_version_raises(self):
        with self.assertRaises(ValueError):
            get_template("9.9.9-never")

    def test_known_versions_listed(self):
        result = get_template()
        self.assertIn(TEMPLATE_VERSION, result["known_versions"])
        for old in _KNOWN_CONTEXT_TEMPLATES:
            self.assertIn(old, result["known_versions"])


if __name__ == "__main__":
    unittest.main()
