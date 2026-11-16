"""Arreglos de la ronda 1 de B5 (R1-01, R1-02, R1-04, R1-05, R1-06, R1-07, R1-08)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

from an_kla import inbox, inbox_drain, remember as remember_module
from an_kla.store import MemoryStore
from tests.inbox_support import AGENT_ENV, EntryFactory, InboxCase, hold_flock
from tests.remember_support import cli, remember
from tests.test_remember import validate

OTHER = {"AN_KLA_AGENT_NAME": "otro-agente"}


class RetryAlreadyCommittedTests(InboxCase):
    """R1-01: el reintento de un `--supersedes` ya comprometido es `committed` + `already_committed`, sin `rejected/`."""

    def queue_then_commit_elsewhere(self, text: str, target: str, env: dict | None = None) -> dict:
        holder = hold_flock(Path(self.store.root) / ".write.lock")
        try:
            rc, queued = remember(self.project, text, "--supersedes", target, env=env)
        finally:
            InboxCase.release(holder)
        self.assertEqual((rc, queued["state"]), (0, "queued"), queued)
        drained = inbox_drain.drain(self.store)  # otro vaciador compromete la entrada en cola
        self.assertEqual(drained["committed"]["count"], 1, drained)
        return queued

    def assert_retry_is_already_committed(self, text: str, target: str, env: dict | None = None) -> dict:
        rc, retry = remember(self.project, text, "--supersedes", target, env=env)
        validate(retry)
        self.assertEqual((rc, retry["state"], retry.get("already_committed")), (0, "committed", True), retry)
        self.assertEqual(retry["rejected"]["count"], 0)
        self.assertEqual(inbox.read_status(self.store)["rejected"]["count"], 0)  # sin evidencia falsa en rejected/
        self.assertEqual(inbox.entry_names(self.store), [])
        return retry

    def test_own_supersede_retried_after_queued(self) -> None:
        _, first = remember(self.project, "versión uno")
        queued = self.queue_then_commit_elsewhere("versión dos", first["record_id"])
        retry = self.assert_retry_is_already_committed("versión dos", first["record_id"])
        self.assertTrue(retry["record_id"])
        texts = [r["text"] for r in MemoryStore(self.project).snapshot().records["facts"]]
        self.assertEqual(texts.count("versión dos"), 1)
        self.assertEqual(queued["state"], "queued")

    def test_foreign_dispute_retried_after_queued(self) -> None:
        _, theirs = remember(self.project, "hecho ajeno", env=OTHER)
        self.queue_then_commit_elsewhere("lo disputo", theirs["record_id"])
        self.assert_retry_is_already_committed("lo disputo", theirs["record_id"])
        texts = [r["text"] for r in MemoryStore(self.project).snapshot().records["facts"]]
        self.assertEqual(texts.count("lo disputo"), 1)

    def test_own_supersede_retried_after_an_unknown_outcome(self) -> None:
        _, first = remember(self.project, "versión uno")
        real_replace, broken = self.store._replace_current, {"on": False}
        real_read = self.store.read_current

        def replace(identifier):
            real_replace(identifier)
            broken["on"] = True

        def read():
            if broken["on"]:
                raise OSError(5, "io")
            return real_read()

        with mock.patch.object(self.store, "_replace_current", replace), mock.patch.object(self.store, "read_current", read):
            unknown = remember_module.remember(self.store, "versión dos", supersedes=first["record_id"], env=AGENT_ENV)
        broken["on"] = False
        self.assertEqual((unknown["state"], unknown["outcome"]), ("queued", "unknown"))
        self.assert_retry_is_already_committed("versión dos", first["record_id"])
        texts = [r["text"] for r in MemoryStore(self.project).snapshot().records["facts"]]
        self.assertEqual(texts.count("versión dos"), 1)

    def test_a_different_text_with_the_same_key_is_still_a_collision(self) -> None:
        remember(self.project, "uno", "--idempotency-key", "k")
        rc, other = remember(self.project, "otro", "--idempotency-key", "k")
        self.assertEqual((rc, other["state"], other["code"]), (3, "rejected", "remember_id_collision"))
        self.assertNotIn("record_id", other)  # R1-06


class BatchWithPriorQueueTests(InboxCase):
    def test_r1_04_the_newest_own_entry_rides_in_the_batch_with_300_pending(self) -> None:
        factory = EntryFactory(self.store, env=AGENT_ENV)
        for index in range(300):
            factory.write(f"previa {index}")
        for index in range(3):
            factory.write(f"episodio {index}", kind="state")
        result = remember_module.remember(self.store, "la propia, la más nueva", env=AGENT_ENV)
        self.assertEqual(result["state"], "committed", result)
        self.assertNotIn(result["entry"], inbox.entry_names(self.store))
        # El lote de la propia (stream facts, add) se arma con la propia dentro: 250 entradas como máximo.
        self.assertGreaterEqual(inbox.read_status(self.store)["pending"]["count"], 53)
        self.assertIn("la propia, la más nueva", [r["text"] for r in self.store.snapshot().records["facts"]])


class OutputShapeTests(InboxCase):
    def test_r1_06_record_id_only_with_committed_and_queued(self) -> None:
        rejected = remember_module.remember(self.store, "x", supersedes="f-no-existe", env=AGENT_ENV)
        self.assertEqual(rejected["state"], "rejected")
        self.assertNotIn("record_id", rejected)
        validate(rejected)
        committed = remember_module.remember(self.store, "y", env=AGENT_ENV)
        self.assertIn("record_id", committed)

    def test_r1_08_the_missing_cli_hint_names_the_variable_once(self) -> None:
        done = cli(self.project, "remember", "--text", "x", agent=False)
        self.assertEqual(done.stderr.count("AN_KLA_AGENT_CLI"), 1, done.stderr)

    def test_r1_05_help_declares_retry_across_sessions_and_the_exit_codes(self) -> None:
        text = " ".join(cli(self.project, "remember", "--help").stdout.split())
        for needle in ("otra sesión", "--idempotency-key estable", "rc 3", "queued + drain_error"):
            self.assertIn(needle, text)

    def test_r1_02_queued_with_drain_error_exits_3_with_the_full_json(self) -> None:
        inbox.ensure_layout(self.store)
        marker = Path(self.store.root) / "inbox" / "inflight" / "0a92bdfb-286a-44b5-8c24-8d7a1332c6b6.json"
        marker.write_bytes(b"{no es un marcador")
        rc, result = remember(self.project, "con marcador roto")
        self.assertEqual((rc, result["state"]), (3, "queued"), result)
        self.assertRegex(result["drain_error"], r"^inflight_marker_")
        validate(result)
        caps = json.loads(cli(self.project, "capabilities").stdout)
        self.assertIn("drain_error", caps["cli_error_surface"]["pending_outcome"]["cases"]["remember"])


class LinkedPendingTests(InboxCase):
    def test_r1_07_a_linked_pending_is_a_drain_error_json_with_rc_3(self) -> None:
        inbox.ensure_layout(self.store)
        pending = Path(self.store.root) / "inbox" / "pending"
        pending.rmdir()
        os.symlink(self.project, pending)
        done = cli(self.project, "inbox", "drain")
        self.assertEqual(done.returncode, 3, done.stderr)
        result = json.loads(done.stdout)
        self.assertEqual((result["state"], result["drain_error"]), ("aborted", "inbox_unsafe_path"))
        self.assertEqual(done.stderr, "")

    def test_r1_07_a_failure_enumerating_pending_after_collect_tmp_is_drain_error(self) -> None:
        """La ventana que el recolector no cubre: `pending/` se vuelve inseguro tras `collect_tmp`."""

        EntryFactory(self.store, env=AGENT_ENV).write("uno")
        with mock.patch.object(inbox_drain, "processable_names", side_effect=inbox.InboxError("inbox_unsafe_path")):
            result = inbox_drain.drain(self.store)
        self.assertEqual((result["state"], result["outcome"], result["drain_error"]), ("aborted", "known", "inbox_unsafe_path"))
        with mock.patch.object(inbox_drain, "processable_names", side_effect=OSError(5, "io /ruta")):
            queued = remember_module.remember(self.store, "dos", env=AGENT_ENV)
        self.assertEqual((queued["state"], queued["drain_error"]), ("queued", "storage_io_failed"))
