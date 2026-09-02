from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import multiprocessing
import shutil
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from an_kla.canonical import digest_json
from an_kla.evaluation import evaluate_retrieval
from an_kla.identity import IdentityError, read_binding
from an_kla.index import INDEX_PROFILE, build_index, detect_fts5, record_text, resolve_index, verify_index_deep
from an_kla.retrieval import SCAN_PROFILE, retrieve
from an_kla.mcp import ReadOnlyMcp
from an_kla.store import ConcurrentUpdateError, IntegrityError, LockBusyError, MemoryStore
from an_kla.subject_binding import check_subject_ref_binding
from an_kla.subject_ref import derive_namespace
from an_kla.write_policy import (
    WritePolicyError,
    build_write_plan,
    evaluate_write,
)


def _concurrent_writer(project_root: str, expected: str, event_id: str, queue: multiprocessing.Queue) -> None:
    store = MemoryStore(project_root)
    try:
        result = store.commit(
            expected_current_hash=expected,
            checkpoint_patch={},
            events=[{"id": event_id, "payload": {"summary": event_id}}],
        )
        queue.put(("committed", result))
    except ConcurrentUpdateError:
        queue.put(("conflict", None))
    except LockBusyError:
        queue.put(("busy", None))
    except OSError:
        # Windows: contención de lock-dir/renombrado bajo 20 procesos
        # puede elevar OSError de SO (compartición violada). Es una
        # terminación terminal legítima de contención, no un crash.
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
        parent_checkpoint = self.store.snapshot().manifest["checkpoint"]
        child = self.store.commit(
            expected_current_hash=self.root_revision,
            checkpoint_patch={},
            facts=[{"id": "f-001", "payload": {"text": "La memoria es datos."}}],
            events=[{"id": "e-001", "payload": {"summary": "inicio"}}],
        )
        snapshot = self.store.snapshot()
        self.assertEqual(snapshot.revision_id, child)
        self.assertEqual(snapshot.manifest["parent"], self.root_revision)
        self.assertEqual(snapshot.manifest["checkpoint"], parent_checkpoint)
        self.assertEqual(snapshot.records["facts"][0]["id"], "f-001")
        self.assertTrue((self.store.root / "refs" / "ref-log" / "sha256").exists())

    def test_stale_writer_fails_without_moving_current(self) -> None:
        self.store.commit(
            expected_current_hash=self.root_revision,
            checkpoint_patch={},
        )
        current = self.store.read_current()
        with self.assertRaises(ConcurrentUpdateError):
            self.store.commit(
                expected_current_hash=self.root_revision,
                checkpoint_patch={},
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

    def test_invalid_checkpoint_v2_revision_fails_verify_and_write_closed(self) -> None:
        parent_checkpoint = self.store.snapshot().manifest["checkpoint"]
        state = {
            "schema": "an-kla/working-state-v2",
            "objective": {"value": "x", "provenance": "caller_asserted"},
            "phase": {"value": None, "provenance": "unavailable"},
            "next_step": {"value": None, "provenance": "unavailable"},
            "decisions": [],
            "blockers": [],
            "evidence": [],
            "source_state": {
                "profile": "none/v1",
                "head": {"value": None, "provenance": "unavailable"},
                "branch": {"value": None, "provenance": "unavailable"},
                "dirty_digest": {"value": None, "provenance": "unavailable"},
            },
            "captured_at": {"value": None, "provenance": "unavailable"},
            "supersedes_checkpoint": parent_checkpoint,
        }
        for checkpoint_revision in (-1, 0, 2, True):
            with self.subTest(checkpoint_revision=checkpoint_revision), tempfile.TemporaryDirectory() as root:
                store = MemoryStore(root)
                parent = store.initialize()
                base = store.snapshot(parent)
                state["supersedes_checkpoint"] = base.manifest["checkpoint"]
                checkpoint_id = store._write_json_object(
                    "checkpoints",
                    {
                        "schema": "an-kla/checkpoint-v2",
                        "revision": checkpoint_revision,
                        "working_state": state,
                    },
                )
                manifest = dict(base.manifest)
                manifest.update(
                    {
                        "parent": parent,
                        "revision": 1,
                        "checkpoint": checkpoint_id,
                        "transaction_id": str(uuid.uuid4()),
                    }
                )
                forged = store._write_json_object("revisions", manifest)
                store._replace_current(forged)
                before = set((store.root / "transactions").rglob("*"))
                with self.assertRaisesRegex(IntegrityError, "checkpoint_v2_invalid"):
                    store.verify()
                with self.assertRaisesRegex(IntegrityError, "checkpoint_v2_invalid"):
                    store.commit(expected_current_hash=forged, checkpoint_patch={})
                self.assertEqual(set((store.root / "transactions").rglob("*")), before)

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

    def test_rehashed_incomplete_index_cannot_suppress_scan_match(self) -> None:
        self.store.commit(expected_current_hash=self.root_revision, checkpoint_patch={}, facts=[
            {"id": "f-001", "payload": {"text": "memory critical decision"}},
        ])
        built = build_index(self.store)
        if built["index"]:
            original = self.store.root / built["index"]
            forged_work = Path(self.temp.name) / "forged.sqlite"
            shutil.copyfile(original, forged_work)
            con = sqlite3.connect(forged_work)
            try:
                con.execute("DELETE FROM facts_fts WHERE id = ?", ("f-001",))
                con.commit()
            finally:
                con.close()
            payload = forged_work.read_bytes()
            forged_hash = "sha256:" + hashlib.sha256(payload).hexdigest()
            forged = original.with_name(forged_hash[7:] + ".sqlite")
            self.store._write_immutable(forged, payload)
            reference = self.store.root / built["index_reference"]
            self.store._atomic_write(reference, (forged_hash + "\n").encode("ascii"))

            result = retrieve(self.store, "critical", 200, profile=INDEX_PROFILE)
            self.assertEqual(result["profile"], SCAN_PROFILE)
            self.assertEqual(result["degradation"], "index_candidate_mismatch")
            self.assertEqual([item["id"] for item in result["selected"]], ["f-001"])
            self.assertTrue(verify_index_deep(self.store)["ok"])

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


_SUBJECT_REF_PREFIX = "an-kla:subject:v1:"


def _subject_proposal(
    base: str,
    record_id: str,
    subject_ref: str | None = None,
    *,
    operation: str = "add",
    representation: str = "summary",
    supersedes: str | None = None,
) -> dict:
    record = {"id": record_id, "indexable_text": record_id, "summary": record_id}
    if subject_ref is not None:
        record["subject_ref"] = subject_ref
    candidate = {
        "schema": "an-kla/write-proposal-v1",
        "base_revision": base,
        "stream": "facts",
        "operation": operation,
        "requested_representation": representation,
        "record": record,
        "lineage": {"derived_from_retrieval": False, "refs": []},
    }
    if supersedes is not None:
        candidate["supersedes"] = supersedes
    return candidate


def _subject_authority(candidate: dict, *, authority_class: str = "model_derived") -> dict:
    issuer_kind = {
        "channel_confirmed": "channel",
        "model_derived": "model",
        "unresolved": "unknown",
    }[authority_class]
    return {
        "schema": "an-kla/write-authority-v1",
        "proposal_sha256": digest_json(candidate),
        "base_revision": candidate["base_revision"],
        "authority_class": authority_class,
        "issuer": {
            "kind": issuer_kind,
            "id": "test-authority",
            "configuration_fingerprint": "sha256:" + "b" * 64,
        },
        "evidence": [],
        "scope": {
            "streams": [candidate["stream"]],
            "representations": [candidate["requested_representation"]],
            "operations": [candidate["operation"]],
        },
    }


def _subject_ref_for(namespace: str, kind: str = "decision", subject_id: str = "adr-0033") -> str:
    return f"{_SUBJECT_REF_PREFIX}{kind}:{namespace}:{subject_id}"


class SubjectRefBindingTests(unittest.TestCase):
    """Phase B (issue #59): ``subject_ref`` namespace binding under ``write_lock``.

    The binding check runs inside ``commit_write_plan`` under the store lock,
    after ``resolve_supersede_targets`` and before ``pending`` construction
    (ADR-0033 §Decisión 5). These tests freeze the failure order and the
    zero-effect guarantee using real commits, patches that inject drift, and
    explicit before/after file-set comparisons (never glob order).
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(self.temp.name)
        self.root_revision = self.store.initialize()
        self.namespace = derive_namespace(
            read_binding(self.store)["project_bytes"]
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _file_state(self) -> set[str]:
        # Data files only: lock/gate artifacts (`.reader-gate`, `.write.lock`,
        # `.write.lock-dir`, `.build-*.sqlite`) are concurrency plumbing
        # created on first acquisition, never committed store data. No object,
        # journal, segment or revision path starts with ``.``.
        root = self.store.root
        return {
            str(path.relative_to(root))
            for path in root.rglob("*")
            if path.is_file() and not path.name.startswith(".")
        }

    def _commit(self, candidate, auth, planning, *, expected=None):
        return self.store.commit_write_plan(
            expected_current_hash=expected if expected is not None else candidate["base_revision"],
            plan=planning["plan"],
            proposal=candidate,
            authority=auth,
            decision=planning["decision"],
        )

    def test_commit_accepts_matching_subject_ref_namespace(self) -> None:
        ref = _subject_ref_for(self.namespace)
        candidate = _subject_proposal(self.root_revision, "f-ctx", ref)
        auth = _subject_authority(candidate)
        planning = self.store.plan_write(candidate, auth)

        result = self._commit(candidate, auth, planning)

        self.assertTrue(result["committed"])
        self.assertNotEqual(result["revision"], self.root_revision)
        snapshot = self.store.snapshot(result["revision"])
        committed = snapshot.records["facts"][0]
        # ADR-0033 §7: persists verbatim, no projection.
        self.assertEqual(committed["subject_ref"], ref)

    def test_commit_rejects_mismatch_with_zero_effects(self) -> None:
        other = "p-" + "f" * 32
        candidate = _subject_proposal(
            self.root_revision, "f-ctx", _subject_ref_for(other)
        )
        auth = _subject_authority(candidate)
        planning = self.store.plan_write(candidate, auth)

        files_before = self._file_state()
        current_before = self.store.read_current()
        with self.assertRaises(WritePolicyError) as caught:
            self._commit(candidate, auth, planning)
        self.assertEqual(caught.exception.code, "subject_ref_namespace_mismatch")
        self.assertEqual(str(caught.exception), "subject_ref_namespace_mismatch")
        # Zero effects: CURRENT, objects, journals and segments unchanged.
        self.assertEqual(self.store.read_current(), current_before)
        self.assertEqual(self._file_state(), files_before)

    def test_mismatch_post_state_analogous_to_supersede_target_missing(self) -> None:
        current = self.store.read_current()
        baseline = self._file_state()

        # Probe A: supersede target missing — the pre-existing zero-effect gate
        # that lives immediately before the binding check.
        sup_candidate = _subject_proposal(
            self.root_revision,
            "f-new",
            operation="supersede",
            supersedes="f-ghost",
        )
        sup_auth = _subject_authority(sup_candidate)
        # Issue #103 (H1): plan_write now rejects the missing target earlier
        # (plan_supersede_target_missing); the commit-time zero-effect gate is
        # frozen here via a plan built through the pure policy API.
        sup_decision = evaluate_write(sup_candidate, sup_auth)
        sup_planning = {
            "plan": build_write_plan(sup_candidate, sup_auth, sup_decision),
            "decision": sup_decision,
        }
        with self.assertRaises(WritePolicyError) as caught:
            self._commit(sup_candidate, sup_auth, sup_planning)
        self.assertEqual(caught.exception.code, "invalid_supersede_target")
        self.assertEqual(caught.exception.detail, "target_missing")
        self.assertEqual(self.store.read_current(), current)
        self.assertEqual(self._file_state(), baseline)

        # Probe B: subject_ref namespace mismatch — the new gate. Both failures
        # leave the exact same file tree (zero new objects/journals/segments).
        other = "p-" + "f" * 32
        candidate = _subject_proposal(
            self.root_revision, "f-ctx", _subject_ref_for(other)
        )
        auth = _subject_authority(candidate)
        planning = self.store.plan_write(candidate, auth)
        with self.assertRaises(WritePolicyError) as caught:
            self._commit(candidate, auth, planning)
        self.assertEqual(caught.exception.code, "subject_ref_namespace_mismatch")
        self.assertEqual(self.store.read_current(), current)
        self.assertEqual(self._file_state(), baseline)

    def test_binding_check_after_assert_unchanged(self) -> None:
        # TOCTOU ordering (ADR-0033 §Decisión 5): if the project identity migrates
        # between the unlocked consultation and the locked commit, assert_unchanged
        # fires store_identity_changed BEFORE the binding check. The proposal
        # carries a mismatched namespace so that, were the binding check reached,
        # it would raise subject_ref_namespace_mismatch instead.
        other = "p-" + "f" * 32
        candidate = _subject_proposal(
            self.root_revision, "f-ctx", _subject_ref_for(other)
        )
        auth = _subject_authority(candidate)
        planning = self.store.plan_write(candidate, auth)

        real_binding = read_binding(self.store)
        drifted = dict(real_binding)
        # Different bytes => assert_unchanged detects the change under the lock.
        drifted["project_bytes"] = (
            b'{"schema":"an-kla/project-identity-v1",'
            b'"project_uuid":"00000000-0000-0000-0000-000000000000",'
            b'"created_by_version":"drift"}'
        )
        with patch("an_kla.store.mutation_preflight", return_value=drifted):
            with self.assertRaises(IdentityError) as caught:
                self._commit(candidate, auth, planning)
        self.assertEqual(str(caught.exception), "store_identity_changed")

    def test_binding_check_after_verify_write_plan(self) -> None:
        # Order: verify_write_plan (fingerprint/hash) runs before the binding
        # check. A stale plan_fingerprint yields write_plan_hash_mismatch, not
        # subject_ref_namespace_mismatch, even when the namespace is wrong.
        other = "p-" + "f" * 32
        candidate = _subject_proposal(
            self.root_revision, "f-ctx", _subject_ref_for(other)
        )
        auth = _subject_authority(candidate)
        planning = self.store.plan_write(candidate, auth)

        corrupted = deepcopy(planning)
        corrupted["plan"] = deepcopy(planning["plan"])
        corrupted["plan"]["plan_fingerprint"] = "sha256:" + "a" * 64
        with self.assertRaises(WritePolicyError) as caught:
            self.store.commit_write_plan(
                expected_current_hash=self.root_revision,
                plan=corrupted["plan"],
                proposal=candidate,
                authority=auth,
                decision=corrupted["decision"],
            )
        self.assertEqual(caught.exception.code, "write_plan_hash_mismatch")

    def test_record_without_subject_ref_commits_unchanged(self) -> None:
        # Legacy compatibility (ADR-0033 §7): a record without subject_ref
        # commits with no behavior change.
        candidate = _subject_proposal(self.root_revision, "f-legacy", None)
        auth = _subject_authority(candidate)
        planning = self.store.plan_write(candidate, auth)

        result = self._commit(candidate, auth, planning)

        self.assertTrue(result["committed"])
        snapshot = self.store.snapshot(result["revision"])
        committed = snapshot.records["facts"][0]
        self.assertNotIn("subject_ref", committed)

    def test_all_plan_records_passed_to_binding_check(self) -> None:
        # The store must hand the COMPLETE checked_plan (business record + the
        # auto-generated event record) to the binding guard, and must reuse the
        # binding captured under lock (no identity re-read). A spy capturing the
        # call proves the wiring; the real implementation then validates.
        ref = _subject_ref_for(self.namespace)
        candidate = _subject_proposal(self.root_revision, "f-ctx", ref)
        auth = _subject_authority(candidate)
        planning = self.store.plan_write(candidate, auth)

        captured: dict = {}

        def spy(checked_plan, binding):
            captured["records"] = deepcopy(checked_plan["records"])
            captured["project_bytes"] = binding["project_bytes"]
            return check_subject_ref_binding(checked_plan, binding)

        with patch("an_kla.store.check_subject_ref_binding", side_effect=spy):
            result = self._commit(candidate, auth, planning)

        self.assertTrue(result["committed"])
        # Both plan records were passed in: the business fact (carrying
        # subject_ref) and the generated event record (without subject_ref).
        self.assertEqual(len(captured["records"]), 2)
        business, event = captured["records"]
        self.assertEqual(business["record"].get("subject_ref"), ref)
        self.assertNotIn("subject_ref", event["record"])
        # No identity re-read outside the lock-captured binding.
        self.assertEqual(
            captured["project_bytes"],
            read_binding(self.store)["project_bytes"],
        )

    def test_supersede_target_error_precedes_subject_ref_mismatch(self) -> None:
        # Full order proof: when both a supersede target is missing AND the
        # namespace mismatches, invalid_supersede_target wins — the supersede
        # resolution runs immediately before the binding check.
        other = "p-" + "f" * 32
        candidate = _subject_proposal(
            self.root_revision,
            "f-new",
            _subject_ref_for(other),
            operation="supersede",
            supersedes="f-ghost",
        )
        auth = _subject_authority(candidate)
        # Issue #103 (H1): plan_write now fails closed earlier with
        # plan_supersede_target_missing; this test freezes the commit-time
        # order (supersede resolution immediately before the binding check),
        # so the plan is built through the pure policy API — how a caller
        # racing the TOCTOU window reaches the block.
        decision = evaluate_write(candidate, auth)
        planning = {
            "plan": build_write_plan(candidate, auth, decision),
            "decision": decision,
        }

        current_before = self.store.read_current()
        files_before = self._file_state()
        with self.assertRaises(WritePolicyError) as caught:
            self._commit(candidate, auth, planning)
        self.assertEqual(caught.exception.code, "invalid_supersede_target")
        self.assertEqual(caught.exception.detail, "target_missing")
        self.assertEqual(self.store.read_current(), current_before)
        self.assertEqual(self._file_state(), files_before)

    def test_valid_supersede_then_binding_mismatch_has_no_filesystem_effects(self) -> None:
        # Adversarial M-2: supersede resolution succeeds, then binding fails.
        # Compare every file, including lock/gate dotfiles, byte-for-byte.
        target_ref = _subject_ref_for(self.namespace)
        target = _subject_proposal(self.root_revision, "f-target", target_ref)
        target_auth = _subject_authority(target)
        target_plan = self.store.plan_write(target, target_auth)
        committed = self._commit(target, target_auth, target_plan)

        other = "p-" + "f" * 32
        candidate = _subject_proposal(
            committed["revision"],
            "f-successor",
            _subject_ref_for(other),
            operation="supersede",
            supersedes="f-target",
        )
        auth = _subject_authority(candidate)
        planning = self.store.plan_write(candidate, auth)
        files_before = {
            str(path.relative_to(self.store.root)): path.read_bytes()
            for path in self.store.root.rglob("*")
            if path.is_file()
        }

        with self.assertRaises(WritePolicyError) as caught:
            self._commit(candidate, auth, planning)

        self.assertEqual(caught.exception.code, "subject_ref_namespace_mismatch")
        self.assertEqual(self.store.read_current(), committed["revision"])
        files_after = {
            str(path.relative_to(self.store.root)): path.read_bytes()
            for path in self.store.root.rglob("*")
            if path.is_file()
        }
        self.assertEqual(files_after, files_before)


if __name__ == "__main__":
    unittest.main()
