from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

from an_kla.canonical import digest_json
from an_kla.storage_primitives import fsync_directory
from an_kla.storage_primitives import storage_error
from an_kla.store import MemoryStore
from an_kla.transactions import (
    TransactionError,
    begin_transaction,
    validate_attempt,
)


def _proposal(base: str, record_id: str) -> dict:
    return {
        "schema": "an-kla/write-proposal-v1",
        "base_revision": base,
        "stream": "facts",
        "operation": "add",
        "requested_representation": "summary",
        "record": {"id": record_id, "payload": {"text": "durable transaction"}},
        "lineage": {"derived_from_retrieval": False, "refs": []},
    }


def _authority(proposal: dict) -> dict:
    return {
        "schema": "an-kla/write-authority-v1",
        "proposal_sha256": digest_json(proposal),
        "base_revision": proposal["base_revision"],
        "authority_class": "model_derived",
        "issuer": {
            "kind": "model",
            "id": "test",
            "configuration_fingerprint": "sha256:" + "1" * 64,
        },
        "evidence": [],
        "scope": {
            "streams": ["facts"],
            "representations": ["summary"],
            "operations": ["add"],
        },
    }


class TransactionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(self.temp.name)
        self.root = self.store.initialize()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _commit(self, base: str, record_id: str, txid: str | None = None) -> dict:
        proposal = _proposal(base, record_id)
        authority = _authority(proposal)
        planning = self.store.plan_write(proposal, authority)
        return self.store.commit_write_plan(
            expected_current_hash=base,
            proposal=proposal,
            authority=authority,
            decision=planning["decision"],
            plan=planning["plan"],
            transaction_id=txid,
        )

    def test_initialize_uses_uuid_attempt_outcome_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            store = MemoryStore(project)
            txid = str(uuid.uuid4())
            created = store.initialize_with_outcome(transaction_id=txid)
            self.assertTrue(created["outcome"]["committed"])
            self.assertEqual(created["outcome"]["transaction_id"], txid)
            self.assertEqual(
                store.snapshot().manifest["transaction_id"], txid
            )
            retried = store.initialize_with_outcome(transaction_id=txid)
            self.assertEqual(retried["revision"], created["revision"])
            self.assertTrue(retried["outcome"]["committed"])
            self.assertEqual(store.snapshot().manifest["revision"], 0)

    def test_initialize_on_advanced_store_does_not_return_child_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            store = MemoryStore(project)
            initialized = store.initialize_with_outcome(transaction_id=str(uuid.uuid4()))
            proposal = _proposal(initialized["revision"], "f-after-init")
            authority = _authority(proposal)
            planning = store.plan_write(proposal, authority)
            child = store.commit_write_plan(
                expected_current_hash=initialized["revision"],
                proposal=proposal,
                authority=authority,
                decision=planning["decision"],
                plan=planning["plan"],
                transaction_id=str(uuid.uuid4()),
            )
            result = store.initialize_with_outcome(transaction_id=str(uuid.uuid4()))
            self.assertEqual(result["revision"], child["revision"])
            self.assertIsNone(result["outcome"])

    def test_concurrent_init_does_not_attribute_winner_txid_to_loser(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            from concurrent.futures import ThreadPoolExecutor

            txids = [str(uuid.uuid4()), str(uuid.uuid4())]

            def initialize(txid):
                return MemoryStore(project).initialize_with_outcome(
                    transaction_id=txid
                )

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(initialize, txids))
            store = MemoryStore(project)
            winning_txid = store.snapshot().manifest["transaction_id"]
            self.assertIn(winning_txid, txids)
            for txid, result in zip(txids, results):
                self.assertEqual(result["revision"], store.read_current())
                if txid == winning_txid:
                    self.assertTrue(result["outcome"]["committed"])
                else:
                    self.assertIsNone(result["outcome"])

    def test_nil_uuid_is_rejected_like_the_schema(self) -> None:
        with self.assertRaisesRegex(TransactionError, "invalid_transaction_id"):
            begin_transaction(
                "write",
                transaction_id="00000000-0000-0000-0000-000000000000",
                base_revision=self.root,
                plan_fingerprint="sha256:" + "2" * 64,
            )

    def test_attempt_is_exact_and_no_io(self) -> None:
        txid = str(uuid.uuid4())
        attempt = begin_transaction(
            "write",
            transaction_id=txid,
            base_revision=self.root,
            plan_fingerprint="sha256:" + "2" * 64,
        )
        self.assertEqual(validate_attempt(attempt), attempt)
        self.assertEqual(attempt["transaction_id"], txid)
        invalid = {**attempt, "extra": True}
        with self.assertRaisesRegex(TransactionError, "invalid_transaction_attempt"):
            validate_attempt(invalid)

    def test_success_and_historical_inspection(self) -> None:
        first_txid = str(uuid.uuid4())
        first = self._commit(self.root, "f-one", first_txid)
        self.assertEqual(first["outcome"]["state"], "committed")
        second = self._commit(first["revision"], "f-two", str(uuid.uuid4()))
        inspected = self.store.inspect_transaction(first_txid)
        self.assertTrue(inspected["committed"])
        self.assertEqual(inspected["candidate_relation"], "ancestor")
        self.assertEqual(inspected["current_observed"], second["revision"])

    def test_transaction_inspect_cli(self) -> None:
        txid = str(uuid.uuid4())
        self._commit(self.root, "f-cli-inspect", txid)
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "an_kla",
                "--no-update-check",
                "--project-root",
                self.temp.name,
                "transaction",
                "inspect",
                txid,
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["state"], "committed")

    def test_transaction_inspect_unknown_is_canonical_and_exit_three(self) -> None:
        txid = str(uuid.uuid4())
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "an_kla",
                "--no-update-check",
                "--project-root",
                self.temp.name,
                "transaction",
                "inspect",
                txid,
            ],
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 3)
        parsed = json.loads(completed.stdout)
        self.assertEqual(parsed["schema"], "an-kla/commit-outcome-v2")
        self.assertEqual(parsed["state"], "outcome_unknown")
        from an_kla.canonical import canonical_json

        self.assertEqual(completed.stdout, canonical_json(parsed))

    def test_first_journal_failure_returns_unrecorded_runtime_outcome(self) -> None:
        proposal = _proposal(self.root, "f-fail-first")
        authority = _authority(proposal)
        planning = self.store.plan_write(proposal, authority)
        txid = str(uuid.uuid4())
        with patch.object(self.store, "_write_transaction", side_effect=OSError("EIO")):
            result = self.store.commit_write_plan(
                expected_current_hash=self.root,
                proposal=proposal,
                authority=authority,
                decision=planning["decision"],
                plan=planning["plan"],
                transaction_id=txid,
            )
        self.assertFalse(result["committed"])
        self.assertFalse(result["outcome"]["recorded"])
        self.assertEqual(result["outcome"]["operation_error_code"], "storage_io_failed")
        self.assertIn("transaction_not_recorded", result["outcome"]["warnings"])
        inspected = self.store.inspect_transaction(txid)
        self.assertEqual(inspected["state"], "outcome_unknown")
        self.assertIsNone(inspected["recorded"])

    def test_journal_binds_attempt_and_receipts(self) -> None:
        txid = str(uuid.uuid4())
        result = self._commit(self.root, "f-receipts", txid)
        journal = json.loads(
            (self.store.root / "transactions" / f"{txid}.json").read_text()
        )
        self.assertEqual(journal["attempt"]["transaction_id"], txid)
        self.assertIsInstance(journal["candidate_receipt"], str)
        self.assertIsInstance(journal["current_receipt"], str)
        receipt_path = (
            self.store.root
            / "transactions"
            / txid
            / "receipts"
            / "sha256"
            / (journal["current_receipt"].removeprefix("sha256:") + ".json")
        )
        receipt = json.loads(receipt_path.read_text())
        self.assertEqual(receipt["candidate_revision"], result["revision"])
        self.assertEqual(receipt["predecessor_receipt"], journal["candidate_receipt"])

    def test_tampered_receipt_cannot_certify_durability(self) -> None:
        txid = str(uuid.uuid4())
        self._commit(self.root, "f-tamper-receipt", txid)
        journal = json.loads(
            (self.store.root / "transactions" / f"{txid}.json").read_text()
        )
        current_id = journal["current_receipt"]
        current_path = (
            self.store.root
            / "transactions"
            / txid
            / "receipts"
            / "sha256"
            / (current_id.removeprefix("sha256:") + ".json")
        )
        current_path.write_bytes(b"{}")
        inspected = self.store.inspect_transaction(txid)
        self.assertTrue(inspected["committed"])
        self.assertEqual(inspected["durability_state"], "incomplete")
        self.assertEqual(inspected["state"], "durability_incomplete")

    def test_repair_durability_is_explicit_and_inspectable(self) -> None:
        txid = str(uuid.uuid4())
        from an_kla import transactions

        original = transactions.write_receipt

        def fail_current(*args, **kwargs):
            if kwargs.get("kind") == "current-durable":
                raise OSError("receipt-EIO")
            return original(*args, **kwargs)

        with patch("an_kla.transactions.write_receipt", side_effect=fail_current):
            result = self._commit(self.root, "f-repair", txid)
        self.assertTrue(result["committed"])
        self.assertEqual(result["outcome"]["state"], "durability_incomplete")
        self.assertEqual(
            self.store.inspect_transaction(txid)["durability_state"], "incomplete"
        )
        repaired = self.store.repair_transaction_durability(txid)
        self.assertEqual(repaired["durability_state"], "complete")
        repair_receipts = []
        for path in (self.store.root / "transactions" / txid / "receipts").rglob(
            "*.json"
        ):
            value = json.loads(path.read_text())
            if value["kind"] == "repair":
                repair_receipts.append(value)
        self.assertEqual(len(repair_receipts), 1)
        self.assertEqual(repair_receipts[0]["repair_for_kind"], "current-durable")

    def test_repair_rejects_substituted_stage_or_intent_evidence(self) -> None:
        for target, error in (
            ("stage", "candidate_stage_missing_or_ambiguous"),
            ("intent", "transaction_intent_missing_or_ambiguous"),
        ):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as project:
                store = MemoryStore(project)
                root = store.initialize()
                txid = str(uuid.uuid4())
                proposal = _proposal(root, "f-substituted-" + target)
                authority = _authority(proposal)
                planning = store.plan_write(proposal, authority)
                result = store.commit_write_plan(
                    expected_current_hash=root,
                    proposal=proposal,
                    authority=authority,
                    decision=planning["decision"],
                    plan=planning["plan"],
                    transaction_id=txid,
                )
                journal = json.loads(
                    (store.root / "transactions" / f"{txid}.json").read_text()
                )
                if target == "stage":
                    identifier = journal["stage_object"]
                    path = store._path_for(f"transactions/{txid}/stages", identifier)
                    unrelated = json.loads(path.read_text())
                    path.unlink()
                    unrelated["candidate"] = root
                    store._write_json_object(
                        f"transactions/{txid}/stages", unrelated
                    )
                else:
                    matches = []
                    for path in (store.root / "refs" / "ref-log" / "sha256").glob(
                        "*.json"
                    ):
                        value = json.loads(path.read_text())
                        if (
                            value.get("kind") == "intent"
                            and value.get("transaction_id") == txid
                            and value.get("candidate") == result["revision"]
                        ):
                            matches.append((path, value))
                    self.assertEqual(len(matches), 1)
                    path, unrelated = matches[0]
                    path.unlink()
                    unrelated["candidate"] = root
                    store._write_json_object("refs/ref-log", unrelated)

                inspected = store.inspect_transaction(txid)
                self.assertEqual(inspected["durability_state"], "incomplete")
                with self.assertRaisesRegex(TransactionError, error):
                    store.repair_transaction_durability(txid)
                self.assertEqual(
                    store.inspect_transaction(txid)["durability_state"], "incomplete"
                )

    def test_current_directory_fsync_failure_is_distinct_after_replace(self) -> None:
        proposal = _proposal(self.root, "f-current-dir")
        authority = _authority(proposal)
        planning = self.store.plan_write(proposal, authority)
        original = self.store._fsync_directory

        def fail_refs(path):
            if path == self.store.current_path.parent:
                raise storage_error("directory_fsync_failed", OSError("EIO"))
            return original(path)

        with patch.object(self.store, "_fsync_directory", side_effect=fail_refs):
            result = self.store.commit_write_plan(
                expected_current_hash=self.root,
                proposal=proposal,
                authority=authority,
                decision=planning["decision"],
                plan=planning["plan"],
                transaction_id=str(uuid.uuid4()),
            )
        self.assertTrue(result["committed"])
        self.assertEqual(result["outcome"]["state"], "durability_incomplete")
        self.assertEqual(
            result["outcome"]["operation_error_code"], "directory_fsync_failed"
        )

    def test_current_reread_failure_is_runtime_unknown_but_inspect_converges(self) -> None:
        proposal = _proposal(self.root, "f-reread")
        authority = _authority(proposal)
        planning = self.store.plan_write(proposal, authority)
        txid = str(uuid.uuid4())
        original = self.store.read_current

        def fail_after_advance():
            value = original()
            if value != self.root:
                raise OSError("read-EIO")
            return value

        with patch.object(self.store, "read_current", side_effect=fail_after_advance):
            result = self.store.commit_write_plan(
                expected_current_hash=self.root,
                proposal=proposal,
                authority=authority,
                decision=planning["decision"],
                plan=planning["plan"],
                transaction_id=txid,
            )
        self.assertIsNone(result["outcome"]["committed"])
        self.assertEqual(result["outcome"]["state"], "outcome_unknown")
        self.assertEqual(
            result["outcome"]["operation_error_code"], "current_reread_failed"
        )
        inspected = self.store.inspect_transaction(txid)
        self.assertTrue(inspected["committed"])
        self.assertEqual(inspected["candidate_relation"], "current")

    def test_corrupt_or_missing_journal_reconstructs_from_immutable_stage(self) -> None:
        for mode in ("corrupt", "missing"):
            with self.subTest(mode=mode):
                with tempfile.TemporaryDirectory() as project:
                    store = MemoryStore(project)
                    root = store.initialize()
                    txid = str(uuid.uuid4())
                    proposal = _proposal(root, "f-" + mode)
                    authority = _authority(proposal)
                    planning = store.plan_write(proposal, authority)
                    result = store.commit_write_plan(
                        expected_current_hash=root,
                        proposal=proposal,
                        authority=authority,
                        decision=planning["decision"],
                        plan=planning["plan"],
                        transaction_id=txid,
                    )
                    journal = store.root / "transactions" / f"{txid}.json"
                    if mode == "corrupt":
                        journal.write_bytes(b"{")
                    else:
                        journal.unlink()
                    inspected = store.inspect_transaction(txid)
                    self.assertTrue(inspected["committed"])
                    self.assertEqual(inspected["candidate_revision"], result["revision"])
                    self.assertEqual(inspected["audit_state"], "incomplete")
                    self.assertEqual(inspected["durability_state"], "complete")

    def test_missing_or_corrupt_journal_cannot_rebind_txid_to_second_child(self) -> None:
        for mode in ("corrupt", "missing"):
            with self.subTest(mode=mode):
                with tempfile.TemporaryDirectory() as project:
                    store = MemoryStore(project)
                    root = store.initialize()
                    txid = str(uuid.uuid4())
                    first_proposal = _proposal(root, "f-first-" + mode)
                    first_authority = _authority(first_proposal)
                    first_plan = store.plan_write(first_proposal, first_authority)
                    first = store.commit_write_plan(
                        expected_current_hash=root,
                        proposal=first_proposal,
                        authority=first_authority,
                        decision=first_plan["decision"],
                        plan=first_plan["plan"],
                        transaction_id=txid,
                    )
                    journal = store.root / "transactions" / f"{txid}.json"
                    if mode == "corrupt":
                        journal.write_bytes(b"{")
                    else:
                        journal.unlink()
                    second_proposal = _proposal(first["revision"], "f-second-" + mode)
                    second_authority = _authority(second_proposal)
                    second_plan = store.plan_write(second_proposal, second_authority)
                    with self.assertRaisesRegex(
                        TransactionError, "transaction_binding_conflict"
                    ):
                        store.commit_write_plan(
                            expected_current_hash=first["revision"],
                            proposal=second_proposal,
                            authority=second_authority,
                            decision=second_plan["decision"],
                            plan=second_plan["plan"],
                            transaction_id=txid,
                        )
                    self.assertEqual(store.read_current(), first["revision"])
                    self.assertEqual(store.snapshot().manifest["revision"], 1)

    def test_manifest_without_journal_or_stage_cannot_rebind_txid(self) -> None:
        txid = str(uuid.uuid4())
        first = self._commit(self.root, "f-binding-lost", txid)
        (self.store.root / "transactions" / f"{txid}.json").unlink()
        for path in (
            self.store.root / "transactions" / txid / "stages" / "sha256"
        ).glob("*.json"):
            path.unlink()
        second_proposal = _proposal(first["revision"], "f-second-binding")
        second_authority = _authority(second_proposal)
        second_plan = self.store.plan_write(second_proposal, second_authority)
        with self.assertRaisesRegex(
            TransactionError, "transaction_evidence_missing_or_invalid"
        ):
            self.store.commit_write_plan(
                expected_current_hash=first["revision"],
                proposal=second_proposal,
                authority=second_authority,
                decision=second_plan["decision"],
                plan=second_plan["plan"],
                transaction_id=txid,
            )
        self.assertEqual(self.store.read_current(), first["revision"])

    def test_retry_resyncs_existing_segment_before_receipt(self) -> None:
        proposal = _proposal(self.root, "f-resync-existing")
        authority = _authority(proposal)
        planning = self.store.plan_write(proposal, authority)
        txid = str(uuid.uuid4())
        original = self.store._fsync_directory
        failed_once = False

        def fail_segment_directory(path):
            nonlocal failed_once
            if "segments/facts/sha256" in path.as_posix() and not failed_once:
                failed_once = True
                raise storage_error("directory_fsync_failed", OSError("EIO"))
            return original(path)

        with patch.object(
            self.store, "_fsync_directory", side_effect=fail_segment_directory
        ):
            failed = self.store.commit_write_plan(
                expected_current_hash=self.root,
                proposal=proposal,
                authority=authority,
                decision=planning["decision"],
                plan=planning["plan"],
                transaction_id=txid,
            )
        self.assertEqual(failed["outcome"]["state"], "durability_incomplete")
        synced: list[str] = []
        from an_kla import storage_primitives

        primitive_fsync = storage_primitives.fsync_directory

        def observe(path):
            synced.append(path.as_posix())
            return primitive_fsync(path)

        with patch(
            "an_kla.storage_primitives.fsync_directory", side_effect=observe
        ):
            retried = self.store.commit_write_plan(
                expected_current_hash=self.root,
                proposal=proposal,
                authority=authority,
                decision=planning["decision"],
                plan=planning["plan"],
                transaction_id=txid,
            )
        self.assertTrue(retried["committed"])
        self.assertTrue(any("segments/facts/sha256" in path for path in synced))

    def test_multiple_manifests_for_txid_fail_inspection_closed(self) -> None:
        txid = str(uuid.uuid4())
        result = self._commit(self.root, "f-ambiguous", txid)
        forged = dict(self.store.snapshot(result["revision"]).manifest)
        forged["revision"] = 999
        self.store._write_json_object("revisions", forged)
        inspected = self.store.inspect_transaction(txid)
        self.assertEqual(inspected["state"], "outcome_unknown")
        self.assertIsNone(inspected["committed"])
        self.assertEqual(
            inspected["operation_error_code"], "transaction_candidate_ambiguous"
        )

    @unittest.skipIf(os.name == "nt", "POSIX flock fault injection")
    def test_unlock_failure_is_audit_warning_not_masking_commit(self) -> None:
        import fcntl

        original = fcntl.flock

        def injected(fd, operation):
            if operation == fcntl.LOCK_UN:
                raise OSError("unlock-EIO")
            return original(fd, operation)

        with patch("fcntl.flock", side_effect=injected):
            result = self._commit(self.root, "f-unlock", str(uuid.uuid4()))
        self.assertTrue(result["committed"])
        self.assertEqual(result["outcome"]["state"], "committed_audit_incomplete")
        self.assertIn("lock_release_incomplete", result["outcome"]["warnings"])


class StrictFsyncTests(unittest.TestCase):
    def test_directory_open_failure_is_not_silenced(self) -> None:
        target = Path(tempfile.gettempdir())
        with patch("an_kla.storage_primitives.os.open", side_effect=OSError("EIO")):
            with self.assertRaisesRegex(OSError, "directory_open_failed") as raised:
                fsync_directory(target)
        self.assertIn("EIO", str(raised.exception.cause))


if __name__ == "__main__":
    unittest.main()
