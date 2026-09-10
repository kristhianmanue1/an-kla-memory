"""test_write_authority_template.py — plan-write --emit-authority-template (issue #125).

Un agente sin leer código interno debe poder escribir memoria gobernada al
primer intento: template con proposal_sha256/base_revision calculados desde
--proposal -> plan-write -> commit-write-plan. La emisión es read-only y
determinista dada la misma revisión, igual que checkpoint plan
--emit-authority-template (#120.3, tests/test_checkpoint_template.py).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def _proposal(base_revision: str) -> dict:
    return {
        "schema": "an-kla/write-proposal-v1",
        "base_revision": base_revision,
        "stream": "episodes",
        "operation": "add",
        "requested_representation": "summary",
        "record": {
            "id": "template-smoke-episode",
            "text": "Prueba del emisor de write-authority (#125).",
        },
        "lineage": {"derived_from_retrieval": False, "refs": []},
    }


class EmitWriteAuthorityTemplateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="ankla-write-template-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _cli(self, args: list) -> subprocess.CompletedProcess:
        env = {"PATH": os.environ["PATH"], "AN_KLA_NO_UPDATE_CHECK": "1"}
        return subprocess.run(
            [sys.executable, "-m", "an_kla", "--project-root", str(self.root)] + args,
            capture_output=True, text=True, cwd=str(ROOT), env=env,
        )

    def _proposal_file(self) -> Path:
        self._cli(["init"])
        base_revision = json.loads(self._cli(["status"]).stdout)["revision"]
        path = self.root / "proposal.json"
        path.write_text(json.dumps(_proposal(base_revision)), encoding="utf-8")
        return path

    def test_template_plans_and_commits_first_try(self) -> None:
        proposal_path = self._proposal_file()
        template = self._cli([
            "plan-write", "--proposal", str(proposal_path),
            "--emit-authority-template",
        ])
        self.assertEqual(template.returncode, 0, template.stderr)
        authority = json.loads(template.stdout)
        self.assertEqual(authority["schema"], "an-kla/write-authority-v1")
        authority_path = self.root / "authority.json"
        authority_path.write_text(json.dumps(authority), encoding="utf-8")

        planned = self._cli([
            "plan-write", "--proposal", str(proposal_path),
            "--authority", str(authority_path),
        ])
        self.assertEqual(planned.returncode, 0, planned.stderr)
        planning = json.loads(planned.stdout)
        self.assertEqual(planning["decision"]["decision"], "write-summary")
        planning_path = self.root / "planning-result.json"
        planning_path.write_text(planned.stdout, encoding="utf-8")

        revision = json.loads(self._cli(["status"]).stdout)["revision"]
        committed = self._cli([
            "commit-write-plan",
            "--expected-current", revision,
            "--proposal", str(proposal_path),
            "--authority", str(authority_path),
            "--planning-result", str(planning_path),
        ])
        self.assertEqual(committed.returncode, 0, committed.stderr)
        self.assertIs(json.loads(committed.stdout)["committed"], True)

    def test_template_is_read_only_and_deterministic(self) -> None:
        proposal_path = self._proposal_file()
        before = sorted(str(p) for p in self.root.rglob("*"))
        first = self._cli([
            "plan-write", "--proposal", str(proposal_path),
            "--emit-authority-template",
        ])
        second = self._cli([
            "plan-write", "--proposal", str(proposal_path),
            "--emit-authority-template",
        ])
        after = sorted(str(p) for p in self.root.rglob("*"))
        self.assertEqual(before, after)
        self.assertEqual(first.stdout, second.stdout)

    def test_missing_authority_gives_stable_usage_error(self) -> None:
        proposal_path = self._proposal_file()
        completed = self._cli(["plan-write", "--proposal", str(proposal_path)])
        self.assertEqual(completed.returncode, 2)
        self.assertIn("missing_write_authority", completed.stderr)


if __name__ == "__main__":
    unittest.main()
