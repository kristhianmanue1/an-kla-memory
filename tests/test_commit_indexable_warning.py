"""H2 (issue #104): warning de registro sin texto indexable en el outcome.

El reason code ``record_without_indexable_text`` ya viajaba en la decisión
(write_policy.py), pero el consumidor (issue #102 §3.2) no lo vio y el
registro quedó invisible para retrieval. Ahora el warning también aparece en
``outcome.warnings`` de ``commit-write-plan`` (commit-outcome-v2 ya declara
el campo). Restricción adversarial respetada: nada se añade al
planning-result (gate de claves exactas en ``_planning_result``).
"""

from __future__ import annotations

import tempfile
import unittest

from an_kla.canonical import digest_json
from an_kla.store import MemoryStore


DIGEST_B = "sha256:" + "b" * 64


def _candidate(store: MemoryStore, base: str, record: dict) -> tuple[dict, dict]:
    proposal = {
        "schema": "an-kla/write-proposal-v1",
        "base_revision": base,
        "stream": "facts",
        "operation": "add",
        "requested_representation": "summary",
        "record": record,
        "lineage": {"derived_from_retrieval": False, "refs": []},
    }
    authority = {
        "schema": "an-kla/write-authority-v1",
        "proposal_sha256": digest_json(proposal),
        "base_revision": base,
        "authority_class": "model_derived",
        "issuer": {
            "kind": "model",
            "id": "test-authority",
            "configuration_fingerprint": DIGEST_B,
        },
        "evidence": [],
        "scope": {
            "streams": ["facts"],
            "representations": ["summary"],
            "operations": ["add"],
        },
    }
    return proposal, authority


class CommitIndexableWarningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(self.temp.name)
        self.root = self.store.initialize()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _commit(self, record: dict) -> dict:
        base = self.store.read_current()
        candidate, auth = _candidate(self.store, base, record)
        planning = self.store.plan_write(candidate, auth)
        return self.store.commit_write_plan(
            expected_current_hash=base,
            proposal=candidate,
            authority=auth,
            decision=planning["decision"],
            plan=planning["plan"],
        )

    def test_unindexable_record_warns_on_outcome(self) -> None:
        result = self._commit({"id": "f-sin-texto", "contenido": "propio"})
        self.assertTrue(result["committed"])
        self.assertIn(
            "record_without_indexable_text", result["reason_codes"]
        )
        self.assertIn(
            "record_without_indexable_text", result["outcome"]["warnings"]
        )

    def test_indexable_record_does_not_warn(self) -> None:
        result = self._commit({"id": "f-con-texto", "text": "visible"})
        self.assertTrue(result["committed"])
        self.assertNotIn(
            "record_without_indexable_text", result["outcome"]["warnings"]
        )
        self.assertNotIn(
            "record_without_indexable_text", result["reason_codes"]
        )

    def test_supersede_record_without_text_also_warns(self) -> None:
        # Follow-up adversarial (LOW): el código es op-agnóstico — cubre
        # add y supersede por igual.
        base = self.store.read_current()
        seed, seed_auth = _candidate(
            self.store, base, {"id": "f-viejo", "text": "viejo"}
        )
        seed_plan = self.store.plan_write(seed, seed_auth)
        committed = self.store.commit_write_plan(
            expected_current_hash=base,
            proposal=seed,
            authority=seed_auth,
            decision=seed_plan["decision"],
            plan=seed_plan["plan"],
        )
        self.assertTrue(committed["committed"])

        successor = {
            "schema": "an-kla/write-proposal-v1",
            "base_revision": committed["revision"],
            "stream": "facts",
            "operation": "supersede",
            "requested_representation": "summary",
            "record": {"id": "f-nuevo", "contenido": "propio"},
            "lineage": {"derived_from_retrieval": False, "refs": []},
            "supersedes": "f-viejo",
        }
        auth = {
            "schema": "an-kla/write-authority-v1",
            "proposal_sha256": digest_json(successor),
            "base_revision": successor["base_revision"],
            "authority_class": "model_derived",
            "issuer": {
                "kind": "model",
                "id": "test-authority",
                "configuration_fingerprint": DIGEST_B,
            },
            "evidence": [],
            "scope": {
                "streams": ["facts"],
                "representations": ["summary"],
                "operations": ["supersede"],
            },
        }
        plan = self.store.plan_write(successor, auth)
        result = self.store.commit_write_plan(
            expected_current_hash=successor["base_revision"],
            proposal=successor,
            authority=auth,
            decision=plan["decision"],
            plan=plan["plan"],
        )
        self.assertTrue(result["committed"])
        self.assertIn(
            "record_without_indexable_text", result["outcome"]["warnings"]
        )


if __name__ == "__main__":
    unittest.main()
