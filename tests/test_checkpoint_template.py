"""test_checkpoint_template.py — --emit-authority-template (#120.3).

Un agente sin leer código interno debe poder escribir un checkpoint
gobernado al primer intento: template con proposal_sha256/base_revision
calculados -> plan write -> commit. La emisión es read-only y
determinista dada la misma revisión.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _working_state(parent_digest: str) -> dict:
    return {
        "schema": "an-kla/working-state-v2",
        "objective": {"provenance": "caller_asserted",
                      "value": "Prueba del emisor de autoridad (#120)."},
        "phase": {"provenance": "caller_asserted", "value": "smoke"},
        "next_step": {"provenance": "caller_asserted",
                      "value": "plan + commit con la plantilla."},
        "decisions": [],
        "blockers": [],
        "evidence": [],
        "source_state": {
            "profile": "none/v1",
            "head": {"provenance": "unavailable", "value": None},
            "branch": {"provenance": "unavailable", "value": None},
            "dirty_digest": {"provenance": "unavailable", "value": None},
        },
        "captured_at": {"provenance": "caller_asserted",
                        "value": datetime.now(timezone.utc).strftime(
                            "%Y-%m-%dT%H:%M:%S.%fZ")},
        "supersedes_checkpoint": parent_digest,
    }


class EmitAuthorityTemplateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="ankla-template-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _cli(self, args: list) -> subprocess.CompletedProcess:
        env = {"PATH": os.environ["PATH"], "AN_KLA_NO_UPDATE_CHECK": "1"}
        return subprocess.run(
            [sys.executable, "-m", "an_kla", "--project-root", str(self.root)] + args,
            capture_output=True, text=True, cwd=str(ROOT), env=env,
        )

    def _working_state_file(self) -> tuple[Path, dict]:
        self._cli(["init"])
        parent = json.loads(
            self._cli(["checkpoint", "show"]).stdout
        )["checkpoint_digest"]
        working_state = _working_state(parent)
        path = self.root / "ws.json"
        path.write_text(json.dumps(working_state), encoding="utf-8")
        return path, working_state

    def test_template_plans_and_commits_first_try(self) -> None:
        ws_path, _ = self._working_state_file()
        template = self._cli([
            "checkpoint", "plan", "--input", str(ws_path),
            "--emit-authority-template",
        ])
        self.assertEqual(template.returncode, 0, template.stderr)
        authority = json.loads(template.stdout)
        self.assertEqual(
            authority["schema"], "an-kla/checkpoint-authority-v1"
        )
        authority_path = self.root / "authority.json"
        authority_path.write_text(json.dumps(authority), encoding="utf-8")

        planned = self._cli([
            "checkpoint", "plan", "--input", str(ws_path),
            "--authority", str(authority_path),
        ])
        self.assertEqual(planned.returncode, 0, planned.stderr)
        planning = json.loads(planned.stdout)
        self.assertEqual(planning["decision"]["decision"], "write")
        plan_path = self.root / "plan.json"
        plan_path.write_text(planned.stdout, encoding="utf-8")

        revision = json.loads(self._cli(["status"]).stdout)["revision"]
        committed = self._cli([
            "checkpoint", "commit", "--plan", str(plan_path),
            "--expected-current", revision,
            "--transaction-id", "00000000-0000-4000-8000-000000000001",
        ])
        self.assertEqual(committed.returncode, 0, committed.stderr)
        self.assertIs(json.loads(committed.stdout)["committed"], True)

    def test_template_is_read_only_and_deterministic(self) -> None:
        ws_path, _ = self._working_state_file()
        before = sorted(str(p) for p in self.root.rglob("*"))
        first = self._cli([
            "checkpoint", "plan", "--input", str(ws_path),
            "--emit-authority-template",
        ])
        second = self._cli([
            "checkpoint", "plan", "--input", str(ws_path),
            "--emit-authority-template",
        ])
        after = sorted(str(p) for p in self.root.rglob("*"))
        self.assertEqual(before, after)
        self.assertEqual(first.stdout, second.stdout)

    def test_missing_authority_gives_stable_usage_error(self) -> None:
        ws_path, _ = self._working_state_file()
        completed = self._cli(["checkpoint", "plan", "--input", str(ws_path)])
        self.assertEqual(completed.returncode, 2)
        self.assertIn("missing_checkpoint_authority", completed.stderr)




if __name__ == "__main__":
    unittest.main()
