"""`inbox requeue` (ADR-0068, #234): reencolar los rechazos de formato que esta versión ya entiende."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from an_kla import inbox, inbox_drain, inbox_rejected
from an_kla.canonical import canonical_json
from an_kla.inbox_entries import INVALID
from an_kla.inbox_rejected import requeue
from an_kla.remember import RememberError, error_result
from an_kla.store import MemoryStore
from tests.inbox_support import AGENT_ENV, HOLDER
from tests.remember_support import cli
from tests.rejected_support import POLICY, RejectedCase, validates


class Crash(Exception):
    """El corte inyectado entre los dos pasos de ``requeue``."""


def requeued(store, *names, **options) -> dict:
    result = requeue(store, names, **options)
    validates(result, "inbox-requeue-result-v1")
    return result


class RequeueTests(RejectedCase):
    def test_rollback_v1_v2_v3_rejected_by_an_older_drain_are_recovered_without_loss(self) -> None:
        """La vuelta atrás real: rechazadas con `inbox_entry_invalid`, `requeue` + `drain` las escribe."""

        v3 = self.factory.entry("hecho v3")
        v3["schema"] = inbox.ENTRY_SCHEMA_V3
        v3_name = self.factory.name_for(v3)
        (self.paths.pending / v3_name).write_bytes(canonical_json(v3))
        self.reject_pending(v3_name)
        self.reject_valid("hecho v1")
        self.reject_valid("estado v2", kind="state", slot="notas")
        self.assertEqual(inbox.read_status(self.store)["rejected"]["count"], 3)
        result = requeued(self.store, all_format=True)
        self.assertEqual([item["result"] for item in result["requeued"]], ["requeued"] * 3)
        self.assertEqual((result["skipped"], result["remaining"]), ([], 0))
        self.assertEqual(self.names(self.paths.rejected), [])
        report = inbox_drain.drain(self.store)
        self.assertEqual((report["state"], report["committed"]["count"]), ("drained", 3))
        status = inbox.read_status(self.store)
        self.assertEqual((status["rejected"]["count"], status["pending"]["count"]), (0, 0))
        self.assertTrue(self.store.verify()["ok"])

    def test_other_candidates_are_reported_and_never_touched(self) -> None:
        policy = self.reject_valid("un estado como hecho", POLICY)
        corrupt = self.reject_pending(self.factory.write_raw(b"{no es json"))
        unsafe = self.reject_unsafe()
        before = self.names(self.paths.rejected)
        result = requeued(self.store, all_format=True)
        self.assertEqual(result["requeued"], [])
        by_name = {item["rejected_name"]: item for item in result["skipped"]}
        self.assertEqual(by_name[policy]["result"], "not_requeueable_policy")
        self.assertEqual(by_name[policy]["code"], POLICY)
        self.assertEqual(by_name[corrupt]["result"], "still_invalid")
        self.assertEqual(by_name[unsafe]["result"], "not_requeueable_unsafe")
        self.assertEqual(by_name[unsafe]["code"], "inbox_entry_unsafe")
        self.assertEqual(self.names(self.paths.rejected), before)
        self.assertEqual(self.names(self.paths.pending), [])
        for item in result["skipped"]:
            self.assertNotIn("pending_name", item)
            self.assertRegex(item["sha256"], r"^sha256:[0-9a-f]{64}$")

    def test_a_suffixed_rejection_returns_with_its_canonical_name(self) -> None:
        data = self.factory.entry("con sufijo")
        canonical = self.factory.name_for(data)
        self.put(data, name=canonical + ".1")
        result = requeued(self.store, canonical + ".1")
        self.assertEqual(result["requeued"][0]["pending_name"], canonical)
        self.assertEqual(result["requeued"][0]["rejected_name"], canonical + ".1")
        self.assertEqual(self.names(self.paths.pending), [canonical])
        self.assertEqual(self.names(self.paths.rejected), [])

    def test_a_name_taken_in_pending_gets_a_new_name_and_nothing_is_replaced(self) -> None:
        data = self.factory.entry("colisión")
        canonical = self.factory.name_for(data)
        taken = canonical_json(self.factory.entry("ya estaba en pending", key=data["idempotency_key"]))
        (self.paths.pending / canonical).write_bytes(taken)
        self.put(data, name=canonical + ".1")
        result = requeued(self.store, all_format=True)
        new_name = result["requeued"][0]["pending_name"]
        self.assertNotEqual(new_name, canonical)
        self.assertTrue(inbox.is_entry_name(new_name))
        self.assertEqual(new_name.split("-")[2], canonical.split("-")[2])  # mismo prefijo de clave
        self.assertEqual((self.paths.pending / canonical).read_bytes(), taken)
        self.assertEqual(sorted(self.names(self.paths.pending)), sorted([canonical, new_name]))

    def test_a_cut_between_the_two_steps_loses_nothing_and_leaves_a_known_name(self) -> None:
        name = self.reject_valid("corte entre pasos")
        real_unlink = os.unlink

        def unlink(path, *args, **kwargs):
            if str(path).endswith(".reason"):
                raise Crash()
            return real_unlink(path, *args, **kwargs)

        with mock.patch.object(os, "unlink", unlink):
            with self.assertRaises(Crash):
                requeue(self.store, [], all_format=True)
        self.assertEqual(self.names(self.paths.pending), [name])  # una sola vez, en pending
        self.assertEqual(self.names(self.paths.rejected), [name + ".reason"])  # el motivo sigue, con nombre conocido
        for known in self.names(self.paths.rejected):
            self.assertIsNotNone(inbox_rejected.base_of(known))
        status = inbox.read_status(self.store)
        self.assertEqual(status["rejected"]["count"], 1)
        self.assertEqual(status["rejected"]["entries"][0]["reason"], INVALID)
        again = requeued(self.store, all_format=True)
        self.assertEqual(again["requeued"], [])
        self.assertEqual([(i["rejected_name"], i["result"]) for i in again["skipped"]], [(name + ".reason", "orphan_reason")])
        self.assertEqual(self.names(self.paths.rejected), [name + ".reason"])  # no se borra el huérfano
        report = inbox_drain.drain(self.store)
        self.assertEqual(report["committed"]["count"], 1)
        self.assertEqual(self.names(self.paths.pending), [])

    def test_batch_counts_only_changes(self) -> None:
        for index in range(80):
            self.put_valid(f"hecho {index}")
        first = requeued(self.store, all_format=True)
        self.assertEqual((len(first["requeued"]), first["remaining"]), (50, 30))
        second = requeued(self.store, all_format=True)
        self.assertEqual((len(second["requeued"]), second["remaining"]), (30, 0))
        self.assertEqual(len(self.names(self.paths.pending)), 80)

    def test_policy_rejections_do_not_consume_the_batch(self) -> None:
        for index in range(300):
            self.put_valid(f"política {index}", POLICY)
        for index in range(10):
            self.put_valid(f"formato {index}")
        result = requeued(self.store, all_format=True)
        self.assertEqual((len(result["requeued"]), len(result["skipped"]), result["remaining"]), (10, 300, 0))

    def test_traversal_is_in_byte_order(self) -> None:
        names = [self.put_valid(f"hecho {index}") for index in range(5)]
        result = requeued(self.store, all_format=True)
        self.assertEqual([item["rejected_name"] for item in result["requeued"]], sorted(names))

    def test_input_errors(self) -> None:
        for bad in ("../x", "/tmp/x.json", "x", "pending/1-1-0000000000000001-00000001.json", ".."):
            with self.assertRaises(inbox.InboxError) as caught:
                requeue(self.store, [bad])
            self.assertEqual(caught.exception.code, "inbox_entry_name_invalid", bad)
        with self.assertRaises(inbox.InboxError) as caught:
            requeue(self.store, [])
        self.assertEqual(caught.exception.code, "inbox_requeue_target_missing")
        with self.assertRaises(inbox.InboxError) as caught:
            requeue(self.store, [self.factory.fresh_name()])
        self.assertEqual(caught.exception.code, "inbox_requeue_target_missing")

    def test_without_an_inbox_nothing_is_created(self) -> None:
        self.assertEqual(requeued(self.store, all_format=True)["requeued"], [])
        import shutil

        shutil.rmtree(self.inbox)
        self.assertEqual(requeued(self.store, all_format=True), {
            "schema": "an-kla/inbox-requeue-result-v1", "untrusted_memory_data": True,
            "requeued": [], "skipped": [], "remaining": 0,
        })
        self.assertFalse(self.inbox.exists())

    def test_requeue_is_idempotent(self) -> None:
        self.reject_valid("una vez")
        self.assertEqual(len(requeued(self.store, all_format=True)["requeued"]), 1)
        self.assertEqual(requeued(self.store, all_format=True)["requeued"], [])


class RequeueLocksTests(RejectedCase):
    def hold(self, path: Path, mode: str = "ex") -> subprocess.Popen:
        child = subprocess.Popen(
            [sys.executable, "-I", "-c", HOLDER, str(path), mode],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        )
        self.addCleanup(self.release, child)
        self.assertEqual(child.stdout.readline().strip(), "ready")
        return child

    def test_write_lock_busy_is_fast_retryable_and_releases_the_inbox(self) -> None:
        self.reject_valid("espera corta")
        child = self.hold(Path(self.store.root) / ".write.lock")
        started = time.monotonic()
        with self.assertRaises(RememberError) as caught:
            requeue(self.store, [], all_format=True)
        self.assertLess(time.monotonic() - started, 1.5)
        error = error_result(caught.exception)
        validates(error, "remember-error-v1")
        self.assertEqual((error["code"], error["retryable"]), ("write_lock_busy", True))
        # La bandeja quedó libre: un `remember` concurrente encola sin `inbox_busy` ni `identity_lock_busy`.
        queued = inbox.enqueue(self.store, "encola mientras tanto", env=AGENT_ENV, wait_seconds=0.2, identity_wait_seconds=0.2)
        self.assertEqual(queued["state"], "queued")
        self.assertEqual(len(self.names(self.paths.rejected)), 2)  # el rechazo sigue donde estaba
        self.release(child)
        self.assertEqual(len(requeued(self.store, all_format=True)["requeued"]), 1)

    def test_a_simulated_relocation_gives_identity_lock_busy(self) -> None:
        self.reject_valid("durante una reubicación")
        child = self.hold(Path(self.store.store_root) / ".identity.lock")
        with self.assertRaises(RememberError) as caught:
            requeue(self.store, [], all_format=True)
        error = error_result(caught.exception)
        validates(error, "remember-error-v1")
        self.assertEqual((error["code"], error["retryable"]), ("identity_lock_busy", True))
        self.assertEqual(len(self.names(self.paths.rejected)), 2)
        self.release(child)

    def test_a_shared_identity_holder_does_not_stop_it(self) -> None:
        self.reject_valid("con un compartido ajeno")
        self.hold(Path(self.store.store_root) / ".identity.lock", "sh")
        self.assertEqual(len(requeued(self.store, all_format=True)["requeued"]), 1)

    def test_cli_busy_answers_rc_3_with_the_error_and_no_changes(self) -> None:
        self.reject_valid("por la CLI")
        child = self.hold(Path(self.store.root) / ".write.lock")
        done = cli(self.project, "inbox", "requeue", "--all-format")
        self.assertEqual(done.returncode, 3, (done.stdout, done.stderr))
        error = json.loads(done.stdout)
        self.assertEqual((error["schema"], error["code"], error["retryable"]), ("an-kla/remember-error-v1", "write_lock_busy", True))
        self.assertEqual(done.stderr, "")
        self.release(child)
        done = cli(self.project, "inbox", "requeue", "--all-format")
        self.assertEqual(done.returncode, 0, (done.stdout, done.stderr))
        result = json.loads(done.stdout)
        validates(result, "inbox-requeue-result-v1")
        self.assertEqual(len(result["requeued"]), 1)
        self.assertNotIn(str(self.project), done.stdout)

    def test_a_drain_that_rejects_while_requeue_runs_loses_and_duplicates_nothing(self) -> None:
        for index in range(3):
            self.put_valid(f"reencolable {index}")
        entered = threading.Event()
        real = inbox_rejected._requeue_one

        def slow(*args, **kwargs):
            entered.set()
            time.sleep(0.25)
            return real(*args, **kwargs)

        outcome: dict = {}

        def drain_rejecting() -> None:
            entered.wait(10)
            self.factory.write_raw(b"{corrupta")
            for _ in range(100):
                report = inbox_drain.drain(MemoryStore(self.project))  # un store propio: el testigo de candado es por instancia
                if report["state"] != "queued":
                    break
                time.sleep(0.1)
            outcome["drain"] = report

        thread = threading.Thread(target=drain_rejecting)
        thread.start()
        with mock.patch.object(inbox_rejected, "_requeue_one", slow):
            requeued(self.store, all_format=True)
        thread.join(60)
        self.assertFalse(thread.is_alive())
        final = inbox_drain.drain(self.store)  # lo que quedó encolado tras el turno de cada uno
        self.assertIn(final["state"], ("drained", "partial"))
        rejected = [name for name in self.names(self.paths.rejected) if not name.endswith(".reason")]
        self.assertEqual(len(rejected), 1)  # sólo la corrupta, una vez
        reason = self.json_file(self.paths.rejected / (rejected[0] + ".reason"))
        self.assertEqual(reason["code"], INVALID)
        self.assertEqual(self.names(self.paths.pending), [])
        self.assertEqual(inbox.read_status(self.store)["rejected"]["count"], 1)
        self.assertTrue(self.store.verify()["ok"])
        self.assertEqual(len(self.store.snapshot().records["facts"]), 3)


if __name__ == "__main__":
    unittest.main()
