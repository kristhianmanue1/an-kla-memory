"""H2 (issue #104): warning de registro sin texto indexable en el outcome.

El reason code ``record_without_indexable_text`` ya viajaba en la decisión
(write_policy.py), pero el consumidor (issue #102 §3.2) no lo vio y el
registro quedó invisible para retrieval. Ahora el warning también aparece en
``outcome.warnings`` de ``commit-write-plan`` (commit-outcome-v2 ya declara
el campo). Restricción adversarial respetada: nada se añade al
planning-result (gate de claves exactas en ``_planning_result``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from an_kla.canonical import digest_json
from an_kla.store import MemoryStore


ROOT = Path(__file__).resolve().parents[1]


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


class CommitIndexableWarningCliTests(unittest.TestCase):
    """Issue #111 (P1): el warning debe verse sin leer JSON crudo.

    La capa CLI replica ``record_without_indexable_text`` en stderr sin
    contaminar el stdout programático (JSON canónico del resultado).
    """

    def test_commit_stderr_warns_and_stdout_stays_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            env = {**os.environ, "AN_KLA_NO_UPDATE_CHECK": "1"}

            def run(*argv: str) -> subprocess.CompletedProcess:
                return subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "an_kla",
                        "--project-root",
                        root,
                        *argv,
                    ],
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=60,
                )

            run("init")
            base = json.loads(run("status").stdout)["revision"]
            proposal = {
                "schema": "an-kla/write-proposal-v1",
                "base_revision": base,
                "stream": "facts",
                "operation": "add",
                "requested_representation": "summary",
                "record": {"id": "f-cli-sin-texto", "contenido": "propio"},
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
            proposal_path = Path(root) / "proposal.json"
            authority_path = Path(root) / "authority.json"
            proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
            authority_path.write_text(json.dumps(authority), encoding="utf-8")
            planning = run(
                "plan-write",
                "--proposal",
                str(proposal_path),
                "--authority",
                str(authority_path),
            ).stdout
            planning_path = Path(root) / "planning-result.json"
            planning_path.write_text(planning, encoding="utf-8")

            completed = run(
                "commit-write-plan",
                "--expected-current",
                base,
                "--proposal",
                str(proposal_path),
                "--authority",
                str(authority_path),
                "--planning-result",
                str(planning_path),
            )

            self.assertIn(
                "warning: record_without_indexable_text "
                "(id=f-cli-sin-texto)",
                completed.stderr,
            )
            payload = json.loads(completed.stdout)
            self.assertIn(
                "record_without_indexable_text",
                payload["outcome"]["warnings"],
            )
            self.assertNotIn("warning:", completed.stdout)


if __name__ == "__main__":
    unittest.main()
