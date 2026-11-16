"""Deuda de la ronda 3 de B1 (R3-02 a R3-05) y plazo opcional de ``write_lock`` (ADR-0063 D1)."""

from __future__ import annotations

import os
import threading
import time
import unittest

from an_kla import inbox, lock_order
from an_kla.store_errors import LockBusyError
from tests.inbox_support import InboxCase


class CollectTmpDebtTests(InboxCase):
    def make_layout(self, *, lock: bool) -> None:
        for name in ("tmp", "pending", "inflight", "rejected"):
            (self.inbox / name).mkdir(parents=True, exist_ok=True)
        if lock:
            (self.inbox / ".lock").write_bytes(b"")

    def test_r3_02_tmp_enlazado_no_se_informa_como_recolectado(self) -> None:
        self.make_layout(lock=True)
        outside = self.project / "fuera"
        outside.mkdir()
        (outside / "huerfano.json").write_bytes(b"x")
        (self.inbox / "tmp").rmdir()
        os.symlink(outside, self.inbox / "tmp")
        with self.assertRaises(inbox.InboxError) as caught:
            inbox.collect_tmp(self.store)
        self.assertEqual(caught.exception.code, "inbox_unsafe_path")
        self.assertTrue((outside / "huerfano.json").exists())

    def test_r3_02_tmp_no_directorio_tambien_es_inseguro(self) -> None:
        self.make_layout(lock=True)
        (self.inbox / "tmp").rmdir()
        (self.inbox / "tmp").write_bytes(b"x")
        with self.assertRaises(inbox.InboxError) as caught:
            inbox.collect_tmp(self.store)
        self.assertEqual(caught.exception.code, "inbox_unsafe_path")

    def test_r3_03_raiz_presente_sin_lock_recolecta_en_vez_de_inbox_absent(self) -> None:
        self.make_layout(lock=False)
        (self.inbox / "tmp" / "huerfano.json").write_bytes(b"x")
        result = inbox.collect_tmp(self.store)
        self.assertEqual(result, {"state": "collected", "removed": 1, "errors": 0})
        self.assertEqual(list((self.inbox / "tmp").iterdir()), [])
        lock = self.inbox / ".lock"
        self.assertTrue(lock.is_file())
        self.assertEqual(lock.stat().st_mode & 0o777, 0o600)
        self.assertEqual(lock.stat().st_nlink, 1)

    def test_r3_03_lock_enlazado_sigue_siendo_inseguro(self) -> None:
        self.make_layout(lock=False)
        os.symlink(self.project / "no-existe", self.inbox / ".lock")
        with self.assertRaises(inbox.InboxError) as caught:
            inbox.collect_tmp(self.store)
        self.assertEqual(caught.exception.code, "inbox_unsafe_path")

    def test_r3_03_sin_raiz_no_crea_nada(self) -> None:
        self.assertEqual(inbox.collect_tmp(self.store), {"state": "absent", "removed": 0, "errors": 0})
        self.assertFalse(self.inbox.exists())


class LockOrderDebtTests(unittest.TestCase):
    def test_r3_04_cierre_en_otro_contexto_no_deja_marcador_pegado(self) -> None:
        manager = lock_order.holding(lock_order.WRITE)
        manager.__enter__()
        self.assertEqual(lock_order.held(), (lock_order.WRITE,))
        failures: list[BaseException] = []

        def close_elsewhere() -> None:
            try:
                manager.__exit__(None, None, None)
            except BaseException as exc:  # noqa: BLE001 - se informa al hilo principal
                failures.append(exc)

        worker = threading.Thread(target=close_elsewhere)
        worker.start()
        worker.join(timeout=10)
        self.assertEqual(failures, [])
        self.assertEqual(lock_order.held(), ())
        lock_order.require_inbox_allowed()  # no falla: nada pegado

    def test_r3_04_cierre_normal_restaura_el_registro(self) -> None:
        with lock_order.holding(lock_order.IDENTITY):
            with lock_order.holding(lock_order.WRITE):
                self.assertEqual(lock_order.held(), (lock_order.IDENTITY, lock_order.WRITE))
            self.assertEqual(lock_order.held(), (lock_order.IDENTITY,))
        self.assertEqual(lock_order.held(), ())

    def test_r3_05_error_sin_nombres_repetidos(self) -> None:
        class Holder:
            _active_write_lock = object()

        with lock_order.holding(lock_order.WRITE):
            with self.assertRaises(lock_order.LockOrderError) as caught:
                lock_order.require_inbox_allowed(Holder())
        self.assertEqual(caught.exception.held, (lock_order.WRITE,))
        self.assertEqual(str(caught.exception), "lock_order_violation: inbox while holding write")

    def test_r3_05_identidad_y_write_se_listan_una_vez(self) -> None:
        with lock_order.holding(lock_order.IDENTITY), lock_order.holding(lock_order.WRITE):
            with self.assertRaises(lock_order.LockOrderError) as caught:
                lock_order.require_inbox_allowed()
        self.assertEqual(caught.exception.held, (lock_order.IDENTITY, lock_order.WRITE))


class WriteLockDeadlineTests(InboxCase):
    def test_plazo_corto_falla_con_write_lock_busy_sin_esperar_diez_segundos(self) -> None:
        with self.store.write_lock():
            other = type(self.store)(self.project)
            started = time.monotonic()
            with self.assertRaises(LockBusyError) as caught:
                with other.write_lock(deadline=0.1):
                    self.fail("el candado debía estar ocupado")
            elapsed = time.monotonic() - started
        self.assertEqual(str(caught.exception), "write_lock_busy")
        self.assertLess(elapsed, 3.0)

    def test_sin_plazo_rige_la_constante_de_diez_segundos(self) -> None:
        from an_kla import store_locks

        self.assertEqual(store_locks.WRITE_LOCK_DEADLINE_SECONDS, 10.0)
        with self.store.write_lock() as result:
            self.assertIs(self.store._active_write_lock, result)
        self.assertIsNone(self.store._active_write_lock)

    def test_plazo_cero_toma_el_candado_libre(self) -> None:
        with self.store.write_lock(deadline=0.0) as result:
            self.assertIsNone(result.release_error)


if __name__ == "__main__":
    unittest.main()
