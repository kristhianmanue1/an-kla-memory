"""H1 (issue #103): validación temprana en ``plan-write``.

Repros del consumidor (issue #102 §3.1): ``duplicate_facts_id`` y
``invalid_supersede_target`` (target_missing / target_not_vigente) ocurrían
sólo en commit, rompiendo el flujo bifásico del agente. Ahora fallan cerrado
en ``plan_write`` con códigos ``plan_*`` estables, leyendo el snapshot base
read-only; la resolución autoritativa bajo lock en commit se conserva
(TOCTOU) y el policy core permanece puro.

Nota de diseño (ronda adversarial del plan #102 absorbida): la
autorreferencia ya fallaba en plan vía ``validate_write_proposal``
(supersedes:self_reference_forbidden); se testea para que siga así.
"""

from __future__ import annotations

import tempfile
import unittest

from an_kla.canonical import digest_json
from an_kla.store import MemoryStore
from an_kla.write_policy import WritePolicyError


DIGEST_B = "sha256:" + "b" * 64


def proposal(
    base: str,
    record_id: str = "f-policy",
    *,
    operation: str = "add",
    supersedes: str | None = None,
) -> dict:
    candidate = {
        "schema": "an-kla/write-proposal-v1",
        "base_revision": base,
        "stream": "facts",
        "operation": operation,
        "requested_representation": "summary",
        "record": {"id": record_id, "text": "memoria durable"},
        "lineage": {"derived_from_retrieval": False, "refs": []},
    }
    if supersedes is not None:
        candidate["supersedes"] = supersedes
    return candidate


def authority(candidate: dict) -> dict:
    return {
        "schema": "an-kla/write-authority-v1",
        "proposal_sha256": digest_json(candidate),
        "base_revision": candidate["base_revision"],
        "authority_class": "model_derived",
        "issuer": {
            "kind": "model",
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


class PlanWriteEarlyValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(self.temp.name)
        self.root = self.store.initialize()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _plan(self, candidate: dict) -> dict:
        return self.store.plan_write(candidate, authority(candidate))

    def _commit(self, candidate: dict) -> dict:
        planning = self._plan(candidate)
        return self.store.commit_write_plan(
            expected_current_hash=candidate["base_revision"],
            proposal=candidate,
            authority=authority(candidate),
            decision=planning["decision"],
            plan=planning["plan"],
        )

    def _seed_fact(self, record_id: str) -> str:
        candidate = proposal(self.store.read_current(), record_id)
        result = self._commit(candidate)
        self.assertTrue(result["committed"])
        return result["revision"]

    def test_duplicate_id_fails_at_plan_not_commit(self) -> None:
        self._seed_fact("f-dup")
        candidate = proposal(self.store.read_current(), "f-dup")
        with self.assertRaisesRegex(WritePolicyError, "plan_duplicate_id"):
            self._plan(candidate)

    def test_supersede_missing_target_fails_at_plan_not_commit(self) -> None:
        candidate = proposal(
            self.store.read_current(),
            "f-new",
            operation="supersede",
            supersedes="f-fantasma",
        )
        with self.assertRaisesRegex(
            WritePolicyError, "plan_supersede_target_missing"
        ):
            self._plan(candidate)

    def test_double_supersede_fails_at_plan_not_commit(self) -> None:
        revision = self._seed_fact("f-objeto")
        candidate = proposal(
            revision, "f-hija", operation="supersede", supersedes="f-objeto"
        )
        result = self._commit(candidate)
        self.assertTrue(result["committed"])
        snapshot = self.store.snapshot(result["revision"])
        self.assertEqual(snapshot.records["facts"][0].get("status"), "sustituida")
        repeat = proposal(
            self.store.read_current(),
            "f-nueva",
            operation="supersede",
            supersedes="f-objeto",
        )
        with self.assertRaisesRegex(
            WritePolicyError, "plan_supersede_target_not_vigente"
        ):
            self._plan(repeat)

    def test_self_reference_still_fails_at_plan(self) -> None:
        candidate = proposal(
            self.store.read_current(),
            "f-auto",
            operation="supersede",
            supersedes="f-auto",
        )
        with self.assertRaises(WritePolicyError) as caught:
            self._plan(candidate)
        # str(error) equals code; detail is informative (not a contract).
        self.assertEqual(caught.exception.code, "invalid_write_proposal")
        self.assertEqual(caught.exception.detail, "supersedes:self_reference_forbidden")

    def test_skip_decision_takes_precedence_over_early_checks(self) -> None:
        self._seed_fact("f-dup")
        candidate = proposal(self.store.read_current(), "f-dup")
        auth = authority(candidate)
        auth["authority_class"] = "unresolved"
        auth["issuer"]["kind"] = "unknown"
        planning = self.store.plan_write(candidate, auth)
        self.assertEqual(planning["decision"]["decision"], "skip")
        self.assertIn("unresolved_authority", planning["decision"]["reason_codes"])

    def test_valid_flow_still_plans_and_commits(self) -> None:
        revision = self._seed_fact("f-uno")
        candidate = proposal(revision, "f-dos")
        planning = self._plan(candidate)
        self.assertEqual(planning["decision"]["decision"], "write-summary")
        result = self.store.commit_write_plan(
            expected_current_hash=revision,
            proposal=candidate,
            authority=authority(candidate),
            decision=planning["decision"],
            plan=planning["plan"],
        )
        self.assertTrue(result["committed"])
        snapshot = self.store.snapshot(result["revision"])
        self.assertEqual(
            [row["id"] for row in snapshot.records["facts"]], ["f-uno", "f-dos"]
        )


if __name__ == "__main__":
    unittest.main()
