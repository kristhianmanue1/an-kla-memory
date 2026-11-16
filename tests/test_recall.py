"""``recall`` (ADR-0064) de extremo a extremo: forma, determinismo, presupuesto, ámbito, disputa, bandeja y sobre."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
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
NO_EXCLUDED = {"budget": 0, "invalid_envelope": 0, "min_terms": 0, "scope": 0, "truncated": 0}


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
            set(out), {"schema", "untrusted_memory_data", "revision", "analyzer", "query", "query_terms", "scope", "streams",
                       "budget_bytes", "used_bytes", "inbox", "excluded", "no_strong_match", "results"})
        self.assertEqual((out["schema"], out["analyzer"], out["streams"], out["budget_bytes"]),
                         ("an-kla/recall-result-v1", "an-kla/lexico-es-v1", ["facts"], 4000))
        self.assertEqual(out["scope"]["mode"], "repo")
        self.assertEqual(out["scope"]["repo_id"], identity_c0.repo_id_for(self.project))
        self.assertEqual(set(out["results"][0]), {"rank", "id", "stream", "score", "text", "writer", "enqueued_at",
                                                  "scope_match", "matched_terms", "truncated", "disputed_by",
                                                  "disputes"})
        self.assertEqual(round(out["results"][0]["score"], 6), out["results"][0]["score"])
        self.assertEqual(self.ok("zzzinexistente")["results"], [])
        self.assertEqual(self.ok("zzzinexistente")["excluded"], NO_EXCLUDED)

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
        self.stubs_seen = 0

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
        self.assertEqual(out["excluded"]["truncated"], sum(r["truncated"] for r in out["results"]), budget)
        self.stubs_seen += out["excluded"]["truncated"]

    def test_len_stdout_fits_and_used_bytes_is_exact_around_digit_changes_and_to_20000(self) -> None:
        budgets = set(range(1, 21)) | set(range(95, 106)) | set(range(990, 1011)) | set(range(9990, 10011))
        budgets |= set(range(1, 20001, 331)) | {20000}
        for budget in sorted(budgets):
            self.check(budget)
        self.assertGreater(self.stubs_seen, 0)  # el barrido pasa por presupuestos donde un resultado sale resumido

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
        # El mejor candidato tiene un id enorme: ni su stub cabe donde sí cabe el de otro más corto.
        self.fact("f-" + "i" * 700, "cuarzo cuarzo cuarzo")
        full = recall(self.store, "cuarzo", budget=50000, scope="all")
        ranks = {r["id"]: r["rank"] for r in full["results"]}
        self.assertEqual(sorted(ranks.values()), list(range(1, 10)))
        self.assertEqual(full["results"][0]["id"], "f-" + "i" * 700)
        floor = self.min_ok("cuarzo")
        for budget in range(floor, floor + 3000, 7):
            out = recall(self.store, "cuarzo", budget=budget, scope="all")
            present = [r["rank"] for r in out["results"]]
            if present and present[0] > 1:
                break
        else:
            self.fail("ningún presupuesto deja un hueco en rank")
        self.assertGreaterEqual(out["excluded"]["budget"], 1)
        self.assertEqual({r["id"]: r["rank"] for r in out["results"]},
                         {r["id"]: ranks[r["id"]] for r in out["results"]})  # rank es el global, no el entregado
        self.assertEqual(out["excluded"]["budget"] + len(out["results"]), 9)

    def test_budget_below_the_empty_response_fails(self) -> None:
        with self.assertRaises(RecallError) as caught:
            recall(self.store, "cuarzo", budget=self.min_ok("cuarzo") - 1, scope="all")
        self.assertEqual(str(caught.exception), "recall_budget_too_small")
        done = cli(self.project, "recall", "--query", "cuarzo", "--budget", "50")
        self.assertEqual((done.returncode, done.stdout), (1, ""))
        self.assertTrue(done.stderr.startswith("an-kla error: recall_budget_too_small"), done.stderr)
        self.assertEqual(recall(self.store, "cuarzo", budget=self.min_ok("cuarzo"), scope="all")["results"], [])


class AmendmentTests(RecallCase):
    """Enmienda 1 del ADR-0064: recencia, stubs, ``query_terms``/``matched_terms`` y ``--min-terms``."""

    def stamped(self, record_id: str, text: str, enqueued: datetime | None, **env: str) -> None:
        envelope = None
        if enqueued is not None:
            identity = identity_c0.build_identity(self.project, {**AGENT_ENV, **env})
            digest = "sha256:" + hashlib.sha256(record_id.encode()).hexdigest()
            envelope = identity_c0.build_envelope(identity, "fact", digest, clock=lambda: enqueued)
        self.fact(record_id, text, **({"an_kla_envelope": envelope} if envelope else {}))

    def test_equal_scores_break_by_recency_then_legacy_behind_then_id(self) -> None:
        text = "el ocelote duerme en la rama"
        at = lambda day: datetime(2026, 11, day, 9, 0, 0, tzinfo=timezone.utc)  # noqa: E731
        self.stamped("f-a-viejo", text, at(1))
        self.stamped("f-z-nuevo", text, at(9))
        self.stamped("f-m-medio", text, at(5))
        self.stamped("f-b-legado", text, None)
        self.stamped("f-c-legado", text, None)
        broken = self.envelope(OTHER_REPO, key="roto")
        broken["enqueued_at"] = "manana"
        self.fact("f-0-roto", text, an_kla_envelope=broken)
        out = self.ok("ocelote rama", "--scope", "all")
        self.assertEqual(self.ids(out), ["f-z-nuevo", "f-m-medio", "f-a-viejo", "f-0-roto", "f-b-legado", "f-c-legado"])
        self.assertEqual(len({r["score"] for r in out["results"]}), 1)

    def test_recency_never_overrides_a_higher_score(self) -> None:
        self.stamped("f-viejo-fuerte", "ocelote ocelote ocelote", datetime(2020, 1, 1, tzinfo=timezone.utc))
        self.stamped("f-nuevo-debil", "ocelote duerme tranquilo en la rama de arriba", datetime(2026, 11, 9, tzinfo=timezone.utc))
        self.assertEqual(self.ids(self.ok("ocelote", "--scope", "all"))[0], "f-viejo-fuerte")

    def test_a_best_result_larger_than_the_budget_comes_out_as_a_stub(self) -> None:
        self.fact("f-grande", "cuarzo cuarzo " + "z" * 900)
        self.fact("f-chico", "cuarzo y otras palabras sueltas sin mas")
        store = MemoryStore(self.project)
        big = recall(store, "cuarzo", budget=50000, scope="all")
        self.assertEqual([r["id"] for r in big["results"]], ["f-grande", "f-chico"])
        self.assertEqual({r["truncated"] for r in big["results"]}, {False})
        budget = big["used_bytes"] - 400
        out = recall(store, "cuarzo", budget=budget, scope="all")
        first = out["results"][0]
        self.assertEqual((first["rank"], first["id"], first["truncated"]), (1, "f-grande", True))
        self.assertEqual(set(first), {"rank", "id", "stream", "score", "enqueued_at", "scope_match", "matched_terms",
                                      "truncated", "disputed"})
        self.assertIs(first["disputed"], False)
        self.assertEqual(out["excluded"]["truncated"], 1)
        self.assertEqual(out["excluded"]["budget"], 0)
        self.assertLessEqual(len(render(out)), budget)
        self.assertEqual(out["used_bytes"], len(render(out)))
        self.assertEqual(out["results"][1]["truncated"], False)

    def test_a_disputed_stub_says_so(self) -> None:
        self.fact("f-x", "cuarzo " + "y" * 900)
        remember(self.project, "el cuarzo es otra cosa", "--supersedes", "f-x", env=A)
        store = MemoryStore(self.project)
        full = recall(store, "cuarzo", budget=50000, scope="all")
        target = next(r for r in full["results"] if r["id"] == "f-x")
        self.assertEqual(len(target["disputed_by"]), 1)
        others = sum(len(canonical_json(r)) for r in full["results"] if r["id"] != "f-x")
        out = recall(store, "cuarzo", budget=others + 1300, scope="all")
        stub = next(r for r in out["results"] if r["id"] == "f-x")
        self.assertEqual((stub["truncated"], stub["disputed"]), (True, True))
        self.assertNotIn("disputed_by", stub)

    def test_query_terms_and_matched_terms_on_a_known_vector(self) -> None:
        self.fact("f-1", "Los puertos del servidor escuchan en la red interna")
        self.fact("f-2", "El servidor se reinicia cada noche")
        self.fact("f-3", "Nada que ver con el tema")
        out = self.ok("¿Qué puertos usa el servidor? Servidor, PUERTO")
        self.assertEqual(out["query_terms"], ["puert", "usa", "el", "servidor"])
        by_id = {r["id"]: r for r in out["results"]}
        self.assertEqual(by_id["f-1"]["matched_terms"], ["puert", "servidor"])
        self.assertEqual(by_id["f-2"]["matched_terms"], ["el", "servidor"])
        self.assertIs(out["no_strong_match"], False)

    def test_min_terms_2_with_only_single_term_matches_gives_no_strong_match(self) -> None:
        for index in range(4):
            self.fact(f"f-{index}", f"el cuarzo aparece en el lote {index}")
        out = self.ok("cuarzo basalto", "--min-terms", "2")
        self.assertEqual((out["results"], out["no_strong_match"]), ([], True))
        self.assertEqual(out["excluded"]["min_terms"], 4)
        self.assertEqual(out["query_terms"], ["cuarz", "basalt"])
        loose = self.ok("cuarzo basalto")
        self.assertEqual((len(loose["results"]), loose["no_strong_match"]), (4, False))

    def test_min_terms_above_the_number_of_query_terms_is_valid(self) -> None:
        self.fact("f-1", "el cuarzo es duro")
        out = self.ok("cuarzo", "--min-terms", "5")
        self.assertEqual((out["results"], out["no_strong_match"], out["excluded"]["min_terms"]), ([], True, 1))

    def test_no_candidates_at_all_is_not_a_strong_match_failure(self) -> None:
        self.fact("f-1", "el cuarzo es duro")
        out = self.ok("zzzinexistente", "--min-terms", "2")
        self.assertEqual((out["results"], out["no_strong_match"]), ([], False))

    def test_min_terms_1_gives_the_same_bytes_as_no_option(self) -> None:
        self.fact("f-1", "el cuarzo es duro")
        self.fact("f-2", "el basalto es oscuro")
        plain = cli(self.project, "recall", "--query", "cuarzo basalto").stdout
        explicit = cli(self.project, "recall", "--query", "cuarzo basalto", "--min-terms", "1").stdout
        self.assertEqual(plain, explicit)

    def test_min_terms_must_be_an_integer_of_at_least_one(self) -> None:
        for value in ("0", "-2"):
            done = cli(self.project, "recall", "--query", "x", "--min-terms", value)
            self.assertEqual((done.returncode, done.stdout), (1, ""), value)
            self.assertTrue(done.stderr.startswith("an-kla error: recall_min_terms_invalid"), done.stderr)

    def test_ranks_stay_contiguous_after_the_min_terms_filter(self) -> None:
        self.fact("f-1", "cuarzo basalto juntos")
        self.fact("f-2", "solo cuarzo aqui")
        self.fact("f-3", "cuarzo y basalto de nuevo")
        out = self.ok("cuarzo basalto", "--min-terms", "2")
        self.assertEqual([r["rank"] for r in out["results"]], [1, 2])
        self.assertEqual(out["excluded"]["min_terms"], 1)


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
        self.assertEqual(out["excluded"], {**NO_EXCLUDED, "invalid_envelope": 2, "scope": 1})

    def test_all_scope_includes_everything_and_marks_each(self) -> None:
        out = self.ok("zorro", "--scope", "all")
        self.assertEqual({r["id"]: r["scope_match"] for r in out["results"]},
                         {self.mine: "repo", "f-legado": "legacy", "f-ajeno": "other",
                          "f-roto": "invalid_envelope", "f-hueco": "invalid_envelope"})
        by_id = {r["id"]: r for r in out["results"]}
        for name in ("f-legado", "f-roto", "f-hueco"):
            self.assertEqual((by_id[name]["writer"], by_id[name]["enqueued_at"]), (None, None), name)
        self.assertEqual(by_id["f-ajeno"]["writer"]["repo"]["id"], OTHER_REPO)
        self.assertEqual(out["excluded"], NO_EXCLUDED)
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
