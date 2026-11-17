"""Deuda de B5 (#218): R3-01 a R3-04 y los caminos de su misma clase (sin JSON o con ruta)."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from unittest import mock

from an_kla import inbox, inbox_drain
from tests.inbox_support import EntryFactory, InboxCase
from tests.remember_support import cli, remember
from tests.test_inbox_drain import validates


class UnopenableWriteLockTests(InboxCase):
    """R3-02: el candado de escritura que no se abre es un `drain_error` tipado, no una línea de error."""

    def setUp(self) -> None:
        super().setUp()
        self.factory = EntryFactory(self.store)

    def break_write_lock(self) -> None:
        lock = Path(self.store.root) / ".write.lock"
        if lock.is_dir():
            shutil.rmtree(lock)
        elif lock.exists():
            lock.unlink()
        lock.mkdir()  # abrirlo como archivo falla con IsADirectoryError (OSError)

    def test_drain_reports_storage_io_failed_without_a_path(self) -> None:
        self.factory.write("uno")
        with mock.patch.object(self.store, "write_lock", side_effect=OSError(13, "denegado /ruta/privada")):
            result = inbox_drain.drain(self.store)
        validates(result)
        self.assertEqual((result["state"], result["outcome"], result["drain_error"]), ("aborted", "known", "storage_io_failed"))
        self.assertNotIn("/ruta", json.dumps(result))
        self.assertEqual(len(inbox.entry_names(self.store)), 1)

    def test_the_cli_drain_prints_the_json_and_exits_3(self) -> None:
        self.factory.write("uno")
        self.break_write_lock()
        done = cli(self.project, "inbox", "drain")
        self.assertEqual(done.returncode, 3, (done.stdout, done.stderr))
        result = json.loads(done.stdout)
        self.assertEqual((result["state"], result["drain_error"]), ("aborted", "storage_io_failed"))
        self.assertNotIn(str(self.project), done.stdout + done.stderr)
        self.assertEqual(done.stderr, "")


class CountIgnoredFailuresTests(InboxCase):
    """R3-04: un fallo de `count_ignored` no escapa sin JSON."""

    def setUp(self) -> None:
        super().setUp()
        self.factory = EntryFactory(self.store)

    def test_a_count_ignored_failure_is_reported_as_drain_error(self) -> None:
        self.factory.write("uno")
        with mock.patch.object(inbox_drain, "count_ignored", side_effect=OSError(5, "io /ruta/privada")):
            result = inbox_drain.drain(self.store)
        validates(result)
        self.assertEqual(result["drain_error"], "storage_io_failed")
        self.assertNotIn("/ruta", json.dumps(result))
        self.assertEqual(result["committed"]["count"], 1)  # lo comprometido se informa igual

    def test_a_count_ignored_failure_in_the_setup_branch_is_reported_too(self) -> None:
        self.factory.write("uno")
        with mock.patch.object(inbox_drain, "collect_tmp", side_effect=inbox.InboxError("inbox_unsafe_path")), \
                mock.patch.object(inbox_drain, "count_ignored", side_effect=OSError(5, "io")):
            result = inbox_drain.drain(self.store)
        self.assertEqual((result["state"], result["drain_error"]), ("aborted", "inbox_unsafe_path"))


class KeyReuseAcrossKindsTests(InboxCase):
    """R3-01 y R3-03: el `kind` y el target forman parte de la intención de una clave dada."""

    def setUp(self) -> None:
        super().setUp()
        self.factory = EntryFactory(self.store)
        self.key = "sha256:" + "ab" * 32

    def test_reusing_a_key_with_another_kind_is_a_typed_rejection(self) -> None:
        self.factory.write("mismo texto", kind="fact", key=self.key)
        self.assertEqual(inbox_drain.drain(self.store)["committed"]["count"], 1)
        name = self.factory.write("mismo texto", kind="decision", key=self.key)
        result = inbox_drain.drain(self.store)
        validates(result)
        self.assertEqual(result["already_committed"]["count"], 0)
        self.assertEqual(result["rejected"]["count"], 1, result)
        rejected = result["rejected"]["entries"][0]
        self.assertEqual((rejected["entry"], rejected["code"]), (name, "remember_id_collision"))
        self.assertEqual(rejected["reason_codes"], ["idempotency_key_other_kind"])

    def test_the_same_key_and_kind_is_still_already_committed(self) -> None:
        self.factory.write("igual", kind="decision", key=self.key)
        inbox_drain.drain(self.store)
        self.factory.write("igual", kind="decision", key=self.key)
        result = inbox_drain.drain(self.store)
        self.assertEqual((result["already_committed"]["count"], result["rejected"]["count"]), (1, 0))

    def test_a_retry_with_a_missing_target_is_not_already_committed(self) -> None:
        self.factory.write("con target", key=self.key)
        inbox_drain.drain(self.store)
        name = self.factory.write("con target", key=self.key, target_id="fact-no-existe")
        result = inbox_drain.drain(self.store)
        validates(result)
        self.assertEqual(result["already_committed"]["count"], 0, result)
        rejected = result["rejected"]["entries"][0]
        self.assertEqual((rejected["entry"], rejected["code"]), (name, "invalid_supersede_target"))
        self.assertEqual(rejected["reason_codes"], ["target_missing"])

    def test_the_cli_remember_answers_the_typed_rejection_for_a_kind_change(self) -> None:
        rc, first = remember(self.project, "texto", "--kind", "fact", "--idempotency-key", "clave-dada")
        self.assertEqual((rc, first["state"]), (0, "committed"))
        rc, second = remember(self.project, "texto", "--kind", "decision", "--idempotency-key", "clave-dada")
        self.assertEqual((rc, second["state"], second["code"]), (3, "rejected", "remember_id_collision"))
        self.assertNotIn("already_committed", second)


class ClassOfFailureTests(InboxCase):
    """Pregunta de clase: ningún camino de `remember`/`inbox`/`disputes` sale sin JSON o con ruta."""

    def test_inbox_status_and_disputes_answer_json(self) -> None:
        done = cli(self.project, "inbox", "status")
        self.assertEqual(done.returncode, 0, done.stderr)
        json.loads(done.stdout)
        done = cli(self.project, "disputes", "list")
        self.assertEqual(done.returncode, 0, done.stderr)
        json.loads(done.stdout)

    def test_disputes_list_with_an_unreadable_store_is_a_coded_error_without_a_path(self) -> None:
        refs = Path(self.store.root) / "refs"
        os.chmod(refs, 0)
        self.addCleanup(os.chmod, refs, 0o755)
        done = cli(self.project, "disputes", "list")
        self.assertEqual((done.returncode, done.stdout), (1, ""))
        self.assertEqual(done.stderr.strip(), "an-kla error: storage_io_failed")
        self.assertNotIn(str(self.project), done.stderr)

    def test_remember_with_an_unopenable_write_lock_is_queued_with_drain_error(self) -> None:
        lock = Path(self.store.root) / ".write.lock"
        if lock.exists():
            lock.unlink()
        lock.mkdir()
        rc, result = remember(self.project, "encolada")
        self.assertEqual((rc, result["state"], result["drain_error"]), (3, "queued", "storage_io_failed"))
        self.assertNotIn(str(self.project), json.dumps(result))
        self.assertEqual(len(inbox.entry_names(self.store)), 1)
