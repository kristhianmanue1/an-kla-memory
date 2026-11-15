"""Candado de bandeja, recolector de ``tmp/`` y orden total de candados (ADR-0063 D1, criterio 9)."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from an_kla import inbox, lock_order
from an_kla.identity import identity_lock
from tests.inbox_support import AGENT_ENV, InboxCase

HAS_FLOCK = inbox.fcntl is not None


class InboxLockTests(InboxCase):
    @unittest.skipUnless(HAS_FLOCK, "sin fcntl no hay candado compartido: siempre exclusivo")
    def test_shared_holders_coexist_and_exclusive_excludes(self) -> None:
        self.hold_lock("sh")
        with inbox.inbox_lock(self.store, exclusive=False) as exclusive:
            self.assertFalse(exclusive)
        with self.assertRaises(inbox.InboxError) as caught:
            with inbox.inbox_lock(self.store, exclusive=True):
                pass
        self.assertEqual(caught.exception.code, "inbox_busy")

    @unittest.skipUnless(HAS_FLOCK, "el modo exclusivo forzado se prueba donde hay fcntl; en Windows es el único")
    def test_without_shared_support_a_shared_request_takes_exclusive(self) -> None:
        child = self.hold_lock("sh")
        with mock.patch.object(inbox, "SHARED_SUPPORTED", False):
            with self.assertRaises(inbox.InboxError) as caught:
                with inbox.inbox_lock(self.store, exclusive=False):
                    pass
            self.assertEqual(caught.exception.code, "inbox_busy")
        self.release(child)
        with mock.patch.object(inbox, "SHARED_SUPPORTED", False):
            with inbox.inbox_lock(self.store, exclusive=False) as exclusive:
                self.assertTrue(exclusive)

    @unittest.skipUnless(inbox.msvcrt is not None, "sólo Windows: msvcrt.locking es exclusivo por construcción")
    def test_windows_locking_is_exclusive_only(self) -> None:  # pragma: no cover - sólo Windows
        with inbox.inbox_lock(self.store, exclusive=False) as exclusive:
            self.assertTrue(exclusive)

    def test_lock_is_released_on_exit_and_layout_is_created(self) -> None:
        with inbox.inbox_lock(self.store, exclusive=True):
            for name in ("tmp", "pending", "inflight", "rejected"):
                self.assertTrue((self.inbox / name).is_dir())
        with inbox.inbox_lock(self.store, exclusive=True):
            pass

    def test_symlinked_layout_fails_closed(self) -> None:
        self.inbox.mkdir()
        target = self.project / "afuera"
        target.mkdir()
        os.symlink(target, self.inbox / "pending")
        with self.assertRaises(inbox.InboxError) as caught:
            with inbox.inbox_lock(self.store, exclusive=False):
                pass
        self.assertEqual(caught.exception.code, "inbox_unsafe_path")
        with self.assertRaises(inbox.InboxError):
            inbox.pending_is_empty(self.store)

    def test_emptiness_definitions_count_only_matching_names(self) -> None:
        self.assertTrue(inbox.pending_is_empty(self.store))
        self.assertTrue(inbox.inflight_is_empty(self.store))
        paths = inbox.inbox_paths(self.store)
        for directory in (paths.pending, paths.inflight):
            directory.mkdir(parents=True)
        (paths.pending / "algo.txt").write_bytes(b"")
        (paths.pending / "1-2-0123456789abcdef-01234567.json").mkdir()  # el patrón es por nombre
        (paths.pending / "1-2-0123456789abcdef-0123456.json").write_bytes(b"")  # un dígito corto: ignorado
        (paths.inflight / "no-es-uuid.json").write_bytes(b"")
        self.assertEqual(inbox.entry_names(self.store), ["1-2-0123456789abcdef-01234567.json"])
        self.assertFalse(inbox.pending_is_empty(self.store))
        self.assertTrue(inbox.inflight_is_empty(self.store))
        marker = "0a92bdfb-286a-44b5-8c24-8d7a1332c6b6.json"
        (paths.inflight / marker).write_bytes(b"{}")
        self.assertEqual(inbox.marker_names(self.store), [marker])
        self.assertFalse(inbox.inflight_is_empty(self.store))


class CollectTmpTests(InboxCase):
    def orphans(self, count: int = 2) -> list[str]:
        """Temporales huérfanos reales: un encolado que falla al publicar los deja en ``tmp/``."""

        def failing(src, dst):
            raise OSError(28, "ENOSPC")

        for index in range(count):
            with self.assertRaises(OSError):
                inbox.enqueue(self.store, f"huérfano {index}", env=AGENT_ENV, replace=failing)
        return sorted(os.listdir(self.inbox / "tmp"))

    def test_absent_inbox_creates_nothing(self) -> None:
        self.assertEqual(inbox.collect_tmp(self.store), {"state": "absent", "removed": 0, "errors": 0})
        self.assertFalse(self.inbox.exists())

    def test_orphans_without_a_live_enqueuer_are_deleted(self) -> None:
        names = self.orphans(3)
        self.assertEqual(len(names), 3)
        (self.inbox / "tmp" / "carpeta").mkdir()
        (self.inbox / "tmp" / "carpeta" / "x").write_bytes(b"x")
        result = inbox.collect_tmp(self.store)
        self.assertEqual(result, {"state": "collected", "removed": 4, "errors": 0})
        self.assertEqual(os.listdir(self.inbox / "tmp"), [])

    def test_pending_entries_are_never_touched(self) -> None:
        entry = inbox.enqueue(self.store, "confirmado", env=AGENT_ENV)["entry"]
        self.orphans(1)
        inbox.collect_tmp(self.store)
        self.assertEqual(inbox.entry_names(self.store), [entry])

    @unittest.skipUnless(HAS_FLOCK, "el encolador vivo toma el compartido; sin fcntl no hay compartido")
    def test_a_live_enqueuer_in_another_process_blocks_collection(self) -> None:
        names = self.orphans(2)
        self.hold_lock("sh")
        result = inbox.collect_tmp(self.store)
        self.assertEqual(result, {"state": "busy", "removed": 0, "errors": 0})
        self.assertEqual(sorted(os.listdir(self.inbox / "tmp")), names)


class LockOrderTests(InboxCase):
    """Criterio 9: ningún camino pide el candado de bandeja teniendo identidad o write_lock."""

    def assert_refused(self, call) -> None:
        with self.assertRaises(lock_order.LockOrderError) as caught:
            call()
        self.assertEqual(caught.exception.code, "lock_order_violation")
        self.assertFalse(self.inbox.exists(), "el camino prohibido no debe crear nada")

    def paths(self):
        return {
            "inbox_lock": lambda: inbox.inbox_lock(self.store, exclusive=False).__enter__(),
            "inbox_lock_exclusive": lambda: inbox.inbox_lock(self.store, exclusive=True).__enter__(),
            "enqueue": lambda: inbox.enqueue(self.store, "x", env=AGENT_ENV),
            "collect_tmp": lambda: inbox.collect_tmp(self.store),
        }

    def test_every_inbox_path_refuses_while_holding_identity_lock(self) -> None:
        for name, call in self.paths().items():
            with self.subTest(path=name), identity_lock(self.store):
                self.assertEqual(lock_order.held(), (lock_order.IDENTITY,))
                self.assert_refused(call)

    def test_every_inbox_path_refuses_while_holding_write_lock(self) -> None:
        for name, call in self.paths().items():
            with self.subTest(path=name), self.store.write_lock():
                self.assert_refused(call)

    def test_allowed_order_inbox_then_identity_then_write(self) -> None:
        with inbox.inbox_lock(self.store, exclusive=True):
            self.assertEqual(lock_order.held(), (lock_order.INBOX,))
            with identity_lock(self.store):
                with self.store.write_lock():
                    self.assertEqual(lock_order.held(), (lock_order.INBOX, lock_order.IDENTITY))
        self.assertEqual(lock_order.held(), ())

    def test_registry_is_restored_after_an_error_inside_the_lock(self) -> None:
        with self.assertRaises(RuntimeError):
            with identity_lock(self.store):
                raise RuntimeError("falla dentro")
        self.assertEqual(lock_order.held(), ())
        with inbox.inbox_lock(self.store, exclusive=False):
            pass


if __name__ == "__main__":
    unittest.main()
