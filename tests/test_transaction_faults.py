from __future__ import annotations

import tempfile
import unittest
import uuid
from unittest.mock import patch
from an_kla.store import MemoryStore
from tests.test_transactions import _authority, _proposal


class TransactionFaultMatrixTests(unittest.TestCase):
    def _run_case(self, point: str) -> None:
        with tempfile.TemporaryDirectory() as project:
            store = MemoryStore(project)
            root = store.initialize()
            proposal = _proposal(root, "f-" + point.replace("_", "-"))
            authority = _authority(proposal)
            planning = store.plan_write(proposal, authority)
            txid = str(uuid.uuid4())

            def commit() -> dict:
                return store.commit_write_plan(
                    expected_current_hash=root,
                    proposal=proposal,
                    authority=authority,
                    decision=planning["decision"],
                    plan=planning["plan"],
                    transaction_id=txid,
                )

            patches = []
            if point in {"journal_prepared", "journal_candidate", "journal_committed"}:
                original = store._write_transaction
                target_stage = point.removeprefix("journal_")
                if target_stage == "candidate":
                    target_stage = "candidate_prepared"

                def write_transaction(tx, body):
                    if body.get("stage") == target_stage:
                        raise OSError("injected-" + point)
                    return original(tx, body)

                patches.append(patch.object(store, "_write_transaction", write_transaction))
            elif point == "segment":
                patches.append(
                    patch.object(store, "_write_segment", side_effect=OSError("injected-segment"))
                )
            elif point in {"checkpoint", "manifest", "candidate_stage"}:
                original = store._write_json_object
                wanted = {
                    "checkpoint": "checkpoints",
                    "manifest": "revisions",
                    "candidate_stage": f"transactions/{txid}/stages",
                }[point]

                def write_json(kind, value):
                    if kind == wanted:
                        raise OSError("injected-" + point)
                    return original(kind, value)

                patches.append(patch.object(store, "_write_json_object", write_json))
            elif point in {"intent", "observed_log"}:
                original = store._write_ref_log
                wanted = "intent" if point == "intent" else "observed_commit"

                def write_ref(entry):
                    if entry.get("kind") == wanted:
                        raise OSError("injected-" + point)
                    return original(entry)

                patches.append(patch.object(store, "_write_ref_log", write_ref))
            elif point == "replace_current":
                patches.append(
                    patch.object(
                        store, "_replace_current", side_effect=OSError("injected-replace")
                    )
                )
            elif point in {"candidate_receipt", "current_receipt"}:
                from an_kla import transactions

                original = transactions.write_receipt
                wanted = point.replace("_receipt", "-data-durable")
                if point == "current_receipt":
                    wanted = "current-durable"

                def receipt(*args, **kwargs):
                    if kwargs.get("kind") == wanted:
                        raise OSError("injected-" + point)
                    return original(*args, **kwargs)

                patches.append(patch("an_kla.transactions.write_receipt", receipt))
            else:
                raise AssertionError(point)

            with patches[0]:
                result = commit()
            outcome = result["outcome"]
            self.assertEqual(outcome["schema"], "an-kla/commit-outcome-v2")
            self.assertEqual(outcome["transaction_id"], txid)
            committed_points = {
                "current_receipt",
                "journal_committed",
                "observed_log",
            }
            self.assertEqual(result["committed"], point in committed_points)

            current_after_failure = store.read_current()
            if point not in committed_points:
                self.assertEqual(current_after_failure, root)
                retry = commit()
                self.assertTrue(retry["committed"])
                self.assertEqual(store.snapshot().manifest["revision"], 1)
            else:
                self.assertNotEqual(current_after_failure, root)
                inspected = store.inspect_transaction(txid)
                self.assertTrue(inspected["committed"])
                if point in {"journal_committed", "observed_log"}:
                    self.assertEqual(inspected["audit_state"], "incomplete")
                    self.assertEqual(inspected["state"], "committed_audit_incomplete")
                self.assertEqual(store.read_current(), current_after_failure)
                self.assertEqual(store.snapshot().manifest["revision"], 1)
                if inspected["durability_state"] == "incomplete":
                    repaired = store.repair_transaction_durability(txid)
                    self.assertEqual(repaired["durability_state"], "complete")

    def test_fault_matrix_converges(self) -> None:
        points = (
            "journal_prepared",
            "segment",
            "manifest",
            "intent",
            "candidate_stage",
            "journal_candidate",
            "candidate_receipt",
            "replace_current",
            "current_receipt",
            "journal_committed",
            "observed_log",
        )
        for point in points:
            with self.subTest(point=point):
                self._run_case(point)

    def test_initialize_faults_converge_with_same_txid(self) -> None:
        points = (
            "journal_prepared",
            "checkpoint",
            "manifest",
            "candidate_receipt",
            "replace_current",
            "current_receipt",
            "journal_committed",
        )
        for point in points:
            with self.subTest(point=point), tempfile.TemporaryDirectory() as project:
                store = MemoryStore(project)
                txid = str(uuid.uuid4())
                if point.startswith("journal_"):
                    original = store._write_transaction
                    wanted = point.removeprefix("journal_")

                    def journal(tx, body, *, _wanted=wanted):
                        if body.get("stage") == _wanted:
                            raise OSError("init-" + point)
                        return original(tx, body)

                    context = patch.object(store, "_write_transaction", journal)
                elif point in {"checkpoint", "manifest"}:
                    original_json = store._write_json_object
                    wanted_kind = "checkpoints" if point == "checkpoint" else "revisions"

                    def write_json(kind, value, *, _wanted=wanted_kind):
                        if kind == _wanted:
                            raise OSError("init-" + point)
                        return original_json(kind, value)

                    context = patch.object(store, "_write_json_object", write_json)
                elif point == "replace_current":
                    context = patch.object(
                        store, "_replace_current", side_effect=OSError("init-replace")
                    )
                else:
                    from an_kla import initialization

                    original_receipt = initialization.write_receipt
                    wanted_receipt = (
                        "candidate-data-durable"
                        if point == "candidate_receipt"
                        else "current-durable"
                    )

                    def receipt(*args, _wanted=wanted_receipt, **kwargs):
                        if kwargs.get("kind") == _wanted:
                            raise OSError("init-" + point)
                        return original_receipt(*args, **kwargs)

                    context = patch("an_kla.initialization.write_receipt", receipt)
                with context:
                    failed = store.initialize_with_outcome(transaction_id=txid)
                committed = point in {"current_receipt", "journal_committed"}
                self.assertEqual(failed["outcome"]["committed"], committed)
                retried = store.initialize_with_outcome(transaction_id=txid)
                self.assertTrue(retried["outcome"]["committed"])
                self.assertEqual(store.snapshot().manifest["revision"], 0)


if __name__ == "__main__":
    unittest.main()
