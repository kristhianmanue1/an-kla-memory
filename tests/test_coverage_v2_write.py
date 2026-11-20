"""ADR-0070, pruebas de aceptación 3, 4 y 5: la cobertura v2 al escribir, lo ya escrito con v1 y la vuelta atrás."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.inbox_support import run_git
from tests.remember_support import ROOT, cli, cli_env, remember
from tests.scope_support import ScopeCase
from tests.test_scope_compat import BASELINE_TAG, baseline_tree

FILE = "El servicio se despliega en el puerto 8081 siempre.\nLa rama de trabajo se llama principal.\n"
V2 = "fact-checks-rules/v2"


class CoverageCase(ScopeCase):
    def setUp(self) -> None:
        super().setUp()
        (self.project / "nota.txt").write_text(FILE)
        run_git(self.project, "add", "nota.txt")
        run_git(self.project, "commit", "-q", "-m", "nota")
        self.env_a = self.env("orq-a")

    def anchored(self, text: str, quote: str, *flags: str) -> tuple[int, dict]:
        return remember(self.project, text, "--anchor-path", "nota.txt", "--anchor-quote", quote, *flags, env=self.env_a)

    def read(self, *args: str, name: str = "orq-a", **options) -> dict:  # type: ignore[override]
        done = cli(self.project, *args, env=self.env(name))
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def stored(self, record_id: str, stream: str = "facts") -> dict:
        return next(r for r in self.store.snapshot().records[stream] if r["id"] == record_id)


class WriteTests(CoverageCase):
    """Criterio 3."""

    def test_a_date_is_one_element_not_three_numbers(self) -> None:
        rc, body = self.anchored("El 2026-11-19 se desplegó en el puerto 8081", "se despliega en el puerto 8081")
        self.assertEqual((rc, body["state"]), (0, "committed"), body)
        self.assertEqual(body["schema"], "an-kla/remember-result-v2")
        self.assertEqual(body["missing"], [{"type": "date", "value": "2026-11-19"}])
        self.assertEqual((body["missing_total"], body["coverage"]),
                         (1, {"total": 2, "present": 1, "level": "partial", "rules": V2}))
        self.assertEqual(self.stored(body["record_id"])["coverage"], body["coverage"])  # el registro dice lo mismo
        self.assertEqual(self.stored(body["record_id"])["missing"], body["missing"])

    def test_a_state_with_progress_figures_and_no_elements_is_unchecked(self) -> None:
        rc, body = self.anchored("3 de 5 tareas terminadas", "El servicio se despliega", "--kind", "state")
        self.assertEqual((rc, body["state"], body["schema"]), (0, "committed", "an-kla/remember-result-v2"), body)
        self.assertEqual((body["coverage"]["level"], body["coverage"]["rules"], body["missing"]), ("unchecked", V2, []))
        shown = self.read("state", "show")["slots"][0]
        self.assertEqual(shown["coverage"], body["coverage"])

    def test_a_state_whose_path_is_not_in_the_quote_is_none(self) -> None:
        rc, body = self.anchored("avance en docs/otro.md, 3 de 5 listas", "El servicio se despliega", "--kind", "state")
        self.assertEqual(rc, 0, body)
        self.assertEqual((body["coverage"]["level"], body["missing"]), ("none", [{"type": "path", "value": "docs/otro.md"}]))

    def test_a_queued_state_drained_by_another_invocation_keeps_the_state_mode(self) -> None:
        """R70-02: el `kind` llega al cálculo del vaciado; sin él saldría `none` por las cifras (modo `fact`)."""

        holder = subprocess.Popen(
            [sys.executable, "-I", "-c", "import fcntl,os,sys\nfd=os.open(sys.argv[1],os.O_RDWR|os.O_CREAT,0o600)\nfcntl.flock(fd,fcntl.LOCK_EX)\nsys.stdout.write('ready\\n');sys.stdout.flush()\nsys.stdin.read()\n",
             str(Path(self.store.root) / ".write.lock")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        )
        self.addCleanup(lambda: (holder.stdin.close(), holder.wait(timeout=10), holder.stdout.close()))
        self.assertEqual(holder.stdout.readline().strip(), "ready")
        rc, queued = self.anchored("3 de 5 tareas terminadas", "El servicio se despliega", "--kind", "state")
        self.assertEqual((rc, queued["state"]), (0, "queued"), queued)
        self.assertEqual(queued["coverage"]["level"], "unchecked")  # la respuesta, calculada al encolar
        holder.stdin.close()
        holder.wait(timeout=10)
        self.assertEqual(self.read("inbox", "drain")["committed"]["count"], 1)  # otra invocación vacía
        row = self.read("state", "show")["slots"][0]
        self.assertEqual((row["coverage"]["level"], row["coverage"]["rules"]), ("unchecked", V2))  # modo state, no fact

    def test_every_write_path_says_its_rules_dispute_included(self) -> None:
        _rc, target = remember(self.project, "el servicio usa el puerto 9090", env=self.env_a)
        done = cli(self.project, "dispute", target["record_id"], "--verdict", "insufficient", "--text-file", "-",
                   "--anchor-path", "nota.txt", "--anchor-quote", "se despliega en el puerto 8081",
                   stdin="El 2026-11-19 sigue el puerto 9090", env=self.env("rev-1", "revisor"))
        body = json.loads(done.stdout)
        self.assertEqual((done.returncode, body["schema"], body["coverage"]["rules"]), (0, "an-kla/remember-result-v2", V2), body)
        self.assertEqual({m["type"] for m in body["missing"]}, {"date", "number"})
        self.assertEqual(self.stored(body["record_id"])["coverage"]["rules"], V2)

    def test_a_plain_write_stays_v1_in_its_schema_and_carries_no_coverage(self) -> None:
        rc, body = remember(self.project, "sin anclas", env=self.env_a)
        self.assertEqual((rc, body["schema"]), (0, "an-kla/remember-result-v1"))
        self.assertNotIn("coverage", body)


class BetaTreeCase(CoverageCase):
    def setUp(self) -> None:
        super().setUp()
        scratch = tempfile.TemporaryDirectory(prefix="beta38-")
        self.addCleanup(scratch.cleanup)
        tree = baseline_tree(Path(scratch.name))
        if tree is None:
            self.skipTest(f"la etiqueta {BASELINE_TAG} no está en este clon")
        self.tree = tree

    def run_tree(self, tree: Path, *args: str) -> bytes:
        done = subprocess.run(
            [sys.executable, "-m", "an_kla", "--project-root", str(self.project), *args], cwd=tree,
            env={**cli_env(self.env("orq-a")), "PYTHONPATH": str(tree)}, capture_output=True,
        )
        self.assertEqual(done.returncode, 0, done.stderr.decode()[-400:])
        return done.stdout


class AlreadyWrittenTests(BetaTreeCase):
    """Criterio 4: lo escrito con beta.38 se sirve con su cobertura v1, sin `rules` y sin recalcular, byte a byte."""

    def test_a_beta38_record_is_served_unchanged(self) -> None:
        def write(*args: str) -> dict:
            done = subprocess.run(
                [sys.executable, "-m", "an_kla", "--project-root", str(self.project), "remember", "--text-file", "-", *args],
                cwd=self.tree, input="El 2026-11-19 se desplegó en el puerto 8081", text=True, capture_output=True,
                env={**cli_env(self.env("orq-a")), "PYTHONPATH": str(self.tree)},
            )
            self.assertEqual(done.returncode, 0, done.stderr)
            return json.loads(done.stdout)

        old = write("--anchor-path", "nota.txt", "--anchor-quote", "se despliega en el puerto 8081")
        self.assertEqual((old["schema"], old["coverage"]["level"]), ("an-kla/remember-result-v1", "partial"))
        self.assertNotIn("rules", old["coverage"])
        self.assertEqual(len(old["missing"]), 3)  # v1: la fecha eran tres números sueltos
        for args in (("history", old["record_id"]), ("state", "show", "--all-slots"), ("anchors", "verify", old["record_id"]),
                     ("anchors", "verify", "--all"), ("list", "--status", "all")):
            with self.subTest(args=args):
                before, after = self.run_tree(self.tree, *args), self.run_tree(ROOT, *args)
                self.assertEqual(after, before)
                self.assertNotIn(b"fact-checks-rules", after)
        row = json.loads(self.run_tree(ROOT, "history", old["record_id"]))
        self.assertEqual(row["schema"], "an-kla/history-result-v1")
        self.assertEqual(self.stored(old["record_id"])["coverage"], old["coverage"])  # nada se reescribió


class RollbackTests(BetaTreeCase):
    """Criterio 5: un registro con cobertura v2 leído por beta.38 se sirve sin error."""

    def test_beta38_reads_a_v2_coverage(self) -> None:
        _rc, fact = self.anchored("El 2026-11-19 usa a92b9252 en el puerto 8081", "se despliega en el puerto 8081")
        _rc, state = self.anchored("avance en docs/otro.md", "El servicio se despliega", "--kind", "state")
        self.assertEqual({m["type"] for m in fact["missing"]}, {"date", "hash"})
        for args in (("verify",), ("status",), ("history", fact["record_id"]), ("state", "show"),
                     ("anchors", "verify", "--all"), ("list", "--status", "all", "--text")):
            with self.subTest(args=args):
                served = self.run_tree(self.tree, *args)
                if args[0] in ("history", "state"):
                    self.assertIn(b'"rules":"fact-checks-rules/v2"', served)  # los datos no entendidos se sirven tal cual
        self.assertIn(b'"type":"hash"', self.run_tree(self.tree, "anchors", "verify", fact["record_id"]))
        self.assertIn(b'"type":"date"', self.run_tree(self.tree, "history", fact["record_id"]))
        self.assertEqual(json.loads(self.run_tree(self.tree, "state", "show"))["slots"][0]["coverage"]["rules"], V2)
        self.assertEqual(state["state"], "committed")


if __name__ == "__main__":
    unittest.main()
