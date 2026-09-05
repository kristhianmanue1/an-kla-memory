"""test_write_commit_cli.py — partición de tests/test_write_commit.py por unidad bajo prueba (beta.22, issue #106).

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


class WriteCommitCliTests(unittest.TestCase):
    def test_write_help_explains_inputs_and_sequential_current(self) -> None:
        root = Path(__file__).resolve().parents[1]
        planned = subprocess.run(
            [sys.executable, "-m", "an_kla", "plan-write", "--help"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        committed = subprocess.run(
            [sys.executable, "-m", "an_kla", "commit-write-plan", "--help"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )

        self.assertIn("an-kla/write-proposal-v1", planned.stdout)
        self.assertIn("an-kla/write-authority-v1", planned.stdout)
        self.assertIn("status", planned.stdout)
        self.assertIn("Digest revision obtenido de status", committed.stdout)
        self.assertIn("stdout exacto de plan-write", committed.stdout)
        self.assertIn("Cada commit mueve CURRENT", committed.stdout)

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
            self.assertIn(b"input_json_unreadable (proposal)", completed.stderr)
            self.assertNotIn(str(secret_path).encode(), completed.stderr)

    def test_cli_invalid_json_names_role_without_disclosing_payload(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = MemoryStore(root)
            store.initialize()
            invalid = Path(root) / "private-authority-name.json"
            invalid.write_text('{"secret":"do-not-disclose"', encoding="utf-8")
            proposal_path = Path(root) / "proposal.json"
            proposal_path.write_text("{}", encoding="utf-8")

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
                    str(invalid),
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                timeout=30,
            )

            self.assertEqual(completed.returncode, 2)
            self.assertIn(b"input_json_invalid (authority)", completed.stderr)
            self.assertNotIn(str(invalid).encode(), completed.stderr)
            self.assertNotIn(b"do-not-disclose", completed.stderr)

    def test_cli_unreadable_planning_result_names_role_without_path(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = MemoryStore(root)
            base = store.initialize()
            missing = Path(root) / "private-planning-name.json"
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
                    str(missing),
                    "--authority",
                    str(missing),
                    "--planning-result",
                    str(missing),
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                timeout=30,
            )

            self.assertEqual(completed.returncode, 2)
            self.assertIn(
                b"input_json_unreadable (planning_result)", completed.stderr
            )
            self.assertNotIn(str(missing).encode(), completed.stderr)

    def test_cli_stale_base_includes_sanitized_recovery_hint(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = MemoryStore(root)
            base = store.initialize()
            stale_candidate = proposal(base, "f-stale")
            stale_authority = authority(stale_candidate)

            advancing_candidate = proposal(base, "f-advance")
            advancing_authority = authority(advancing_candidate)
            planning = store.plan_write(advancing_candidate, advancing_authority)
            store.commit_write_plan(
                expected_current_hash=base,
                proposal=advancing_candidate,
                authority=advancing_authority,
                decision=planning["decision"],
                plan=planning["plan"],
            )

            proposal_path = Path(root) / "proposal.json"
            authority_path = Path(root) / "authority.json"
            proposal_path.write_text(json.dumps(stale_candidate), encoding="utf-8")
            authority_path.write_text(json.dumps(stale_authority), encoding="utf-8")
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
            self.assertIn(
                b"write_plan_base_changed (refresh_status_and_replan)",
                completed.stderr,
            )


if __name__ == "__main__":
    unittest.main()
