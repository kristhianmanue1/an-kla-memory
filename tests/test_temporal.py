from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from an_kla.temporal import (
    MICROSECONDS_PER_DAY,
    TemporalError,
    compute_freshness,
    format_utc,
    normalize_freshness_now,
    parse_verified_at,
    project_record_freshness,
    validate_stale_after_days,
)


class VerifiedAtGrammarTests(unittest.TestCase):
    def test_closed_grammar_accepts_canonical_variants(self) -> None:
        cases = {
            "2026-08-08T00:00:00Z": "2026-08-08T00:00:00.000000Z",
            "2026-08-08T01:02:03.1+02:00": "2026-08-07T23:02:03.100000Z",
            "2026-08-08T01:02:03.123456-05:30": "2026-08-08T06:32:03.123456Z",
            "2026-08-08T00:00:00+14:00": "2026-08-07T10:00:00.000000Z",
            "2026-08-08T00:00:00-14:00": "2026-08-08T14:00:00.000000Z",
            "2026-08-08T00:00:00-00:01": "2026-08-08T00:01:00.000000Z",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(format_utc(parse_verified_at(text)), expected)

    def test_closed_grammar_rejects_lexical_and_calendar_variants(self) -> None:
        cases = (
            "2026-08-08 00:00:00Z",
            "2026-08-08T00:00Z",
            "2026-08-08T00:00:00z",
            "2026-08-08T00:00:00",
            "2026-08-08T00:00:00.1234567Z",
            "2026-02-30T00:00:00Z",
            "2026-08-08T00:00:00-00:00",
            "2026-08-08T00:00:00+14:01",
            "2026-08-08T00:00:00-14:01",
            "2026-08-08T00:00:00+15:00",
        )
        for text in cases:
            with self.subTest(text=text), self.assertRaises(TemporalError) as caught:
                parse_verified_at(text)
            self.assertEqual(caught.exception.code, "unparseable_verified_at")

    def test_utc_unrepresentable_extremes_are_distinct(self) -> None:
        for text in (
            "0001-01-01T00:00:00+14:00",
            "9999-12-31T23:59:59-14:00",
        ):
            with self.subTest(text=text), self.assertRaises(TemporalError) as caught:
                parse_verified_at(text)
            self.assertEqual(caught.exception.code, "unrepresentable_verified_at")


class FreshnessProjectionTests(unittest.TestCase):
    NOW = datetime(2026, 8, 8, tzinfo=timezone.utc)

    def test_complete_days_and_threshold_are_exact(self) -> None:
        stale = compute_freshness("2026-07-29T00:00:00Z", self.NOW, 7)
        self.assertEqual(stale["days_since_verified"], 10)
        self.assertTrue(stale["stale"])
        fresh = compute_freshness("2026-07-29T00:00:00Z", self.NOW, 30)
        self.assertNotIn("stale", fresh)

    def test_future_dates_truncate_toward_zero_and_never_mark_stale(self) -> None:
        one_hour = compute_freshness("2026-08-08T01:00:00Z", self.NOW, 0)
        twenty_five = compute_freshness("2026-08-09T01:00:00Z", self.NOW, 0)
        self.assertEqual(one_hour["days_since_verified"], 0)
        self.assertEqual(twenty_five["days_since_verified"], -1)
        self.assertNotIn("stale", one_hour)
        self.assertNotIn("stale", twenty_five)

    def test_integer_arithmetic_handles_large_and_boundary_deltas(self) -> None:
        verified = parse_verified_at("0001-01-02T00:00:00Z")
        now = datetime(2738, 11, 28, 23, 59, 59, 999999, tzinfo=timezone.utc)
        projection = compute_freshness("0001-01-02T00:00:00Z", now)
        delta = now - verified
        exact_micros = (
            (delta.days * 86_400 + delta.seconds) * 1_000_000
            + delta.microseconds
        )
        self.assertGreater(delta.days, 999_000)
        self.assertEqual(
            projection["days_since_verified"],
            exact_micros // MICROSECONDS_PER_DAY,
        )

    def test_twenty_four_hour_boundaries_are_exact_to_one_microsecond(self) -> None:
        cases = {
            "2026-08-07T00:00:00.000001Z": 0,
            "2026-08-07T00:00:00.000000Z": 1,
            "2026-08-06T23:59:59.999999Z": 1,
            "2026-08-08T23:59:59.999999Z": 0,
            "2026-08-09T00:00:00.000000Z": -1,
            "2026-08-09T00:00:00.000001Z": -1,
        }
        for verified_at, expected in cases.items():
            with self.subTest(verified_at=verified_at):
                self.assertEqual(
                    compute_freshness(verified_at, self.NOW)["days_since_verified"],
                    expected,
                )

    def test_legacy_values_are_projected_without_mutation(self) -> None:
        self.assertEqual(compute_freshness(None, self.NOW), {})
        self.assertEqual(compute_freshness(42, self.NOW), {})
        invalid = compute_freshness("not-a-date", self.NOW)
        self.assertEqual(
            invalid,
            {
                "verified_at": "not-a-date",
                "freshness_error": "unparseable_verified_at",
            },
        )
        unrepresentable = compute_freshness(
            "0001-01-01T00:00:00+14:00", self.NOW
        )
        self.assertEqual(
            unrepresentable["freshness_error"],
            "unrepresentable_verified_at",
        )

    def test_record_projection_only_reads_verified_at(self) -> None:
        record = {"id": "f-1", "verified_at": "2026-08-07T00:00:00Z"}
        before = dict(record)
        self.assertEqual(
            project_record_freshness(record, self.NOW),
            {"verified_at": record["verified_at"], "days_since_verified": 1},
        )
        self.assertEqual(record, before)

    def test_invalid_now_and_threshold_have_stable_codes(self) -> None:
        with self.assertRaises(TemporalError) as naive:
            normalize_freshness_now(datetime(2026, 8, 8))
        self.assertEqual(naive.exception.code, "invalid_freshness_now")
        for threshold in (True, -1, 1.5, "7"):
            with self.subTest(threshold=threshold), self.assertRaises(
                TemporalError
            ) as caught:
                validate_stale_after_days(threshold)  # type: ignore[arg-type]
            self.assertEqual(caught.exception.code, "invalid_stale_after_days")

    def test_now_that_overflows_during_utc_normalization_is_rejected(self) -> None:
        cases = (
            datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=14))),
            datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone(timedelta(hours=-14))),
        )
        for value in cases:
            with self.subTest(value=value), self.assertRaises(TemporalError) as caught:
                normalize_freshness_now(value)
            self.assertEqual(caught.exception.code, "invalid_freshness_now")

    def test_temporal_module_contains_no_clock_reads(self) -> None:
        path = Path(__file__).resolve().parents[1] / "an_kla" / "temporal.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        forbidden = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"now", "today", "utcnow"}
        }
        self.assertEqual(forbidden, set())

    def test_format_utc_is_fixed_width_and_offset_normalized(self) -> None:
        value = datetime(
            9,
            2,
            3,
            4,
            5,
            6,
            7,
            tzinfo=timezone(timedelta(hours=2)),
        )
        self.assertEqual(format_utc(value), "0009-02-03T02:05:06.000007Z")


if __name__ == "__main__":
    unittest.main()
