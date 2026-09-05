"""test_store_subject_ref.py — partición de tests/test_store.py por unidad bajo prueba (beta.22, issue #106).

Casos y aserciones sin cambios; el prelude (imports y helpers de módulo) se
copia del archivo de origen para mantener cada archivo autocontenido.
"""
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
