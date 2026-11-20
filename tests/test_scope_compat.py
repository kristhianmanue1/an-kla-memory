"""ADR-0069, prueba de aceptación 5: un store sin campos nuevos se lee byte a byte como en beta.38, y sin `git`."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.remember_support import ROOT, cli, cli_env, remember
from tests.scope_support import OTHER, ScopeCase

BASELINE_TAG = "v0.1.0-beta.38"
_MCP = (
    "import json, sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "from an_kla.mcp import ReadOnlyMcp\n"
    "import an_kla\n"
    "assert an_kla.__file__.startswith(sys.argv[1]), an_kla.__file__\n"
    "now = '2026-06-01T00:00:00Z'\n"
    "plain = ReadOnlyMcp(sys.argv[2]).call('an_kla_retrieve', {'query': 'puerto', 'budget_bytes': 4000})\n"
    "fresh = ReadOnlyMcp(sys.argv[2]).call('an_kla_retrieve', {'query': 'puerto', 'budget_bytes': 4000, 'freshness_profile': 'computed-age/v1', 'now': now})\n"
    "context = ReadOnlyMcp(sys.argv[2]).call('an_kla_assemble_context', {'query': 'puerto', 'budget_bytes': 4000})\n"
    "sys.stdout.write(json.dumps([plain, fresh, context], sort_keys=True))\n"
)


def baseline_tree(target: Path) -> Path | None:
    """``git archive`` de beta.38 en ``target`` (sin instalar nada); ``None`` si la etiqueta no está en este clon."""

    tag = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--verify", "-q", BASELINE_TAG + "^{commit}"], capture_output=True)
    if tag.returncode != 0:
        return None
    archive = subprocess.run(["git", "-C", str(ROOT), "archive", BASELINE_TAG], capture_output=True, check=True)
    subprocess.run(["tar", "-x", "-C", str(target)], input=archive.stdout, check=True)
    return target


class ByteIdenticalWithBetaTests(ScopeCase):
    """Los mismos comandos sobre el mismo store, con el árbol de beta.38 y con el actual, dan los mismos bytes."""

    COMMANDS = (
        ("retrieve", "--query", "puerto", "--budget", "4000"),
        ("retrieve", "--query", "puerto estado", "--budget", "300", "--streams", "facts,episodes"),
        ("retrieve", "--query", "puerto", "--budget", "4000", "--freshness-profile", "computed-age/v1", "--now", "2026-06-01T00:00:00Z"),
        ("retrieve", "--query", "nada que ver", "--budget", "4000"),
        ("assemble-context", "--query", "puerto", "--budget", "4000"),
        ("resume", "--query", "puerto", "--budget", "100000"),
        ("list", "--status", "all", "--streams", "facts,episodes"),
        ("state", "show", "--all-slots"),
        ("disputes", "list"),
    )

    def setUp(self) -> None:
        super().setUp()
        env = self.env("orq-plano")
        remember(self.project, "el puerto de quetzal es 8081", env=env)
        _rc, old = remember(self.project, "el puerto de quetzal es 8080", "--kind", "decision", env=env)
        remember(self.project, "puerto corregido a 8081", "--supersedes", old["record_id"], env=env)
        _rc, disputed = remember(self.project, "el puerto de quetzal es 9090", env=env)
        remember(self.project, "en curso: revisar el puerto", "--kind", "state", env=env)
        remember(self.project, "otro estado del puerto", "--kind", "state", "--slot", "lateral", env=env)
        self.assertEqual(cli(self.project, "dispute", disputed["record_id"], "--verdict", "insufficient", "--text", "sin cita", env=self.env("rev-1", "revisor")).returncode, 0)
        remember(self.project, "el puerto de otro agente", env=self.env("orq-ajeno"))

    def run_tree(self, tree: Path, *args: str) -> bytes:
        done = subprocess.run(
            [sys.executable, "-m", "an_kla", "--project-root", str(self.project), *args], cwd=tree,
            env={**cli_env(self.env("orq-plano")), "PYTHONPATH": str(tree)}, capture_output=True,
        )
        self.assertEqual(done.returncode, 0, done.stderr.decode()[-400:])
        return done.stdout

    def test_cli_and_mcp_are_byte_identical_to_beta38(self) -> None:
        with tempfile.TemporaryDirectory(prefix="beta38-") as scratch:
            tree = baseline_tree(Path(scratch))
            if tree is None:
                self.skipTest(f"la etiqueta {BASELINE_TAG} no está en este clon")
            self.assertEqual(
                subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); import an_kla.version as v; print(v.VERSION)", str(tree)],
                               capture_output=True, text=True).stdout.strip(), "0.1.0b38")
            for args in self.COMMANDS:
                with self.subTest(args=args):
                    before, after = self.run_tree(tree, *args), self.run_tree(ROOT, *args)
                    self.assertEqual(after, before)
                    self.assertNotIn(b"other_audience", after)
                    self.assertNotIn(b"for_reader", after)
            mcp = [subprocess.run([sys.executable, "-c", _MCP, str(root), str(self.project)], capture_output=True, env=cli_env(self.env("orq-plano")))
                   for root in (tree, ROOT)]
            self.assertEqual([m.returncode for m in mcp], [0, 0], [m.stderr[-300:] for m in mcp])
            self.assertEqual(mcp[1].stdout, mcp[0].stdout)
            schemas = {item["schema"] for item in json.loads(mcp[1].stdout)}
            self.assertFalse(any(s.endswith("-v4") or s.endswith("assembly-v3") for s in schemas), schemas)


class NoGitTests(ScopeCase):
    """Sin `git` en el `PATH`: un store sin campos nuevos se lee igual y sin llamar a nada; con `subject` falla cerrado."""

    def setUp(self) -> None:
        super().setUp()
        self.nogit = self.scratch / "sin-git"
        self.nogit.mkdir()
        remember(self.project, "el puerto de quetzal es 8081", env=self.env("orq-plano"))

    def test_plain_store_needs_no_git(self) -> None:
        with_git = cli(self.project, "retrieve", "--query", "puerto", "--budget", "4000", env=self.env("orq-plano"))
        without = cli(self.project, "retrieve", "--query", "puerto", "--budget", "4000", env={**self.env("orq-plano"), "PATH": str(self.nogit)})
        self.assertEqual((without.returncode, without.stdout), (0, with_git.stdout), without.stderr)
        for args in (("list",), ("assemble-context", "--query", "puerto", "--budget", "4000")):  # `state show` exige git desde ADR-0065
            self.assertEqual(cli(self.project, *args, env={**self.env("orq-plano"), "PATH": str(self.nogit)}).returncode, 0, args)

    def test_with_an_explicit_subject_and_no_git_everything_is_for_another(self) -> None:
        remember(self.project, "puerto de este repo", "--subject", self.repo_id, env=self.env("orq-plano"))
        done = cli(self.project, "retrieve", "--query", "puerto", "--budget", "4000", env={**self.env("orq-plano"), "PATH": str(self.nogit)})
        got = json.loads(done.stdout)
        self.assertEqual([i["render"] for i in got["selected"]], ["el puerto de quetzal es 8081"])  # falla cerrado
        self.assertEqual(got["excluded_summary"]["other_audience"], 1)


if __name__ == "__main__":
    unittest.main()
