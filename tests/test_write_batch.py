"""Commit gobernado en lote — write-proposal/v2 (ADR-0054, issue #149 P2d).

Contratos congelados: homogeneidad, evaluación contra estado pre-lote,
prohibición de supersede intra-lote, atomicidad all-or-nothing con efectos
cero, un evento por lote con digests ordenados, y una revisión por lote.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from an_kla.canonical import digest_json
from an_kla.store import MemoryStore
from an_kla.write_policy import WritePolicyError, evaluate_write

DIGEST_B = "sha256:" + "b" * 64
TEXT = "registro {i} sobre quetzal y memoria de trabajo"


def authority(candidate: dict) -> dict:
    return {
        "schema": "an-kla/write-authority-v1",
        "proposal_sha256": digest_json(candidate),
        "base_revision": candidate["base_revision"],
        "authority_class": "model_derived",
        "issuer": {"kind": "model", "id": "batch-test",
                   "configuration_fingerprint": DIGEST_B},
        "evidence": [],
        "scope": {
            "streams": [candidate["stream"]],
            "representations": [candidate["requested_representation"]],
            "operations": [candidate["operation"]],
        },
    }


def batch(
    base: str,
    count: int = 3,
    *,
    operation: str = "add",
    supersedes: dict | None = None,
) -> dict:
    proposal = {
        "schema": "an-kla/write-proposal-v2",
        "base_revision": base,
        "stream": "facts",
        "operation": operation,
        "requested_representation": "summary",
        "records": [
            {"id": f"b-{i}", "payload": {"text": TEXT.format(i=i)}}
            for i in range(count)
        ],
        "lineage": {"derived_from_retrieval": False, "refs": []},
    }
    if supersedes is not None:
        proposal["supersedes"] = supersedes
    return proposal


def governed(store, cur: str, proposal: dict) -> str:
    auth = authority(proposal)
    planning = store.plan_write(proposal, auth)
    result = store.commit_write_plan(
        expected_current_hash=cur, proposal=proposal, authority=auth,
        decision=planning["decision"], plan=planning["plan"],
    )
    assert result["committed"] is True
    return result["revision"]


class BatchShapeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = "sha256:" + "0" * 64

    def _error(self, proposal: dict) -> tuple[str, str]:
        with self.assertRaises(WritePolicyError) as caught:
            evaluate_write(proposal, authority(proposal))
        return caught.exception.code, str(caught.exception.detail)

    def test_rejects_empty_and_oversized(self) -> None:
        code, detail = self._error(batch(self.base, count=0))
        self.assertEqual(code, "invalid_write_proposal")
        self.assertIn("records:not_list", detail)

    def test_rejects_duplicate_ids(self) -> None:
        proposal = batch(self.base, count=2)
        proposal["records"][1]["id"] = "b-0"
        code, detail = self._error(proposal)
        self.assertIn("records:duplicate_id", detail)

    def test_rejects_intra_batch_supersede(self) -> None:
        proposal = batch(
            self.base, count=2, operation="supersede",
            supersedes={"b-0": "b-1", "b-1": "b-0"},
        )
        code, detail = self._error(proposal)
        self.assertIn("supersedes:intra_batch_forbidden", detail)

    def test_rejects_partial_supersede_mapping(self) -> None:
        proposal = batch(
            self.base, count=2, operation="supersede",
            supersedes={"b-0": "target"},
        )
        code, detail = self._error(proposal)
        self.assertIn("supersedes:missing_for_supersede", detail)

    def test_rejects_self_reference(self) -> None:
        proposal = batch(
            self.base, count=1, operation="supersede",
            supersedes={"b-0": "b-0"},
        )
        code, detail = self._error(proposal)
        self.assertIn("supersedes:self_reference_forbidden", detail)

    def test_rejects_supersedes_without_operation(self) -> None:
        proposal = batch(self.base, count=1)
        proposal["supersedes"] = {"b-0": "x"}
        code, detail = self._error(proposal)
        self.assertIn("supersedes:present_without_supersede", detail)


class BatchGovernedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(self.temp.name)
        self.cur = self.store.initialize()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_one_revision_one_event_per_batch(self) -> None:
        revision = governed(self.store, self.cur, batch(self.cur, count=5))
        snap = self.store.snapshot(revision)
        self.assertEqual(len(snap.records["facts"]), 5)
        events = [
            row for row in snap.records["events"]
            if row.get("type") == "write_policy_decision"
        ]
        self.assertEqual(len(events), 1)
        payload = events[0]["payload"]
        self.assertEqual(len(payload["batch_records_sha256"]), 5)
        self.assertEqual(
            payload["batch_records_sha256"],
            sorted(payload["batch_records_sha256"]),
        )

    def test_batch_supersede_marks_targets(self) -> None:
        first = governed(self.store, self.cur, batch(self.cur, count=2))
        proposal = batch(first, count=1, operation="supersede",
                         supersedes={"b-new": "b-1"})
        proposal["records"][0]["id"] = "b-new"
        second = governed(self.store, first, proposal)
        snap = self.store.snapshot(second)
        statuses = {
            row["id"]: row.get("status") for row in snap.records["facts"]
        }
        self.assertIsNone(statuses.get("b-0"))
        self.assertEqual(statuses.get("b-1"), "sustituida")
        self.assertIn("b-new", statuses)

    def test_ceiling_skip_has_zero_effects(self) -> None:
        proposal = batch(self.cur, count=3)
        proposal["requested_representation"] = "full"
        auth = authority(proposal)
        planning = self.store.plan_write(proposal, auth)
        self.assertEqual(planning["decision"]["decision"], "skip")
        self.assertIn(
            "summary_required_for_authority_ceiling",
            planning["decision"]["reason_codes"],
        )
        self.assertEqual(planning["plan"]["records"], [])
        before = self.store.read_current()
        result = self.store.commit_write_plan(
            expected_current_hash=self.cur, proposal=proposal,
            authority=auth, decision=planning["decision"],
            plan=planning["plan"],
        )
        self.assertFalse(result["committed"])
        self.assertEqual(self.store.read_current(), before)

    def test_guard_rejects_duplicate_against_snapshot(self) -> None:
        governed(self.store, self.cur, batch(self.cur, count=1))
        proposal = batch(self.store.read_current(), count=2)
        proposal["records"][0]["id"] = "b-0"
        with self.assertRaises(WritePolicyError) as caught:
            self.store.plan_write(proposal, authority(proposal))
        self.assertEqual(caught.exception.code, "plan_duplicate_id")

    def test_guard_rejects_intra_batch_target_at_plan_time(self) -> None:
        first = governed(self.store, self.cur, batch(self.cur, count=2))
        proposal = batch(first, count=1, operation="supersede",
                         supersedes={"b-fresh": "no-existe"})
        proposal["records"][0]["id"] = "b-fresh"
        with self.assertRaises(WritePolicyError) as caught:
            self.store.plan_write(proposal, authority(proposal))
        self.assertEqual(caught.exception.code, "plan_supersede_target_missing")

    def test_record_without_text_reason_aggregates(self) -> None:
        proposal = batch(self.cur, count=2)
        proposal["records"][1]["payload"] = {"number": 7}
        decision = evaluate_write(proposal, authority(proposal))
        self.assertEqual(decision["decision"], "write-summary")
        self.assertIn("record_without_indexable_text", decision["reason_codes"])


if __name__ == "__main__":
    unittest.main()
