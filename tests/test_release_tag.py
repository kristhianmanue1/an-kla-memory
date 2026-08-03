from __future__ import annotations

import unittest

from an_kla.version import normalized_release_tag


class ReleaseTagTests(unittest.TestCase):
    def test_alpha_tag_normalizes_to_pep440(self) -> None:
        self.assertEqual(normalized_release_tag("v0.1.0-alpha.3"), "0.1.0a3")

    def test_future_release_phases_are_supported(self) -> None:
        self.assertEqual(normalized_release_tag("v0.1.0-beta.1"), "0.1.0b1")
        self.assertEqual(normalized_release_tag("v0.1.0-beta.2"), "0.1.0b2")
        self.assertEqual(normalized_release_tag("v0.1.0-beta.3"), "0.1.0b3")
        self.assertEqual(normalized_release_tag("v1.0.0-rc.2"), "1.0.0rc2")
        self.assertEqual(normalized_release_tag("v1.0.0"), "1.0.0")

    def test_unknown_tag_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported_release_tag"):
            normalized_release_tag("release-0.1.0")


if __name__ == "__main__":
    unittest.main()
