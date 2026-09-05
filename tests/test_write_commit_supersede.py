"""test_write_commit_supersede.py — partición de tests/test_write_commit.py por unidad bajo prueba (beta.22, issue #106).

Casos y aserciones sin cambios; el prelude (imports y helpers de módulo) se
copia del archivo de origen para mantener cada archivo autocontenido.
"""
from __future__ import annotations

from copy import deepcopy
import json
import multiprocessing
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

from an_kla.canonical import digest_json
from an_kla.retrieval import retrieve
from an_kla.store import LockBusyError, MemoryStore
from an_kla.write_policy import (
    WritePolicyError,
    build_write_plan as pure_build_write_plan,
    evaluate_write as pure_evaluate_write,
    verify_write_plan as pure_verify_write_plan,
)


DIGEST_B = "sha256:" + "b" * 64
BETA8_POLICY_FINGERPRINT = (
    "sha256:41d23cf05e393c31e8b88f2bb1e415c0a3961bc963c01944e1ef8cae892eaa77"
)


def proposal(base: str, record_id: str = "f-policy", *, representation: str = "summary") -> dict:
    return {
        "schema": "an-kla/write-proposal-v1",
        "base_revision": base,
        "stream": "facts",
        "operation": "add",
        "requested_representation": representation,
        "record": {"id": record_id, "payload": {"text": "memoria durable"}},
        "lineage": {"derived_from_retrieval": False, "refs": []},
    }


def authority(candidate: dict, *, authority_class: str = "model_derived") -> dict:
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
            "configuration_fingerprint": DIGEST_B,
        },
        "evidence": [],
        "scope": {
            "streams": [candidate["stream"]],
            "representations": [candidate["requested_representation"]],
            "operations": [candidate["operation"]],
        },
    }


def beta8_planning(candidate: dict, auth: dict) -> tuple[dict, dict]:
    """Build the frozen beta.8 shape, including formerly opaque record keys."""

    proposal_sha256 = digest_json(candidate)
    authority_sha256 = digest_json(auth)
    decision = {
        "schema": "an-kla/write-decision-v1",
        "proposal_sha256": proposal_sha256,
        "authority_sha256": authority_sha256,
        "policy_profile": "write-policy/v1",
        "policy_fingerprint": BETA8_POLICY_FINGERPRINT,
        "decision": "write-summary",
        "reason_codes": ["derived_authority_capped", "representation_accepted"],
    }
    records = [
        {
            "stream": candidate["stream"],
            "operation": candidate["operation"],
            "representation": candidate["requested_representation"],
            "record": deepcopy(candidate["record"]),
        },
        {
            "stream": "events",
            "operation": "add",
            "representation": "summary",
            "record": {
                "schema": "an-kla/event-v1",
                "id": "e-write-policy-" + proposal_sha256[7:],
                "type": "write_policy_decision",
                "payload": {
                    "authority_class": auth["authority_class"],
                    "authority_sha256": authority_sha256,
                    "decision": decision["decision"],
                    "policy_fingerprint": BETA8_POLICY_FINGERPRINT,
                    "policy_profile": decision["policy_profile"],
                    "proposal_sha256": proposal_sha256,
                    "reason_codes": deepcopy(decision["reason_codes"]),
                },
            },
        },
    ]
    core = {
        "base_revision": candidate["base_revision"],
        "proposal_sha256": proposal_sha256,
        "authority_sha256": authority_sha256,
        "policy_fingerprint": BETA8_POLICY_FINGERPRINT,
        "decision": decision["decision"],
        "decision_sha256": digest_json(decision),
        "planned_records_sha256": digest_json(records),
    }
    return decision, {
        "schema": "an-kla/write-plan-v1",
        "core": core,
        "records": records,
        "plan_fingerprint": digest_json(core),
    }


def _policy_writer(
    project_root: str,
    expected: str,
    record_id: str,
    queue: multiprocessing.Queue,
) -> None:
    store = MemoryStore(project_root)
    candidate = proposal(expected, record_id)
    auth = authority(candidate)
    try:
        planning = store.plan_write(candidate, auth)
        result = store.commit_write_plan(
            expected_current_hash=expected,
            proposal=candidate,
            authority=auth,
            decision=planning["decision"],
            plan=planning["plan"],
        )
        queue.put(("committed", result["revision"]))
    except WritePolicyError:
        queue.put(("conflict", None))
    except LockBusyError:
        queue.put(("busy", None))


class SupersedeStoreTests(unittest.TestCase):
    """ADR-0019 (PR-B): supersede storage — overlay, CAS inmutability, guards."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(self.temp.name)
        self.root_revision = self.store.initialize()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _add(self, base: str, record_id: str) -> str:
        candidate = proposal(base, record_id, representation="summary")
        candidate["record"]["indexable_text"] = record_id
        auth = authority(candidate)
        planning = self.store.plan_write(candidate, auth)
        result = self.store.commit_write_plan(
            expected_current_hash=base,
            plan=planning["plan"],
            proposal=candidate,
            authority=auth,
            decision=planning["decision"],
        )
        return result["revision"]

    def _supersede(self, base: str, new_id: str, target_id: str) -> str:
        candidate = {
            "schema": "an-kla/write-proposal-v1",
            "base_revision": base,
            "stream": "facts",
            "operation": "supersede",
            "requested_representation": "summary",
            "record": {"id": new_id, "indexable_text": new_id, "summary": new_id},
            "lineage": {"derived_from_retrieval": False, "refs": []},
            "supersedes": target_id,
        }
        auth = authority(candidate)
        planning = self.store.plan_write(candidate, auth)
        result = self.store.commit_write_plan(
            expected_current_hash=base,
            plan=planning["plan"],
            proposal=candidate,
            authority=auth,
            decision=planning["decision"],
        )
        return result["revision"]

    def _facts(self) -> dict:
        return {r["id"]: r for r in self.store.snapshot().records["facts"]}

    def test_supersede_marks_target_sustituida_and_new_vigente(self) -> None:
        rev1 = self._add(self.root_revision, "f-old")
        rev2 = self._supersede(rev1, "f-new", "f-old")
        facts = self._facts()
        self.assertEqual(facts["f-old"].get("status"), "sustituida")
        self.assertNotIn("status", facts["f-new"])
        manifest = self.store.snapshot(rev2).manifest
        self.assertEqual(
            manifest["supersedes_map"],
            [{"stream": "facts", "target_id": "f-old", "sustituida_por": "f-new"}],
        )

    def test_supersede_keeps_target_segment_immutable(self) -> None:
        rev1 = self._add(self.root_revision, "f-old")
        manifest_before = self.store.snapshot(rev1).manifest
        target_segment = manifest_before["facts_segments"][0]
        rows_before = self.store._read_segment("facts", target_segment)
        self._supersede(rev1, "f-new", "f-old")
        # Segment content is content-addressed and immutable: same segment id is
        # still referenced by the child manifest and yields identical rows.
        rows_after = self.store._read_segment("facts", target_segment)
        self.assertEqual(rows_before, rows_after)
        self.assertIn(target_segment, self.store.snapshot().manifest["facts_segments"])

    def test_supersede_chain_accumulates_map(self) -> None:
        rev1 = self._add(self.root_revision, "A")
        rev2 = self._supersede(rev1, "B", "A")
        rev3 = self._supersede(rev2, "C", "B")
        facts = self._facts()
        self.assertEqual(facts["A"].get("status"), "sustituida")
        self.assertEqual(facts["B"].get("status"), "sustituida")
        self.assertNotIn("status", facts["C"])
        # Cumulative map: both entries preserved in revision C.
        entries = self.store.snapshot(rev3).manifest["supersedes_map"]
        self.assertEqual(
            {(e["target_id"], e["sustituida_por"]) for e in entries},
            {("A", "B"), ("B", "C")},
        )

    def test_supersede_missing_target_is_terminal(self) -> None:
        rev1 = self._add(self.root_revision, "f-old")
        # Issue #103 (H1): the condition now fails closed at planning time
        # with the stable ``plan_*`` code (no plan is produced).
        with self.assertRaises(WritePolicyError) as caught:
            self._supersede(rev1, "f-new", "f-never-existed")
        self.assertEqual(caught.exception.code, "plan_supersede_target_missing")
        # No CURRENT moved, no side effects.
        self.assertEqual(self.store.read_current(), rev1)

    def test_supersede_missing_target_still_terminal_at_commit(self) -> None:
        # Issue #103 (H1): the commit-time resolution stays authoritative for
        # the TOCTOU window. A plan built through the pure policy API
        # (bypassing plan_write's early checks) must still terminate under
        # the write lock with the legacy code.
        rev1 = self._add(self.root_revision, "f-old")
        candidate = {
            "schema": "an-kla/write-proposal-v1",
            "base_revision": rev1,
            "stream": "facts",
            "operation": "supersede",
            "requested_representation": "summary",
            "record": {"id": "f-new", "indexable_text": "f-new"},
            "lineage": {"derived_from_retrieval": False, "refs": []},
            "supersedes": "f-never-existed",
        }
        auth = authority(candidate)
        decision = pure_evaluate_write(candidate, auth)
        plan = pure_build_write_plan(candidate, auth, decision)
        with self.assertRaises(WritePolicyError) as caught:
            self.store.commit_write_plan(
                expected_current_hash=rev1,
                plan=plan,
                proposal=candidate,
                authority=auth,
                decision=decision,
            )
        self.assertEqual(caught.exception.code, "invalid_supersede_target")
        self.assertEqual(caught.exception.detail, "target_missing")
        self.assertEqual(self.store.read_current(), rev1)

    def test_supersede_already_sustituida_target_is_terminal(self) -> None:
        rev1 = self._add(self.root_revision, "A")
        rev2 = self._supersede(rev1, "B", "A")
        # Issue #103 (H1): fails closed at planning time.
        with self.assertRaises(WritePolicyError) as caught:
            self._supersede(rev2, "C", "A")  # A is already sustituida
        self.assertEqual(caught.exception.code, "plan_supersede_target_not_vigente")
        self.assertEqual(self.store.read_current(), rev2)

    def test_retrieve_excludes_sustituida_target(self) -> None:
        rev1 = self._add(self.root_revision, "f-old")
        self._supersede(rev1, "f-new", "f-old")
        result = retrieve(self.store, query="f", budget=2000)
        ids = [str(r.get("id", "")) for r in result["selected"]]
        self.assertNotIn("f-old", ids)
        self.assertIn("f-new", ids)

    def test_supersede_target_in_other_stream_is_missing(self) -> None:
        # The guard resolves the target within item["stream"] only; a target id
        # that exists in a different stream does not match (axes are not
        # interchangeable, ADR-0019 decision 3).
        rev1 = self._add(self.root_revision, "f-old")
        # Seed an event sharing the id, then supersede it as a fact: must miss.
        evt_base = rev1
        evt_candidate = {
            "schema": "an-kla/write-proposal-v1",
            "base_revision": evt_base,
            "stream": "events",
            "operation": "add",
            "requested_representation": "summary",
            "record": {"id": "shared-id", "indexable_text": "evt"},
            "lineage": {"derived_from_retrieval": False, "refs": []},
        }
        evt_auth = authority(evt_candidate)
        evt_planning = self.store.plan_write(evt_candidate, evt_auth)
        rev2 = self.store.commit_write_plan(
            expected_current_hash=evt_base,
            plan=evt_planning["plan"],
            proposal=evt_candidate,
            authority=evt_auth,
            decision=evt_planning["decision"],
        )["revision"]
        with self.assertRaises(WritePolicyError) as caught:
            self._supersede(rev2, "f-new", "shared-id")  # shared-id lives in events, not facts
        # Issue #103 (H1): now caught at planning time; axes remain
        # non-interchangeable (ADR-0019 decision 3).
        self.assertEqual(caught.exception.code, "plan_supersede_target_missing")

    def test_add_only_revision_has_no_supersedes_map_field(self) -> None:
        # Backwards-compat: a plain add revision omits the field entirely
        # (byte-identical to pre-PR-B); snapshot reads it as no-op overlay.
        rev1 = self._add(self.root_revision, "f-old")
        manifest = self.store.snapshot(rev1).manifest
        self.assertNotIn("supersedes_map", manifest)
        self.assertNotIn("status", self._facts()["f-old"])


class ContextDiagnosticsTests(unittest.TestCase):
    """ADR-0020: ``context_diagnostics`` in the commit-write-plan result."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(self.temp.name)
        self.root_revision = self.store.initialize()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _commit_add(self) -> dict:
        candidate = proposal(self.root_revision, "f-x", representation="summary")
        auth = authority(candidate)
        planning = self.store.plan_write(candidate, auth)
        return self.store.commit_write_plan(
            expected_current_hash=self.root_revision,
            plan=planning["plan"],
            proposal=candidate,
            authority=auth,
            decision=planning["decision"],
        )

    def test_commit_result_includes_context_diagnostics(self) -> None:
        result = self._commit_add()
        self.assertIn("context_diagnostics", result)
        # Consistent with context_status(project_root) of the same root.
        from an_kla.context_package import context_status

        expected = dict(context_status(self.temp.name))
        self.assertEqual(result["context_diagnostics"], expected)
        self.assertEqual(
            result["context_diagnostics"]["schema"], "an-kla/context-status/v1"
        )

    def test_context_diagnostics_degraded_when_context_status_raises(self) -> None:
        # commit must stay authoritative even if context_status blows up.
        with patch("an_kla.store.context_status", side_effect=OSError("boom")):
            result = self._commit_add()
        self.assertTrue(result["committed"])
        cd = result["context_diagnostics"]
        self.assertIsNone(cd["ok"])
        self.assertEqual(cd["diagnostics"], ["context_status_unavailable"])
        self.assertEqual(cd["schema"], "an-kla/context-status/v1")
        self.assertIn("error", cd)

    def test_skip_result_includes_context_diagnostics(self) -> None:
        # unresolved authority -> skip; diagnostics still surfaced (ADR-0020).
        candidate = proposal(self.root_revision, "f-skip", representation="full")
        auth = authority(candidate, authority_class="unresolved")
        planning = self.store.plan_write(candidate, auth)
        result = self.store.commit_write_plan(
            expected_current_hash=self.root_revision,
            plan=planning["plan"],
            proposal=candidate,
            authority=auth,
            decision=planning["decision"],
        )
        self.assertFalse(result["committed"])
        self.assertIn("context_diagnostics", result)
        self.assertEqual(
            result["context_diagnostics"]["schema"], "an-kla/context-status/v1"
        )


    def test_managed_block_modified_surfaces_in_context_diagnostics(self) -> None:
        # ADR-0020 §Test de regresión #2: a tampered managed block must show up
        # in context_diagnostics of the commit (not only via separate context
        # status). Install the contract, mutate the block payload, then commit.
        from an_kla.context_package import apply_context_plan, plan_context_change

        plan = plan_context_change(self.temp.name, "install")
        apply_context_plan(self.temp.name, plan)
        agents = Path(self.temp.name) / "AGENTS.md"
        text = agents.read_text(encoding="utf-8")
        agents.write_text(
            text.replace("## AN-KLA Memory", "## AN-KLA Memory TAMPERED"),
            encoding="utf-8",
        )
        result = self._commit_add()
        self.assertIn(
            "managed_block_modified", result["context_diagnostics"]["diagnostics"]
        )


if __name__ == "__main__":
    unittest.main()
