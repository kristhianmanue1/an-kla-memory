from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from an_kla.canonical import canonical_json
from an_kla.index import INDEX_PROFILE, build_index, detect_fts5
from an_kla.retrieval import retrieve
from an_kla.store import MemoryStore
from an_kla.temporal import FRESHNESS_PROFILE, TemporalError


REVISION = "sha256:" + "a" * 64
NOW = datetime(2026, 8, 8, tzinfo=timezone.utc)
TEMPORAL_ITEM_KEYS = {
    "verified_at",
    "days_since_verified",
    "stale",
    "freshness_error",
}


class StubStore:
    def __init__(self) -> None:
        self.records = (
            {"id": "f-valid", "indexable_text": "needle valid", "verified_at": "2026-08-01T00:00:00Z"},
            {"id": "f-invalid", "indexable_text": "needle invalid", "verified_at": "opaque-beta8"},
            {"id": "f-null", "indexable_text": "needle null", "verified_at": None},
            {"id": "f-nonstr", "indexable_text": "needle number", "verified_at": 7},
            {"id": "f-missing", "indexable_text": "needle missing"},
        )

    def snapshot(self) -> SimpleNamespace:
        return SimpleNamespace(
            revision_id=REVISION,
            records={"facts": self.records, "events": (), "episodes": ()},
        )


class RetrievalFreshnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = StubStore()

    def test_v1_payload_is_golden_and_does_not_read_clock(self) -> None:
        class ClockBomb:
            @classmethod
            def now(cls, _zone):
                raise AssertionError("v1_must_not_read_clock")

        with patch("an_kla.retrieval.datetime", ClockBomb):
            result = retrieve(self.store, "needle", 10_000)  # type: ignore[arg-type]
        expected = {
            "schema": "an-kla/retrieval-result-v1",
            "revision": REVISION,
            "requested_profile": "scan-fallback/v1",
            "profile": "scan-fallback/v1",
            "degradation": "none",
            "streams_searched": ["facts"],
            "budget_bytes": 10_000,
            "used_bytes": 64,
            "reserved_overhead_bytes": {"fixed": 0, "per_record": 0},
            "excluded_summary": {},
            "excluded_detail": {"ids": {}, "truncated": {}, "cap": 50},
            "selected": [
                {"id": "f-invalid", "stream": "facts", "score": 1, "render": "needle invalid", "cost_bytes": 14},
                {"id": "f-missing", "stream": "facts", "score": 1, "render": "needle missing", "cost_bytes": 14},
                {"id": "f-nonstr", "stream": "facts", "score": 1, "render": "needle number", "cost_bytes": 13},
                {"id": "f-null", "stream": "facts", "score": 1, "render": "needle null", "cost_bytes": 11},
                {"id": "f-valid", "stream": "facts", "score": 1, "render": "needle valid", "cost_bytes": 12},
            ],
        }
        self.assertEqual(canonical_json(result), canonical_json(expected))

    def test_v2_preserves_selection_scores_costs_and_used_bytes(self) -> None:
        v1 = retrieve(self.store, "needle", 10_000)  # type: ignore[arg-type]
        v2 = retrieve(
            self.store,  # type: ignore[arg-type]
            "needle",
            10_000,
            freshness_profile=FRESHNESS_PROFILE,
            now=NOW,
            stale_after_days=6,
        )
        self.assertEqual(v2["schema"], "an-kla/retrieval-result-v2")
        self.assertEqual(v2["used_bytes"], v1["used_bytes"])
        self.assertEqual(
            [item["id"] for item in v2["selected"]],
            [item["id"] for item in v1["selected"]],
        )
        stripped = [
            {key: value for key, value in item.items() if key not in TEMPORAL_ITEM_KEYS}
            for item in v2["selected"]
        ]
        self.assertEqual(stripped, v1["selected"])
        items = {item["id"]: item for item in v2["selected"]}
        self.assertEqual(
            items["f-invalid"]["freshness_error"],
            "unparseable_verified_at",
        )
        self.assertNotIn("verified_at", items["f-missing"])
        self.assertNotIn("verified_at", items["f-null"])
        self.assertNotIn("verified_at", items["f-nonstr"])
        self.assertEqual(items["f-valid"]["days_since_verified"], 7)
        self.assertTrue(items["f-valid"]["stale"])
        self.assertEqual(
            v2["freshness"],
            {
                "semantics": "self_asserted_timestamp",
                "source_field": "record.verified_at",
                "computed_at": "2026-08-08T00:00:00.000000Z",
                "stale_after_days": 6,
                "evaluated": 1,
                "not_evaluable": 3,
                "unparseable": 1,
                "stale": 1,
            },
        )

    def test_default_now_is_captured_once_for_all_selected_items(self) -> None:
        class OneShotClock:
            calls = 0

            @classmethod
            def now(cls, zone):
                cls.calls += 1
                self.assertIs(zone, timezone.utc)
                return NOW

        with patch("an_kla.retrieval.datetime", OneShotClock):
            result = retrieve(
                self.store,  # type: ignore[arg-type]
                "needle",
                10_000,
                freshness_profile=FRESHNESS_PROFILE,
            )
        self.assertEqual(OneShotClock.calls, 1)
        self.assertEqual(
            result["freshness"]["computed_at"],
            "2026-08-08T00:00:00.000000Z",
        )

    def test_profile_cooccurrence_and_validation_errors_are_stable(self) -> None:
        cases = (
            ({"now": NOW}, "freshness_profile_required"),
            ({"stale_after_days": 7}, "freshness_profile_required"),
            ({"now": "bad", "stale_after_days": True}, "freshness_profile_required"),
            ({"freshness_profile": "unknown/v1"}, "unsupported_freshness_profile"),
            (
                {"freshness_profile": "unknown/v1", "now": "bad", "stale_after_days": True},
                "unsupported_freshness_profile",
            ),
            (
                {"freshness_profile": FRESHNESS_PROFILE, "now": datetime(2026, 8, 8)},
                "invalid_freshness_now",
            ),
            (
                {"freshness_profile": FRESHNESS_PROFILE, "now": NOW, "stale_after_days": True},
                "invalid_stale_after_days",
            ),
        )
        for kwargs, expected in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(TemporalError) as caught:
                retrieve(self.store, "needle", 10_000, **kwargs)  # type: ignore[arg-type]
            self.assertEqual(caught.exception.code, expected)

    def test_null_threshold_never_emits_stale(self) -> None:
        result = retrieve(
            self.store,  # type: ignore[arg-type]
            "needle",
            10_000,
            freshness_profile=FRESHNESS_PROFILE,
            now=NOW,
        )
        self.assertIsNone(result["freshness"]["stale_after_days"])
        self.assertTrue(all("stale" not in item for item in result["selected"]))

    def test_projection_does_not_change_budget_exclusions(self) -> None:
        v1 = retrieve(self.store, "needle", 30)  # type: ignore[arg-type]
        v2 = retrieve(
            self.store,  # type: ignore[arg-type]
            "needle",
            30,
            freshness_profile=FRESHNESS_PROFILE,
            now=NOW,
        )
        self.assertEqual(v2["used_bytes"], v1["used_bytes"])
        self.assertEqual(v2["excluded_summary"], v1["excluded_summary"])
        self.assertEqual(v2["excluded_detail"], v1["excluded_detail"])
        self.assertEqual(
            [item["id"] for item in v2["selected"]],
            [item["id"] for item in v1["selected"]],
        )

    @unittest.skipUnless(detect_fts5(), "SQLite build lacks FTS5")
    def test_scan_and_index_emit_identical_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(directory)
            root = store.initialize()
            revision = store.commit(
                expected_current_hash=root,
                checkpoint_patch={},
                facts=[
                    {
                        "id": "f-temporal",
                        "indexable_text": "needle temporal",
                        "verified_at": "2026-08-01T00:00:00Z",
                    }
                ],
            )
            build_index(store, revision_id=revision)
            scan = retrieve(
                store,
                "needle",
                10_000,
                freshness_profile=FRESHNESS_PROFILE,
                now=NOW,
            )
            indexed = retrieve(
                store,
                "needle",
                10_000,
                profile=INDEX_PROFILE,
                freshness_profile=FRESHNESS_PROFILE,
                now=NOW,
            )
            self.assertEqual(indexed["degradation"], "none")
            self.assertEqual(indexed["selected"], scan["selected"])
            self.assertEqual(indexed["freshness"], scan["freshness"])

    @unittest.skipUnless(detect_fts5(), "SQLite build lacks FTS5")
    def test_index_degradations_preserve_scan_selection_and_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(directory)
            root = store.initialize()
            revision = store.commit(
                expected_current_hash=root,
                checkpoint_patch={},
                facts=[
                    {
                        "id": "f-temporal",
                        "indexable_text": "needle temporal",
                        "verified_at": "2026-08-01T00:00:00Z",
                    }
                ],
            )
            kwargs = {
                "freshness_profile": FRESHNESS_PROFILE,
                "now": NOW,
            }
            scan = retrieve(store, "needle", 10_000, **kwargs)
            unavailable = retrieve(
                store,
                "needle",
                10_000,
                profile=INDEX_PROFILE,
                **kwargs,
            )
            self.assertEqual(unavailable["degradation"], "index_unavailable")
            self.assertEqual(unavailable["selected"], scan["selected"])

            built = build_index(store, revision_id=revision)
            with patch("an_kla.retrieval._narrow_with_index", return_value=set()):
                mismatch = retrieve(
                    store,
                    "needle",
                    10_000,
                    profile=INDEX_PROFILE,
                    **kwargs,
                )
            self.assertEqual(mismatch["degradation"], "index_candidate_mismatch")
            self.assertEqual(mismatch["selected"], scan["selected"])
            index_path = store.root / built["index"]
            index_path.write_bytes(index_path.read_bytes() + b"corrupt")
            corrupt = retrieve(
                store,
                "needle",
                10_000,
                profile=INDEX_PROFILE,
                **kwargs,
            )
            self.assertEqual(corrupt["degradation"], "index_hash_mismatch")
            self.assertEqual(corrupt["selected"], scan["selected"])


if __name__ == "__main__":
    unittest.main()
