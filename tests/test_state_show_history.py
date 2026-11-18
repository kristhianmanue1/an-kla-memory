"""ADR-0065 (E1.d1): `state show`, `history`, sus presupuestos y el criterio de aceptación 1."""

from __future__ import annotations

import json
import unittest
from unittest import mock
from datetime import datetime, timezone
from types import SimpleNamespace

from an_kla import identity_c0, inbox_drain
from an_kla.history import history
from an_kla.remember import remember
from an_kla.state_show import StateReadError, serialized_size, state_show
from an_kla.state_slot import state_rows
from tests.inbox_support import AGENT_ENV, EntryFactory, InboxCase
from tests.remember_support import cli
from tests.test_state_slot import A, B, C, StateCase


def envelope(agent: str, stamp: str, kind: str = "state", text: str = "t") -> dict:
    env = {**AGENT_ENV, "AN_KLA_AGENT_NAME": agent, "AN_KLA_SESSION_ID": f"{agent}-s"}
    identity = _identity(env)
    key = identity_c0.derive_idempotency_key(identity, kind, text + stamp, None, "main" if kind == "state" else None)
    moment = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    return identity_c0.build_envelope(identity, kind, key, lambda: moment)


_SHARED: dict = {}


def _identity(env: dict) -> dict:
    """Identidad C0 de un agente en UN repo compartido por todas las filas sintéticas (misma ``repo.id``)."""

    if "project" not in _SHARED:
        import atexit
        import tempfile
        from pathlib import Path
        from tests.inbox_support import make_project

        temp = tempfile.TemporaryDirectory(prefix="ident-")
        atexit.register(temp.cleanup)
        _SHARED["project"] = make_project(Path(temp.name).resolve())
    name = env["AN_KLA_AGENT_NAME"]
    if name not in _SHARED:
        _SHARED[name] = identity_c0.build_identity(_SHARED["project"], env)
    return _SHARED[name]


def snapshot(episodes=(), facts=(), supersedes=()) -> SimpleNamespace:
    """Un snapshot sintético: lo que `plan-write` no deja crear (ciclos, aristas colgantes) se prueba aquí."""

    records = {"facts": tuple(facts), "events": (), "episodes": tuple(episodes)}
    return SimpleNamespace(
        revision_id="sha256:" + "0" * 64, records=records, raw_records=records,
        manifest={"supersedes_map": [dict(e) for e in supersedes]},
    )


def state_row(rid: str, agent: str, stamp: str, slot: str | None = "main", **extra) -> dict:
    row = {"id": rid, "text": f"texto {rid}", "an_kla_envelope": envelope(agent, stamp)}
    if slot is not None:
        row["slot"] = slot
    return {**row, **extra}


class NoInbox(unittest.TestCase):
    """Los snapshots sintéticos no tienen bandeja: `pending_states` se sustituye por «nada pendiente»."""

    def setUp(self) -> None:
        patcher = mock.patch("an_kla.state_show.pending_states", return_value=(0, {}))
        patcher.start()
        self.addCleanup(patcher.stop)


class HeadTests(NoInbox):
    def test_head_is_the_greatest_enqueued_at_then_the_greatest_id(self) -> None:
        stamp = "2026-05-01T10:00:00.000000Z"
        rows = [state_row("ep-b", "a", stamp), state_row("ep-a", "b", stamp), state_row("ep-c", "c", "2026-04-30T10:00:00.000000Z")]
        store = SimpleNamespace(project_root=".", snapshot=lambda: snapshot(rows))
        shown = state_show(store, repo_id=state_rows(snapshot(rows))[0].repo_id, scope="repo")
        self.assertEqual([s["id"] for s in shown["slots"]], ["ep-b"])
        self.assertEqual(shown["slots"][0]["conflict"], ["ep-c", "ep-a", "ep-b"])

    def test_legacy_states_are_out_of_every_slot(self) -> None:
        legacy = [{"id": "ep-viejo", "text": "sin sobre"}, {"id": "ep-roto", "text": "x", "an_kla_envelope": {"schema": "mal"}}]
        self.assertEqual(state_rows(snapshot(legacy)), [])
        bad_slot = state_row("ep-s", "a", "2026-05-01T10:00:00.000000Z", slot="MAL")
        self.assertEqual(state_rows(snapshot([bad_slot])), [])

    def test_a_row_without_slot_belongs_to_main(self) -> None:
        member = state_rows(snapshot([state_row("ep-x", "a", "2026-05-01T10:00:00.000000Z", slot=None)]))[0]
        self.assertEqual(member.slot, "main")


class HistoryGraphTests(unittest.TestCase):
    def test_a_cycle_is_walked_once_and_is_deterministic(self) -> None:
        rows = [state_row(i, "a", s) for i, s in (("ep-1", "2026-05-01T10:00:00.000000Z"), ("ep-2", "2026-05-02T10:00:00.000000Z"))]
        ring = [{"stream": "episodes", "target_id": "ep-1", "sustituida_por": "ep-2"},
                {"stream": "episodes", "target_id": "ep-2", "sustituida_por": "ep-1"}]
        snap = snapshot(rows, supersedes=ring)
        first, second = history(snap, "ep-1"), history(snap, "ep-1")
        self.assertEqual(first, second)
        self.assertEqual([n["id"] for n in first["nodes"]], ["ep-1", "ep-2"])
        self.assertEqual([(e["from"], e["to"]) for e in first["edges"]], [("ep-1", "ep-2"), ("ep-2", "ep-1")])
        self.assertFalse(first["truncated"])

    def test_a_dangling_edge_makes_neither_node_nor_edge(self) -> None:
        rows = [state_row("ep-1", "a", "2026-05-01T10:00:00.000000Z")]
        snap = snapshot(rows, supersedes=[{"stream": "episodes", "target_id": "ep-1", "sustituida_por": "ep-fantasma"}])
        result = history(snap, "ep-1")
        self.assertEqual((len(result["nodes"]), result["edges"]), (1, []))

    def test_legacy_nodes_come_last_and_disputes_are_edges(self) -> None:
        legacy = {"id": "f-legado", "text": "sin sobre"}
        env = envelope("a", "2026-05-01T10:00:00.000000Z", kind="fact")
        dispute = {"id": "f-nuevo", "text": "disputa", "an_kla_envelope": env,
                   "disputes": {"stream": "facts", "target_id": "f-legado", "target_record_sha256": "sha256:" + "1" * 64}}
        result = history(snapshot(facts=[legacy, dispute]), "f-legado")
        self.assertEqual([n["id"] for n in result["nodes"]], ["f-nuevo", "f-legado"])
        self.assertEqual(result["edges"], [{"from": "f-nuevo", "to": "f-legado", "type": "disputes"}])
        self.assertEqual(result["nodes"][1]["enqueued_at"], None)
        self.assertEqual(result["nodes"][1]["kind"], "fact")

    def test_limit_prunes_with_truncated_and_keeps_edges_among_kept_nodes(self) -> None:
        rows = [state_row(f"ep-{n}", "a", f"2026-05-0{n}T10:00:00.000000Z") for n in range(1, 6)]
        chain = [{"stream": "episodes", "target_id": f"ep-{n}", "sustituida_por": f"ep-{n + 1}"} for n in range(1, 5)]
        result = history(snapshot(rows, supersedes=chain), "ep-3", limit=3)
        self.assertTrue(result["truncated"])
        ids = {n["id"] for n in result["nodes"]}
        self.assertEqual(len(ids), 3)
        self.assertIn("ep-3", ids)
        for edge in result["edges"]:
            self.assertTrue({edge["from"], edge["to"]} <= ids)

    def test_unknown_and_ambiguous_ids(self) -> None:
        with self.assertRaises(StateReadError) as caught:
            history(snapshot([]), "ep-no")
        self.assertEqual(str(caught.exception), "history_id_not_found")
        twin_facts = [{"id": "x", "text": "f"}]
        snap = snapshot([{"id": "x", "text": "e"}], facts=twin_facts)
        with self.assertRaises(StateReadError) as caught:
            history(snap, "x")
        self.assertEqual(str(caught.exception), "history_id_ambiguous")


class BudgetTests(NoInbox):
    def sweep(self, make, floor_error: str) -> list[int]:
        """Presupuesto de 1 en 1: nunca se supera, y por debajo del suelo el error tipado."""

        sizes, errors = [], 0
        for budget in range(1, 3000):
            try:
                result = make(budget)
            except StateReadError as exc:
                self.assertEqual(str(exc), floor_error)
                self.assertEqual(sizes, [], "un error después de una respuesta válida")
                errors += 1
                continue
            size = serialized_size(result)
            self.assertLessEqual(size, budget, budget)
            self.assertEqual(result["used_bytes"], size, budget)
            sizes.append(size)
        self.assertGreater(errors, 0)
        return sizes

    def test_state_show_budget_never_exceeded_one_by_one(self) -> None:
        stamp = "2026-05-01T10:00:00.000000Z"
        rows = [state_row(f"ep-{slot}", "a", stamp, slot=slot) for slot in ("alfa", "beta", "gamma")]
        rows = [{**r, "text": "t" * 120} for r in rows]
        repo = state_rows(snapshot(rows))[0].repo_id
        store = SimpleNamespace(project_root=".", snapshot=lambda: snapshot(rows))
        full = state_show(store, all_slots=True, repo_id=repo, budget=10**6)
        self.assertEqual(len(full["slots"]), 3)
        seen_stub = seen_excluded = False

        def make(budget: int) -> dict:
            return state_show(store, all_slots=True, repo_id=repo, budget=budget)

        for budget in range(1, serialized_size(full) + 40):
            try:
                result = make(budget)
            except StateReadError as exc:
                self.assertEqual(str(exc), "state_budget_too_small")
                continue
            self.assertLessEqual(serialized_size(result), budget)
            self.assertEqual(result["used_bytes"], serialized_size(result))
            self.assertEqual(len(result["slots"]) + result["excluded"]["budget"], 3)
            seen_stub |= any(s.get("truncated") for s in result["slots"])
            seen_excluded |= result["excluded"]["budget"] > 0
        self.assertTrue(seen_stub and seen_excluded)
        self.assertEqual(make(serialized_size(full)), full)

    def test_history_budget_never_exceeded_one_by_one(self) -> None:
        rows = [state_row(f"ep-{n}", "a", f"2026-05-0{n}T10:00:00.000000Z") for n in range(1, 6)]
        chain = [{"stream": "episodes", "target_id": f"ep-{n}", "sustituida_por": f"ep-{n + 1}"} for n in range(1, 5)]
        snap = snapshot(rows, supersedes=chain)
        full = history(snap, "ep-1", budget=10**6)
        self.assertEqual(len(full["nodes"]), 5)
        counts = set()
        for budget in range(1, serialized_size(full) + 40):
            try:
                result = history(snap, "ep-1", budget=budget)
            except StateReadError as exc:
                self.assertEqual(str(exc), "history_budget_too_small")
                continue
            self.assertLessEqual(serialized_size(result), budget)
            self.assertEqual(result["used_bytes"], serialized_size(result))
            self.assertEqual(result["truncated"], len(result["nodes"]) < 5)
            kept = {n["id"] for n in result["nodes"]}
            self.assertTrue(all({e["from"], e["to"]} <= kept for e in result["edges"]))
            counts.add(len(result["nodes"]))
        self.assertEqual(counts, {0, 1, 2, 3, 4, 5})


class Acceptance1Tests(StateCase):
    """20 estados en 2 casillas por 3 agentes: `state show --all-slots` da 2 e `history` da la cadena de cada uno."""

    def test_twenty_states_two_slots_three_agents(self) -> None:
        factories = [EntryFactory(self.store, env) for env in (A, B, C)]
        shared = factories[0]
        for n in range(20):
            slot = "main" if n % 2 == 0 else "lateral"
            writer = factories[n % 3]
            writer.counter = shared.counter = max(writer.counter, shared.counter)
            writer.write(f"estado {n}", kind="state", slot=slot)
            shared.counter = writer.counter
        report = inbox_drain.drain(self.store)
        self.assertEqual((report["state"], report["committed"]["count"]), ("drained", 20))
        shown = state_show(self.store, all_slots=True)
        self.assertEqual([s["slot"] for s in shown["slots"]], ["lateral", "main"])
        self.assertEqual({s["text"] for s in shown["slots"]}, {"estado 18", "estado 19"})
        snap = self.store.snapshot()
        chains = {}
        for head in shown["slots"]:
            result = history(snap, head["id"], limit=200, budget=10**6)
            chains[head["slot"]] = result
            self.assertEqual(len(result["nodes"]), 10)
            self.assertEqual(len(result["edges"]), 9)
            self.assertEqual({n["slot"] for n in result["nodes"]}, {head["slot"]})
            self.assertEqual([n["status"] for n in result["nodes"]].count("active"), 1)
            self.assertEqual(head["retired_count"], 9)
        self.assertEqual(sum(len(c["nodes"]) for c in chains.values()), 20)
        self.assertEqual({n["writer"]["agent"]["name"] for c in chains.values() for n in c["nodes"]},
                         {"agente-a", "agente-b", "agente-c"})

    def test_state_show_does_not_drain_and_reports_pending(self) -> None:
        self.assertTrue(state_show(self.store)["empty"])
        remember(self.store, "ya vaciado", kind="state", slot="lateral", env=B)
        factory = EntryFactory(self.store, A)
        factory.write("sin vaciar", kind="state", slot="lateral")
        shown = state_show(self.store, all_slots=True)
        self.assertEqual(shown["inbox"]["pending"], 1)
        self.assertEqual([(s["slot"], s["text"], s["pending_states"]) for s in shown["slots"]], [("lateral", "ya vaciado", 1)])
        self.assertEqual(len(list(factory.pending.iterdir())), 1)  # `state show` no vació la bandeja


class CliTests(InboxCase):
    def test_cli_state_show_and_history_end_to_end(self) -> None:
        first = json.loads(cli(self.project, "remember", "--text", "uno", "--kind", "state", "--slot", "trabajo").stdout)
        second = json.loads(cli(self.project, "remember", "--text", "dos", "--kind", "state", "--slot", "trabajo").stdout)
        self.assertEqual(second["retired"]["id"], first["record_id"])
        done = cli(self.project, "state", "show", "--slot", "trabajo")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(done.stdout.endswith("\n"))
        shown = json.loads(done.stdout)
        self.assertEqual([(s["id"], s["text"], s["retired_count"]) for s in shown["slots"]], [(second["record_id"], "dos", 1)])
        self.assertEqual(len(done.stdout.encode("utf-8")), shown["used_bytes"])
        past = json.loads(cli(self.project, "history", second["record_id"]).stdout)
        self.assertEqual([n["id"] for n in past["nodes"]], [first["record_id"], second["record_id"]])
        self.assertEqual(past["edges"], [{"from": second["record_id"], "to": first["record_id"], "type": "supersedes"}])
        self.assertEqual(json.loads(cli(self.project, "state", "show").stdout)["empty"], True)

    def test_cli_budget_too_small_is_rc_1(self) -> None:
        remember_done = cli(self.project, "remember", "--text", "x", "--kind", "state")
        self.assertEqual(remember_done.returncode, 0, remember_done.stderr)
        done = cli(self.project, "state", "show", "--budget", "10")
        self.assertEqual(done.returncode, 1)
        self.assertIn("state_budget_too_small", done.stderr)
        self.assertEqual(done.stdout, "")
        done = cli(self.project, "history", "no-existe")
        self.assertEqual(done.returncode, 1)
        self.assertIn("history_id_not_found", done.stderr)


if __name__ == "__main__":
    unittest.main()
