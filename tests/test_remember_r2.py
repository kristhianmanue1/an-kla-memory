"""Arreglos de la ronda 2 de B5 (R2-01, R2-02, R2-03)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

from an_kla import inbox, inbox_drain, remember as remember_module
from an_kla.store import MemoryStore
from tests.inbox_support import AGENT_ENV, EntryFactory, InboxCase
from tests.remember_support import cli, remember
from tests.test_remember import validate

KEY = "clave-dada-r2"


class StreamScopedDedupTests(InboxCase):
    def snapshot(self):
        return MemoryStore(self.project).snapshot()

    def test_r2_01_same_given_key_and_text_with_another_kind_commits_in_its_own_stream(self) -> None:
        _, first = remember(self.project, "mismo texto", "--idempotency-key", KEY)
        rc, second = remember(self.project, "mismo texto", "--kind", "state", "--idempotency-key", KEY)
        validate(second)
        self.assertEqual((rc, second["state"], second.get("already_committed")), (0, "committed", None), second)
        self.assertEqual(second["stream"], "episodes")
        self.assertNotEqual(second["record_id"], first["record_id"])
        snapshot = self.snapshot()
        self.assertEqual([r["id"] for r in snapshot.records["episodes"]], [second["record_id"]])
        self.assertEqual([r["id"] for r in snapshot.records["facts"]], [first["record_id"]])
        self.assertEqual(inbox.entry_names(self.store), [])

    def test_r2_01_a_real_collision_with_other_text_and_the_same_id_is_rejected(self) -> None:
        remember(self.project, "uno", "--idempotency-key", KEY)
        rc, other = remember(self.project, "otro texto", "--idempotency-key", KEY)
        self.assertEqual((rc, other["state"], other["code"]), (3, "rejected", "remember_id_collision"))
        self.assertEqual(other["reason_codes"], ["id_exists_in_snapshot"])
        self.assertEqual([r["text"] for r in self.snapshot().records["facts"]], ["uno"])

    def test_r2_01_the_retries_of_r1_01_still_hold_for_own_and_foreign_targets(self) -> None:
        _, theirs = remember(self.project, "ajeno", env={"AN_KLA_AGENT_NAME": "otro"})
        _, mine = remember(self.project, "propio")
        for target, text in ((theirs["record_id"], "disputa"), (mine["record_id"], "sustituye")):
            _, first = remember(self.project, text, "--supersedes", target)
            self.assertEqual(first["state"], "committed")
            rc, retry = remember(self.project, text, "--supersedes", target)
            self.assertEqual((rc, retry["state"], retry.get("already_committed")), (0, "committed", True), retry)
            self.assertEqual(retry["rejected"]["count"], 0)
        self.assertEqual(inbox.read_status(self.store)["rejected"]["count"], 0)

    def test_r2_02_a_given_key_reused_with_another_target_is_the_same_intention(self) -> None:
        _, one = remember(self.project, "base uno")
        _, two = remember(self.project, "base dos")
        _, first = remember(self.project, "v2", "--supersedes", one["record_id"], "--idempotency-key", KEY)
        rc, again = remember(self.project, "v2", "--supersedes", two["record_id"], "--idempotency-key", KEY)
        self.assertEqual((rc, again["state"], again.get("already_committed")), (0, "committed", True))
        rows = {r["id"]: r for r in self.snapshot().records["facts"]}
        self.assertEqual(rows[one["record_id"]].get("status"), "sustituida")
        self.assertNotEqual(rows[two["record_id"]].get("status"), "sustituida")  # la nueva sustitución no se aplicó
        self.assertEqual(first["state"], "committed")

    def test_r2_02_the_help_declares_the_reused_key_semantics(self) -> None:
        text = " ".join(cli(self.project, "remember", "--help").stdout.split())
        self.assertIn("otro --supersedes del mismo stream es la misma intención", text)


class DrainErrorEverywhereTests(InboxCase):
    def setUp(self) -> None:
        super().setUp()
        self.factory = EntryFactory(self.store, env=AGENT_ENV)

    def assert_aborted(self, result: dict, code: str) -> None:
        self.assertEqual((result["state"], result["outcome"], result["drain_error"]), ("aborted", "known", code), result)

    def test_r2_03a_an_inbox_error_inside_the_locked_attempt_is_drain_error(self) -> None:
        self.factory.write("uno")
        real, calls = inbox_drain.processable_names, {"n": 0}

        def second_call_fails(store):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise inbox.InboxError("inbox_unsafe_path")
            return real(store)

        with mock.patch.object(inbox_drain, "processable_names", second_call_fails):
            self.assert_aborted(inbox_drain.drain(self.store), "inbox_unsafe_path")

    def test_r2_03b_an_unsafe_root_is_json_with_rc_3_not_a_one_line_error(self) -> None:
        self.factory.write("uno")
        root = Path(self.store.root) / "inbox"
        moved = root.with_name("inbox-real")
        root.rename(moved)
        os.symlink(moved, root)
        done = cli(self.project, "inbox", "drain")
        self.assertEqual((done.returncode, done.stderr), (3, ""), done.stdout)
        self.assertEqual(json.loads(done.stdout)["drain_error"], "inbox_unsafe_path")
        with mock.patch.object(inbox_drain, "root_state", side_effect=OSError(5, "io /ruta")):
            self.assert_aborted(inbox_drain.drain(self.store), "storage_io_failed")

    def test_r2_03c_a_failing_has_work_after_a_batch_is_aborted_not_a_silent_partial(self) -> None:
        for index in range(3):
            self.factory.write(f"p{index}")
        real, calls = inbox_drain._has_work, {"n": 0}

        def fails_after_the_batch(store):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise inbox.InboxError("inbox_unsafe_path")
            return real(store)

        with mock.patch.object(inbox_drain, "_has_work", fails_after_the_batch):
            result = inbox_drain.drain(self.store, max_batches=1)
        self.assert_aborted(result, "inbox_unsafe_path")
        self.assertEqual(result["committed"]["count"], 3)

    def test_r2_03_remember_reports_queued_with_the_code_for_each_case(self) -> None:
        with mock.patch.object(inbox_drain, "root_state", side_effect=inbox.InboxError("inbox_unsafe_path")):
            result = remember_module.remember(self.store, "dentro", env=AGENT_ENV)
        self.assertEqual((result["state"], result["drain_error"]), ("queued", "inbox_unsafe_path"))
        validate(result)
