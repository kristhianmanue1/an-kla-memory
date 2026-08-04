"""Tests for P3 (ADR-0015): excluded_detail transparency."""

from __future__ import annotations

import tempfile
import unittest

from an_kla.retrieval import EXCLUDED_DETAIL_CAP, retrieve
from an_kla.store import MemoryStore


class ExcludedDetailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(self.temp.name)
        self.base = self.store.initialize()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _seed_many_facts(self, n: int) -> None:
        facts = [
            {
                "id": f"f-big-{i:03d}",
                "schema": "an-kla/fact-v1",
                "payload": {"text": f"documento largo numero {i} " * 30},
            }
            for i in range(n)
        ]
        self.store.commit(
            expected_current_hash=self.base,
            checkpoint_patch={},
            facts=facts,
        )

    def test_budget_exclusion_lists_ids(self):
        self._seed_many_facts(3)
        out = retrieve(self.store, "documento", budget=200)
        self.assertIn("budget", out["excluded_summary"])
        self.assertGreaterEqual(out["excluded_summary"]["budget"], 1)
        self.assertIn("budget", out["excluded_detail"]["ids"])
        self.assertGreaterEqual(len(out["excluded_detail"]["ids"]["budget"]), 1)
        self.assertFalse(out["excluded_detail"]["truncated"]["budget"])

    def test_zero_score_exclusion_lists_ids(self):
        self._seed_many_facts(3)
        out = retrieve(self.store, "zzznmatch", budget=10000)
        self.assertEqual(out["excluded_summary"].get("zero_score", 0), 3)
        ids = out["excluded_detail"]["ids"]["zero_score"]
        self.assertEqual(len(ids), 3)
        self.assertIn("f-big-000", ids)

    def test_truncation_at_cap(self):
        # Seed more than EXCLUDED_DETAIL_CAP facts that all match the query
        # but blow the budget: only the first CAP budget-excluded IDs appear.
        self._seed_many_facts(EXCLUDED_DETAIL_CAP + 30)
        out = retrieve(self.store, "documento", budget=200)
        budget_count = out["excluded_summary"]["budget"]
        self.assertGreater(budget_count, EXCLUDED_DETAIL_CAP)
        self.assertEqual(len(out["excluded_detail"]["ids"]["budget"]), EXCLUDED_DETAIL_CAP)
        self.assertTrue(out["excluded_detail"]["truncated"]["budget"])
        self.assertEqual(out["excluded_detail"]["cap"], EXCLUDED_DETAIL_CAP)

    def test_no_text_records_are_tracked(self):
        self.store.commit(
            expected_current_hash=self.base,
            checkpoint_patch={},
            facts=[
                {"id": "f-empty", "schema": "an-kla/fact-v1", "payload": {}},
                {"id": "f-real", "schema": "an-kla/fact-v1", "payload": {"text": "documento real"}},
            ],
        )
        out = retrieve(self.store, "documento", budget=10000)
        self.assertEqual(out["excluded_summary"].get("no_text", 0), 1)
        self.assertEqual(out["excluded_detail"]["ids"]["no_text"], ["f-empty"])

    def test_inactive_records_are_tracked(self):
        self.store.commit(
            expected_current_hash=self.base,
            checkpoint_patch={},
            facts=[
                {
                    "id": "f-inactive",
                    "schema": "an-kla/fact-v1",
                    "status": "sustituida",
                    "payload": {"text": "documento inactivo"},
                },
                {"id": "f-real", "schema": "an-kla/fact-v1", "payload": {"text": "documento real"}},
            ],
        )
        out = retrieve(self.store, "documento", budget=10000)
        self.assertEqual(out["excluded_summary"].get("inactive", 0), 1)
        self.assertEqual(out["excluded_detail"]["ids"]["inactive"], ["f-inactive"])

    def test_empty_detail_keys_omitted(self):
        # Single happy path: one matching record, no exclusions at all.
        self.store.commit(
            expected_current_hash=self.base,
            checkpoint_patch={},
            facts=[{"id": "f-lone", "schema": "an-kla/fact-v1", "payload": {"text": "documento unico"}}],
        )
        out = retrieve(self.store, "documento", budget=10000)
        self.assertEqual(out["excluded_detail"]["ids"], {})


if __name__ == "__main__":
    unittest.main()
