"""Criterio 8 (ADR-0063): lote y entradas malas; bisección por prefijos y último recurso uno a uno."""

from __future__ import annotations

import json
import os
import signal
from pathlib import Path
from unittest import mock

from an_kla import inbox, inbox_drain
from an_kla.canonical import canonical_json
from an_kla.disputes import build_remember_plan as real_plan
from an_kla.store_errors import StoreError
from tests.inbox_support import EntryFactory, InboxCase

REPORT = os.environ.get("AN_KLA_BATCH_REPORT")


def facts(store) -> dict[str, dict]:
    return {str(row["id"]): row for row in store.snapshot().records["facts"]}


def report(name: str, data: dict) -> None:
    """Con ``AN_KLA_BATCH_REPORT`` define un archivo, añade las cifras medidas (para el informe de B2)."""

    if not REPORT:
        return
    path = Path(REPORT)
    current = json.loads(path.read_text()) if path.exists() else {}
    current[name] = data
    path.write_text(json.dumps(current, indent=1, sort_keys=True))


class BatchLimitCase(InboxCase):
    def setUp(self) -> None:
        super().setUp()
        self.factory = EntryFactory(self.store)
        self.paths = inbox.inbox_paths(self.store)

    def names(self, directory: Path) -> list[str]:
        return sorted(p.name for p in directory.iterdir())


class ThousandPendingTests(BatchLimitCase):
    def test_1000_pending_with_c0_envelope_drain_in_several_commits(self) -> None:
        for index in range(1000):
            self.factory.write(f"recuerdo número {index}")
        result = inbox_drain.drain(self.store, budget_seconds=600)
        self.assertEqual(result["state"], "drained")
        self.assertEqual(result["committed"]["count"], 1000)
        self.assertEqual([b["entries"] for b in result["batches"]], [250, 250, 250, 250])
        self.assertEqual(result["rejected"]["count"], 0)
        self.assertNotIn("drain_error", result)
        self.assertEqual(self.names(self.paths.pending) + self.names(self.paths.inflight), [])
        self.assertEqual(len(facts(self.store)), 1000)
        self.assertTrue(self.store.verify()["ok"])
        for code in ("invalid_write_proposal", "invalid_write_plan"):
            self.assertNotIn(code, json.dumps(result))
        report("thousand", {"batches": [b["entries"] for b in result["batches"]], **result["metrics"]})

    def test_node_budget_trims_the_batch_to_the_document_limit(self) -> None:
        for index in range(30):
            self.factory.write(f"recuerdo {index}")
        with mock.patch.object(inbox_drain, "MAX_DOCUMENT_NODES", 400):  # ~14 entradas por documento
            result = inbox_drain.drain(self.store)
        sizes = [b["entries"] for b in result["batches"]]
        self.assertEqual(sum(sizes), 30)
        self.assertGreater(len(sizes), 1)
        self.assertLessEqual(max(sizes), 400 // 26)
        self.assertEqual(result["state"], "drained")

    def test_real_proposal_and_plan_nodes_stay_under_the_core_limit_at_250(self) -> None:
        entries = []
        for index in range(250):
            self.factory.write(f"recuerdo {index}")
        scanner = inbox_drain.Scanner(self.store, self.store.snapshot(), self.store.read_current(), inbox_drain.Run())
        entries = scanner.scan(inbox_drain._pending_names(self.store, None))
        built = inbox_drain.plan_batch(self.store.read_current(), entries)
        proposal_nodes = inbox_drain.json_nodes(built["proposal"])
        plan_nodes = inbox_drain.json_nodes(built["plan"])
        self.assertLessEqual(max(proposal_nodes, plan_nodes), inbox_drain.MAX_DOCUMENT_NODES)
        report("nodes_at_250", {"proposal": proposal_nodes, "plan": plan_nodes,
                                "sum": proposal_nodes + plan_nodes, "limit_per_document": inbox_drain.MAX_DOCUMENT_NODES})


class BadEntriesTests(BatchLimitCase):
    def test_all_the_bad_entries_at_once_do_not_block_the_drain(self) -> None:
        self.factory.write("objetivo")
        target = inbox_drain.drain(self.store)["committed"]["entries"][0]["record_id"]
        corrupt = self.factory.write_raw(b"{roto")
        fifo = self.factory.fresh_name()
        os.mkfifo(self.paths.pending / fifo)
        link = self.factory.fresh_name()
        os.symlink(self.project / "fuera", self.paths.pending / link)
        folder = self.factory.fresh_name()
        (self.paths.pending / folder).mkdir()
        twin_a = self.factory.write("gemela")
        twin_b = self.factory.write("gemela")
        key = self.factory.entry("colisión")["idempotency_key"]
        first = self.factory.write("colisión", key=key)
        clash = self.factory.write_raw(canonical_json(self.factory.entry("colisión distinta", key=key)))
        missing = self.factory.write("sin objetivo", target_id="f-no-existe")
        skipped = self.factory.write("la política dice skip")
        older = self.factory.write("sustituye uno", target_id=target)
        newer = self.factory.write("sustituye dos", target_id=target)
        good = [self.factory.write(f"bueno {index}") for index in range(5)]

        def plan(proposal):
            built = real_plan(proposal)
            if "record" in proposal and proposal["record"]["text"] == "la política dice skip":
                built["decision"] = {**built["decision"], "decision": "skip", "reason_codes": ["authority_scope_mismatch"]}
            return built

        def alarm(*_args) -> None:
            raise AssertionError("el vaciado se bloqueó")

        signal.signal(signal.SIGALRM, alarm)
        signal.alarm(60)
        try:
            with mock.patch.object(inbox_drain, "build_remember_plan", side_effect=plan):
                result = inbox_drain.drain(self.store)
        finally:
            signal.alarm(0)
        self.assertEqual(result["state"], "drained")
        rejected = {item["entry"]: item["code"] for item in result["rejected"]["entries"]}
        self.assertEqual(
            rejected,
            {corrupt: "inbox_entry_invalid", fifo: "inbox_entry_unsafe", link: "inbox_entry_unsafe",
             clash: "remember_id_collision", missing: "invalid_supersede_target", skipped: "remember_policy_skip",
             newer: "supersedes:duplicate_target"},
        )
        committed = {item["entry"] for item in result["committed"]["entries"]}
        self.assertEqual(committed, {twin_a, first, older, *good})
        self.assertEqual(result["duplicates_removed"]["names"], [twin_b])
        self.assertEqual(self.names(self.paths.pending), [folder])  # el directorio se ignora, sin tocarlo
        self.assertEqual(self.names(self.paths.inflight), [])
        self.assertEqual(len(self.names(self.paths.rejected)), 2 * len(rejected))  # entrada + .reason
        self.assertEqual(sum(1 for r in facts(self.store).values() if r["text"] == "gemela"), 1)
        self.assertEqual(facts(self.store)[target]["status"], "sustituida")
        self.assertTrue(self.store.verify()["ok"])
        report("bad_entries", {"max_write_lock_seconds": result["metrics"]["max_write_lock_seconds"],
                               "attempts": result["metrics"]["attempts"], "rejected": len(rejected)})


class BisectionTests(BatchLimitCase):
    def seed_targets(self, count: int) -> list[str]:
        for index in range(count):
            self.factory.write(f"objetivo {index}")
        done = inbox_drain.drain(self.store, budget_seconds=600)
        by_text = {facts(self.store)[i["record_id"]]["text"]: i["record_id"] for i in done["committed"]["entries"]}
        return [by_text[f"objetivo {index}"] for index in range(count)]

    def test_batch_of_250_with_a_pair_failure_the_prefilter_misses_uses_at_most_8_evaluations(self) -> None:
        targets = self.seed_targets(249)
        names = [self.factory.write(f"reemplazo {i}", target_id=targets[i]) for i in range(249)]
        # el par: la entrada 250 apunta al mismo target que la 100; el prefiltro no la ve
        pair = self.factory.write("reemplazo par", target_id=targets[99])
        self.assertEqual(len(self.names(self.paths.pending)), 250)
        with mock.patch.object(inbox_drain, "duplicate_supersede_targets", return_value=[]):
            result = inbox_drain.drain(self.store, budget_seconds=600)
        self.assertEqual(result["state"], "drained")
        self.assertEqual([(i["entry"], i["code"]) for i in result["rejected"]["entries"]], [(pair, "supersedes:duplicate_target")])
        self.assertEqual([b["entries"] for b in result["batches"]], [249])  # el resto, en un solo lote
        self.assertEqual({i["entry"] for i in result["committed"]["entries"]}, set(names))
        self.assertLessEqual(result["metrics"]["bisect_probes"], 8)
        self.assertEqual(result["metrics"]["one_by_one_commits"], 0)
        self.assertEqual(result["metrics"]["max_write_lock_seconds"] > 0, True)
        self.assertEqual(self.names(self.paths.pending) + self.names(self.paths.inflight), [])
        self.assertTrue(self.store.verify()["ok"])
        report("pair_failure_250", {"bisect_probes": result["metrics"]["bisect_probes"],
                                    "plan_evaluations": result["metrics"]["plan_evaluations"],
                                    "batches": [b["entries"] for b in result["batches"]],
                                    "max_write_lock_seconds": result["metrics"]["max_write_lock_seconds"]})

    def test_two_bad_entries_cost_at_most_8_probes_each(self) -> None:
        targets = self.seed_targets(60)
        names = [self.factory.write(f"reemplazo {i}", target_id=targets[i]) for i in range(60)]
        bad_a = self.factory.write("par a", target_id=targets[10])
        bad_b = self.factory.write("par b", target_id=targets[40])
        with mock.patch.object(inbox_drain, "duplicate_supersede_targets", return_value=[]):
            result = inbox_drain.drain(self.store, budget_seconds=600)
        self.assertEqual({i["entry"] for i in result["rejected"]["entries"]}, {bad_a, bad_b})
        self.assertEqual({i["entry"] for i in result["committed"]["entries"]}, set(names))
        self.assertLessEqual(result["metrics"]["bisect_probes"], 2 * 6)  # ⌈log₂ 62⌉ = 6 por entrada mala
        self.assertEqual([b["entries"] for b in result["batches"]], [60])


class LastResortTests(BatchLimitCase):
    def test_forced_last_resort_commits_one_by_one_with_two_marker_fsyncs_per_entry(self) -> None:
        names = [self.factory.write(f"recuerdo {index}") for index in range(30)]
        real_assign = self.store._assign_records

        def assign(base, pending):
            if len(pending["facts"]) > 1:
                raise StoreError("duplicate_facts_id")
            return real_assign(base, pending)

        markers: list[str] = []
        real_marker = inbox_drain.write_marker

        def marker(store, txid, base, entries):
            markers.append(txid)
            return real_marker(store, txid, base, entries)

        with mock.patch.object(self.store, "_assign_records", assign), mock.patch.object(inbox_drain, "write_marker", marker):
            result = inbox_drain.drain(self.store, budget_seconds=600)
        self.assertEqual(result["state"], "drained")
        self.assertEqual(result["metrics"]["one_by_one_commits"], 30)
        self.assertEqual({i["entry"] for i in result["committed"]["entries"]}, set(names))
        self.assertEqual(len(markers), 31)  # el del lote que falló y uno por commit
        self.assertEqual(result["rejected"]["count"], 0)
        self.assertEqual(self.names(self.paths.pending) + self.names(self.paths.inflight), [])
        self.assertTrue(self.store.verify()["ok"])
        report("last_resort_30", {"commits": result["metrics"]["one_by_one_commits"], "markers": len(markers),
                                  "max_write_lock_seconds": result["metrics"]["max_write_lock_seconds"]})


if __name__ == "__main__":
    import unittest

    unittest.main()
