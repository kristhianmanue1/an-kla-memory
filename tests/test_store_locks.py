"""test_store_locks.py — liveness del write lock (#111/P2, beta.22).

POSIX ya no bloquea indefinidamente: LOCK_NB + backoff con deadline
(10s por defecto, constante congelada) -> ``LockBusyError("write_lock_busy")``,
paridad con la rama Windows y con el reader gate.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from an_kla.store import LockBusyError, MemoryStore
from an_kla import store_locks


class WriteLockDeadlineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="ankla-lock-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = MemoryStore(self.root)
        self.store.initialize()

    def test_second_writer_hits_deadline_with_stable_code(self) -> None:
        with mock.patch.object(
            store_locks, "WRITE_LOCK_DEADLINE_SECONDS", 0.05
        ):
            with self.store.write_lock():
                with self.assertRaises(LockBusyError) as ctx:
                    with self.store.write_lock():
                        pass  # nunca llega: el lock está tomado
        self.assertEqual(str(ctx.exception), "write_lock_busy")

    def test_lock_is_reentrant_across_sequential_uses(self) -> None:
        with self.store.write_lock():
            pass
        with self.store.write_lock() as result:
            self.assertIsNone(result.release_error)


if __name__ == "__main__":
    unittest.main()
