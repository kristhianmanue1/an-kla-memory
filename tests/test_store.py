from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import multiprocessing
import json

from an_kla.evaluation import evaluate_retrieval
from an_kla.index import build_index
from an_kla.retrieval import retrieve
from an_kla.mcp import ReadOnlyMcp
from an_kla.store import ConcurrentUpdateError, IntegrityError, MemoryStore


def _concurrent_writer(project_root: str, expected: str, event_id: str, queue: multiprocessing.Queue) -> None:
    store = MemoryStore(project_root)
    try:
        result = store.commit(
            expected_current_hash=expected,
            checkpoint_patch={"winner": event_id},
            events=[{"id": event_id, "payload": {"summary": event_id}}],
        )
        queue.put(("committed", result))
    except ConcurrentUpdateError:
        queue.put(("conflict", None))


class MemoryStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(self.temp.name)
        self.root_revision = self.store.initialize()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_initial_current_is_canonical_and_empty(self) -> None:
        self.assertEqual(len(self.store.current_path.read_bytes()), 72)
        snapshot = self.store.snapshot()
        self.assertEqual(snapshot.revision_id, self.root_revision)
        self.assertEqual(snapshot.manifest["revision"], 0)
        self.assertEqual(snapshot.records["facts"], ())

    def test_commit_creates_immutable_child_revision(self) -> None:
        child = self.store.commit(
            expected_current_hash=self.root_revision,
            checkpoint_patch={"goal": "recordar decisiones"},
            facts=[{"id": "f-001", "payload": {"text": "La memoria es datos."}}],
            events=[{"id": "e-001", "payload": {"summary": "inicio"}}],
        )
        snapshot = self.store.snapshot()
        self.assertEqual(snapshot.revision_id, child)
        self.assertEqual(snapshot.manifest["parent"], self.root_revision)
        self.assertEqual(snapshot.checkpoint["goal"], "recordar decisiones")
        self.assertEqual(snapshot.records["facts"][0]["id"], "f-001")
        self.assertTrue((self.store.root / "refs" / "ref-log" / "sha256").exists())

    def test_stale_writer_fails_without_moving_current(self) -> None:
        self.store.commit(
            expected_current_hash=self.root_revision,
            checkpoint_patch={"goal": "first"},
        )
        current = self.store.read_current()
        with self.assertRaises(ConcurrentUpdateError):
            self.store.commit(
                expected_current_hash=self.root_revision,
                checkpoint_patch={"goal": "stale"},
            )
        self.assertEqual(self.store.read_current(), current)

    def test_reader_snapshot_is_stable_after_new_commit(self) -> None:
        first = self.store.commit(
            expected_current_hash=self.root_revision,
            checkpoint_patch={},
            facts=[{"id": "f-001", "payload": {"text": "uno"}}],
        )
        pinned = self.store.snapshot(first)
        self.store.commit(
            expected_current_hash=first,
            checkpoint_patch={},
            facts=[{"id": "f-002", "payload": {"text": "dos"}}],
        )
        self.assertEqual([row["id"] for row in pinned.records["facts"]], ["f-001"])
        self.assertEqual([row["id"] for row in self.store.snapshot().records["facts"]], ["f-001", "f-002"])

    def test_invalid_current_fails_closed(self) -> None:
        self.store.current_path.write_text("bad\n", encoding="ascii")
        with self.assertRaises(IntegrityError):
            self.store.snapshot()

    def test_conflicting_unreferenced_object_is_quarantined(self) -> None:
        checkpoint = {"schema": "an-kla/checkpoint-v1", "revision": 77}
        identifier = self.store._write_json_object("checkpoints", checkpoint)
        path = self.store._path_for("checkpoints", identifier)
        path.write_bytes(b"wrong")
        self.store._write_json_object("checkpoints", checkpoint)
        self.assertEqual(path.read_bytes(), b'{"revision":77,"schema":"an-kla/checkpoint-v1"}')
        self.assertEqual(self.store.doctor()["quarantine_objects"], 1)

    def test_duplicate_id_is_rejected_before_current_moves(self) -> None:
        first = self.store.commit(
            expected_current_hash=self.root_revision,
            checkpoint_patch={},
            facts=[{"id": "f-001", "payload": {"text": "uno"}}],
        )
        with self.assertRaises(Exception):
            self.store.commit(
                expected_current_hash=first,
                checkpoint_patch={},
                facts=[{"id": "f-001", "payload": {"text": "otro"}}],
            )
        self.assertEqual(self.store.read_current(), first)

    def test_retrieval_respects_byte_budget(self) -> None:
        revision = self.store.commit(
            expected_current_hash=self.root_revision,
            checkpoint_patch={},
            facts=[
                {"id": "f-001", "payload": {"text": "memoria decisiones"}},
                {"id": "f-002", "payload": {"text": "irrelevante"}},
            ],
        )
        result = retrieve(self.store, "memoria", 20)
        self.assertEqual(result["revision"], revision)
        self.assertLessEqual(result["used_bytes"], 20)
        self.assertEqual([item["id"] for item in result["selected"]], ["f-001"])

    def test_retrieval_reserves_transport_overhead_and_explains_exclusions(self) -> None:
        self.store.commit(
            expected_current_hash=self.root_revision,
            checkpoint_patch={},
            facts=[
                {"id": "f-001", "payload": {"text": "memoria corta"}},
                {"id": "f-002", "payload": {"text": "memoria demasiado extensa"}},
                {"id": "f-003", "status": "eliminada", "payload": {"text": "memoria"}},
                {"id": "f-004", "payload": {"text": "distractor"}},
            ],
        )
        result = retrieve(self.store, "memoria", 30, fixed_overhead_bytes=8, per_record_overhead_bytes=4)
        self.assertEqual(result["used_bytes"], 25)
        self.assertEqual([item["id"] for item in result["selected"]], ["f-001"])
        self.assertEqual(result["excluded_summary"], {"inactive": 1, "zero_score": 1, "budget": 1})

    def test_index_is_bound_to_revision_when_fts_is_available(self) -> None:
        revision = self.store.commit(
            expected_current_hash=self.root_revision,
            checkpoint_patch={},
            facts=[{"id": "f-001", "payload": {"text": "memoria"}}],
        )
        result = build_index(self.store)
        self.assertEqual(result["revision"], revision)
        if result["index"]:
            self.assertIn(revision[7:], result["index"])

    def test_two_processes_commit_once_and_one_conflicts(self) -> None:
        queue: multiprocessing.Queue = multiprocessing.Queue()
        processes = [
            multiprocessing.Process(target=_concurrent_writer, args=(self.temp.name, self.root_revision, f"e-00{index}", queue))
            for index in (1, 2)
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(10)
            self.assertEqual(process.exitcode, 0)
        outcomes = [queue.get(timeout=2)[0] for _ in processes]
        self.assertEqual(outcomes.count("committed"), 1)
        self.assertEqual(outcomes.count("conflict"), 1)

    def test_twenty_processes_commit_once_and_nineteen_conflict(self) -> None:
        queue: multiprocessing.Queue = multiprocessing.Queue()
        processes = [
            multiprocessing.Process(target=_concurrent_writer, args=(self.temp.name, self.root_revision, f"e-{index:03d}", queue))
            for index in range(1, 21)
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(15)
            self.assertEqual(process.exitcode, 0)
        outcomes = [queue.get(timeout=2)[0] for _ in processes]
        self.assertEqual(outcomes.count("committed"), 1)
        self.assertEqual(outcomes.count("conflict"), 19)

    def test_synthetic_evaluation_uses_revisioned_retrieval(self) -> None:
        self.store.commit(
            expected_current_hash=self.root_revision,
            checkpoint_patch={},
            facts=[
                {"id": "f-003", "payload": {"text": "decisión de presupuesto"}},
                {"id": "f-004", "payload": {"text": "distractor"}},
            ],
        )
        queries = Path(self.temp.name) / "queries.jsonl"
        queries.write_text('{"id":"q","query":"decisión presupuesto","relevant":["f-003"]}\n', encoding="utf-8")
        report = evaluate_retrieval(self.store, queries, 1200)
        self.assertEqual(report["macro"]["recall"], 1.0)

    def test_recovery_never_guesses_past_current(self) -> None:
        report = self.store.recover()
        self.assertEqual(report["current"], self.root_revision)
        self.assertEqual(report["action"], "none_current_authoritative")

    def test_mcp_retrieval_measures_exact_utf8_payload(self) -> None:
        self.store.commit(expected_current_hash=self.root_revision, checkpoint_patch={}, facts=[
            {"id": "f-001", "payload": {"text": "memoria ágil"}},
            {"id": "f-002", "payload": {"text": "memoria muy larga para el límite"}},
        ])
        server = ReadOnlyMcp(self.temp.name)
        payload = server.call("an_kla_retrieve", {"query": "memoria", "budget_bytes": 400})
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.assertEqual(len(encoded), payload["used_bytes"])
        self.assertLessEqual(payload["used_bytes"], payload["budget_bytes"])
        self.assertTrue(payload["untrusted_memory_data"])
        self.assertRaises(ValueError, server.call, "an_kla_retrieve", {"query": "memoria", "budget_bytes": 1})

if __name__ == "__main__":
    unittest.main()
