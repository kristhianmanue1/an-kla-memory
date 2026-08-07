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
from an_kla.retrieval import retrieve
from an_kla.store import LockBusyError, MemoryStore
from an_kla.write_policy import WritePolicyError, verify_write_plan as pure_verify_write_plan


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

    def test_caller_mutation_after_verification_cannot_change_written_bytes(self) -> None:
        candidate, auth, planning = self.planning()

        def verify_then_mutate(plan, proposal, authority, decision):
            pure_verify_write_plan(plan, proposal, authority, decision)
            planning["plan"]["records"][0]["record"]["payload"]["text"] = (
                "mutado despues de verificar"
            )

        with patch("an_kla.store.verify_write_plan", side_effect=verify_then_mutate):
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

    def test_cli_rejects_tampered_planning_result_revision(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = MemoryStore(root)
            base = store.initialize()
            candidate = proposal(base)
            auth = authority(candidate)
            planning = store.plan_write(candidate, auth)
            planning["current_revision"] = "sha256:" + "c" * 64
            proposal_path = Path(root) / "proposal.json"
            authority_path = Path(root) / "authority.json"
            planning_path = Path(root) / "planning.json"
            proposal_path.write_text(json.dumps(candidate), encoding="utf-8")
            authority_path.write_text(json.dumps(auth), encoding="utf-8")
            planning_path.write_text(json.dumps(planning), encoding="utf-8")
            completed = subprocess.run(
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
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(b"invalid_write_planning_result", completed.stderr)
            self.assertEqual(store.read_current(), base)

    def test_cli_input_error_does_not_disclose_path(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = MemoryStore(root)
            store.initialize()
            secret_path = Path(root) / "private-candidate-name.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "an_kla",
                    "--project-root",
                    root,
                    "plan-write",
                    "--proposal",
                    str(secret_path),
                    "--authority",
                    str(secret_path),
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                timeout=30,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(b"input_json_unreadable", completed.stderr)
            self.assertNotIn(str(secret_path).encode(), completed.stderr)


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
        with self.assertRaises(WritePolicyError) as caught:
            self._supersede(rev1, "f-new", "f-never-existed")
        self.assertEqual(caught.exception.code, "invalid_supersede_target")
        self.assertEqual(caught.exception.detail, "target_missing")
        # No CURRENT moved, no side effects.
        self.assertEqual(self.store.read_current(), rev1)

    def test_supersede_already_sustituida_target_is_terminal(self) -> None:
        rev1 = self._add(self.root_revision, "A")
        rev2 = self._supersede(rev1, "B", "A")
        with self.assertRaises(WritePolicyError) as caught:
            self._supersede(rev2, "C", "A")  # A is already sustituida
        self.assertEqual(caught.exception.code, "invalid_supersede_target")
        self.assertEqual(caught.exception.detail, "target_not_vigente")
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
        self.assertEqual(caught.exception.code, "invalid_supersede_target")
        self.assertEqual(caught.exception.detail, "target_missing")

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
