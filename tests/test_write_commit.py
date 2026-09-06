"""tests/test_write_commit.py

Particionado en beta.22 (issue #106, plan docs/plans/2026-09-01-deuda-tamanos-adopcion-skevi.md): parte del contenido vive ahora en tests/test_write_commit_cli.py, tests/test_write_commit_supersede.py. Casos y aserciones sin cambios.
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


class WriteCommitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(self.temp.name)
        self.root_revision = self.store.initialize()
        self.initial_journals = list((self.store.root / "transactions").glob("*.json"))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def planning(self, *, authority_class: str = "model_derived", representation: str = "summary"):
        candidate = proposal(self.root_revision, representation=representation)
        auth = authority(candidate, authority_class=authority_class)
        return candidate, auth, self.store.plan_write(candidate, auth)

    def test_plan_is_non_mutating_and_commit_revalidates_inside_lock(self) -> None:
        candidate, auth, planning = self.planning()
        self.assertEqual(self.store.read_current(), self.root_revision)
        self.assertEqual(
            list((self.store.root / "transactions").glob("*.json")),
            self.initial_journals,
        )

        result = self.store.commit_write_plan(
            expected_current_hash=self.root_revision,
            proposal=candidate,
            authority=auth,
            decision=planning["decision"],
            plan=planning["plan"],
        )

        self.assertTrue(result["committed"])
        snapshot = self.store.snapshot(result["revision"])
        self.assertEqual([row["id"] for row in snapshot.records["facts"]], ["f-policy"])
        policy_events = [
            row for row in snapshot.records["events"] if row.get("type") == "write_policy_decision"
        ]
        self.assertEqual(len(policy_events), 1)
        self.assertEqual(policy_events[0]["payload"]["authority_class"], "model_derived")
        self.assertNotIn("issuer", policy_events[0]["payload"])
        journal = json.loads(
            (
                self.store.root
                / "transactions"
                / f"{result['outcome']['transaction_id']}.json"
            ).read_text()
        )
        self.assertEqual(journal["write_policy"]["plan_fingerprint"], result["plan_fingerprint"])
        self.assertNotIn("authority", journal["write_policy"])

    def test_skip_does_not_create_revision_event_or_journal(self) -> None:
        candidate, auth, planning = self.planning(
            authority_class="unresolved", representation="full"
        )
        result = self.store.commit_write_plan(
            expected_current_hash=self.root_revision,
            proposal=candidate,
            authority=auth,
            decision=planning["decision"],
            plan=planning["plan"],
        )
        self.assertFalse(result["committed"])
        self.assertEqual(result["revision"], self.root_revision)
        self.assertEqual(self.store.snapshot().records["events"], ())
        self.assertEqual(
            list((self.store.root / "transactions").glob("*.json")),
            self.initial_journals,
        )

    def test_current_change_between_plan_and_commit_is_terminal_without_journal(self) -> None:
        candidate, auth, planning = self.planning()
        advanced = self.store.commit(
            expected_current_hash=self.root_revision,
            checkpoint_patch={},
        )
        journals_before = list((self.store.root / "transactions").glob("*.json"))
        with self.assertRaisesRegex(WritePolicyError, "write_plan_base_changed"):
            self.store.commit_write_plan(
                expected_current_hash=self.root_revision,
                proposal=candidate,
                authority=auth,
                decision=planning["decision"],
                plan=planning["plan"],
            )
        self.assertEqual(self.store.read_current(), advanced)
        self.assertEqual(
            list((self.store.root / "transactions").glob("*.json")), journals_before
        )

    def test_beta8_invalid_verified_at_replay_precedence_has_no_new_objects(self) -> None:
        candidate = proposal(self.root_revision)
        candidate["record"]["verified_at"] = "not-a-date"
        auth = authority(candidate)
        old_decision, old_plan = beta8_planning(candidate, auth)
        before = {
            path.relative_to(self.store.root): path.read_bytes()
            for path in self.store.root.rglob("*")
            if path.is_file()
        }
        with self.assertRaises(WritePolicyError) as current_base:
            self.store.commit_write_plan(
                expected_current_hash=self.root_revision,
                proposal=candidate,
                authority=auth,
                decision=old_decision,
                plan=old_plan,
            )
        self.assertEqual(current_base.exception.code, "invalid_write_proposal")
        after = {
            path.relative_to(self.store.root): path.read_bytes()
            for path in self.store.root.rglob("*")
            if path.is_file()
        }
        self.assertEqual(after, before)

        advanced = self.store.commit(
            expected_current_hash=self.root_revision,
            checkpoint_patch={},
        )
        files_after_advance = {
            path.relative_to(self.store.root): path.read_bytes()
            for path in self.store.root.rglob("*")
            if path.is_file()
        }
        with self.assertRaises(WritePolicyError) as stale_expected:
            self.store.commit_write_plan(
                expected_current_hash=self.root_revision,
                proposal=candidate,
                authority=auth,
                decision=old_decision,
                plan=old_plan,
            )
        self.assertEqual(stale_expected.exception.code, "write_plan_base_changed")
        with self.assertRaises(WritePolicyError) as current_expected:
            self.store.commit_write_plan(
                expected_current_hash=advanced,
                proposal=candidate,
                authority=auth,
                decision=old_decision,
                plan=old_plan,
            )
        self.assertEqual(current_expected.exception.code, "invalid_write_proposal")
        final_files = {
            path.relative_to(self.store.root): path.read_bytes()
            for path in self.store.root.rglob("*")
            if path.is_file()
        }
        self.assertEqual(final_files, files_after_advance)

    def test_beta8_valid_verified_at_replay_precedence_has_no_new_objects(self) -> None:
        candidate = proposal(self.root_revision)
        candidate["record"]["verified_at"] = "2026-08-08T00:00:00Z"
        auth = authority(candidate)
        old_decision, old_plan = beta8_planning(candidate, auth)
        before = {
            path.relative_to(self.store.root): path.read_bytes()
            for path in self.store.root.rglob("*")
            if path.is_file()
        }
        with self.assertRaises(WritePolicyError) as current_base:
            self.store.commit_write_plan(
                expected_current_hash=self.root_revision,
                proposal=candidate,
                authority=auth,
                decision=old_decision,
                plan=old_plan,
            )
        self.assertEqual(
            current_base.exception.code,
            "write_policy_fingerprint_mismatch",
        )
        after = {
            path.relative_to(self.store.root): path.read_bytes()
            for path in self.store.root.rglob("*")
            if path.is_file()
        }
        self.assertEqual(after, before)

        advanced = self.store.commit(
            expected_current_hash=self.root_revision,
            checkpoint_patch={},
        )
        files_after_advance = {
            path.relative_to(self.store.root): path.read_bytes()
            for path in self.store.root.rglob("*")
            if path.is_file()
        }
        with self.assertRaises(WritePolicyError) as stale_expected:
            self.store.commit_write_plan(
                expected_current_hash=self.root_revision,
                proposal=candidate,
                authority=auth,
                decision=old_decision,
                plan=old_plan,
            )
        self.assertEqual(stale_expected.exception.code, "write_plan_base_changed")
        with self.assertRaises(WritePolicyError) as current_expected:
            self.store.commit_write_plan(
                expected_current_hash=advanced,
                proposal=candidate,
                authority=auth,
                decision=old_decision,
                plan=old_plan,
            )
        self.assertEqual(
            current_expected.exception.code,
            "write_policy_fingerprint_mismatch",
        )
        final_files = {
            path.relative_to(self.store.root): path.read_bytes()
            for path in self.store.root.rglob("*")
            if path.is_file()
        }
        self.assertEqual(final_files, files_after_advance)

    def test_tampered_plan_is_rejected_before_journal(self) -> None:
        candidate, auth, planning = self.planning()
        tampered = deepcopy(planning["plan"])
        tampered["records"][0]["record"]["payload"]["text"] = "alterado"
        with self.assertRaisesRegex(WritePolicyError, "write_content_hash_mismatch"):
            self.store.commit_write_plan(
                expected_current_hash=self.root_revision,
                proposal=candidate,
                authority=auth,
                decision=planning["decision"],
                plan=tampered,
            )
        self.assertEqual(self.store.read_current(), self.root_revision)
        self.assertEqual(
            list((self.store.root / "transactions").glob("*.json")),
            self.initial_journals,
        )

    def test_store_operation_guard_exposes_not_committable_detail(self) -> None:
        candidate, auth, planning = self.planning()
        tampered = deepcopy(planning["plan"])
        tampered["records"][0]["operation"] = "refute"
        before = {
            str(path.relative_to(self.store.root)): path.read_bytes()
            for directory in ("objects", "revisions", "transactions")
            for path in (self.store.root / directory).glob("*.json")
        }
        # The pure verifier normally rejects this first. Bypass it solely to
        # exercise the store's independent defense-in-depth guard from #32.
        with patch("an_kla.write_commit.verify_write_plan", return_value=None):
            with self.assertRaises(WritePolicyError) as caught:
                self.store.commit_write_plan(
                    expected_current_hash=self.root_revision,
                    proposal=candidate,
                    authority=auth,
                    decision=planning["decision"],
                    plan=tampered,
                )
        self.assertEqual(caught.exception.code, "invalid_write_plan")
        self.assertEqual(str(caught.exception), "invalid_write_plan")
        self.assertEqual(
            caught.exception.detail,
            "records[]:operation:not_committable",
        )
        after = {
            str(path.relative_to(self.store.root)): path.read_bytes()
            for directory in ("objects", "revisions", "transactions")
            for path in (self.store.root / directory).glob("*.json")
        }
        self.assertEqual(after, before)
        self.assertEqual(self.store.read_current(), self.root_revision)

    def test_caller_mutation_after_verification_cannot_change_written_bytes(self) -> None:
        candidate, auth, planning = self.planning()

        def verify_then_mutate(plan, proposal, authority, decision):
            pure_verify_write_plan(plan, proposal, authority, decision)
            planning["plan"]["records"][0]["record"]["payload"]["text"] = (
                "mutado despues de verificar"
            )

        with patch("an_kla.write_commit.verify_write_plan", side_effect=verify_then_mutate):
            result = self.store.commit_write_plan(
                expected_current_hash=self.root_revision,
                proposal=candidate,
                authority=auth,
                decision=planning["decision"],
                plan=planning["plan"],
            )
        written = self.store.snapshot(result["revision"]).records["facts"][0]
        self.assertEqual(written["payload"]["text"], "memoria durable")

    def test_failure_before_current_keeps_base_and_retry_can_commit(self) -> None:
        candidate, auth, planning = self.planning()
        txid = str(uuid.uuid4())
        with patch.object(self.store, "_replace_current", side_effect=OSError("injected")):
            failed = self.store.commit_write_plan(
                expected_current_hash=self.root_revision,
                proposal=candidate,
                authority=auth,
                decision=planning["decision"],
                plan=planning["plan"],
                transaction_id=txid,
            )
        self.assertFalse(failed["committed"])
        self.assertEqual(failed["revision"], self.root_revision)
        self.assertNotEqual(
            failed["outcome"]["candidate_revision"], self.root_revision
        )
        self.assertEqual(failed["outcome"]["state"], "not_committed")
        self.assertEqual(failed["outcome"]["operation_error_code"], "storage_io_failed")
        self.assertEqual(self.store.read_current(), self.root_revision)
        self.assertEqual(
            self.store.recover()["pending_transactions"][0]["status"],
            "candidate_prepared",
        )

        result = self.store.commit_write_plan(
            expected_current_hash=self.root_revision,
            proposal=candidate,
            authority=auth,
            decision=planning["decision"],
            plan=planning["plan"],
            transaction_id=txid,
        )
        self.assertTrue(result["committed"])
        self.assertEqual(result["outcome"]["transaction_id"], txid)

    def test_failure_after_current_is_diagnostic_and_retry_does_not_recommit(self) -> None:
        candidate, auth, planning = self.planning()
        txid = str(uuid.uuid4())
        original = self.store._write_transaction

        def fail_committed(txid, body):
            if body.get("stage") == "committed":
                raise OSError("after-current")
            original(txid, body)

        with patch.object(self.store, "_write_transaction", side_effect=fail_committed):
            failed = self.store.commit_write_plan(
                expected_current_hash=self.root_revision,
                proposal=candidate,
                authority=auth,
                decision=planning["decision"],
                plan=planning["plan"],
                transaction_id=txid,
            )
        self.assertTrue(failed["committed"])
        self.assertEqual(failed["outcome"]["state"], "committed_audit_incomplete")
        committed_revision = self.store.read_current()
        self.assertNotEqual(committed_revision, self.root_revision)
        self.assertEqual(
            self.store.recover()["pending_transactions"][0]["status"],
            "candidate_prepared",
        )
        inspected = self.store.inspect_transaction(txid)
        self.assertTrue(inspected["committed"])
        self.assertEqual(inspected["candidate_relation"], "current")
        self.assertEqual(inspected["durability_state"], "complete")
        with self.assertRaisesRegex(WritePolicyError, "write_plan_base_changed"):
            self.store.commit_write_plan(
                expected_current_hash=self.root_revision,
                proposal=candidate,
                authority=auth,
                decision=planning["decision"],
                plan=planning["plan"],
            )
        self.assertEqual(self.store.read_current(), committed_revision)

    def test_two_policy_writers_produce_one_authoritative_commit(self) -> None:
        queue: multiprocessing.Queue = multiprocessing.Queue()
        processes = [
            multiprocessing.Process(
                target=_policy_writer,
                args=(self.temp.name, self.root_revision, f"f-writer-{index}", queue),
            )
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
        self.assertEqual(len(self.store.snapshot().records["facts"]), 1)

    def test_python_api_can_receive_resolved_channel_authority(self) -> None:
        candidate = proposal(self.root_revision, representation="full")
        auth = authority(candidate, authority_class="channel_confirmed")
        planning = self.store.plan_write(candidate, auth)
        result = self.store.commit_write_plan(
            expected_current_hash=self.root_revision,
            proposal=candidate,
            authority=auth,
            decision=planning["decision"],
            plan=planning["plan"],
        )
        self.assertTrue(result["committed"])
        self.assertEqual(result["decision"], "write-full")


if __name__ == "__main__":
    unittest.main()
