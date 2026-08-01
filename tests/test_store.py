from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import multiprocessing
import json
import sqlite3

from an_kla.evaluation import evaluate_retrieval
from an_kla.index import INDEX_PROFILE, build_index, detect_fts5, record_text, resolve_index, verify_index_deep
from an_kla.retrieval import SCAN_PROFILE, retrieve
from an_kla.mcp import ReadOnlyMcp
from an_kla.store import ConcurrentUpdateError, IntegrityError, LockBusyError, MemoryStore


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
    except LockBusyError:
        queue.put(("busy", None))


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

    def test_fixed_overhead_cannot_exceed_budget(self) -> None:
        self.store.commit(
            expected_current_hash=self.root_revision,
            checkpoint_patch={},
            facts=[{"id": "f-001", "payload": {"text": "memoria"}}],
        )
        exact = retrieve(self.store, "memoria", 8, fixed_overhead_bytes=8)
        self.assertEqual(exact["used_bytes"], 8)
        self.assertEqual(exact["selected"], [])
        with self.assertRaisesRegex(ValueError, "fixed_overhead_exceeds_budget"):
            retrieve(self.store, "memoria", 8, fixed_overhead_bytes=9)

    def test_index_is_bound_to_revision_when_fts_is_available(self) -> None:
        revision = self.store.commit(
            expected_current_hash=self.root_revision,
            checkpoint_patch={},
            facts=[{"id": "f-001", "payload": {"text": "memoria"}}],
        )
        result = build_index(self.store)
        self.assertEqual(result["revision"], revision)
        if detect_fts5():
            self.assertIsNotNone(result["index"])
            self.assertEqual(result["profile"], "sqlite-fts5/v1")
            self.assertIn(revision[7:], result["index"])
            self.assertEqual(resolve_index(self.store, revision), self.store.root / result["index"])
            self.assertIn("CURRENT", result["index_reference"])
            self.assertTrue(verify_index_deep(self.store)["ok"])
        else:
            self.assertIsNone(result["index"])

    def test_detect_fts5_matches_direct_sqlite_capability(self) -> None:
        con = sqlite3.connect(":memory:")
        try:
            try:
                con.execute("CREATE VIRTUAL TABLE probe USING fts5(text)")
                available = True
            except sqlite3.DatabaseError:
                available = False
        finally:
            con.close()
        self.assertEqual(detect_fts5(), available)

    def test_retrieval_excludes_fact_without_supported_text(self) -> None:
        self.store.commit(expected_current_hash=self.root_revision, checkpoint_patch={}, facts=[
            {"id": "f-001", "payload": {"other": "not searchable"}},
            {"id": "f-002", "render": "memoria recuperable"},
        ])
        result = retrieve(self.store, "memoria", 200)
        self.assertEqual([item["id"] for item in result["selected"]], ["f-002"])
        self.assertEqual(result["excluded_summary"], {"no_text": 1})

    def test_record_text_supports_hybrid_fallbacks_and_rejects_non_text(self) -> None:
        self.assertEqual(
            record_text({"payload": {"meta": "x"}, "render": " visible legacy "}),
            "visible legacy",
        )
        self.assertEqual(
            record_text({"payload": {"text": None}, "render": "visible fallback"}),
            "visible fallback",
        )
        self.assertEqual(record_text({"payload": {"text": 123}}), "")
        self.assertEqual(record_text({"payload": " raw legacy payload "}), "raw legacy payload")
        self.assertEqual(
            record_text({"payload": "raw fallback", "text": "normative root"}),
            "normative root",
        )
        self.assertEqual(
            record_text({"payload": {"render": "payload render"}, "text": "root text"}),
            "root text",
        )

    def test_mixed_legacy_shapes_remain_retrievable_after_upgrade(self) -> None:
        facts = [
            {"id": f"f-render-{index:02d}", "render": f"legacytoken {index}", "tags": ["legacy"]}
            for index in range(22)
        ]
        facts.extend(
            {"id": f"f-text-{index:02d}", "payload": {"text": f"moderntoken {index}"}, "status": "active"}
            for index in range(18)
        )
        facts.append({
            "id": "f-mixed",
            "payload": {"text": "prioritytoken", "render": "ignoredtoken"},
            "render": "outerignoredtoken",
        })
        self.store.commit(
            expected_current_hash=self.root_revision,
            checkpoint_patch={},
            facts=facts,
        )
        legacy = retrieve(self.store, "legacytoken", 100_000)
        modern = retrieve(self.store, "moderntoken", 100_000)
        priority = retrieve(self.store, "prioritytoken", 100_000)
        self.assertEqual(len(legacy["selected"]), 22)
        self.assertEqual(len(modern["selected"]), 18)
        self.assertEqual([item["id"] for item in priority["selected"]], ["f-mixed"])

    def test_scan_is_default_even_when_an_index_exists(self) -> None:
        self.store.commit(expected_current_hash=self.root_revision, checkpoint_patch={}, facts=[
            {"id": "f-001", "payload": {"text": "memory budget"}},
        ])
        build_index(self.store)
        result = retrieve(self.store, "memory", 200)
        self.assertEqual(result["requested_profile"], SCAN_PROFILE)
        self.assertEqual(result["profile"], SCAN_PROFILE)
        self.assertEqual(result["degradation"], "none")

    def test_unknown_retrieval_profile_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported_retrieval_profile"):
            retrieve(self.store, "memory", 200, profile="unknown/v1")

    def test_retrieval_uses_only_explicit_index_reference(self) -> None:
        revision = self.store.commit(expected_current_hash=self.root_revision, checkpoint_patch={}, facts=[
            {"id": "f-001", "payload": {"text": "memoria indexada"}},
        ])
        built = build_index(self.store)
        result = retrieve(self.store, "memoria", 200, profile=INDEX_PROFILE)
        if built["index"]:
            self.assertEqual(result["profile"], "sqlite-fts5/v1")
            reference = self.store.root / built["index_reference"]
            reference.unlink()
            fallback = retrieve(self.store, "memoria", 200, profile=INDEX_PROFILE)
            self.assertEqual(fallback["profile"], "scan-fallback/v1")
            self.assertEqual(fallback["degradation"], "index_unavailable")
        else:
            self.assertEqual(result["profile"], "scan-fallback/v1")
        self.assertEqual(result["revision"], revision)

    def test_fts_and_scan_are_equivalent_for_ascii_compatible_tokens(self) -> None:
        self.store.commit(expected_current_hash=self.root_revision, checkpoint_patch={}, facts=[
            {"id": "f-001", "payload": {"text": "memory budget decision"}},
            {"id": "f-002", "payload": {"text": "memory exception"}},
            {"id": "f-003", "payload": {"text": "unrelated"}},
        ])
        built = build_index(self.store)
        indexed = retrieve(self.store, "memory budget", 200, profile=INDEX_PROFILE)
        if built["index"]:
            reference = self.store.root / built["index_reference"]
            reference.unlink()
            scanned = retrieve(self.store, "memory budget", 200)
            self.assertEqual(indexed["selected"], scanned["selected"])
            self.assertEqual(indexed["used_bytes"], scanned["used_bytes"])

    def test_semantically_tampered_index_falls_back_explicitly(self) -> None:
        self.store.commit(expected_current_hash=self.root_revision, checkpoint_patch={}, facts=[
            {"id": "f-001", "payload": {"text": "memory critical decision"}},
        ])
        built = build_index(self.store)
        if built["index"]:
            path = self.store.root / built["index"]
            con = sqlite3.connect(path)
            try:
                con.execute("DELETE FROM facts_fts WHERE id = ?", ("f-001",))
                con.commit()
            finally:
                con.close()
            result = retrieve(self.store, "critical", 200, profile=INDEX_PROFILE)
            self.assertEqual(result["profile"], SCAN_PROFILE)
            self.assertEqual(result["degradation"], "index_hash_mismatch")
            self.assertEqual([item["id"] for item in result["selected"]], ["f-001"])
            self.assertFalse(verify_index_deep(self.store)["ok"])

    def test_doctor_counts_legacy_index_temporary(self) -> None:
        legacy = self.store.root / "indexes" / ".build-leftover.sqlite"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_bytes(b"temporary")
        self.assertEqual(self.store.doctor()["index_orphan_temporaries"], 1)

    def test_two_processes_commit_once_and_one_terminal_result(self) -> None:
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
        self.assertEqual(outcomes.count("conflict") + outcomes.count("busy"), 1)

    def test_twenty_processes_commit_once_and_nineteen_terminal_results(self) -> None:
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
        self.assertEqual(outcomes.count("conflict") + outcomes.count("busy"), 19)

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
