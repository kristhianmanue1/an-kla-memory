from __future__ import annotations

import tempfile
import threading
import time
import unittest

from an_kla.reader_gate import ReaderGateError, exclusive_reader_gate, shared_reader_gate
from an_kla.store import MemoryStore

try:
    import fcntl  # noqa: F401
    _FCNTL = True
except ImportError:
    _FCNTL = False


@unittest.skipUnless(_FCNTL, "reader gate requiere fcntl (no disponible en Windows)")
class ReaderGateTests(unittest.TestCase):
    def test_shared_is_reentrant_and_exclusive_waits(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = MemoryStore(root)
            store.initialize()
            entered = threading.Event()
            released = threading.Event()

            def reader() -> None:
                with shared_reader_gate(store):
                    with shared_reader_gate(store):
                        entered.set()
                        released.wait(2)

            thread = threading.Thread(target=reader)
            thread.start()
            self.assertTrue(entered.wait(1))
            with self.assertRaisesRegex(ReaderGateError, "compaction_readers_active"):
                with exclusive_reader_gate(store, timeout=0.03):
                    pass
            released.set()
            thread.join(2)
            with exclusive_reader_gate(store, timeout=0.2):
                with self.assertRaisesRegex(ReaderGateError, "reader_gate_mode_reentry"):
                    store.snapshot()

    def test_snapshot_creates_permanent_gate_ignored_by_export(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = MemoryStore(root)
            store.initialize()
            self.assertTrue(store.snapshot().revision_id)
            self.assertTrue((store.root / ".reader-gate").is_file())


if __name__ == "__main__":
    unittest.main()
