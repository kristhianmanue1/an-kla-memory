from __future__ import annotations

from copy import deepcopy
import json
import multiprocessing
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from an_kla.canonical import digest_json
from an_kla.store import LockBusyError, MemoryStore
from an_kla.write_policy import WritePolicyError


DIGEST_B = "sha256:" + "b" * 64


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

    def tearDown(self) -> None:
        self.temp.cleanup()

    def planning(self, *, authority_class: str = "model_derived", representation: str = "summary"):
        candidate = proposal(self.root_revision, representation=representation)
        auth = authority(candidate, authority_class=authority_class)
        return candidate, auth, self.store.plan_write(candidate, auth)

    def test_plan_is_non_mutating_and_commit_revalidates_inside_lock(self) -> None:
        candidate, auth, planning = self.planning()
        self.assertEqual(self.store.read_current(), self.root_revision)
        self.assertEqual(list((self.store.root / "transactions").glob("*.json")), [])

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
        journal = json.loads(next((self.store.root / "transactions").glob("*.json")).read_text())
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
        self.assertEqual(list((self.store.root / "transactions").glob("*.json")), [])

    def test_current_change_between_plan_and_commit_is_terminal_without_journal(self) -> None:
        candidate, auth, planning = self.planning()
        advanced = self.store.commit(
            expected_current_hash=self.root_revision,
            checkpoint_patch={"goal": "advanced"},
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
        self.assertEqual(list((self.store.root / "transactions").glob("*.json")), [])

    def test_failure_before_current_keeps_base_and_retry_can_commit(self) -> None:
        candidate, auth, planning = self.planning()
        with patch.object(self.store, "_replace_current", side_effect=OSError("injected")):
            with self.assertRaisesRegex(OSError, "injected"):
                self.store.commit_write_plan(
                    expected_current_hash=self.root_revision,
                    proposal=candidate,
                    authority=auth,
                    decision=planning["decision"],
                    plan=planning["plan"],
                )
        self.assertEqual(self.store.read_current(), self.root_revision)
        self.assertEqual(self.store.recover()["pending_transactions"][0]["status"], "prepared")

        result = self.store.commit_write_plan(
            expected_current_hash=self.root_revision,
            proposal=candidate,
            authority=auth,
            decision=planning["decision"],
            plan=planning["plan"],
        )
        self.assertTrue(result["committed"])

    def test_failure_after_current_is_diagnostic_and_retry_does_not_recommit(self) -> None:
        candidate, auth, planning = self.planning()
        original = self.store._write_transaction

        def fail_committed(txid, body):
            if body.get("stage") == "committed":
                raise OSError("after-current")
            original(txid, body)

        with patch.object(self.store, "_write_transaction", side_effect=fail_committed):
            with self.assertRaisesRegex(OSError, "after-current"):
                self.store.commit_write_plan(
                    expected_current_hash=self.root_revision,
                    proposal=candidate,
                    authority=auth,
                    decision=planning["decision"],
                    plan=planning["plan"],
                )
        committed_revision = self.store.read_current()
        self.assertNotEqual(committed_revision, self.root_revision)
        self.assertEqual(self.store.recover()["pending_transactions"][0]["status"], "prepared")
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


class WriteCommitCliTests(unittest.TestCase):
    def test_cli_plans_then_commits_exact_derived_summary(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = MemoryStore(root)
            base = store.initialize()
            candidate = proposal(base)
            auth = authority(candidate)
            proposal_path = Path(root) / "proposal.json"
            authority_path = Path(root) / "authority.json"
            planning_path = Path(root) / "planning.json"
            proposal_path.write_text(json.dumps(candidate), encoding="utf-8")
            authority_path.write_text(json.dumps(auth), encoding="utf-8")

            planned = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "an_kla",
                    "--project-root",
                    root,
                    "plan-write",
                    "--proposal",
                    str(proposal_path),
                    "--authority",
                    str(authority_path),
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                timeout=30,
                check=True,
            )
            planning = json.loads(planned.stdout)
            planning_path.write_bytes(planned.stdout)
            self.assertEqual(planning["decision"]["decision"], "write-summary")
            self.assertEqual(store.read_current(), base)

            committed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "an_kla",
                    "--project-root",
                    root,
                    "commit-write-plan",
                    "--expected-current",
                    base,
                    "--proposal",
                    str(proposal_path),
                    "--authority",
                    str(authority_path),
                    "--planning-result",
                    str(planning_path),
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                timeout=30,
                check=True,
            )
            result = json.loads(committed.stdout)
            self.assertTrue(result["committed"])
            self.assertEqual(store.read_current(), result["revision"])

    def test_cli_refuses_unresolved_privileged_authority_file(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = MemoryStore(root)
            base = store.initialize()
            candidate = proposal(base, representation="full")
            auth = authority(candidate, authority_class="channel_confirmed")
            proposal_path = Path(root) / "proposal.json"
            authority_path = Path(root) / "authority.json"
            proposal_path.write_text(json.dumps(candidate), encoding="utf-8")
            authority_path.write_text(json.dumps(auth), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "an_kla",
                    "--project-root",
                    root,
                    "plan-write",
                    "--proposal",
                    str(proposal_path),
                    "--authority",
                    str(authority_path),
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                timeout=30,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(b"cli_privileged_authority_unresolved", completed.stderr)
            self.assertEqual(store.read_current(), base)


if __name__ == "__main__":
    unittest.main()
