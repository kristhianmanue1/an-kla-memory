"""Paso 0 del vaciado y cierre del journal (ADR-0063 D1): ramas, predicado, orden y evidencia."""

from __future__ import annotations

import json
import os
import signal
from pathlib import Path
from unittest import mock

from an_kla import inbox, inbox_close, inbox_drain
from an_kla import transactions as tx
from an_kla.canonical import canonical_json
from tests import inbox_cuts
from tests.inbox_support import EntryFactory, InboxCase


class Crash(BaseException):
    pass


def crash() -> None:
    raise Crash()


class CloseCase(InboxCase):
    def setUp(self) -> None:
        super().setUp()
        self.factory = EntryFactory(self.store)
        self.paths = inbox.inbox_paths(self.store)
        self.root = Path(self.store.root)

    def crash_at(self, point: str, entries: int = 3) -> str:
        """Encola ``entries`` y deja el vaciado muerto en ``point``; devuelve el ``txid`` del lote."""

        for index in range(entries):
            self.factory.write(f"recuerdo {index}")
        with inbox_cuts.install(self.store, point, crash):
            with self.assertRaises(Crash):
                inbox_drain.drain(self.store)
        (marker,) = [p for p in self.paths.inflight.iterdir() if inbox.is_marker_name(p.name)]
        return marker.stem

    def journal_path(self, txid: str) -> Path:
        return self.root / "transactions" / f"{txid}.json"

    def journal(self, txid: str) -> dict:
        return json.loads(self.journal_path(txid).read_bytes())

    def names(self, directory: Path) -> list[str]:
        return sorted(p.name for p in directory.iterdir())

    def tearDown_project(self) -> None:
        """Proyecto limpio entre subpruebas (comparten el ``setUp``)."""

        import shutil

        from an_kla.store import MemoryStore

        shutil.rmtree(self.project / ".an-kla", ignore_errors=True)
        self.store = MemoryStore(self.project)
        self.store.initialize()
        self.factory = EntryFactory(self.store)
        self.paths = inbox.inbox_paths(self.store)
        self.root = Path(self.store.root)


class CommittedBranchTests(CloseCase):
    def test_open_journal_with_candidate_current_is_closed_linked_and_audit_complete(self) -> None:
        txid = self.crash_at("pre_committed_journal")
        self.assertEqual(self.journal(txid)["stage"], "candidate_prepared")
        info = tx.inspect_transaction(self.store, txid)
        self.assertEqual((info["committed"], info["audit_state"]), (True, "incomplete"))
        result = inbox_drain.drain(self.store)
        self.assertEqual(result["closed_journals"], [{"txid": txid, "branch": "committed", "journal_closed": True}])
        journal = self.journal(txid)
        self.assertEqual(journal["stage"], "committed")
        self.assertIsInstance(journal["observed_log"], str)
        for field in ("parent", "candidate", "attempt", "stage_object", "candidate_receipt", "current_receipt", "write_policy"):
            self.assertIn(field, journal)
        final = tx.inspect_transaction(self.store, txid)
        self.assertEqual((final["state"], final["audit_state"], final["durability_state"]), ("committed", "complete", "complete"))
        self.assertEqual(self.names(self.paths.pending) + self.names(self.paths.inflight), [])
        self.assertEqual(len(self.store.snapshot().records["facts"]), 3)

    def test_second_closure_is_a_noop_that_does_not_rewrite_the_journal(self) -> None:
        txid = self.crash_at("pre_committed_journal")
        self.assertTrue(inbox_close.close_committed_journal(self.store, txid)["closed"])
        before = self.journal_path(txid).read_bytes()
        mtime = self.journal_path(txid).stat().st_mtime_ns
        again = inbox_close.close_committed_journal(self.store, txid)
        self.assertEqual(again, {"closed": False, "reason": "already_committed"})
        self.assertEqual(self.journal_path(txid).read_bytes(), before)
        self.assertEqual(self.journal_path(txid).stat().st_mtime_ns, mtime)

    def test_durability_incomplete_is_repaired_and_no_receipt_is_fabricated(self) -> None:
        txid = self.crash_at("post_replace_current")
        before = tx.inspect_transaction(self.store, txid)
        self.assertEqual((before["state"], before["durability_state"]), ("durability_incomplete", "incomplete"))
        result = inbox_drain.drain(self.store)
        self.assertEqual(result["state"], "drained")
        after = tx.inspect_transaction(self.store, txid)
        self.assertEqual((after["committed"], after["durability_state"], after["audit_state"]), (True, "complete", "complete"))
        journal = self.journal(txid)
        self.assertIsNone(journal["current_receipt"])  # nunca se fabrica: lo cubre el recibo `repair`
        kinds = set()
        for path in (self.root / "transactions" / txid / "receipts" / "sha256").glob("*.json"):
            kinds.add(json.loads(path.read_bytes())["kind"])
        self.assertEqual(kinds, {"candidate-data-durable", "repair"})
        self.assertEqual(self.names(self.paths.pending) + self.names(self.paths.inflight), [])

    def test_failing_repair_aborts_without_deleting_marker_or_entries(self) -> None:
        txid = self.crash_at("post_replace_current")
        with mock.patch.object(inbox_close, "repair_durability", side_effect=OSError(5, "io")):
            result = inbox_drain.drain(self.store)
            again = inbox_drain.drain(self.store)  # persiste: es deliberado, no se borra sin durabilidad
        self.assertEqual((result["state"], result["drain_error"]), ("aborted", "transaction_durability_repair_failed"))
        self.assertEqual(again["drain_error"], "transaction_durability_repair_failed")
        self.assertEqual(len(self.names(self.paths.pending)), 3)
        self.assertEqual(self.names(self.paths.inflight), [f"{txid}.json"])
        self.assertEqual(self.names(self.paths.rejected), [])
        self.assertEqual(inbox_drain.drain(self.store)["state"], "drained")  # con E/S sana se resuelve

    def test_predicate_failure_after_repair_aborts_with_the_state_of_the_outcome(self) -> None:
        txid = self.crash_at("post_replace_current")
        with mock.patch.object(inbox_close, "repair_durability", return_value={}):  # no repara nada
            result = inbox_drain.drain(self.store)
        self.assertEqual((result["state"], result["drain_error"]), ("aborted", "transaction_durability_incomplete"))
        self.assertEqual(len(self.names(self.paths.pending)), 3)
        self.assertEqual(self.names(self.paths.inflight), [f"{txid}.json"])

    def test_incomplete_audit_does_not_abort_and_warns(self) -> None:
        txid = self.crash_at("pre_committed_journal")

        def close_without_log(store, identifier):
            journal = dict(inbox_close._usable_journal(store, identifier))
            journal["stage"] = "committed"
            store._write_transaction(identifier, journal)
            return {"closed": True}

        with mock.patch.object(inbox_close, "close_committed_journal", close_without_log):
            result = inbox_drain.drain(self.store)
        self.assertEqual(result["state"], "drained")
        self.assertIn("inbox_audit_incomplete", result["warnings"])
        self.assertEqual(tx.inspect_transaction(self.store, txid)["audit_state"], "incomplete")
        self.assertEqual(self.names(self.paths.pending) + self.names(self.paths.inflight), [])
        self.assertEqual(len(self.store.snapshot().records["facts"]), 3)

    def test_order_is_journal_then_entries_then_marker(self) -> None:
        txid = self.crash_at("pre_committed_journal")
        events: list[str] = []
        real_write = self.store._write_transaction
        real_entries, real_marker = inbox_close.delete_entries, inbox_close.delete_marker

        def write(identifier, body):
            if body.get("stage") == "committed":
                events.append("journal")
            real_write(identifier, body)

        def entries(store, names):
            events.append("entries")
            real_entries(store, names)

        def marker(store, identifier):
            events.append("marker")
            real_marker(store, identifier)

        with mock.patch.object(self.store, "_write_transaction", write), mock.patch.object(
            inbox_close, "delete_entries", entries
        ), mock.patch.object(inbox_close, "delete_marker", marker):
            inbox_drain.drain(self.store)
        self.assertEqual(events, ["journal", "entries", "marker"])
        self.assertEqual(self.names(self.paths.inflight), [])
        self.assertNotIn(f"{txid}.json", self.names(self.paths.inflight))

    def test_missing_or_corrupt_journal_is_rebuilt_from_the_immutable_stage(self) -> None:
        for damage in ("missing", "corrupt"):
            with self.subTest(damage=damage):
                self.tearDown_project()
                txid = self.crash_at("pre_committed_journal")
                stage = next((self.root / "transactions" / txid / "stages" / "sha256").glob("*.json"))
                if damage == "missing":
                    self.journal_path(txid).unlink()
                else:
                    self.journal_path(txid).write_bytes(b"\x00no es json")
                result = inbox_drain.drain(self.store)
                self.assertEqual(result["closed_journals"][0]["branch"], "committed")
                journal = self.journal(txid)
                self.assertEqual(journal["stage"], "committed")
                self.assertEqual(journal["stage_object"], "sha256:" + stage.stem)
                self.assertIsInstance(journal["observed_log"], str)
                self.assertEqual(tx.inspect_transaction(self.store, txid)["audit_state"], "complete")
                self.assertEqual(self.names(self.paths.pending) + self.names(self.paths.inflight), [])


class OtherBranchTests(CloseCase):
    def test_not_committed_deletes_only_the_marker_and_the_same_txid_is_retried(self) -> None:
        txid = self.crash_at("pre_replace_current")
        self.assertFalse(tx.inspect_transaction(self.store, txid)["committed"])
        result = inbox_drain.drain(self.store)
        self.assertEqual(result["closed_journals"], [{"txid": txid, "branch": "not_committed"}])
        self.assertEqual(result["batches"][0]["transaction_id"], txid)  # reintento sobre el journal existente
        self.assertEqual(len(self.store.snapshot().records["facts"]), 3)
        self.assertEqual(self.names(self.paths.pending) + self.names(self.paths.inflight), [])

    def test_marker_without_journal_trace_is_dropped_and_its_entries_are_recommitted(self) -> None:
        txid = self.crash_at("post_marker")
        self.assertTrue(inbox_close.has_no_trace(self.store, txid))
        result = inbox_drain.drain(self.store)
        self.assertEqual(result["closed_journals"], [{"txid": txid, "branch": "no_trace"}])
        self.assertEqual(self.names(self.paths.inflight), [])
        self.assertEqual(result["committed"]["count"], 3)  # y las entradas, que seguían pendientes, se comprometen

    def test_none_with_trace_aborts_and_keeps_everything(self) -> None:
        txid = "7b0f6a62-0f3e-5f6b-8d49-4a1d6a1c9a11"
        for trace in ("journal", "directory"):
            with self.subTest(trace=trace):
                self.tearDown_project()
                name = self.factory.write(f"pendiente {trace}")
                self.paths.inflight.mkdir(parents=True, exist_ok=True)
                (self.paths.inflight / f"{txid}.json").write_bytes(
                    canonical_json({"txid": txid, "base_revision": "sha256:" + "0" * 64, "entries": [name]})
                )
                if trace == "journal":
                    self.journal_path(txid).write_bytes(b"\x00corrupto")
                else:
                    (self.root / "transactions" / txid).mkdir()
                result = inbox_drain.drain(self.store)
                self.assertEqual((result["state"], result["outcome"]), ("aborted", "unknown"))
                self.assertEqual(result["drain_error"], "transaction_evidence_missing_or_invalid")
                self.assertEqual(self.names(self.paths.pending), [name])
                self.assertEqual(self.names(self.paths.inflight), [f"{txid}.json"])
                self.assertEqual(self.names(self.paths.rejected), [])

    def test_other_commands_journals_are_not_touched(self) -> None:
        self.factory.write("uno")
        before = {p.name: p.read_bytes() for p in (self.root / "transactions").glob("*.json")}
        inbox_drain.drain(self.store)
        after = {p.name: p.read_bytes() for p in (self.root / "transactions").glob("*.json")}
        for name, payload in before.items():
            self.assertEqual(after[name], payload)
        self.assertEqual(len(after), len(before) + 1)


class StaleTemporaryTests(CloseCase):
    def test_orphan_atomic_write_temporaries_are_removed_and_real_files_are_kept(self) -> None:
        self.factory.write("uno")
        self.paths.inflight.mkdir(parents=True, exist_ok=True)
        self.paths.rejected.mkdir(parents=True, exist_ok=True)
        stale = "." + "7b0f6a62-0f3e-5f6b-8d49-4a1d6a1c9a11.json." + "a" * 32 + ".tmp"
        (self.paths.inflight / stale).write_bytes(b"x")
        (self.paths.rejected / ("." + "x.json.reason." + "b" * 32 + ".tmp")).write_bytes(b"x")
        (self.paths.rejected / "evidencia.json").write_bytes(b"{}")
        (self.paths.inflight / ".otra-cosa").write_bytes(b"x")
        inbox_drain.drain(self.store)
        self.assertEqual(self.names(self.paths.inflight), [".otra-cosa"])
        self.assertEqual(self.names(self.paths.rejected), ["evidencia.json"])


class MarkerValidationTests(CloseCase):
    def put(self, name: str, payload: bytes) -> None:
        self.paths.inflight.mkdir(parents=True, exist_ok=True)
        (self.paths.inflight / name).write_bytes(payload)

    def test_invalid_marker_aborts_without_deleting_anything(self) -> None:
        txid = "7b0f6a62-0f3e-5f6b-8d49-4a1d6a1c9a11"
        entry = self.factory.write("uno")
        for label, payload in (
            ("junk", b"{no"),
            ("other_txid", canonical_json({"txid": "x", "base_revision": "b", "entries": []})),
            ("traversal", canonical_json({"txid": txid, "base_revision": "sha256:" + "0" * 64, "entries": ["../../x.json"]})),
        ):
            with self.subTest(label=label):
                self.put(f"{txid}.json", payload)
                result = inbox_drain.drain(self.store)
                self.assertEqual((result["state"], result["drain_error"]), ("aborted", "inflight_marker_invalid"))
                self.assertEqual(self.names(self.paths.pending), [entry])
                self.assertEqual(self.names(self.paths.inflight), [f"{txid}.json"])
                (self.paths.inflight / f"{txid}.json").unlink()

    def test_fifo_marker_aborts_without_hanging(self) -> None:
        txid = "7b0f6a62-0f3e-5f6b-8d49-4a1d6a1c9a11"
        self.factory.write("uno")
        self.paths.inflight.mkdir(parents=True, exist_ok=True)
        os.mkfifo(self.paths.inflight / f"{txid}.json")

        def alarm(*_args) -> None:
            raise AssertionError("el vaciado se colgó con un marcador FIFO")

        signal.signal(signal.SIGALRM, alarm)
        signal.alarm(30)
        try:
            result = inbox_drain.drain(self.store)
        finally:
            signal.alarm(0)
        self.assertEqual(result["drain_error"], "inflight_marker_unsafe")
        self.assertEqual(len(self.names(self.paths.pending)), 1)

    def test_transaction_code_does_not_double_the_prefix(self) -> None:
        self.assertEqual(inbox_close.transaction_code("durability_incomplete"), "transaction_durability_incomplete")
        self.assertEqual(
            inbox_close.transaction_code("transaction_candidate_ambiguous"), "transaction_candidate_ambiguous"
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
