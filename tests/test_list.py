"""ADR-0067 (#233): `list`, listado determinista de registros por stream y vigencia; sus pruebas de aceptación."""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest import mock

from an_kla.history import history
from an_kla.listing import list_records
from an_kla.state_show import StateReadError, serialized_size
from tests.inbox_support import InboxCase
from tests.remember_support import cli, remember
from tests.test_state_show_history import envelope, snapshot, state_row

DIGEST = "sha256:" + "a" * 64


def fact_row(rid: str, stamp: str | None, text: str | None = None, kind: str = "fact", **extra) -> dict:
    row = {"id": rid, "text": text if text is not None else f"texto {rid}", **extra}
    if stamp is not None:
        row["an_kla_envelope"] = envelope("agente-a", stamp, kind=kind, text=row["text"])
    return row


def store_of(facts=(), episodes=(), events=(), supersedes=()) -> SimpleNamespace:
    records = {"facts": tuple(facts), "events": tuple(events), "episodes": tuple(episodes)}
    return SimpleNamespace(
        revision_id="sha256:" + "0" * 64, records=records, raw_records=records,
        manifest={"supersedes_map": [dict(e) for e in supersedes]},
    )


def ids(result: dict) -> list[str]:
    return [item["id"] for item in result["items"]]


class SelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snap = store_of(
            facts=[
                fact_row("f-viejo", "2026-05-01T10:00:00.000000Z", status="superseded"),
                fact_row("f-nuevo", "2026-05-02T10:00:00.000000Z"),
                fact_row("f-malo", "2026-05-03T10:00:00.000000Z", status="refutada"),
                fact_row("f-checkpoint", "2026-05-04T10:00:00.000000Z", text="checkpoint: el piloto sigue abierto"),
            ],
            supersedes=[{"stream": "facts", "target_id": "f-viejo", "sustituida_por": "f-nuevo"}],
        )

    def test_status_all_lists_every_record_with_status_and_superseded_by(self) -> None:
        result = list_records(self.snap, status="all")
        self.assertEqual(ids(result), ["f-viejo", "f-nuevo", "f-malo", "f-checkpoint"])
        self.assertEqual([i["status"] for i in result["items"]], ["superseded", "active", "refuted", "active"])
        self.assertEqual(result["items"][0]["superseded_by"], "f-nuevo")
        self.assertNotIn("superseded_by", result["items"][1])
        self.assertEqual((result["total"], result["returned"], result["truncated"], result["next"]), (4, 4, False, None))

    def test_default_is_active_facts_and_a_checkpoint_without_the_word_estado_is_listed(self) -> None:
        result = list_records(self.snap)
        self.assertEqual(ids(result), ["f-nuevo", "f-checkpoint"])
        self.assertEqual(
            result["filters"],
            {"streams": ["facts"], "status": "active", "kind": None, "slot": None, "limit": 1000, "budget": 65536, "text": False},
        )
        self.assertEqual(list_records(self.snap, status="refuted")["items"][0]["id"], "f-malo")
        self.assertEqual(ids(list_records(self.snap, status="superseded")), ["f-viejo"])

    def test_kind_and_slot_filter_by_stream_and_slot(self) -> None:
        episodes = [
            state_row("ep-main", "agente-a", "2026-05-01T10:00:00.000000Z"),
            state_row("ep-lateral", "agente-b", "2026-05-02T10:00:00.000000Z", slot="lateral"),
        ]
        snap = store_of(facts=[fact_row("f-1", "2026-05-01T09:00:00.000000Z")], episodes=episodes)
        result = list_records(snap, streams="facts,episodes", kind="state", slot="main")
        self.assertEqual([(i["stream"], i["id"], i["slot"]) for i in result["items"]], [("episodes", "ep-main", "main")])
        empty = list_records(snap, streams="facts", kind="state")
        self.assertEqual((empty["items"], empty["total"], empty["truncated"]), ([], 0, False))
        decision = store_of(facts=[fact_row("d-1", "2026-05-01T09:00:00.000000Z", kind="decision")])
        self.assertEqual(ids(list_records(decision, kind="decision")), ["d-1"])
        self.assertEqual(ids(list_records(decision, kind="fact")), [])

    def test_text_only_with_the_flag_and_text_bytes_always(self) -> None:
        snap = store_of(facts=[fact_row("f-1", "2026-05-01T09:00:00.000000Z", text="ñandú")])
        plain = list_records(snap)["items"][0]
        self.assertNotIn("text", plain)
        self.assertEqual(plain["text_bytes"], len("ñandú".encode()))
        with_text = list_records(snap, text=True)
        self.assertEqual(with_text["items"][0]["text"], "ñandú")
        self.assertTrue(with_text["filters"]["text"])
        self.assertNotIn("ñandú", json.dumps(plain, ensure_ascii=False))

    def test_disputes_count_counts_vigent_disputes(self) -> None:
        def dispute(rid: str, **extra) -> dict:
            return fact_row(rid, "2026-06-01T10:00:00.000000Z", disputes={"stream": "facts", "target_id": "f-1", "target_record_sha256": DIGEST}, **extra)

        snap = store_of(facts=[
            fact_row("f-1", "2026-05-01T10:00:00.000000Z"), fact_row("f-2", "2026-05-02T10:00:00.000000Z"),
            dispute("d-1"), dispute("d-2", verdict="contradicted"), dispute("d-3", status="refutada"),
        ])
        by_id = {i["id"]: i for i in list_records(snap, status="all")["items"]}
        self.assertEqual((by_id["f-1"]["disputes_count"], by_id["f-2"]["disputes_count"]), (2, 0))
        self.assertNotIn("disputed", by_id["f-1"])

    def test_anchors_count_and_coverage_level_without_git(self) -> None:
        anchored = fact_row(
            "f-anclado", "2026-05-01T10:00:00.000000Z",
            anchors=[{"source": {"kind": "document"}}, {"source": {"kind": "conversation"}}],
            coverage={"total": 3, "present": 2, "level": "partial"},
        )
        snap = store_of(facts=[anchored, fact_row("f-plano", "2026-05-02T10:00:00.000000Z")])
        with mock.patch("an_kla.anchors_git.GitRepo", side_effect=AssertionError("list no lee Git")), \
                mock.patch("an_kla.anchors_read.GitRepo", side_effect=AssertionError("list no lee Git")):
            items = {i["id"]: i for i in list_records(snap)["items"]}
        self.assertEqual((items["f-anclado"]["anchors_count"], items["f-anclado"]["coverage_level"]), (2, "partial"))
        self.assertFalse({"anchors_count", "coverage_level", "anchors"} & set(items["f-plano"]))

    def test_legacy_records_are_flagged_and_go_last_of_their_stream(self) -> None:
        snap = store_of(
            facts=[fact_row("f-legado", None), fact_row("f-b", "2026-05-02T10:00:00.000000Z"), fact_row("f-a", "2026-05-01T10:00:00.000000Z")],
            episodes=[{"id": "ep-legado", "text": "sin sobre"}],
        )
        result = list_records(snap, streams="facts,episodes")
        self.assertEqual(ids(result), ["f-a", "f-b", "f-legado", "ep-legado"])
        legacy = result["items"][2]
        self.assertEqual((legacy["legacy"], legacy["writer"], legacy["enqueued_at"], legacy["kind"]), (True, None, None, "fact"))
        self.assertEqual(result["items"][3]["kind"], "state")
        self.assertNotIn("legacy", result["items"][0])


class OrderTests(unittest.TestCase):
    def test_partition_follows_the_requested_streams_and_is_deterministic(self) -> None:
        facts = [fact_row("f-2", "2026-05-02T10:00:00.000000Z"), fact_row("f-1", "2026-05-03T10:00:00.000000Z")]
        episodes = [state_row("ep-1", "agente-a", "2026-05-01T10:00:00.000000Z")]
        events = [{"id": "ev-1", "text": "e"}]
        forward = list_records(store_of(facts, episodes, events), streams="facts,episodes,events")
        backward = list_records(store_of(reversed(facts), episodes, events), streams="events,episodes,facts")
        self.assertEqual(ids(forward), ["f-2", "f-1", "ep-1", "ev-1"])
        self.assertEqual(ids(backward), ["ev-1", "ep-1", "f-2", "f-1"])
        self.assertEqual(ids(list_records(store_of(facts, episodes, events), streams="events")), ["ev-1"])
        self.assertEqual(list_records(store_of(facts), streams="facts"), list_records(store_of(reversed(facts)), streams="facts"))

    def test_same_stamp_breaks_by_id(self) -> None:
        stamp = "2026-05-01T10:00:00.000000Z"
        snap = store_of(facts=[fact_row("f-b", stamp), fact_row("f-a", stamp)])
        self.assertEqual(ids(list_records(snap)), ["f-a", "f-b"])


class BudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snap = store_of(facts=[fact_row(f"f-{n}", f"2026-05-0{n}T10:00:00.000000Z", text="x" * (30 * n)) for n in range(1, 6)])
        self.full = list_records(self.snap, budget=10**6, text=True)

    def test_budget_never_exceeded_one_by_one(self) -> None:
        counts, seen_next = set(), False
        for budget in range(1, serialized_size(self.full) + 40):
            try:
                result = list_records(self.snap, budget=budget, text=True)
            except StateReadError as exc:
                self.assertEqual(str(exc), "list_budget_too_small")
                continue
            self.assertLessEqual(serialized_size(result), budget)
            self.assertEqual(result["used_bytes"], serialized_size(result))
            self.assertEqual(ids(result), ids(self.full)[:result["returned"]])  # se poda del final
            self.assertEqual(result["truncated"], result["returned"] < 5)
            self.assertEqual(result["excluded"], {"limit": 0, "budget": 5 - result["returned"]})
            self.assertEqual(result["next"] is not None, result["truncated"])
            counts.add(result["returned"])
            seen_next |= result["next"] is not None
        self.assertEqual(counts, {0, 1, 2, 3, 4, 5})
        self.assertTrue(seen_next)
        exact = list_records(self.snap, budget=serialized_size(self.full) - 3, text=True)  # filters.budget se hace eco: 7 cifras menos 4
        self.assertEqual((exact["items"], exact["truncated"]), (self.full["items"], False))

    def test_minimal_budget_is_too_small(self) -> None:
        with self.assertRaises(StateReadError) as raised:
            list_records(self.snap, budget=10)
        self.assertEqual(str(raised.exception), "list_budget_too_small")

    def test_limit_cuts_by_number_before_the_budget(self) -> None:
        result = list_records(self.snap, limit=2)
        self.assertEqual(ids(result), ["f-1", "f-2"])
        self.assertEqual((result["total"], result["excluded"], result["truncated"]), (5, {"limit": 3, "budget": 0}, True))
        self.assertIsNotNone(result["next"])
        both = list_records(self.snap, limit=4, budget=serialized_size(list_records(self.snap, limit=2, text=True)), text=True)
        self.assertEqual(both["excluded"]["limit"], 1)
        self.assertGreater(both["excluded"]["budget"], 0)
        self.assertEqual(both["total"], both["returned"] + sum(both["excluded"].values()))


class PaginationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.facts = [fact_row(f"f-{n:02d}", f"2026-05-{n:02d}T10:00:00.000000Z") for n in range(1, 12)]
        self.facts.insert(3, fact_row("f-legado", None))
        self.snap = store_of(facts=self.facts, episodes=[state_row("ep-1", "agente-a", "2026-04-01T10:00:00.000000Z")])

    def walk(self, **options) -> list[str]:
        seen, after = [], None
        for _ in range(50):
            page = list_records(self.snap, streams="facts,episodes", after=after, **options)
            seen += ids(page)
            after = page["next"]
            if after is None:
                return seen
        self.fail("la paginación no termina")

    def test_walking_with_after_equals_one_big_page(self) -> None:
        big = ids(list_records(self.snap, streams="facts,episodes", budget=10**6))
        self.assertEqual(len(big), 13)
        for limit in (1, 2, 5, 12, 13):
            with self.subTest(limit=limit):
                self.assertEqual(self.walk(limit=limit), big)
        one = serialized_size(list_records(self.snap, streams="facts,episodes", limit=1))
        self.assertEqual(self.walk(budget=one + 700), big)  # por presupuesto, no por límite

    def test_cursor_from_another_revision_is_stale(self) -> None:
        page = list_records(self.snap, limit=2)
        newer = store_of(facts=self.facts)
        newer.revision_id = "sha256:" + "1" * 64
        with self.assertRaises(StateReadError) as raised:
            list_records(newer, limit=2, after=page["next"])
        self.assertEqual(str(raised.exception), "list_cursor_stale")

    def test_malformed_cursor_or_other_filters_is_invalid(self) -> None:
        page = list_records(self.snap, limit=2)
        for bad, options in (
            ("no es base64!", {}), ("", {}), ("e30", {}), (page["next"], {"status": "all"}),
            (page["next"], {"streams": "facts,episodes"}), (page["next"], {"text": True}), (page["next"], {"kind": "fact"}),
        ):
            with self.subTest(cursor=bad, options=options), self.assertRaises(StateReadError) as raised:
                list_records(self.snap, after=bad, limit=2, **options)
            self.assertEqual(str(raised.exception), "list_cursor_invalid")
        self.assertIsNotNone(list_records(self.snap, limit=5, after=page["next"])["items"])  # el tamaño de página sí puede cambiar


class ValidationTests(unittest.TestCase):
    def test_every_invalid_input_has_its_own_code(self) -> None:
        snap = store_of()
        cases = {
            "list_streams_invalid": [{"streams": "nada"}, {"streams": ""}, {"streams": "facts,facts"}, {"streams": "facts,"}],
            "list_status_invalid": [{"status": "vigente"}],
            "list_kind_invalid": [{"kind": "otro"}],
            "list_slot_invalid": [{"slot": "MAL"}, {"slot": ""}],
            "list_limit_invalid": [{"limit": 0}, {"limit": -1}, {"limit": 10001}, {"limit": True}],
            "list_budget_invalid": [{"budget": 0}, {"budget": -5}, {"budget": True}],
        }
        for code, variants in cases.items():
            for options in variants:
                with self.subTest(code=code, options=options), self.assertRaises(StateReadError) as raised:
                    list_records(snap, **options)
                self.assertEqual(str(raised.exception), code)
        self.assertEqual(list_records(snap, limit=10000)["total"], 0)


class HistoryUnchangedTests(unittest.TestCase):
    """`history` sigue sirviendo el mismo prefijo que antes de extraer el ajuste de presupuesto a `read_budget`."""

    @staticmethod
    def reference(snap, root: str, budget: int):
        """El ajuste original de `history` (búsqueda binaria + punto fijo), con las funciones de `history`."""

        from an_kla import history as module

        nodes, edges = module._graph(snap)
        visited, truncated = module._walk(nodes, edges, next(k for k in nodes if k[1] == root), 200)
        ordered = sorted(visited, key=lambda n: module._order(nodes[n]))

        def build(count: int, used: int) -> dict:
            kept = ordered[:count]
            return module._response(snap.revision_id, root, [nodes[n] for n in kept], module._edges_among(set(kept), edges),
                                    truncated or count < len(ordered), used, {})

        if serialized_size(build(0, budget)) > budget:
            return "too_small"
        low, high = 0, len(ordered)
        while low < high:
            middle = (low + high + 1) // 2
            if serialized_size(build(middle, budget)) <= budget:
                low = middle
            else:
                high = middle - 1
        used = budget
        for _ in range(8):
            result = build(low, used)
            size = serialized_size(result)
            if size == used:
                return result
            used = size
        return build(low, budget)

    def test_history_equals_the_original_algorithm_for_every_budget(self) -> None:
        rows = [state_row(f"ep-{n}", "a", f"2026-05-0{n}T10:00:00.000000Z") for n in range(1, 6)]
        chain = [{"stream": "episodes", "target_id": f"ep-{n}", "sustituida_por": f"ep-{n + 1}"} for n in range(1, 5)]
        snap = snapshot(rows, supersedes=chain)
        top = serialized_size(history(snap, "ep-1", budget=10**6))
        for budget in range(1, top + 60):
            expected = self.reference(snap, "ep-1", budget)
            try:
                actual = history(snap, "ep-1", budget=budget)
            except StateReadError as exc:
                self.assertEqual((str(exc), expected), ("history_budget_too_small", "too_small"))
                continue
            self.assertEqual(actual, expected, budget)


class CliTests(InboxCase):
    def run_list(self, *args: str) -> tuple[int, dict | None, str]:
        done = cli(self.project, "list", *args)
        return done.returncode, (json.loads(done.stdout) if done.returncode == 0 else None), done.stderr

    def test_end_to_end_without_git_reads_and_byte_exact_output(self) -> None:
        _, first = remember(self.project, "primer hecho")
        _, second = remember(self.project, "segundo hecho", "--supersedes", first["record_id"])
        remember(self.project, "estado actual", "--kind", "state", "--slot", "trabajo")
        done = cli(self.project, "list", "--status", "all", "--streams", "facts,episodes", "--text")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(done.stdout.endswith("\n"))
        result = json.loads(done.stdout)
        self.assertEqual(len(done.stdout.encode()), result["used_bytes"])
        by_id = {i["id"]: i for i in result["items"]}
        self.assertEqual(by_id[first["record_id"]]["status"], "superseded")
        self.assertEqual(by_id[first["record_id"]]["superseded_by"], second["record_id"])
        self.assertEqual([i["stream"] for i in result["items"]], ["facts", "facts", "episodes"])
        self.assertEqual(cli(self.project, "list", "--status", "all", "--streams", "facts,episodes", "--text").stdout, done.stdout)
        plain = json.loads(cli(self.project, "list").stdout)
        self.assertEqual(ids(plain), [second["record_id"]])
        self.assertNotIn("segundo hecho", json.dumps(plain))
        history_done = cli(self.project, "history", second["record_id"])
        self.assertEqual(json.loads(history_done.stdout)["nodes"][0]["id"], first["record_id"])

    def test_remember_between_pages_makes_the_cursor_stale(self) -> None:
        for n in range(3):
            remember(self.project, f"hecho {n}")
        rc, page, _ = self.run_list("--limit", "1")
        self.assertEqual((rc, page["truncated"]), (0, True))
        remember(self.project, "uno más")
        done = cli(self.project, "list", "--limit", "1", "--after", page["next"])
        self.assertEqual((done.returncode, done.stdout), (1, ""))
        self.assertIn("list_cursor_stale", done.stderr)
        rc, fresh, _ = self.run_list("--limit", "10")
        self.assertEqual((rc, fresh["total"]), (0, 4))

    def test_invalid_flags_are_rc_1_without_paths(self) -> None:
        remember(self.project, "x")
        cases = {
            "list_streams_invalid": ["--streams", "nada"], "list_status_invalid": ["--status", "vigente"],
            "list_kind_invalid": ["--kind", "otro"], "list_slot_invalid": ["--slot", "MAL"],
            "list_limit_invalid": ["--limit", "0"], "list_budget_invalid": ["--budget", "0"],
            "list_cursor_invalid": ["--after", "basura"], "list_budget_too_small": ["--budget", "10"],
        }
        for code, args in cases.items():
            with self.subTest(code=code):
                done = cli(self.project, "list", *args)
                self.assertEqual((done.returncode, done.stdout), (1, ""))
                self.assertIn(f"an-kla error: {code}", done.stderr)
                self.assertNotIn(str(self.project), done.stderr)
        rc, empty, _ = self.run_list("--kind", "state", "--streams", "facts")
        self.assertEqual((rc, empty["total"], empty["items"]), (0, 0, []))

    def test_list_creates_nothing_and_does_not_drain_the_inbox(self) -> None:
        remember(self.project, "hecho")
        before = sorted(p.name for p in self.inbox.rglob("*"))
        self.assertEqual(cli(self.project, "list").returncode, 0)
        self.assertEqual(sorted(p.name for p in self.inbox.rglob("*")), before)


if __name__ == "__main__":
    unittest.main()
