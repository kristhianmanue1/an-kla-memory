"""test_contract_agent_recipe.py — la «Referencia rápida para agentes» es ejecutable.

Los agentes de proyectos consumidores sólo ven `AGENTS.md`, `AN-KLA.md` y el
`--help` del CLI (la documentación del repo fuente no viaja con el paquete).
Este test extrae del contrato distribuido los bloques JSON y bash de la receta,
sustituye sus marcadores y los ejecuta tal cual contra un store temporal, para
que la documentación no pueda divergir del CLI sin romper CI.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from an_kla.context_text import COMPACT_PAYLOAD, DETAILED_CONTRACT

ROOT = Path(__file__).resolve().parents[1]
SECTION_TITLE = "## Referencia rápida para agentes"


def _section() -> str:
    start = DETAILED_CONTRACT.index(SECTION_TITLE)
    end = DETAILED_CONTRACT.index("\n## ", start + len(SECTION_TITLE))
    return DETAILED_CONTRACT[start:end]


def _blocks(kind: str) -> list[str]:
    return re.findall(r"```" + kind + r"\n(.*?)```", _section(), flags=re.S)


def _commands(block: str) -> list[list[str]]:
    joined = block.replace("\\\n", " ")
    return [shlex.split(line) for line in joined.splitlines() if line.strip()]


class AgentRecipeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "proj"
        self.work = Path(self.temp.name) / "work"
        self.root.mkdir()
        self.work.mkdir()
        self.env = {"PATH": os.environ["PATH"], "AN_KLA_NO_UPDATE_CHECK": "1",
                    "PYTHONPATH": str(ROOT)}

    def _cli(self, args: list[str]) -> dict:
        result = subprocess.run(
            [sys.executable, "-m", "an_kla", "--project-root", str(self.root)] + args,
            capture_output=True, text=True, env=self.env, cwd=str(self.work))
        self.assertEqual(result.returncode, 0, (args, result.stderr))
        return json.loads(result.stdout)

    def _run_documented(self, argv: list[str], values: dict[str, str]) -> dict:
        """Run one documented line: `python3 -m an_kla --project-root . ...`."""

        self.assertEqual(argv[:5], ["python3", "-m", "an_kla", "--project-root", "."])
        args = [values.get(token, token) for token in argv[5:]]
        unresolved = [token for token in args if token.startswith("<")]
        self.assertEqual(unresolved, [], f"marcador sin resolver en {argv}")
        target = None
        if ">" in args:
            index = args.index(">")
            args, target = args[:index], args[index + 1]
        output = self._cli(args)
        if target is not None:
            (self.work / target).write_text(json.dumps(output), encoding="utf-8")
        return output

    def _fill(self, template: str, values: dict[str, str]) -> dict:
        for marker, value in values.items():
            template = template.replace(marker, value)
        template = re.sub(r"<[^<>\"]+>", "x", template)
        return json.loads(template)

    def test_recipe_runs_verbatim_and_outputs_match_the_prose(self) -> None:
        proposal_tpl, working_state_tpl = _blocks("json")
        write_block, checkpoint_block = _blocks("bash")
        self._cli(["init"])
        rev = self._cli(["status"])["revision"]

        proposal = self._fill(proposal_tpl, {"<REV>": rev})
        (self.work / "proposal.json").write_text(json.dumps(proposal), encoding="utf-8")
        outputs = [self._run_documented(argv, {"<REV>": rev})
                   for argv in _commands(write_block)]
        authority, plan, commit = outputs
        self.assertEqual(authority["authority_class"], "model_derived")
        self.assertIn(plan["decision"]["decision"], ("write-full", "write-summary", "skip"))
        self.assertIs(commit["committed"], True)
        self.assertNotIn("record_without_indexable_text", json.dumps(commit))
        rev2 = commit["revision"]
        self.assertEqual(self._cli(["status"])["revision"], rev2)

        parent = self._cli(["checkpoint", "show"])["checkpoint_digest"]
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        working_state = self._fill(working_state_tpl, {
            "<checkpoint_digest de checkpoint show>": parent,
            "<YYYY-MM-DDTHH:MM:SS.ffffffZ>": now,
        })
        (self.work / "working-state.json").write_text(
            json.dumps(working_state), encoding="utf-8")
        values = {"<REV de la última escritura>": rev2, "<uuid4 nuevo>": str(uuid.uuid4())}
        argvs = []
        for argv in _commands(checkpoint_block):
            argvs.append([token for token in argv])
        # Los marcadores con espacios quedan partidos por shlex: re-únelos.
        rejoined = []
        for argv in argvs:
            out, buffer = [], None
            for token in argv:
                if buffer is not None:
                    buffer += " " + token
                    if token.endswith(">"):
                        out.append(buffer)
                        buffer = None
                elif token.startswith("<") and not token.endswith(">"):
                    buffer = token
                else:
                    out.append(token)
            rejoined.append(out)
        cp_authority, cp_plan, cp_commit = [
            self._run_documented(argv, values) for argv in rejoined]
        self.assertEqual(cp_authority["authority_class"], "model_derived")
        self.assertEqual(cp_plan["decision"]["decision"], "write")
        self.assertIs(cp_commit["committed"], True)
        self.assertIn("checkpoint", cp_commit)
        self.assertTrue(self._cli(["verify"])["ok"])

    def test_every_command_in_the_table_exists(self) -> None:
        commands = set()
        table = _section().split("| Necesito | Comando |", 1)[1].split("\n\n", 1)[0]
        for row in re.findall(r"^\| [^|]+ \| (.+) \|$", table, flags=re.M):
            # El texto entre paréntesis es explicativo (schemas, notas).
            for span in re.findall(r"`([^`]+)`", re.sub(r"\([^)]*\)", "", row)):
                if re.fullmatch(r"[a-z0-9-]+-v[0-9]+", span):
                    continue  # nombre de schema, no comando
                head = re.match(r"[a-z][a-z-]*(?: [a-z][a-z-]*)?", span)
                if head:
                    commands.add(head.group(0))
        self.assertTrue(commands)
        for command in sorted(commands):
            words = [w for w in command.split() if not w.startswith("<")]
            with self.subTest(command=command):
                result = subprocess.run(
                    [sys.executable, "-m", "an_kla"] + words + ["--help"],
                    capture_output=True, text=True, env=self.env)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_compact_block_points_to_the_reference(self) -> None:
        self.assertIn("Referencia rápida para agentes", COMPACT_PAYLOAD)


if __name__ == "__main__":
    unittest.main()
