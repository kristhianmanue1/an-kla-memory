"""Tests for P1 (ADR-0013): opt-in multi-stream retrieval."""

from __future__ import annotations

import tempfile
import unittest

from an_kla.retrieval import SCAN_PROFILE, retrieve
from an_kla.store import MemoryStore


def _seed_three_streams(store: MemoryStore, base: str) -> str:
    """Commit one record in each stream via the legacy compatible API."""

    return store.commit(
        expected_current_hash=base,
        checkpoint_patch={},
        facts=[
            {
                "id": "f-multi-1",
                "schema": "an-kla/fact-v1",
                "payload": {"text": "facto sobre multistream retrieval"},
            }
        ],
        events=[
            {
                "id": "e-multi-1",
                "schema": "an-kla/event-v1",
                "payload": {"text": "evento cronologico multistream"},
                "timestamp": "2026-08-03T22:00:00Z",
                "type": "test_event",
            }
        ],
        episodes=[
            {
                "id": "ep-multi-1",
                "schema": "an-kla/episode-v1",
                "payload": {"text": "leccion aprendida en multistream", "outcome": "ok"},
                "timestamp": "2026-08-03T22:00:00Z",
                "type": "lesson",
            }
        ],
    )


class MultiStreamRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(self.temp.name)
        self.base = self.store.initialize()
        self.current = _seed_three_streams(self.store, self.base)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_default_preserves_facts_only_contract(self):
        out = retrieve(self.store, "multistream", 5000)
        self.assertEqual(out["streams_searched"], ["facts"])
        ids = [s["id"] for s in out["selected"]]
        self.assertEqual(ids, ["f-multi-1"])

    def test_streams_explicit_facts_and_episodes(self):
        out = retrieve(
            self.store, "multistream", 5000, streams=["facts", "episodes"]
        )
        self.assertEqual(out["streams_searched"], ["facts", "episodes"])
        ids_streams = {s["stream"] for s in out["selected"]}
        self.assertEqual(ids_streams, {"facts", "episodes"})
        ids = {s["id"] for s in out["selected"]}
        self.assertEqual(ids, {"f-multi-1", "ep-multi-1"})

    def test_streams_all_three(self):
        out = retrieve(
            self.store,
            "multistream",
            5000,
            streams=("facts", "events", "episodes"),
        )
        ids = {s["id"] for s in out["selected"]}
        self.assertEqual(ids, {"f-multi-1", "e-multi-1", "ep-multi-1"})

    def test_streams_duplicates_are_deduped(self):
        out = retrieve(
            self.store,
            "multistream",
            5000,
            streams=["facts", "facts", "facts"],
        )
        ids = [s["id"] for s in out["selected"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, ["f-multi-1"])

    def test_streams_invalid_value_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            retrieve(self.store, "x", 100, streams=("bogus",))
        self.assertIn("unsupported_retrieval_stream", str(ctx.exception))

    def test_streams_empty_tuple_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            retrieve(self.store, "x", 100, streams=())
        self.assertIn("unsupported_retrieval_stream", str(ctx.exception))

    def test_selected_record_carries_stream_field(self):
        out = retrieve(self.store, "multistream", 5000, streams=["episodes"])
        self.assertEqual(len(out["selected"]), 1)
        record = out["selected"][0]
        self.assertEqual(record["stream"], "episodes")
        self.assertEqual(record["id"], "ep-multi-1")

    def test_streams_order_preserved_in_output(self):
        out = retrieve(
            self.store,
            "multistream",
            5000,
            streams=("episodes", "facts"),
        )
        self.assertEqual(out["streams_searched"], ["episodes", "facts"])

    def test_zero_score_excludes_records_from_all_streams(self):
        out = retrieve(
            self.store,
            "zzznoexiste",
            5000,
            streams=("facts", "events", "episodes"),
        )
        self.assertEqual(out["selected"], [])
        self.assertEqual(out["excluded_summary"].get("zero_score", 0), 3)


if __name__ == "__main__":
    unittest.main()
