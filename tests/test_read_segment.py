"""ADR-0057: lectura de segmentos sin re-canonicalización.

El ancla de integridad (hash de bytes + framing) sigue detectando
manipulación; la forma canónica la garantiza la escritura por construcción.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from an_kla.store import IntegrityError, MemoryStore

TEXT = "registro {i} sobre quetzal y memoria de trabajo"


def build(ws: Path, n: int) -> tuple[MemoryStore, str]:
    store = MemoryStore(str(ws))
    cur = store.initialize()
    cur = store.commit(
        expected_current_hash=cur, checkpoint_patch={},
        facts=[{"id": f"f-{i}", "payload": {"text": TEXT.format(i=i)}}
               for i in range(n)],
    )
    return store, cur


class ReadSegmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store, self.cur = build(Path(self.temp.name), 5)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _first_segment_path(self) -> Path:
        manifest = self.store._read_json_object("revisions", self.cur)
        seg = manifest["facts_segments"][0]
        return (
            Path(self.store.root) / "segments" / "facts" / "sha256"
            / (seg.removeprefix("sha256:") + ".jsonl")
        )

    def test_read_serves_written_rows(self) -> None:
        snap = self.store.snapshot(self.cur)
        self.assertEqual(len(snap.records["facts"]), 5)
        self.assertEqual(snap.records["facts"][0]["payload"]["text"],
                         TEXT.format(i=0))

    def test_tampered_byte_is_detected(self) -> None:
        path = self._first_segment_path()
        payload = bytearray(path.read_bytes())
        payload[10] = payload[10] ^ 0x20
        path.write_bytes(bytes(payload))
        with self.assertRaises(IntegrityError) as caught:
            self.store.snapshot(self.cur)
        self.assertIn("segment_hash_or_framing_invalid",
                      str(caught.exception))

    def test_framing_truncation_is_detected(self) -> None:
        path = self._first_segment_path()
        payload = path.read_bytes()
        path.write_bytes(payload[:-1])  # quita el \n final
        with self.assertRaises(IntegrityError):
            self.store.snapshot(self.cur)

    def test_verify_full_audit_still_passes_on_healthy_store(self) -> None:
        result = self.store.verify()
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
