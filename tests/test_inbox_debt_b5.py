"""Deuda heredada que corrige B5: R3-01 y R3-06 de B2 (y R3-06 de B1 en ``test_remember``)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

from an_kla import inbox, inbox_drain, remember as remember_module
from an_kla.custody import CustodyError
from an_kla.identity import IdentityError
from tests.inbox_support import AGENT_ENV, EntryFactory, InboxCase
from tests.remember_support import cli, remember
from tests.test_inbox_drain import validates


class UnsafeInodeInStatusTests(InboxCase):
    """R3-01: un inodo inseguro deja sólo ``rejected/<nombre>.reason``; ``inbox status`` lo muestra."""

    def setUp(self) -> None:
        super().setUp()
        self.factory = EntryFactory(self.store)
        self.paths = inbox.inbox_paths(self.store)

    def test_unsafe_inodes_appear_in_status_with_their_reason(self) -> None:
        good = self.factory.write("bueno")
        link, fifo = self.factory.fresh_name(), self.factory.fresh_name()
        os.symlink(self.project / "destino-secreto", self.paths.pending / link)
        os.mkfifo(self.paths.pending / fifo)
        corrupt = self.factory.write_raw(b"{no es json")
        result = inbox_drain.drain(self.store)
        validates(result)
        self.assertEqual(result["committed"]["count"], 1)
        self.assertEqual(sorted(p.name for p in self.paths.rejected.iterdir() if not p.name.endswith(".reason")), [corrupt])
        status = inbox.read_status(self.store)
        by_name = {item["name"]: item for item in status["rejected"]["entries"]}
        self.assertEqual(status["rejected"]["count"], 3, by_name)
        for unsafe in (link, fifo):
            self.assertEqual(by_name[unsafe + ".reason"]["reason"], "inbox_entry_unsafe")
        self.assertEqual(by_name[corrupt]["reason"], "inbox_entry_invalid")
        self.assertNotIn(corrupt + ".reason", by_name)  # el .reason de una movida no se cuenta dos veces
        self.assertNotIn("destino-secreto", json.dumps(status))
        validates_status(status)
        self.assertNotIn(good, by_name)

    def test_the_rejected_of_a_remember_run_names_the_unsafe_evidence(self) -> None:
        inbox.ensure_layout(self.store)
        os.symlink(self.project / "x", self.paths.pending / self.factory.fresh_name())
        result = remember_module.remember(self.store, "legítimo", env=AGENT_ENV)
        self.assertEqual(result["state"], "committed")
        self.assertEqual(result["rejected"]["count"], 1)
        self.assertEqual(result["rejected"]["entries"][0]["code"], "inbox_entry_unsafe")


def validates_status(status: dict) -> None:
    from an_kla.schemas import schema_document

    try:
        import jsonschema
    except ImportError:  # pragma: no cover
        return
    jsonschema.Draft202012Validator(schema_document("inbox-status-v1")).validate(status)


class SetupFailuresAreDrainErrorsTests(InboxCase):
    """R3-06: preflight, ``ensure_layout`` y ``collect_tmp`` informan ``drain_error``, nunca una traza."""

    def setUp(self) -> None:
        super().setUp()
        self.factory = EntryFactory(self.store)

    def assert_aborted(self, result: dict, code: str) -> None:
        validates(result)
        self.assertEqual((result["state"], result["outcome"], result["drain_error"]), ("aborted", "known", code))
        self.assertEqual(result["batches"], [])

    def test_a_preflight_failure_is_drain_error(self) -> None:
        self.factory.write("uno")
        for error, code in ((CustodyError("store_root_divergence"), "store_root_divergence"),
                            (IdentityError("store_identity_changed"), "store_identity_changed")):
            with self.subTest(code=code), mock.patch.object(inbox_drain, "_mutation_preflight_with_context", side_effect=error):
                self.assert_aborted(inbox_drain.drain(self.store), code)
        self.assertEqual(len(inbox.entry_names(self.store)), 1)

    def test_ensure_layout_and_make_layout_failures_are_drain_error(self) -> None:
        self.factory.write("uno")
        with mock.patch.object(inbox_drain, "ensure_layout", side_effect=OSError(13, "denegado /ruta/privada")):
            result = inbox_drain.drain(self.store)
        self.assert_aborted(result, "storage_io_failed")
        self.assertNotIn("/ruta", json.dumps(result))
        with mock.patch.object(self.store, "_make_layout", side_effect=OSError(28, "sin espacio")):
            self.assert_aborted(inbox_drain.drain(self.store), "storage_io_failed")

    def test_a_collect_tmp_failure_is_drain_error(self) -> None:
        self.factory.write("uno")
        with mock.patch.object(inbox_drain, "collect_tmp", side_effect=inbox.InboxError("inbox_unsafe_path")):
            self.assert_aborted(inbox_drain.drain(self.store), "inbox_unsafe_path")
        with mock.patch.object(inbox_drain, "collect_tmp", side_effect=OSError(5, "io")):
            self.assert_aborted(inbox_drain.drain(self.store), "storage_io_failed")

    def test_the_cli_drain_prints_the_json_and_exits_3_instead_of_a_traceback(self) -> None:
        self.factory.write("uno")
        root = self.paths_inbox()
        (root / "tmp").rmdir()
        os.symlink(self.project, root / "tmp")  # tmp/ enlazado: inbox_unsafe_path
        done = cli(self.project, "inbox", "drain")
        self.assertEqual(done.returncode, 3, done.stderr)
        result = json.loads(done.stdout)
        self.assertEqual((result["state"], result["drain_error"]), ("aborted", "inbox_unsafe_path"))
        self.assertEqual(done.stderr, "")
        self.assertNotIn("Traceback", done.stdout)

    def test_remember_is_queued_with_drain_error_when_the_entry_was_enqueued(self) -> None:
        with mock.patch.object(inbox_drain, "_mutation_preflight_with_context", side_effect=CustodyError("store_root_divergence")):
            result = remember_module.remember(self.store, "encolada", env=AGENT_ENV)
        self.assertEqual((result["state"], result["drain_error"]), ("queued", "store_root_divergence"))
        self.assertEqual(len(inbox.entry_names(self.store)), 1)

    def test_remember_without_an_enqueued_entry_is_an_error_with_a_code(self) -> None:
        with mock.patch.object(remember_module, "enqueue", side_effect=CustodyError("store_root_divergence")):
            with self.assertRaises(CustodyError):
                remember_module.remember(self.store, "no se encola", env=AGENT_ENV)
        self.assertEqual(inbox.entry_names(self.store), [])

    def test_cli_remember_with_an_unsafe_tmp_is_a_coded_error(self) -> None:
        rc, first = remember(self.project, "primero")
        self.assertEqual(first["state"], "committed")
        root = self.paths_inbox()
        (root / "tmp").rmdir()
        os.symlink(self.project, root / "tmp")
        done = cli(self.project, "remember", "--text", "segundo")
        self.assertNotIn("Traceback", done.stderr)
        self.assertNotIn(str(self.project), done.stdout + done.stderr)
        self.assertEqual((done.returncode, done.stdout), (1, ""))  # no se encoló: error con código, sin traza
        self.assertEqual(done.stderr.strip(), "an-kla error: inbox_unsafe_path")

    def paths_inbox(self) -> Path:
        inbox.ensure_layout(self.store)
        return Path(self.store.root) / "inbox"
