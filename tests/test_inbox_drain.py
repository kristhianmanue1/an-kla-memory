"""Vaciado de la bandeja (ADR-0063 D1, B2): pasos 1 a 7, D3, deduplicación, rechazos y ramas del resultado."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest import mock

from an_kla import inbox, inbox_close, inbox_drain, lock_order
from an_kla.canonical import canonical_json
from an_kla.disputes import build_remember_plan as real_plan
from an_kla.store import MemoryStore
from an_kla.store_errors import LockBusyError, StoreError
from an_kla.write_policy import WritePolicyError
from tests.inbox_support import AGENT_ENV, EntryFactory, InboxCase, hold_flock

ROOT = Path(__file__).resolve().parents[1]


class Crash(BaseException):
    """Simula un corte: no es ``Exception``, así que ningún ``except Exception`` del vaciado la absorbe."""


def facts(store: MemoryStore) -> dict[str, dict]:
    return {str(row["id"]): row for row in store.snapshot().records["facts"]}


def validates(result: dict) -> None:
    from jsonschema import Draft202012Validator

    schema = json.loads((ROOT / "an_kla/schemas/inbox-drain-result-v1.schema.json").read_text())
    errors = sorted(Draft202012Validator(schema).iter_errors(result), key=str)
    assert not errors, errors[:3]


class DrainCase(InboxCase):
    def setUp(self) -> None:
        super().setUp()
        self.factory = EntryFactory(self.store)
        self.paths = inbox.inbox_paths(self.store)

    def drain(self, **options) -> dict:
        result = inbox_drain.drain(self.store, **options)
        validates(result)
        return result

    def names(self, directory: Path) -> list[str]:
        return sorted(p.name for p in directory.iterdir()) if directory.exists() else []

    def journal(self, txid: str) -> dict:
        return json.loads((Path(self.store.root) / "transactions" / f"{txid}.json").read_bytes())


class BasicDrainTests(DrainCase):
    def test_drain_commits_entries_in_one_batch_and_empties_the_inbox(self) -> None:
        for index in range(5):
            self.factory.write(f"hecho {index}")
        result = self.drain()
        self.assertEqual((result["state"], result["outcome"], result["queued"]), ("drained", "known", False))
        self.assertEqual(result["committed"]["count"], 5)
        self.assertEqual(len(result["batches"]), 1)
        self.assertEqual(result["batches"][0]["entries"], 5)
        self.assertEqual(self.names(self.paths.pending), [])
        self.assertEqual(self.names(self.paths.inflight), [])
        self.assertEqual(len(facts(self.store)), 5)
        self.assertTrue(self.store.verify()["ok"])
        record = next(iter(facts(self.store).values()))
        self.assertEqual(set(record), {"id", "text", "an_kla_envelope"})

    def test_empty_and_absent_inbox_are_idle_and_create_nothing(self) -> None:
        self.assertEqual(self.drain()["state"], "drained")
        self.assertFalse(self.inbox.exists())
        self.inbox.mkdir()
        result = self.drain()
        self.assertEqual((result["state"], result["batches"]), ("drained", []))

    def test_include_entry_goes_in_the_first_batch_even_when_it_is_the_newest(self) -> None:
        names = [self.factory.write(f"hecho {index}") for index in range(300)]
        result = self.drain(include_entry=names[-1], max_batches=1)
        self.assertEqual(result["state"], "partial")
        self.assertEqual(len(result["batches"]), 1)
        self.assertIn(names[-1], [item["entry"] for item in result["committed"]["entries"]])
        self.assertEqual(result["batches"][0]["entries"], 250)
        self.assertEqual(len(self.names(self.paths.pending)), 50)

    def test_max_batches_and_budget_report_partial_then_drained(self) -> None:
        for index in range(260):
            self.factory.write(f"hecho {index}")
        partial = self.drain(max_batches=1)
        self.assertEqual((partial["state"], len(partial["batches"])), ("partial", 1))
        ticks = iter([0.0, 5.0, 5.0, 5.0, 5.0])
        expired = self.drain(budget_seconds=1.0, clock=lambda: next(ticks))
        self.assertEqual(expired["committed"]["count"], 10)
        self.assertEqual(expired["state"], "drained")
        self.assertEqual(len(facts(self.store)), 260)

    def test_homogeneous_batches_split_by_stream(self) -> None:
        self.factory.write("un hecho")
        self.factory.write("un estado", kind="state")
        self.factory.write("otro hecho")
        result = self.drain()
        streams = sorted((batch["stream"], batch["entries"]) for batch in result["batches"])
        self.assertEqual(streams, [("episodes", 1), ("facts", 2)])
        self.assertEqual(len(self.store.snapshot().records["episodes"]), 1)

    def test_transaction_id_is_uuid5_of_base_and_sorted_digests_in_a_fixed_namespace(self) -> None:
        self.assertEqual(
            inbox_drain.NS_AN_KLA_INBOX, uuid.uuid5(uuid.NAMESPACE_DNS, "inbox.memory.an-kla.v1")
        )
        self.factory.write("uno")
        self.factory.write("dos")
        base = self.store.read_current()
        result = self.drain()
        txid = result["batches"][0]["transaction_id"]
        entries = [inbox_drain.Entry(name="x", data={}, digest=d) for d in ("sha256:" + "b" * 64, "sha256:" + "a" * 64)]
        self.assertEqual(
            inbox_drain.batch_txid(base, entries),
            str(uuid.uuid5(inbox_drain.NS_AN_KLA_INBOX, base + "sha256:" + "a" * 64 + "sha256:" + "b" * 64)),
        )
        self.assertEqual(str(uuid.UUID(txid)), txid)
        self.assertEqual(self.journal(txid)["stage"], "committed")

    def test_same_batch_after_an_unknown_result_reuses_the_transaction_id(self) -> None:
        self.factory.write("uno")
        base = self.store.read_current()
        with mock.patch.object(inbox_drain, "_commit_write_plan_locked", side_effect=RuntimeError("boom")):
            first = self.drain()
        self.assertEqual((first["state"], first["outcome"]), ("aborted", "unknown"))
        second = self.drain()
        self.assertEqual(second["committed"]["count"], 1)
        names = {p.stem for p in (Path(self.store.root) / "transactions").glob("*.json")}
        self.assertIn(second["batches"][0]["transaction_id"], names)
        self.assertEqual(base, self.store.snapshot().manifest["parent"])


class RejectionTests(DrainCase):
    def reasons(self) -> dict[str, dict]:
        return {item["name"]: item for item in inbox.read_status(self.store)["rejected"]["entries"]}

    def test_corrupt_unsafe_and_invalid_entries_go_to_rejected_with_reason(self) -> None:
        good = self.factory.write("bueno")
        corrupt = self.factory.write_raw(b"{no es json")
        schema = self.factory.write_raw(canonical_json({"schema": "otro"}))
        fifo = self.factory.fresh_name()
        os.mkfifo(self.paths.pending / fifo)
        link = self.factory.fresh_name()
        os.symlink(self.project / "fuera", self.paths.pending / link)
        hard = self.factory.write("enlace duro")
        os.link(self.paths.pending / hard, self.project / "otro-nombre")
        folder = self.factory.fresh_name()
        (self.paths.pending / folder).mkdir()
        (self.paths.pending / "nota.txt").write_bytes(b"ignorada")

        def alarm(*_args) -> None:
            raise AssertionError("el vaciado se colgó (¿abrió el FIFO?)")

        signal.signal(signal.SIGALRM, alarm)
        signal.alarm(30)
        try:
            result = self.drain()
        finally:
            signal.alarm(0)
        self.assertEqual(result["state"], "drained")
        self.assertEqual(result["committed"]["count"], 1)
        self.assertEqual(result["committed"]["entries"][0]["entry"], good)
        rejected = {item["entry"]: item["code"] for item in result["rejected"]["entries"]}
        self.assertEqual(
            rejected,
            {corrupt: "inbox_entry_invalid", schema: "inbox_entry_invalid", fifo: "inbox_entry_unsafe",
             link: "inbox_entry_unsafe", hard: "inbox_entry_unsafe"},
        )
        self.assertEqual(self.reasons()[corrupt]["reason"], "inbox_entry_invalid")
        self.assertIn("json", self.reasons()[corrupt]["reason_codes"])
        self.assertEqual(sorted(self.names(self.paths.pending)), sorted([folder, "nota.txt"]))
        self.assertTrue((self.paths.pending / folder).is_dir())
        self.assertEqual(result["metrics"]["ignored"], 2)  # el directorio y `nota.txt`

    def test_tampered_payload_digest_or_envelope_is_invalid(self) -> None:
        data = self.factory.entry("manipulada")
        data["payload_sha256"] = "sha256:" + "0" * 64
        bad_payload = self.factory.write_raw(canonical_json(data))
        data2 = self.factory.entry("manipulada dos")
        data2["envelope"]["kind"] = "state"
        bad_envelope = self.factory.write_raw(canonical_json(data2))
        result = self.drain()
        by_name = {item["entry"]: item for item in result["rejected"]["entries"]}
        self.assertIn("payload_sha256_mismatch", by_name[bad_payload]["reason_codes"])
        self.assertEqual(by_name[bad_envelope]["code"], "inbox_entry_invalid")
        self.assertEqual(result["committed"]["count"], 0)

    def test_same_key_and_payload_commit_once_and_delete_the_rest(self) -> None:
        first = self.factory.write("repetida")
        second = self.factory.write("repetida")
        third = self.factory.write("repetida")
        result = self.drain()
        self.assertEqual(result["committed"]["count"], 1)
        self.assertEqual(result["committed"]["entries"][0]["entry"], first)
        self.assertEqual(sorted(result["duplicates_removed"]["names"]), sorted([second, third]))
        self.assertEqual(self.names(self.paths.pending), [])
        self.assertEqual(len(facts(self.store)), 1)

    def test_same_id_other_payload_is_a_collision(self) -> None:
        key = self.factory.entry("original")["idempotency_key"]
        kept = self.factory.write("original", key=key)
        other = self.factory.entry("otro texto", key=key)
        collided = self.factory.write_raw(canonical_json(other))
        result = self.drain()
        self.assertEqual(result["committed"]["entries"][0]["entry"], kept)
        self.assertEqual(
            [(item["entry"], item["code"]) for item in result["rejected"]["entries"]],
            [(collided, "remember_id_collision")],
        )
        self.assertEqual(self.reasons()[collided]["reason"], "remember_id_collision")
        self.assertEqual(len(facts(self.store)), 1)

    def test_retry_of_a_committed_entry_is_already_committed_and_same_id_other_text_collides(self) -> None:
        self.factory.write("ya está")
        self.drain()
        again = self.factory.write("ya está")
        key = self.factory.entry("ya está")["idempotency_key"]
        clash = self.factory.write_raw(canonical_json(self.factory.entry("distinto", key=key)))
        result = self.drain()
        self.assertEqual(result["committed"]["count"], 0)
        self.assertEqual([item["entry"] for item in result["already_committed"]["entries"]], [again])
        self.assertEqual([item["entry"] for item in result["rejected"]["entries"]], [clash])
        self.assertEqual(len(facts(self.store)), 1)

    def test_policy_skip_goes_to_rejected_with_its_reason_codes(self) -> None:
        skipped = self.factory.write("saltar esta")
        kept = self.factory.write("esta sí")

        def plan(proposal):
            built = real_plan(proposal)
            if "record" in proposal and proposal["record"]["text"] == "saltar esta":
                built["decision"] = {**built["decision"], "decision": "skip", "reason_codes": ["authority_scope_mismatch"]}
            return built

        with mock.patch.object(inbox_drain, "build_remember_plan", side_effect=plan):
            result = self.drain()
        self.assertEqual([item["entry"] for item in result["committed"]["entries"]], [kept])
        self.assertEqual(
            [(item["entry"], item["code"], item["reason_codes"]) for item in result["rejected"]["entries"]],
            [(skipped, "remember_policy_skip", ["authority_scope_mismatch"])],
        )
        self.assertEqual(self.reasons()[skipped]["reason_codes"], ["authority_scope_mismatch"])

    def test_two_supersedes_to_the_same_target_keep_the_oldest(self) -> None:
        self.factory.write("objetivo")
        target = self.drain()["committed"]["entries"][0]["record_id"]
        older = self.factory.write("primero", target_id=target)
        newer = self.factory.write("segundo", target_id=target)
        result = self.drain()
        self.assertEqual([item["entry"] for item in result["committed"]["entries"]], [older])
        self.assertEqual(
            [(item["entry"], item["code"]) for item in result["rejected"]["entries"]],
            [(newer, "supersedes:duplicate_target")],
        )
        self.assertEqual(facts(self.store)[target]["status"], "sustituida")

    def test_missing_target_and_kind_mismatch_are_rejected_by_d3(self) -> None:
        self.factory.write("objetivo")
        target = self.drain()["committed"]["entries"][0]["record_id"]
        missing = self.factory.write("sin objetivo", target_id="f-no-existe")
        mismatch = self.factory.write("estado", kind="state", target_id=target, kind_explicit=True)
        result = self.drain()
        self.assertEqual(
            {item["entry"]: item["code"] for item in result["rejected"]["entries"]},
            {missing: "invalid_supersede_target", mismatch: "remember_kind_mismatch"},
        )
        self.assertEqual(self.reasons()[missing]["reason_codes"], ["target_missing"])
        self.assertEqual(result["committed"]["count"], 0)

    def test_target_in_two_streams_is_ambiguous(self) -> None:
        self.commit_record("dup-id", text="en facts", summary="en facts")
        self.commit_record("dup-id", stream="episodes", text="en episodes", summary="en episodes")
        ambiguous = self.factory.write("dudoso", target_id="dup-id")
        result = self.drain()
        self.assertEqual([(i["entry"], i["code"]) for i in result["rejected"]["entries"]], [(ambiguous, "remember_target_ambiguous")])

    def test_own_target_is_superseded_and_foreign_or_legacy_or_unnamed_is_disputed(self) -> None:
        self.factory.write("mío")
        own = self.drain()["committed"]["entries"][0]["record_id"]
        foreign_factory = self.factory.other_writer(AN_KLA_AGENT_NAME="otro-agente")
        foreign_factory.write("de otro")
        foreign = next(i["record_id"] for i in self.drain()["committed"]["entries"])
        self.commit_record("f-legado", text="legado", summary="legado")
        unnamed = EntryFactory(self.store, {k: v for k, v in AGENT_ENV.items() if k != "AN_KLA_AGENT_NAME"})
        self.factory.write("reemplazo propio", target_id=own)
        self.factory.write("disputa ajena", target_id=foreign)
        self.factory.write("disputa legado", target_id="f-legado")
        unnamed.write("sin nombre sobre lo suyo", target_id=foreign)
        result = self.drain()
        by_text = {facts(self.store)[i["record_id"]]["text"]: i for i in result["committed"]["entries"]}
        self.assertEqual(by_text["reemplazo propio"]["operation"], "supersede")
        self.assertEqual(by_text["reemplazo propio"]["superseded"], own)
        self.assertEqual(facts(self.store)[own]["status"], "sustituida")
        for text, target in (("disputa ajena", foreign), ("disputa legado", "f-legado"), ("sin nombre sobre lo suyo", foreign)):
            self.assertEqual(by_text[text]["operation"], "add")
            self.assertEqual(by_text[text]["disputed"]["target_id"], target)
            self.assertNotEqual(facts(self.store)[target].get("status"), "sustituida")
        self.assertTrue(self.store.verify()["ok"])


class QueuedAndTmpTests(DrainCase):
    def test_write_lock_busy_gives_queued_and_keeps_pending(self) -> None:
        name = self.factory.write("en cola")
        holder = hold_flock(Path(self.store.root) / ".write.lock")
        self.addCleanup(self.release, holder)
        result = self.drain(lock_wait_seconds=0.1)
        self.assertEqual((result["state"], result["queued"], result["committed"]["count"]), ("queued", True, 0))
        self.assertEqual(result["metrics"]["queued_attempts"], 1)
        self.assertEqual(self.names(self.paths.pending), [name])
        self.release(holder)
        self.assertEqual(self.drain()["committed"]["count"], 1)

    def test_orphan_tmp_is_collected_before_asking_for_write_lock(self) -> None:
        self.factory.write("una")
        (self.paths.tmp).mkdir(parents=True, exist_ok=True)
        (self.paths.tmp / "huerfano.json").write_bytes(b"x")
        order: list[str] = []
        real_collect, real_lock = inbox_drain.collect_tmp, MemoryStore.write_lock

        def collect(store):
            order.append("collect")
            return real_collect(store)

        def lock(self_store, *args, **kwargs):
            order.append("write_lock")
            return real_lock(self_store, *args, **kwargs)

        with mock.patch.object(inbox_drain, "collect_tmp", side_effect=collect), mock.patch.object(
            MemoryStore, "write_lock", lock
        ):
            result = self.drain()
        self.assertEqual(order[:2], ["collect", "write_lock"])
        self.assertEqual(result["tmp"], {"state": "collected", "removed": 1, "errors": 0})
        self.assertEqual(self.names(self.paths.tmp), [])

    def test_tmp_of_a_live_enqueuer_is_not_collected(self) -> None:
        self.factory.write("una")
        self.paths.tmp.mkdir(parents=True, exist_ok=True)
        (self.paths.tmp / "en-curso.json").write_bytes(b"x")
        holder = hold_flock(self.paths.lock, "sh")
        self.addCleanup(self.release, holder)
        result = self.drain()
        self.assertEqual(result["tmp"]["state"], "busy")
        self.assertEqual(self.names(self.paths.tmp), ["en-curso.json"])
        self.assertEqual(result["committed"]["count"], 1)


class ResultBranchTests(DrainCase):
    def test_not_committed_with_known_outcome_deletes_marker_and_keeps_pending(self) -> None:
        name = self.factory.write("uno")
        with mock.patch.object(self.store, "_write_segment", side_effect=OSError(5, "io")):
            result = self.drain()
        self.assertEqual((result["state"], result["outcome"]), ("aborted", "known"))
        self.assertEqual(result["drain_error"], "storage_io_failed")
        self.assertEqual(self.names(self.paths.pending), [name])
        self.assertEqual(self.names(self.paths.inflight), [])
        self.assertEqual(self.names(self.paths.rejected), [])
        self.assertEqual(self.drain()["committed"]["count"], 1)

    def test_unknown_outcome_keeps_marker_and_pending_and_the_next_drain_closes_it(self) -> None:
        name = self.factory.write("uno")
        real_replace = self.store._replace_current
        state = {"broken": False}

        def replace(identifier):
            real_replace(identifier)
            state["broken"] = True

        real_read = self.store.read_current

        def read():
            if state["broken"]:
                raise OSError(5, "io")
            return real_read()

        with mock.patch.object(self.store, "_replace_current", replace), mock.patch.object(self.store, "read_current", read):
            result = self.drain()
        state["broken"] = False
        self.assertEqual((result["state"], result["outcome"]), ("aborted", "unknown"))
        self.assertEqual(result["drain_error"], "current_reread_failed")
        self.assertEqual(self.names(self.paths.pending), [name])
        self.assertEqual(len(self.names(self.paths.inflight)), 1)
        self.assertEqual(self.names(self.paths.rejected), [])
        second = self.drain()
        self.assertEqual((second["state"], second["closed_journals"][0]["branch"]), ("drained", "committed"))
        self.assertEqual(len(facts(self.store)), 1)
        self.assertEqual(self.names(self.paths.pending) + self.names(self.paths.inflight), [])
        self.assertTrue(self.store.verify()["ok"])

    def test_known_infrastructure_errors_delete_the_marker_and_abort(self) -> None:
        self.factory.write("uno")
        for exc in (LockBusyError("write_lock_busy"), WritePolicyError("write_plan_base_changed")):
            with self.subTest(exc=str(exc)):
                with mock.patch.object(inbox_drain, "_commit_write_plan_locked", side_effect=exc):
                    result = self.drain()
                self.assertEqual((result["state"], result["outcome"], result["drain_error"]), ("aborted", "known", str(exc)))
                self.assertEqual(self.names(self.paths.inflight), [])
                self.assertEqual(len(self.names(self.paths.pending)), 1)

    def test_unclassified_exception_keeps_the_marker_and_the_next_drain_recovers(self) -> None:
        self.factory.write("uno")
        with mock.patch.object(inbox_drain, "_commit_write_plan_locked", side_effect=RuntimeError("boom")):
            result = self.drain()
        self.assertEqual((result["outcome"], result["drain_error"]), ("unknown", "boom"))
        self.assertEqual(len(self.names(self.paths.inflight)), 1)
        second = self.drain()
        self.assertEqual(second["closed_journals"], [{"txid": mock.ANY, "branch": "no_trace"}])
        self.assertEqual(second["committed"]["count"], 1)

    def test_read_errors_under_the_lock_abort_with_a_code(self) -> None:
        self.factory.write("uno")
        with mock.patch.object(self.store, "snapshot", side_effect=StoreError("integrity_broken")):
            result = self.drain()
        self.assertEqual((result["state"], result["drain_error"]), ("aborted", "integrity_broken"))
        self.assertEqual(self.names(self.paths.rejected), [])


class LastResortTests(DrainCase):
    def force_duplicate_ids(self, *, only_batches: bool = True, bad_text: str | None = None):
        real = self.store._assign_records

        def assign(base, pending):
            rows = pending["facts"]
            if bad_text is not None and any(r["text"] == bad_text for r in rows):
                raise StoreError("duplicate_facts_id")
            if bad_text is None and len(rows) > 1:
                raise StoreError("duplicate_facts_id")
            return real(base, pending)

        return mock.patch.object(self.store, "_assign_records", assign)

    def test_batch_failing_with_unpredicted_duplicate_id_commits_one_by_one_with_a_marker_each(self) -> None:
        for index in range(4):
            self.factory.write(f"hecho {index}")
        markers: list[str] = []
        real_marker = inbox_drain.write_marker

        def marker(store, txid, base, names):
            markers.append(txid)
            return real_marker(store, txid, base, names)

        with self.force_duplicate_ids(), mock.patch.object(inbox_drain, "write_marker", marker):
            result = self.drain()
        self.assertEqual(result["state"], "drained")
        self.assertEqual(result["metrics"]["one_by_one_commits"], 4)
        self.assertEqual([b["mode"] for b in result["batches"]], ["one_by_one"] * 4)
        self.assertEqual(len(markers), 5)  # el del lote y uno por entrada
        self.assertEqual(len(set(markers)), 5)
        self.assertEqual(len(facts(self.store)), 4)
        self.assertEqual(self.names(self.paths.inflight) + self.names(self.paths.pending), [])
        self.assertEqual(self.names(self.paths.rejected), [])
        self.assertTrue(self.store.verify()["ok"])

    def test_an_entry_failing_alone_goes_to_rejected_and_the_rest_commit(self) -> None:
        for index in range(3):
            self.factory.write(f"hecho {index}")
        bad = self.factory.write("hecho malo")
        with self.force_duplicate_ids(bad_text="hecho malo"):
            result = self.drain()
        self.assertEqual([(i["entry"], i["code"]) for i in result["rejected"]["entries"]], [(bad, "duplicate_facts_id")])
        self.assertEqual(result["committed"]["count"], 3)
        self.assertEqual(result["state"], "drained")
        self.assertEqual(self.names(self.paths.inflight) + self.names(self.paths.pending), [])

    def test_batch_level_policy_failure_is_bisected_without_writing(self) -> None:
        for index in range(6):
            self.factory.write(f"hecho {index}")
        real = inbox_drain.build_remember_proposal

        def proposal(base, ops):
            if any(op.record["text"] == "hecho 3" for op in ops) and len(ops) > 1:
                raise WritePolicyError("supersedes:duplicate_target")
            return real(base, ops)

        with mock.patch.object(inbox_drain, "build_remember_proposal", proposal):
            result = self.drain()
        self.assertEqual([i["code"] for i in result["rejected"]["entries"]], ["supersedes:duplicate_target"])
        self.assertEqual(result["committed"]["count"], 5)
        self.assertEqual(result["metrics"]["bisect_probes"], 2)  # prefijos 3 y 4; cota ⌈log₂ 6⌉ = 3
        self.assertEqual(len(result["batches"]), 1)


class ReleaseErrorTests(DrainCase):
    def test_a_failed_unlock_is_reported_as_a_warning_and_the_commit_stands(self) -> None:
        """``lock_result.release_error``: el post-proceso común lo anota tras soltar; no deshace nada."""

        import fcntl

        original = fcntl.flock

        def injected(fd, operation):
            if operation == fcntl.LOCK_UN:
                raise OSError("unlock-EIO")
            return original(fd, operation)

        name = self.factory.write("uno")
        with mock.patch("fcntl.flock", side_effect=injected):
            result = self.drain()
        self.assertEqual(result["state"], "drained")
        self.assertEqual([i["entry"] for i in result["committed"]["entries"]], [name])
        self.assertIn("lock_release_incomplete", result["warnings"])
        self.assertEqual(self.names(self.paths.pending) + self.names(self.paths.inflight), [])
        self.assertEqual(len(facts(self.store)), 1)
        self.assertTrue(self.store.verify()["ok"])


class ErrorCodeTests(unittest.TestCase):
    def test_error_code_never_echoes_a_message_with_a_path_or_prose(self) -> None:
        self.assertEqual(inbox_drain.error_code(RuntimeError("/Users/x/store: fallo grave")), "runtimeerror")
        self.assertEqual(inbox_drain.error_code(OSError(5, "io", "/ruta/secreta")), "storage_io_failed")
        self.assertEqual(inbox_drain.error_code(StoreError("duplicate_facts_id")), "duplicate_facts_id")


class LockOrderTests(DrainCase):
    def test_drain_is_refused_with_identity_or_write_lock_held(self) -> None:
        self.factory.write("uno")
        with self.store.write_lock():
            with self.assertRaises(lock_order.LockOrderError):
                inbox_drain.drain(self.store)
        with lock_order.holding(lock_order.IDENTITY):
            with self.assertRaises(lock_order.LockOrderError):
                inbox_drain.drain(self.store)
        self.assertEqual(len(self.names(self.paths.pending)), 1)

    def test_no_drain_path_asks_for_the_inbox_lock_while_holding_a_later_lock(self) -> None:
        """Criterio 9: instrumenta ``require_inbox_allowed`` en un vaciado con commit, rechazos y paso 0."""

        seen: list[tuple[str, ...]] = []
        real = lock_order.require_inbox_allowed

        def spy(store=None):
            seen.append(lock_order.held())
            return real(store)

        self.factory.write("uno")
        self.factory.write_raw(b"{roto")
        with mock.patch.object(lock_order, "require_inbox_allowed", spy):
            self.drain()
            self.factory.write("dos")
            self.drain()
        self.assertTrue(seen)
        for held in seen:
            self.assertFalse({lock_order.IDENTITY, lock_order.WRITE} & set(held), held)

    def test_the_drain_never_holds_the_inbox_lock_while_it_holds_write_lock(self) -> None:
        held_inside: list[tuple[str, ...]] = []
        real = inbox_drain._locked_attempt

        def spy(*args, **kwargs):
            held_inside.append(lock_order.held())
            return real(*args, **kwargs)

        self.factory.write("uno")
        with mock.patch.object(inbox_drain, "_locked_attempt", spy):
            self.drain()
        self.assertEqual(held_inside, [(lock_order.WRITE,)])


class Step7OrderTests(DrainCase):
    """R1-02: en el paso 7 se borran las entradas y DESPUÉS el marcador (ADR: orden obligatorio)."""

    def spy(self):
        events: list[str] = []
        real_entries, real_marker = inbox_drain.delete_entries, inbox_drain.delete_marker

        def entries(store, names):
            events.append("entries")
            real_entries(store, names)

        def marker(store, txid):
            events.append("marker")
            real_marker(store, txid)

        return events, mock.patch.multiple(inbox_drain, delete_entries=entries, delete_marker=marker)

    def test_batch_deletes_entries_then_marker(self) -> None:
        for index in range(3):
            self.factory.write(f"hecho {index}")
        events, patch = self.spy()
        with patch:
            self.drain()
        self.assertEqual(events, ["entries", "marker"])

    def test_last_resort_deletes_entries_then_marker_for_each_commit(self) -> None:
        for index in range(3):
            self.factory.write(f"hecho {index}")
        real = self.store._assign_records

        def assign(base, pending):
            if len(pending["facts"]) > 1:
                raise StoreError("duplicate_facts_id")
            return real(base, pending)

        events, patch = self.spy()
        with patch, mock.patch.object(self.store, "_assign_records", assign):
            self.drain()
        self.assertEqual(events, ["marker"] + ["entries", "marker"] * 3)  # el lote fallido sólo borra su marcador

    def test_replay_with_incomplete_durability_goes_through_settle_committed(self) -> None:
        """R1-09: la rama de replay no borra sin el predicado de durabilidad completa."""

        from an_kla.write_commit import _LockedCommit

        self.factory.write("uno")
        for state, settled in (("durability_incomplete", True), ("committed", False)):
            with self.subTest(state=state):
                final = {"committed": True, "revision": "sha256:" + "a" * 64, "outcome": {"state": state}}
                with mock.patch.object(inbox_drain, "_commit_write_plan_locked", return_value=_LockedCommit(final=final)), \
                        mock.patch.object(inbox_drain, "settle_committed") as settle, \
                        mock.patch.object(inbox_drain, "delete_entries") as delete:
                    result = self.drain(max_batches=1)  # el borrado simulado deja la entrada: un solo lote
                self.assertEqual(settle.called, settled)
                self.assertEqual(delete.called, not settled)
                self.assertEqual(result["committed"]["count"], 1)
                for path in list(self.paths.inflight.iterdir()):
                    path.unlink()


class IgnoredTests(DrainCase):
    """R1-10: «entrada» = nombre que casa y NO es directorio; `ignored` cuenta directorios y nombres que no casan."""

    def test_ignored_counts_directories_and_foreign_names_whatever_entry_names_does(self) -> None:
        real = inbox.entry_names
        self.factory.write("uno")
        folder = self.factory.fresh_name()
        (self.paths.pending / folder).mkdir()
        (self.paths.pending / "nota.txt").write_bytes(b"x")
        self.paths.inflight.mkdir(parents=True, exist_ok=True)
        (self.paths.inflight / "no-es-marcador").write_bytes(b"x")
        without_dirs = lambda store: [n for n in real(store) if not (self.paths.pending / n).is_dir()]  # noqa: E731 - semántica de B4
        for label, lister in (("cuenta directorios (B1)", real), ("excluye directorios (B4)", without_dirs)):
            with self.subTest(label=label), mock.patch.object(inbox, "entry_names", lister):
                self.factory.write(f"otro {label}")
                result = self.drain()
                self.assertEqual(result["state"], "drained")
                self.assertEqual(result["metrics"]["ignored"], 3)
                self.assertTrue((self.paths.pending / folder).is_dir())


def policy_skip(*texts: str):
    """Parche de `build_remember_plan`: la política dice `skip` para los records con esos textos."""

    def plan(proposal):
        built = real_plan(proposal)
        if "record" in proposal and proposal["record"]["text"] in texts:
            built["decision"] = {**built["decision"], "decision": "skip", "reason_codes": ["authority_scope_mismatch"]}
        return built

    return mock.patch.object(inbox_drain, "build_remember_plan", side_effect=plan)


class Round2Tests(DrainCase):
    def committed_target(self) -> str:
        self.factory.write("objetivo")
        return self.drain()["committed"]["entries"][0]["record_id"]

    def test_r2_01_a_policy_rejected_supersede_never_blocks_a_valid_one(self) -> None:
        target = self.committed_target()
        skipped = self.factory.write("sustituye A", target_id=target)
        valid = self.factory.write("sustituye B", target_id=target)
        with policy_skip("sustituye A"):
            result = self.drain()
        self.assertEqual([i["entry"] for i in result["committed"]["entries"]], [valid])
        self.assertEqual([(i["entry"], i["code"]) for i in result["rejected"]["entries"]], [(skipped, "remember_policy_skip")])
        self.assertEqual(facts(self.store)[target]["status"], "sustituida")

    def test_r2_01_among_those_that_passed_the_oldest_wins(self) -> None:
        target = self.committed_target()
        older = self.factory.write("uno", target_id=target)
        newer = self.factory.write("dos", target_id=target)
        result = self.drain()
        self.assertEqual([i["entry"] for i in result["committed"]["entries"]], [older])
        self.assertEqual([(i["entry"], i["code"]) for i in result["rejected"]["entries"]], [(newer, "supersedes:duplicate_target")])

    def test_r2_02_unsafe_names_are_rejected_with_any_entry_names_semantics(self) -> None:
        real = inbox.entry_names
        only_regular = lambda store: [n for n in real(store) if (self.paths.pending / n).is_file() and not (self.paths.pending / n).is_symlink()]  # noqa: E731
        no_dirs = lambda store: [n for n in real(store) if not (self.paths.pending / n).is_dir()]  # noqa: E731
        for label, lister in (("B1", real), ("sin directorios", no_dirs), ("sólo regulares", only_regular), ("vacío", lambda store: [])):
            with self.subTest(label=label), mock.patch.object(inbox, "entry_names", lister), \
                    mock.patch.object(inbox_drain, "entry_names", lister, create=True):
                self.tearDown_project()
                fifo = self.factory.fresh_name()
                self.paths.pending.mkdir(parents=True, exist_ok=True)
                os.mkfifo(self.paths.pending / fifo)
                link = self.factory.fresh_name()
                os.symlink(self.project / "fuera", self.paths.pending / link)
                hard = self.factory.write("enlace duro")
                os.link(self.paths.pending / hard, self.project / "otro-nombre")
                result = self.drain()
                self.assertEqual(
                    {i["entry"]: i["code"] for i in result["rejected"]["entries"]},
                    {fifo: "inbox_entry_unsafe", link: "inbox_entry_unsafe", hard: "inbox_entry_unsafe"},
                )
                self.assertEqual(self.names(self.paths.pending), [])

    def tearDown_project(self) -> None:
        import shutil

        shutil.rmtree(self.project / ".an-kla", ignore_errors=True)
        shutil.rmtree(self.project / "otro-nombre", ignore_errors=True)
        (self.project / "otro-nombre").unlink(missing_ok=True)
        self.store = MemoryStore(self.project)
        self.store.initialize()
        self.factory = EntryFactory(self.store)
        self.paths = inbox.inbox_paths(self.store)

    def test_r2_03_twin_of_a_rejected_entry_is_rejected_not_removed(self) -> None:
        first = self.factory.write("gemela")
        twin = self.factory.write("gemela")
        with policy_skip("gemela"):
            result = self.drain()
        self.assertEqual(
            sorted((i["entry"], i["code"]) for i in result["rejected"]["entries"]),
            sorted([(first, "remember_policy_skip"), (twin, "remember_policy_skip")]),
        )
        self.assertEqual(result["duplicates_removed"], {"count": 0, "names": [], "truncated": False})
        self.assertEqual(len(self.names(self.paths.rejected)), 4)  # dos entradas + dos .reason
        self.assertEqual((self.names(self.paths.pending), len(facts(self.store))), ([], 0))

    def test_r2_03_twin_of_a_committed_entry_is_removed_only_after_the_commit(self) -> None:
        first = self.factory.write("gemela")
        twin = self.factory.write("gemela")
        result = self.drain()
        self.assertEqual([i["entry"] for i in result["committed"]["entries"]], [first])
        self.assertEqual(result["duplicates_removed"]["names"], [twin])
        self.assertEqual(result["rejected"]["count"], 0)

    def test_r2_03_twin_stays_pending_when_the_conserved_one_is_not_committed(self) -> None:
        first = self.factory.write("gemela")
        twin = self.factory.write("gemela")
        with mock.patch.object(self.store, "_write_segment", side_effect=OSError(5, "io")):
            result = self.drain()
        self.assertEqual(result["state"], "aborted")
        self.assertEqual(self.names(self.paths.pending), sorted([first, twin]))
        self.assertEqual(result["duplicates_removed"]["count"], 0)
        again = self.drain()
        self.assertEqual((again["committed"]["count"], again["duplicates_removed"]["names"]), (1, [twin]))

    def test_r2_04_pending_with_only_a_directory_named_like_an_entry_is_idle(self) -> None:
        folder = self.factory.fresh_name()
        self.paths.pending.mkdir(parents=True, exist_ok=True)
        (self.paths.pending / folder).mkdir()
        with mock.patch.object(MemoryStore, "write_lock", side_effect=AssertionError("no debía pedir write_lock")):
            result = self.drain()
        self.assertEqual((result["state"], result["metrics"]["attempts"], result["metrics"]["ignored"]), ("drained", 1, 1))
        self.assertEqual(result["batches"], [])
        self.assertTrue((self.paths.pending / folder).is_dir())

    def test_r2_05_duplicates_removed_is_capped_with_truncated(self) -> None:
        run = inbox_drain.Run()
        run.duplicates_removed = [f"{n}.json" for n in range(inbox_drain.MAX_LISTED + 5)]
        body = inbox_drain._result(run, "drained", "present")
        self.assertEqual(body["duplicates_removed"]["count"], inbox_drain.MAX_LISTED + 5)
        self.assertEqual(len(body["duplicates_removed"]["names"]), inbox_drain.MAX_LISTED)
        self.assertTrue(body["duplicates_removed"]["truncated"])
        validates(body)
        run.duplicates_removed = ["a.json"]
        self.assertFalse(inbox_drain._result(run, "drained", "present")["duplicates_removed"]["truncated"])


class DrainExitCodeTests(DrainCase):
    """R1-01: rc 3 (`inbox_drain_outcome_not_firm`) con `aborted`/`outcome != known`; 0 en el resto."""

    def cli(self, *args: str) -> subprocess.CompletedProcess:
        from tests.inbox_support import GIT_ENV

        return subprocess.run(
            [sys.executable, "-m", "an_kla", "--project-root", str(self.project), *args],
            cwd=ROOT, capture_output=True, text=True,
            env={**os.environ, **GIT_ENV, "AN_KLA_NO_UPDATE_CHECK": "1", "PYTHONDONTWRITEBYTECODE": "1"},
        )

    def test_matrix_function_by_state(self) -> None:
        from argparse import Namespace

        from an_kla.__main__ import pending_outcome_reason

        args = Namespace(command="inbox", inbox_command="drain")
        for result, expected in (
            ({"state": "aborted", "outcome": "known"}, "inbox_drain_outcome_not_firm"),
            ({"state": "aborted", "outcome": "unknown"}, "inbox_drain_outcome_not_firm"),
            ({"state": "drained", "outcome": "unknown"}, "inbox_drain_outcome_not_firm"),
            ({"state": "drained", "outcome": "known"}, None),
            ({"state": "queued", "outcome": "known"}, None),
            ({"state": "partial", "outcome": "known"}, None),
        ):
            with self.subTest(result=result):
                self.assertEqual(pending_outcome_reason(args, result), expected)
        self.assertIsNone(pending_outcome_reason(Namespace(command="inbox", inbox_command="status"), {"state": "aborted"}))

    def test_cli_aborted_is_rc3_with_full_payload_and_empty_stderr(self) -> None:
        self.factory.write("uno")
        txid = "7b0f6a62-0f3e-5f6b-8d49-4a1d6a1c9a11"
        self.paths.inflight.mkdir(parents=True, exist_ok=True)
        os.mkfifo(self.paths.inflight / f"{txid}.json")
        done = self.cli("inbox", "drain")
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertEqual(done.stderr, "")
        body = json.loads(done.stdout)
        validates(body)
        self.assertEqual((body["state"], body["drain_error"]), ("aborted", "inflight_marker_unsafe"))

    def test_cli_drained_queued_and_partial_are_rc0(self) -> None:
        self.factory.write("uno")
        holder = hold_flock(Path(self.store.root) / ".write.lock")
        self.addCleanup(self.release, holder)
        queued = self.cli("inbox", "drain")
        self.assertEqual((queued.returncode, json.loads(queued.stdout)["state"]), (0, "queued"))
        self.release(holder)
        drained = self.cli("inbox", "drain")
        self.assertEqual((drained.returncode, json.loads(drained.stdout)["state"]), (0, "drained"))
        for index in range(3):
            self.factory.write(f"otro {index}")
        partial = self.cli("inbox", "drain", "--budget-seconds", "0.000001")
        self.assertEqual(partial.returncode, 0, partial.stderr)

    def test_capabilities_list_the_case(self) -> None:
        pending = json.loads(self.cli("capabilities").stdout)["cli_error_surface"]["pending_outcome"]
        self.assertIn("inbox drain", pending["cases"])


class CliTests(unittest.TestCase):
    def run_cli(self, project: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "an_kla", "--project-root", str(project), *args],
            cwd=ROOT, capture_output=True, text=True,
            env={**os.environ, "AN_KLA_NO_UPDATE_CHECK": "1", "PYTHONDONTWRITEBYTECODE": "1"},
        )

    def test_absent_inbox_creates_nothing_and_budget_is_validated(self) -> None:
        with tempfile.TemporaryDirectory(prefix="drain-cli-") as temp:
            project = Path(temp).resolve()
            done = self.run_cli(project, "inbox", "drain")
            self.assertEqual(done.returncode, 0, done.stderr)
            body = json.loads(done.stdout)
            validates(body)
            self.assertEqual((body["state"], body["inbox"]), ("drained", "absent"))
            self.assertEqual(list(project.iterdir()), [])
            bad = self.run_cli(project, "inbox", "drain", "--budget-seconds", "0")
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn("invalid_budget_seconds", bad.stderr)

    def test_drain_by_cli_commits_and_registers_the_schema(self) -> None:
        names = {item["name"] for item in json.loads(self.run_cli(ROOT, "schema", "list").stdout)["schemas"]}
        self.assertIn("inbox-drain-result-v1", names)
        storage = json.loads(self.run_cli(ROOT, "capabilities").stdout)["storage"]
        self.assertEqual(storage["inbox"]["drain"]["schema"], "an-kla/inbox-drain-result-v1")
        self.assertEqual(
            (ROOT / "docs/schemas/inbox-drain-result-v1.schema.json").read_bytes(),
            (ROOT / "an_kla/schemas/inbox-drain-result-v1.schema.json").read_bytes(),
        )
        self.assertIn("--budget-seconds", self.run_cli(ROOT, "inbox", "drain", "--help").stdout)


if __name__ == "__main__":
    unittest.main()
