"""test_contract_agent_recipe.py — la «Referencia rápida para agentes» es ejecutable.

Los agentes de proyectos consumidores sólo ven `AGENTS.md`, `AN-KLA.md` y el
`--help` del CLI (la documentación del repo fuente no viaja con el paquete).
Este test trata la sección del contrato distribuido como especificación:

- ejecuta sus bloques JSON y bash tal cual contra un store temporal;
- compara cada comando y cada flag citados con el parser real, de forma exacta
  (argparse aceptaría abreviaturas, así que `--help` no basta);
- contrasta con el código los valores de decisión, campos de salida, códigos
  de error y comportamientos que la prosa afirma.
"""

from __future__ import annotations

import argparse
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

from an_kla.cli_parser import build_parser
from an_kla.context_text import COMPACT_PAYLOAD, DETAILED_CONTRACT
from an_kla.schemas import schema_bytes

ROOT = Path(__file__).resolve().parents[1]
SECTION_TITLE = "## Referencia rápida para agentes"
PREFIX = ["python3", "-m", "an_kla", "--project-root", "."]


def _section() -> str:
    start = DETAILED_CONTRACT.index(SECTION_TITLE)
    end = DETAILED_CONTRACT.index("\n## ", start + len(SECTION_TITLE))
    return DETAILED_CONTRACT[start:end]


def _blocks(kind: str) -> list[str]:
    return re.findall(r"```" + kind + r"\n(.*?)```", _section(), flags=re.S)


def _commands(block: str) -> list[list[str]]:
    joined = block.replace("\\\n", " ")
    return [shlex.split(line) for line in joined.splitlines() if line.strip()]


def _table(header: str) -> list[list[str]]:
    body = _section().split(header, 1)[1].split("\n\n", 1)[0]
    rows = re.findall(r"^\| (.+) \|$", body, flags=re.M)
    return [row.split(" | ") for row in rows if not row.startswith("---")]


def _subparser(words: list[str]) -> tuple[argparse.ArgumentParser, list[str], int]:
    """Resolve `a b --x` to the deepest subparser, remaining tokens and depth."""

    parser = build_parser()
    rest = list(words)
    depth = 0
    while rest:
        actions = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
        if not actions or rest[0] not in actions[0].choices:
            break
        parser = actions[0].choices[rest.pop(0)]
        depth += 1
    return parser, rest, depth


def _options(parser: argparse.ArgumentParser) -> set[str]:
    return {flag for action in parser._actions for flag in action.option_strings}


def _table_commands() -> list[str]:
    """Code spans of the command column, minus explanatory parentheses."""

    spans = []
    for row in _table("| Necesito | Comando |"):
        cell = re.sub(r"\([^)]*\)", "", row[1])
        for span in re.findall(r"`([^`]+)`", cell):
            if not re.fullmatch(r"[a-z0-9-]+-v[0-9]+", span):
                spans.append(span)
    return spans


class ReferenceAgainstParserTests(unittest.TestCase):
    def _assert_resolves(self, tokens: list[str]) -> None:
        words = [t for t in tokens if not t.startswith("<")]
        parser, rest, depth = _subparser(words)
        self.assertGreater(depth, 0, f"comando inexistente: {tokens}")
        pending = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
        if pending:
            nxt = next((t for t in rest if not t.startswith("-")), None)
            if (nxt is None and pending[0].required) or (
                    nxt is not None and nxt not in pending[0].choices):
                self.fail(f"subcomando incompleto o inexistente: {tokens}")
        flags = {t for t in rest if t.startswith("--")}
        unknown = flags - _options(parser) - {"--project-root"}
        self.assertEqual(unknown, set(), f"flags inexistentes en {tokens}")

    def test_every_table_command_and_flag_exists_exactly(self) -> None:
        spans = _table_commands()
        self.assertGreaterEqual(len(spans), 15)
        for span in spans:
            with self.subTest(span=span):
                tokens = re.sub(r"<[^<>]*>", "<x>", span).split()
                self._assert_resolves(tokens)

    def test_every_command_span_in_the_section_resolves(self) -> None:
        # Cualquier span cuyo primer token sea un subcomando de primer nivel,
        # también entre paréntesis y en la columna de acción de los errores.
        top = set(_subparser([])[0]._subparsers._group_actions[0].choices)
        checked = 0
        # Sin los bloques ``` (sus comillas desplazarían el emparejamiento).
        prose = re.sub(r"```.*?```", "", _section(), flags=re.S)
        for span in re.findall(r"`([^`]+)`", prose):
            tokens = re.sub(r"<[^<>]*>", "<x>", span).split()
            if tokens and tokens[0] in top:
                parser, _, _ = _subparser(tokens[:1])
                subs = [a for a in parser._actions
                        if isinstance(a, argparse._SubParsersAction)]
                if len(tokens) == 1 and subs and subs[0].required:
                    continue  # nombre suelto (p. ej. el campo `checkpoint`)
                with self.subTest(span=span):
                    self._assert_resolves(tokens)
                checked += 1
        self.assertGreaterEqual(checked, 25)

    def test_interpreter_forms_are_real(self) -> None:
        section = _section()
        self.assertIn("`.venv/bin/python -m an_kla`", section)
        self.assertIn("`an-kla`", section)
        self.assertEqual(set(re.findall(r"-m ([A-Za-z_.]+)", section)), {"an_kla", "pip"})
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertRegex(pyproject, r'(?m)^an-kla = "an_kla\.__main__:main"$')

    def test_working_state_limits_match_the_policy(self) -> None:
        from an_kla.checkpoint_policy import _CONFIG as cfg
        section = " ".join(_section().split())
        self.assertIn(f"{cfg['maximum_items_per_list']} elementos por lista", section)
        self.assertIn(f"{cfg['maximum_item_bytes'] // 1024} KiB por `value`", section)
        self.assertIn(f"{cfg['maximum_working_state_bytes'] // 1024} KiB por working-state",
                      section)

    def test_resume_rejects_streams_as_documented(self) -> None:
        self.assertIn("no admite `--streams`", " ".join(_section().split()))
        parser, _, _ = _subparser(["resume"])
        self.assertNotIn("--streams", _options(parser))

    def test_every_bash_line_uses_exact_flags(self) -> None:
        for block in _blocks("bash"):
            for argv in _commands(block):
                with self.subTest(argv=argv):
                    self.assertEqual(argv[:5], PREFIX)
                    tokens = argv[5:]
                    if ">" in tokens:
                        tokens = tokens[: tokens.index(">")]
                    self._assert_resolves(tokens)

    def test_schema_names_resolve(self) -> None:
        names = set(re.findall(r"`(?:schema show )?([a-z0-9-]+-v[0-9]+)`", _section()))
        self.assertTrue({"write-proposal-v1", "working-state-v2"} <= names)
        for name in names:
            with self.subTest(name=name):
                json.loads(schema_bytes(name))

    def test_documented_decision_values_match_the_schema(self) -> None:
        documented = re.search(r"`decision\.decision` \(([^)]*)\)", _section()).group(1)
        values = set(re.findall(r"`([^`]+)`", documented))
        enum = set(json.loads(schema_bytes("write-decision-v1"))
                   ["properties"]["decision"]["enum"])
        self.assertEqual(values, enum)

    def test_error_codes_exist_in_the_engine(self) -> None:
        sources = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "an_kla").rglob("*.py")
            if path.name != "context_text.py"
        )
        codes = []
        for row in _table("| Error | Qué hacer |"):
            codes += re.findall(r"`([a-z_]+)", row[0])
        self.assertGreaterEqual(len(codes), 8)
        for code in codes:
            with self.subTest(code=code):
                self.assertRegex(sources, r"[\"']" + re.escape(code) + r"[\"']")

    def test_compact_block_points_to_the_reference(self) -> None:
        self.assertIn("Referencia rápida para agentes", COMPACT_PAYLOAD)


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
        self.assertEqual(argv[:5], PREFIX)
        args = [values.get(token, token) for token in argv[5:]]
        self.assertEqual([t for t in args if t.startswith("<")], [], argv)
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
        return json.loads(re.sub(r"<[^<>\"]+>", "x", template))

    def _write(self, name: str, payload: dict) -> None:
        (self.work / name).write_text(json.dumps(payload), encoding="utf-8")

    def _plan_and_commit(self, name: str, proposal: dict, rev: str) -> tuple[dict, dict]:
        self._write(f"{name}.json", proposal)
        self._write(f"{name}-auth.json", self._cli(
            ["plan-write", "--proposal", f"{name}.json", "--emit-authority-template"]))
        plan = self._cli(["plan-write", "--proposal", f"{name}.json",
                          "--authority", f"{name}-auth.json"])
        self._write(f"{name}-plan.json", plan)
        commit = self._cli(["commit-write-plan", "--expected-current", rev,
                            "--proposal", f"{name}.json", "--authority", f"{name}-auth.json",
                            "--planning-result", f"{name}-plan.json"])
        return plan, commit

    def test_recipe_runs_verbatim_and_outputs_match_the_prose(self) -> None:
        proposal_tpl, working_state_tpl = _blocks("json")
        write_block, checkpoint_block = _blocks("bash")
        self._cli(["init"])
        rev = self._cli(["status"])["revision"]

        self._write("proposal.json", self._fill(proposal_tpl, {"<REV>": rev}))
        authority, plan, commit = [
            self._run_documented(argv, {"<REV>": rev}) for argv in _commands(write_block)]
        self.assertEqual(authority["authority_class"], "model_derived")
        self.assertEqual(plan["decision"]["decision"], "write-summary")
        self.assertIs(commit["committed"], True)
        self.assertNotIn("record_without_indexable_text", json.dumps(commit))
        rev2 = commit["revision"]
        self.assertNotEqual(rev2, rev)
        self.assertEqual(self._cli(["status"])["revision"], rev2)

        parent = self._cli(["checkpoint", "show"])["checkpoint_digest"]
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        self._write("working-state.json", self._fill(working_state_tpl, {
            "<checkpoint_digest de checkpoint show>": parent,
            "<YYYY-MM-DDTHH:MM:SS.ffffffZ>": now,
        }))
        # «Cada elemento de `decisions` ... lleva `id`, `value` y `provenance`».
        self.assertIn("lleva `id` (único en su lista), `value` y `provenance`",
                      " ".join(_section().split()))
        filled = json.loads((self.work / "working-state.json").read_text(encoding="utf-8"))
        self.assertEqual(set(filled["decisions"][0]), {"id", "value", "provenance"})
        # Las tres listas comparten forma: también blockers y evidence no vacíos.
        for key in ("blockers", "evidence"):
            filled[key] = [dict(filled["decisions"][0], id=f"{key[0]}-x")]
        self._write("working-state.json", filled)
        values = {"<REV-vigente>": rev2, "<uuid4-nuevo>": str(uuid.uuid4())}
        cp_authority, cp_plan, cp_commit = [
            self._run_documented(argv, values) for argv in _commands(checkpoint_block)]
        self.assertEqual(cp_authority["authority_class"], "model_derived")
        section = " ".join(_section().split())
        decided = re.search(r"El plan de checkpoint decide `([^`]+)`", section).group(1)
        self.assertEqual(cp_plan["decision"]["decision"], decided)
        # Campos citados en «el commit responde ...» existen en la salida.
        for sentence in re.findall(r"[Ee]l commit responde ([^.]*)\.", section):
            for name in re.findall(r"`([a-z_]+)(?::[^`]*)?`", sentence):
                with self.subTest(field=name):
                    self.assertTrue(name in commit or name in cp_commit, name)
        self.assertEqual(cp_plan["current_revision"], rev2)
        self.assertIs(cp_commit["committed"], True)
        self.assertIn("checkpoint", cp_commit)
        self.assertTrue(self._cli(["verify"])["ok"])

    def test_prose_claims_hold(self) -> None:
        proposal_tpl = _blocks("json")[0]
        section = " ".join(_section().split())
        self._cli(["init"])
        rev = self._cli(["status"])["revision"]

        # «pedir `full` produce `skip`»; «su commit responde `committed: false`
        # y la misma `revision`».
        self.assertIn("pedir `full` produce `skip`", section)
        self.assertIn("`committed: false` y la misma `revision`", section)
        full = self._fill(proposal_tpl, {"<REV>": rev})
        full["requested_representation"] = "full"
        plan, skipped = self._plan_and_commit("full", full, rev)
        self.assertEqual(plan["decision"]["decision"], "skip")
        self.assertIn("summary_required_for_authority_ceiling",
                      plan["decision"]["reason_codes"])
        self.assertIs(skipped["committed"], False)
        self.assertEqual(skipped["revision"], rev)
        for name in re.findall(r"`([a-z_]+)(?::[^`]*)?`",
                               re.search(r"su commit responde ([^.]*)\.", section).group(1)):
            self.assertIn(name, skipped)

        # «Con `model_derived` pide `summary`»: es lo que usa la plantilla.
        asked = re.search(r"Con `model_derived` pide `([a-z]+)`", section).group(1)
        self.assertEqual(asked, self._fill(proposal_tpl, {"<REV>": rev})
                         ["requested_representation"])
        fact, fact_commit = self._plan_and_commit(
            "fact", self._fill(proposal_tpl, {"<REV>": rev}), rev)
        self.assertEqual(fact["decision"]["decision"], f"write-{asked}")
        rev = fact_commit["revision"]

        # Supersede según el fragmento de la prosa.
        fragment = section.split("Para corregir un record vigente", 1)[1].split(". ", 1)[0]
        pairs = dict(re.findall(r'`"([a-z_]+)": "([^"`]+)"`', fragment))
        self.assertEqual(set(pairs), {"operation", "supersedes"})
        correction = self._fill(proposal_tpl, {"<REV>": rev})
        original_id = correction["record"]["id"]
        correction["operation"] = pairs["operation"]
        correction["supersedes"] = original_id
        correction["record"]["id"] = original_id + "-v2"
        _, superseded = self._plan_and_commit("supersede", correction, rev)
        self.assertIs(superseded["committed"], True)
        rev = superseded["revision"]
        states = {r["id"]: r["status"] for r in
                  self._cli(["inventory", "--revision", rev])["records"]}
        self.assertEqual(states[original_id], "sustituida")

        # «Para `events` o `episodes` cambia sólo `stream`».
        self.assertIn("cambia sólo `stream`", section)
        event = self._fill(proposal_tpl, {"<REV>": rev})
        event["base_revision"] = rev
        event["stream"] = "events"
        event["record"]["id"] = "e-x"
        event["record"]["text"] = "hallazgo registrado como event"
        _, committed = self._plan_and_commit("event", event, rev)
        self.assertIs(committed["committed"], True)

        # Lote v2 según la prosa: varios records en un solo commit.
        self.assertIn('`"schema": "an-kla/write-proposal-v2"` con `"records": [...]`', section)
        batch = self._fill(proposal_tpl, {"<REV>": rev})
        record = batch.pop("record")
        batch["schema"] = "an-kla/write-proposal-v2"
        batch["base_revision"] = committed["revision"]
        batch["records"] = [dict(record, id="f-lote-1"), dict(record, id="f-lote-2")]
        plan, batched = self._plan_and_commit("batch", batch, committed["revision"])
        self.assertEqual(plan["decision"]["decision"], f"write-{asked}")
        self.assertIs(batched["committed"], True)
        listed = {r["id"] for r in
                  self._cli(["inventory", "--revision", batched["revision"]])["records"]}
        self.assertTrue({"f-lote-1", "f-lote-2"} <= listed)

        # «sin `--streams` sólo busca `facts`»; resume «busca en los tres streams».
        self.assertIn("sin `--streams` sólo busca `facts`", section)
        self.assertIn("busca en los tres streams", section)
        plain = self._cli(["retrieve", "--query", "hallazgo", "--budget", "8192"])
        self.assertEqual(plain["streams_searched"], ["facts"])
        wide = self._cli(["retrieve", "--query", "hallazgo", "--budget", "8192",
                          "--streams", "facts,events,episodes"])
        self.assertIn("e-x", [item["id"] for item in wide["selected"]])
        resumed = self._cli(["resume", "--query", "hallazgo", "--budget", "16384"])
        self.assertIn("e-x", [item["id"] for item in resumed["retrieved_evidence"]])


if __name__ == "__main__":
    unittest.main()
