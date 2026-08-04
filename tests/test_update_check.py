"""Tests for the optional, read-only release availability check."""

from __future__ import annotations

import json
from pathlib import Path

import unittest
from unittest import mock

from an_kla import update_check
from an_kla.version import VERSION, is_newer_release, normalized_release_tag


class VersionComparisonTests(unittest.TestCase):
    def test_same_version_is_not_newer(self):
        self.assertFalse(is_newer_release("v0.1.0-beta.3", VERSION))

    def test_pre_release_ordering(self):
        self.assertTrue(is_newer_release("v0.1.0-beta.3", "0.1.0b2"))
        self.assertFalse(is_newer_release("v0.1.0-beta.1", "0.1.0b2"))

    def test_final_beats_prerelease(self):
        self.assertTrue(is_newer_release("v0.1.0", "0.1.0b3"))

    def test_invalid_tag_raises(self):
        with self.assertRaises(ValueError):
            is_newer_release("not-a-tag", VERSION)


class CheckForUpdateTests(unittest.TestCase):
    def setUp(self):
        # Force a clean cache location for every test.
        self.tmp_cache = Path(self.mktemp()) if False else None
        self.cache_dir = Path(__file__).parent / ".update-check-cache"
        self.cache_file = self.cache_dir / f"test-{id(self)}.json"
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        try:
            if self.cache_file.exists():
                self.cache_file.unlink()
        except OSError:
            pass

    def test_skip_when_opt_out_env_set(self):
        with mock.patch.dict(
            "os.environ", {"AN_KLA_NO_UPDATE_CHECK": "1", "CI": ""}
        ):
            notice = update_check.check_for_update(
                force=False, cache_path=self.cache_file
            )
        self.assertEqual(notice.status, "skipped_by_env:AN_KLA_NO_UPDATE_CHECK")
        self.assertIsNone(notice.latest_release_tag)

    def test_skip_when_ci_env_set(self):
        with mock.patch.dict("os.environ", {"CI": "true"}):
            notice = update_check.check_for_update(
                force=False, cache_path=self.cache_file
            )
        self.assertEqual(notice.status, "skipped_by_env:CI")

    def test_fetch_failure_returns_advisory_status(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with mock.patch.object(
                update_check, "_fetch_latest_release", return_value=None
            ):
                notice = update_check.check_for_update(
                    force=True, cache_path=self.cache_file
                )
        self.assertEqual(notice.status, "fetch_failed")
        self.assertIsNone(notice.latest_release_tag)
        self.assertIsNone(notice.notice)

    def test_same_version_produces_no_notice(self):
        fake_release = {
            "tag_name": f"v{normalized_release_tag_inv(VERSION)}",
            "html_url": "https://example/release",
        }
        with mock.patch.dict("os.environ", {}, clear=True):
            with mock.patch.object(
                update_check, "_fetch_latest_release", return_value=fake_release
            ):
                notice = update_check.check_for_update(
                    force=True, cache_path=self.cache_file
                )
        self.assertEqual(notice.status, "fresh")
        self.assertIsNone(notice.notice)

    def test_newer_version_produces_notice(self):
        # 0.1.0 (final) is strictly newer than any 0.1.0 pre-release.
        fake_release = {
            "tag_name": "v0.1.0",
            "html_url": "https://example/release",
        }
        with mock.patch.dict("os.environ", {}, clear=True):
            with mock.patch.object(
                update_check, "_fetch_latest_release", return_value=fake_release
            ):
                notice = update_check.check_for_update(
                    force=True, cache_path=self.cache_file
                )
        self.assertEqual(notice.status, "fresh")
        self.assertEqual(notice.latest_release_tag, "v0.1.0")
        self.assertIsNotNone(notice.notice)
        self.assertIn("AN-KLA no se actualiza a sí mismo", notice.notice)

    def test_cache_is_used_when_fresh(self):
        fake_release = {
            "tag_name": "v0.1.0",
            "html_url": "https://example/release",
        }
        with mock.patch.dict("os.environ", {}, clear=True):
            with mock.patch.object(
                update_check, "_fetch_latest_release", return_value=fake_release
            ) as fetch_mock:
                update_check.check_for_update(
                    force=True, cache_path=self.cache_file
                )
                # Second call must not hit the network.
                notice2 = update_check.check_for_update(
                    force=False, cache_path=self.cache_file
                )
        self.assertEqual(fetch_mock.call_count, 1)
        self.assertEqual(notice2.status, "cached")
        self.assertEqual(notice2.latest_release_tag, "v0.1.0")


def normalized_release_tag_inv(version: str) -> str:
    """Inverse of normalized_release_tag for test fixtures only."""

    mapping = {
        "0.1.0b1": "0.1.0-beta.1",
        "0.1.0b2": "0.1.0-beta.2",
        "0.1.0b3": "0.1.0-beta.3",
        "0.1.0b4": "0.1.0-beta.4",
        "0.1.0b5": "0.1.0-beta.5",
    }
    if version in mapping:
        return mapping[version]
    if version.count(".") == 2 and "b" not in version:
        return version
    return version


if __name__ == "__main__":
    unittest.main()
