"""``recall`` (ADR-0064) de extremo a extremo: forma, determinismo, presupuesto, ámbito, disputa, bandeja y sobre."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from an_kla import identity_c0, inbox
from an_kla.canonical import canonical_json
from an_kla.recall import RecallError, recall, render
from an_kla.store import MemoryStore
from tests.inbox_support import AGENT_ENV, GIT_ENV, InboxCase, run_git
from tests.remember_support import ROOT, cli, remember

A = {"AN_KLA_AGENT_NAME": "agente-a", "AN_KLA_SESSION_ID": "sesion-a-1"}
B = {"AN_KLA_AGENT_NAME": "agente-b", "AN_KLA_SESSION_ID": "sesion-b-1"}
OTHER_REPO = "github.com/otro/repo"


class RecallCase(InboxCase):
    """Un proyecto Git con store; ``fact`` guarda un hecho legado (sin sobre) y ``recall_cli`` lanza la orden real."""

    def fact(self, record_id: str, text: str, **extra: Any) -> None:
        self.commit_record(record_id, indexable_text=text, text=text, **extra)

    def envelope(self, repo_id: str | None = None, *, key: str | None = None, **env: str) -> dict[str, Any]:
        identity = identity_c0.build_identity(self.project, {**AGENT_ENV, **env})
        if repo_id is not None:
            identity["repo"] = {"id": repo_id}
        digest = "sha256:" + hashlib.sha256((key or repo_id or "propio").encode()).hexdigest()
        return identity_c0.build_envelope(identity, "fact", digest)

    def recall_cli(self, query: str, *args: str, **options: Any) -> tuple[int, dict[str, Any] | None, str]:
        done = cli(self.project, "recall", "--query", query, *args, **options)
        return done.returncode, (json.loads(done.stdout) if done.stdout else None), done.stderr

    def scratch(self, name: str) -> Path:
        """Un directorio temporal propio de la prueba, borrado al terminar."""

        base = Path(tempfile.mkdtemp(prefix=f"recall-{name}-")).resolve()
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        return base

    def ok(self, query: str, *args: str, **options: Any) -> dict[str, Any]:
        rc, out, err = self.recall_cli(query, *args, **options)
        self.assertEqual((rc, err), (0, ""), err)
        assert out is not None
        return out

    def ids(self, out: dict[str, Any]) -> list[str]:
        return [item["id"] for item in out["results"]]


class ShapeTests(RecallCase):
    def setUp(self) -> None:
        super().setUp()
        self.fact("f-puertos", "El servidor expone los puertos 8080 y 9090 hacia la red interna")
        self.fact("f-factura", "La facturacion mensual se emite el dia uno de cada mes")
        self.fact("f-config", "La variable NOMBRE_CONFIG apunta al archivo de configuración")
        self.fact("f-lanza", "El agente lanza la compilación nocturna del paquete")
        self.fact("f-ruido", "Un registro cualquiera sobre cosas distintas sin relación alguna")

    def test_plural_and_singular_find_each_other_in_both_directions(self) -> None:
        self.assertEqual(self.ids(self.ok("puerto"))[:1], ["f-puertos"])
        self.assertEqual(self.ids(self.ok("puertos"))[:1], ["f-puertos"])
        self.fact("f-singular", "Cada puerto registra su tráfico")
        self.assertEqual(set(self.ids(self.ok("puertos"))), {"f-puertos", "f-singular"})
        self.assertEqual(set(self.ids(self.ok("puerto"))), {"f-puertos", "f-singular"})

    def test_accented_and_plain_forms_match_in_both_directions(self) -> None:
        self.assertEqual(self.ids(self.ok("facturación"))[:1], ["f-factura"])
        self.assertEqual(self.ids(self.ok("facturacion"))[:1], ["f-factura"])
        self.assertEqual(self.ids(self.ok("configuracion"))[:1], ["f-config"])  # el registro lleva tilde

    def test_identifier_with_underscore_matches_the_plain_word(self) -> None:
        self.assertEqual(self.ids(self.ok("configuración del archivo"))[:1], ["f-config"])
        self.assertEqual(self.ids(self.ok("NOMBRE_CONFIG"))[:1], ["f-config"])
        self.assertEqual(self.ids(self.ok("nombre"))[:1], ["f-config"])

    def test_verb_inflection_meets(self) -> None:
        self.assertEqual(self.ids(self.ok("lanzo la compilacion"))[:1], ["f-lanza"])

    def test_same_ranking_with_and_without_accents_in_the_query(self) -> None:
        for plain, accented in (("compilacion nocturna", "compilación nocturna"),
                                ("facturacion mensual", "facturación mensual")):
            a, b = self.ok(plain), self.ok(accented)
            self.assertEqual([(r["id"], r["score"]) for r in a["results"]],
                             [(r["id"], r["score"]) for r in b["results"]])

    def test_interrogatives_are_dropped_from_the_query_only(self) -> None:
        with_q = self.ok("¿Qué puertos expone servidor?")
        without = self.ok("puertos expone servidor")
        self.assertEqual([(r["id"], r["score"]) for r in with_q["results"]],
                         [(r["id"], r["score"]) for r in without["results"]])
        self.assertEqual(with_q["query"], "¿Qué puertos expone servidor?")
        self.assertEqual(self.ok("qué")["results"], [])  # sólo interrogativos: nada que puntuar

    def test_response_shape_and_empty_results(self) -> None:
        out = self.ok("puertos")
        self.assertEqual(
            set(out), {"schema", "untrusted_memory_data", "revision", "analyzer", "query", "scope", "streams",
                       "budget_bytes", "used_bytes", "inbox", "excluded", "results"})
        self.assertEqual((out["schema"], out["analyzer"], out["streams"], out["budget_bytes"]),
                         ("an-kla/recall-result-v1", "an-kla/lexico-es-v1", ["facts"], 4000))
        self.assertEqual(out["scope"]["mode"], "repo")
        self.assertEqual(out["scope"]["repo_id"], identity_c0.repo_id_for(self.project))
        self.assertEqual(set(out["results"][0]), {"rank", "id", "stream", "score", "text", "writer", "enqueued_at",
                                                  "scope_match", "disputed_by", "disputes"})
        self.assertEqual(round(out["results"][0]["score"], 6), out["results"][0]["score"])
        self.assertEqual(self.ok("zzzinexistente")["results"], [])
        self.assertEqual(self.ok("zzzinexistente")["excluded"], {"budget": 0, "invalid_envelope": 0, "scope": 0})

    def test_empty_store_returns_no_results(self) -> None:
        empty = self.scratch("vacio")
        run_git(empty, "init", "-q")
        run_git(empty, "commit", "-q", "--allow-empty", "-m", "base")
        MemoryStore(empty).initialize()
        done = cli(empty, "recall", "--query", "puertos")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["results"], [])

    def test_episodes_are_searched_on_request_only(self) -> None:
        self.commit_record("e-estado", stream="episodes", indexable_text="el estado del servidor es sano", text="x")
        self.assertEqual(self.ids(self.ok("estado")), [])
        out = self.ok("estado", "--streams", "facts,episodes")
        self.assertEqual([(r["id"], r["stream"]) for r in out["results"]], [("e-estado", "episodes")])
        self.assertEqual(out["streams"], ["facts", "episodes"])

    def test_errors_are_stable_codes_with_rc_1(self) -> None:
        for args, code in ((("--query", "¿?!"), "recall_query_empty"),
                           (("--query", "x", "--streams", "events"), "unsupported_recall_stream"),
                           (("--query", "x", "--streams", ""), "unsupported_recall_stream")):
            done = cli(self.project, "recall", *args)
            self.assertEqual((done.returncode, done.stdout), (1, ""), args)
            self.assertTrue(done.stderr.startswith(f"an-kla error: {code}"), done.stderr)


class DeterminismTests(RecallCase):
    def test_two_invocations_give_the_same_bytes_and_ties_break_by_id(self) -> None:
        for name in ("f-c", "f-a", "f-b"):  # insertados fuera de orden, con el mismo texto
            self.fact(name, "el cuarzo es un mineral")
        self.fact("f-z", "el cuarzo es un mineral muy abundante en la corteza terrestre")
        first = cli(self.project, "recall", "--query", "cuarzo").stdout
        second = cli(self.project, "recall", "--query", "cuarzo").stdout
        self.assertEqual(first, second)
        out = json.loads(first)
        scores = [r["score"] for r in out["results"]]
        self.assertEqual(scores[0], scores[1])
        self.assertEqual(scores[1], scores[2])
        self.assertEqual(self.ids(out)[:3], ["f-a", "f-b", "f-c"])
        self.assertEqual([r["rank"] for r in out["results"]], [1, 2, 3, 4])
        self.assertEqual(first, render(out).decode("utf-8"))  # salida canónica y salto final
        self.assertTrue(first.endswith("}\n") and not first.endswith("\n\n"))


class BudgetTests(RecallCase):
    def setUp(self) -> None:
        super().setUp()
        for index in range(8):
            self.fact(f"f-{index}", f"el cuarzo número {index} aparece en la región {'norte ' * (index + 1)}")
        self.store = MemoryStore(self.project)
        self.floor = self.min_ok("cuarzo región")

    def min_ok(self, query: str) -> int:
        """El menor ``--budget`` con el que cabe la respuesta vacía de ``query`` (cuentan las cifras del presupuesto)."""

        def fits(budget: int) -> bool:
            try:
                recall(self.store, query, budget=budget, scope="all")
            except RecallError:
                return False
            return True

        low, high = 1, 5000  # `fits` es monótona: una respuesta vacía crece con el presupuesto sólo por sus cifras
        self.assertTrue(fits(high))
        while low < high:
            mid = (low + high) // 2
            low, high = (low, mid) if fits(mid) else (mid + 1, high)
        return low

    def check(self, budget: int) -> None:
        try:
            out = recall(self.store, "cuarzo región", budget=budget, scope="all")
        except RecallError as exc:
            self.assertEqual(str(exc), "recall_budget_too_small")
            self.assertLess(budget, self.floor)
            return
        raw = render(out)
        self.assertLessEqual(len(raw), budget, budget)
        self.assertEqual(out["used_bytes"], len(raw), budget)
        self.assertEqual(out["excluded"]["budget"] + len(out["results"]), 8, budget)

    def test_len_stdout_fits_and_used_bytes_is_exact_around_digit_changes_and_to_20000(self) -> None:
        budgets = set(range(1, 21)) | set(range(95, 106)) | set(range(990, 1011)) | set(range(9990, 10011))
        budgets |= set(range(1, 20001, 331)) | {20000}
        for budget in sorted(budgets):
            self.check(budget)

    def test_every_budget_in_the_window_where_results_start_to_fit(self) -> None:
        for budget in range(self.floor - 3, self.floor + 420):
            self.check(budget)

    def test_cli_stdout_respects_the_budget(self) -> None:
        for budget in (self.floor + 250, 999, 1000, 1001, 2500):
            out = cli(self.project, "recall", "--query", "cuarzo región", "--budget", str(budget), "--scope", "all")
            self.assertEqual(out.returncode, 0, out.stderr)
            parsed = json.loads(out.stdout)
            self.assertLessEqual(len(out.stdout.encode("utf-8")), budget)
            self.assertEqual(parsed["used_bytes"], len(out.stdout.encode("utf-8")))

    def test_a_skipped_result_leaves_a_gap_in_rank(self) -> None:
        self.fact("f-grande", "cuarzo cuarzo " + "z" * 900)
        self.fact("f-corto", "cuarzo")
        full = recall(self.store, "cuarzo", budget=50000, scope="all")
        ranks = {r["id"]: r["rank"] for r in full["results"]}
        self.assertEqual(sorted(ranks.values()), list(range(1, 11)))
        floor = self.min_ok("cuarzo")
        for budget in range(floor, floor + 3000, 7):
            out = recall(self.store, "cuarzo", budget=budget, scope="all")
            present = [r["rank"] for r in out["results"]]
            if present and present != list(range(1, len(present) + 1)):
                break
        else:
            self.fail("ningún presupuesto deja un hueco en rank")
        self.assertGreaterEqual(out["excluded"]["budget"], 1)
        self.assertEqual({r["id"]: r["rank"] for r in out["results"]},
                         {r["id"]: ranks[r["id"]] for r in out["results"]})  # rank es el global, no el entregado
        self.assertEqual(out["excluded"]["budget"] + len(out["results"]), 10)

    def test_budget_below_the_empty_response_fails(self) -> None:
        with self.assertRaises(RecallError) as caught:
            recall(self.store, "cuarzo", budget=self.min_ok("cuarzo") - 1, scope="all")
        self.assertEqual(str(caught.exception), "recall_budget_too_small")
        done = cli(self.project, "recall", "--query", "cuarzo", "--budget", "50")
        self.assertEqual((done.returncode, done.stdout), (1, ""))
        self.assertTrue(done.stderr.startswith("an-kla error: recall_budget_too_small"), done.stderr)
        self.assertEqual(recall(self.store, "cuarzo", budget=self.min_ok("cuarzo"), scope="all")["results"], [])


class ScopeTests(RecallCase):
    def setUp(self) -> None:
        super().setUp()
        self.fact("f-legado", "el zorro duerme de dia")
        self.fact("f-ajeno", "el zorro caza de noche", an_kla_envelope=self.envelope(OTHER_REPO))
        broken = self.envelope(OTHER_REPO, key="roto")
        broken["enqueued_at"] = "ayer"
        self.fact("f-roto", "el zorro con sobre corrupto de otro repo", an_kla_envelope=broken)
        self.fact("f-hueco", "el zorro con sobre hueco", an_kla_envelope={"kind": "decision"})
        _, mine = remember(self.project, "el zorro es del repo propio", env=A)
        self.mine = mine["record_id"]

    def test_repo_scope_keeps_own_and_legacy_and_counts_the_rest(self) -> None:
        out = self.ok("zorro")
        self.assertEqual(set(self.ids(out)), {self.mine, "f-legado"})
        self.assertEqual({r["id"]: r["scope_match"] for r in out["results"]},
                         {self.mine: "repo", "f-legado": "legacy"})
        self.assertEqual(out["excluded"], {"budget": 0, "invalid_envelope": 2, "scope": 1})

    def test_all_scope_includes_everything_and_marks_each(self) -> None:
        out = self.ok("zorro", "--scope", "all")
        self.assertEqual({r["id"]: r["scope_match"] for r in out["results"]},
                         {self.mine: "repo", "f-legado": "legacy", "f-ajeno": "other",
                          "f-roto": "invalid_envelope", "f-hueco": "invalid_envelope"})
        by_id = {r["id"]: r for r in out["results"]}
        for name in ("f-legado", "f-roto", "f-hueco"):
            self.assertEqual((by_id[name]["writer"], by_id[name]["enqueued_at"]), (None, None), name)
        self.assertEqual(by_id["f-ajeno"]["writer"]["repo"]["id"], OTHER_REPO)
        self.assertEqual(out["excluded"], {"budget": 0, "invalid_envelope": 0, "scope": 0})
        self.assertEqual(out["scope"]["mode"], "all")

    def test_a_corrupt_envelope_of_another_repo_never_enters_repo_scope(self) -> None:
        self.assertNotIn("f-roto", self.ids(self.ok("zorro")))
        self.assertNotIn("f-hueco", self.ids(self.ok("zorro")))

    def test_repo_scope_without_git_fails_and_never_degrades_to_all(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sin-git-") as raw:
            plain = Path(raw).resolve()
            MemoryStore(plain).initialize()
            ceiling = {"GIT_CEILING_DIRECTORIES": str(plain.parent)}
            done = cli(plain, "recall", "--query", "zorro", env=ceiling)
            self.assertEqual((done.returncode, done.stdout), (1, ""))
            self.assertTrue(done.stderr.startswith("an-kla error: recall_scope_unavailable"), done.stderr)
            self.assertIn("--scope all", done.stderr)
            done = cli(plain, "recall", "--query", "zorro", "--scope", "all", env=ceiling)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIsNone(json.loads(done.stdout)["scope"]["repo_id"])


class DisputeTests(RecallCase):
    def test_disputed_fact_stays_vigent_with_disputed_by_and_the_dispute_points_back(self) -> None:
        _, theirs = remember(self.project, "el servidor es debian", env=B)
        _, mine = remember(self.project, "el servidor es ubuntu", "--supersedes", theirs["record_id"], env=A)
        self.assertEqual(mine["operation"], "add")
        out = self.ok("servidor")
        by_id = {r["id"]: r for r in out["results"]}
        original, dispute = by_id[theirs["record_id"]], by_id[mine["record_id"]]
        self.assertIsNone(original["disputes"])
        self.assertEqual([d["id"] for d in original["disputed_by"]], [mine["record_id"]])
        self.assertEqual(original["disputed_by"][0]["text"], "el servidor es ubuntu")
        self.assertEqual(original["disputed_by"][0]["writer"]["agent"]["name"], "agente-a")
        self.assertEqual(dispute["disputes"], {"stream": "facts", "target_id": theirs["record_id"]})
        self.assertEqual(dispute["disputed_by"], [])
        listed = json.loads(cli(self.project, "disputes", "list", "--target", theirs["record_id"]).stdout)
        self.assertEqual([d["id"] for d in listed["disputes"]], [d["id"] for d in original["disputed_by"]])

    def test_disputes_do_not_change_anyones_score(self) -> None:
        self.fact("f-x", "el cuarzo es duro")
        self.fact("f-y", "el cuarzo es blando")
        before = {r["id"]: r["score"] for r in self.ok("cuarzo duro")["results"]}
        remember(self.project, "el cuarzo no es duro", "--supersedes", "f-x", env=A)
        after = {r["id"]: r["score"] for r in self.ok("cuarzo duro")["results"]}
        self.assertIn("f-x", after)
        self.assertIn("f-y", after)
        self.assertNotEqual(before.keys(), after.keys())  # la disputa es un registro más del conjunto
        self.assertEqual(next(r for r in self.ok("cuarzo duro")["results"] if r["id"] == "f-x")["disputed_by"][0]["id"],
                         next(i for i in after if i not in ("f-x", "f-y")))


class InboxTests(RecallCase):
    def setUp(self) -> None:
        super().setUp()
        self.fact("f-uno", "el pangolín come hormigas")

    def snapshot_inbox(self) -> list[tuple[str, int, int, str]]:
        rows = []
        for path in sorted(self.inbox.rglob("*")):
            stat = path.lstat()
            digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""
            rows.append((str(path.relative_to(self.inbox)), stat.st_size, stat.st_mtime_ns, digest))
        return rows

    def test_absent_inbox_responds_and_is_not_created(self) -> None:
        self.assertFalse(self.inbox.exists())
        out = self.ok("pangolin")
        self.assertEqual(out["inbox"], {"state": "absent", "pending": 0, "inflight": 0})
        self.assertEqual(self.ids(out), ["f-uno"])
        self.assertFalse(self.inbox.exists())

    def test_pending_entries_are_counted_not_searched_and_not_drained(self) -> None:
        for text in ("el pangolín duerme", "el pangolín corre"):
            inbox.enqueue(self.store, text, env=AGENT_ENV)
        out = self.ok("pangolin")
        self.assertEqual(out["inbox"], {"state": "present", "pending": 2, "inflight": 0})
        self.assertEqual(self.ids(out), ["f-uno"])  # una escritura cuenta cuando está comprometida
        self.assertEqual(self.ok("pangolin")["inbox"]["pending"], 2)

    @unittest.skipIf(os.name == "nt", "enlaces simbólicos")
    def test_unsafe_inbox_still_answers(self) -> None:
        elsewhere = self.scratch("otra-bandeja")
        os.symlink(elsewhere, self.inbox)
        out = self.ok("pangolin")
        self.assertEqual(out["inbox"]["state"], "unsafe")
        self.assertIsNone(out["inbox"]["pending"])
        self.assertEqual(self.ids(out), ["f-uno"])

    def test_current_and_inbox_listing_are_identical_after_ten_recalls(self) -> None:
        inbox.enqueue(self.store, "el pangolín trepa", env=AGENT_ENV)
        current, listing = self.store.read_current(), self.snapshot_inbox()
        self.assertTrue(listing)
        for _ in range(10):
            self.ok("pangolin")
        self.assertEqual(self.store.read_current(), current)
        self.assertEqual(self.snapshot_inbox(), listing)

    @unittest.skipIf(os.name == "nt", "enlaces simbólicos")
    def test_unsafe_subdirectory_nulls_only_the_affected_count(self) -> None:
        inbox.enqueue(self.store, "el pangolín trepa", env=AGENT_ENV)
        pending = self.inbox / "pending"
        moved = self.inbox / "pending-real"
        pending.rename(moved)
        os.symlink(moved, pending)
        out = self.ok("pangolin")
        self.assertEqual(out["inbox"], {"state": "unsafe", "pending": None, "inflight": 0})


class EnvelopeTests(RecallCase):
    def test_writer_and_enqueued_at_come_from_a_remember_and_are_null_otherwise(self) -> None:
        self.fact("f-legado", "el castor construye presas")
        self.fact("f-roto", "el castor roe troncos", an_kla_envelope={"kind": "decision"})
        _, saved = remember(self.project, "el castor nada bien", env=A)
        out = self.ok("castor", "--scope", "all")
        by_id = {r["id"]: r for r in out["results"]}
        mine = by_id[saved["record_id"]]
        self.assertEqual(mine["enqueued_at"], saved["enqueued_at"])
        self.assertEqual(mine["writer"]["agent"]["name"], "agente-a")
        self.assertEqual(mine["writer"]["repo"]["id"], identity_c0.repo_id_for(self.project))
        for name in ("f-legado", "f-roto"):
            self.assertEqual((by_id[name]["writer"], by_id[name]["enqueued_at"]), (None, None))


class SurfaceTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if not k.startswith("AN_KLA_")}
        env.update({"AN_KLA_NO_UPDATE_CHECK": "1", "PYTHONDONTWRITEBYTECODE": "1", **GIT_ENV})
        import sys
        return subprocess.run([sys.executable, "-m", "an_kla", *args], cwd=ROOT, env=env, capture_output=True, text=True)

    def test_recall_is_listed_in_help_capabilities_and_schema_list(self) -> None:
        self.assertIn("recall", self.run_cli("--help").stdout)
        caps = json.loads(self.run_cli("capabilities").stdout)
        entry = caps["storage"]["recall"]
        self.assertEqual((entry["schema"], entry["analyzer"], entry["read_only"]),
                         ("an-kla/recall-result-v1", "an-kla/lexico-es-v1", True))
        names = [s["name"] for s in json.loads(self.run_cli("schema", "list").stdout)["schemas"]]
        self.assertIn("recall-result-v1", names)
        shown = json.loads(self.run_cli("schema", "show", "recall-result-v1").stdout)
        self.assertEqual(shown["$id"], "urn:an-kla:schema:recall-result:v1")


class NoRegressionTests(unittest.TestCase):
    def test_retrieval_mcp_index_and_write_policy_are_untouched(self) -> None:
        """``retrieval.py``, ``mcp.py``, ``index.py`` y ``write_policy.py`` no difieren de ``main``."""

        def git(*args: str) -> subprocess.CompletedProcess:
            return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True,
                                  env={**os.environ, **GIT_ENV})

        base = next((git("merge-base", "HEAD", ref).stdout.strip() for ref in ("main", "origin/main")
                     if git("merge-base", "HEAD", ref).returncode == 0), "")
        if not base:
            self.skipTest("sin rama main para comparar")
        done = git("diff", "--name-only", base, "--", "an_kla/retrieval.py", "an_kla/mcp.py", "an_kla/index.py",
                   "an_kla/write_policy.py", "AGENTS.md", "AN-KLA.md", "tests/legacy_store_goldens.py")
        self.assertEqual((done.returncode, done.stdout.strip()), (0, ""))


if __name__ == "__main__":
    unittest.main()
