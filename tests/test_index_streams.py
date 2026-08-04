"""Tests for P2 (ADR-0014): index v2 multi-stream FTS5."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest

from an_kla.index import (
    INDEX_SCHEMA,
    INDEX_VERSION,
    INDEX_VERSION_KEY,
    build_index,
    index_resolution,
)
from an_kla.retrieval import INDEX_PROFILE, retrieve
from an_kla.store import MemoryStore


def _seed(store: MemoryStore, base: str) -> str:
    return store.commit(
        expected_current_hash=base,
        checkpoint_patch={},
        facts=[{"id": "f-ix-1", "payload": {"text": "facto indexable"}}],
        events=[{"id": "e-ix-1", "payload": {"text": "evento indexable"}}],
        episodes=[{"id": "ep-ix-1", "payload": {"text": "episodio indexable"}}],
    )


class IndexV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(self.temp.name)
        self.base = self.store.initialize()
        self.current = _seed(self.store, self.base)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_build_index_covers_three_streams(self):
        out = build_index(self.store)
        self.assertEqual(out["profile"], "sqlite-fts5/v1")
        self.assertEqual(out["index_version"], INDEX_VERSION)
        per = out["indexed_per_stream"]
        self.assertEqual(per["facts"], 1)
        self.assertEqual(per["events"], 1)
        self.assertEqual(per["episodes"], 1)

    def test_metadata_records_schema_and_version(self):
        build_index(self.store)
        resolution = index_resolution(self.store, self.current)
        self.assertEqual(resolution.status, "none")
        con = sqlite3.connect(f"file:{resolution.path}?mode=ro", uri=True)
        try:
            meta = dict(con.execute("SELECT key, value FROM metadata").fetchall())
        finally:
            con.close()
        self.assertEqual(meta["schema"], INDEX_SCHEMA)
        self.assertEqual(meta[INDEX_VERSION_KEY], INDEX_VERSION)

    def test_index_resolution_reports_none_for_current_v2(self):
        build_index(self.store)
        resolution = index_resolution(self.store, self.current)
        self.assertEqual(resolution.status, "none")
        self.assertIsNotNone(resolution.path)

    def test_simulated_v1_index_is_rejected_as_obsolete(self):
        build_index(self.store)
        resolution = index_resolution(self.store, self.current)
        assert resolution.path is not None
        # Mutate the metadata to drop the index_version key (simulates v1).
        con = sqlite3.connect(str(resolution.path))
        try:
            con.execute(f"DELETE FROM metadata WHERE key = '{INDEX_VERSION_KEY}'")
            con.commit()
        finally:
            con.close()
        # The on-disk hash no longer matches the path stem, so the integrity
        # check fires first; verify that index_obsolete is reported when the
        # hash still matches by instead mutating a fresh copy.
        # Build a fresh index for the same revision (immutable writes skip
        # when bytes match), then craft an old-style metadata in a new file.
        # The simpler observable contract: index_resolution of a v1 marker
        # returns status == "index_obsolete". We craft that scenario below.
        # Instead of corrupting the live file, write an entirely synthetic
        # v1 index in a sibling directory.
        from pathlib import Path
        from an_kla.canonical import bare_digest
        directory = (
            self.store.root
            / "indexes"
            / bare_digest(self.current)
            / "sqlite-fts5-v1"
        )
        # Create a parallel synthetic file to avoid touching the live one.
        # Already mutated the live one above; rebuild it to restore state.
        build_index(self.store)
        # Synthetic v1 (no index_version metadata).
        import hashlib
        import os
        synthetic = directory / ".synthetic-v1.sqlite"
        con = sqlite3.connect(str(synthetic))
        try:
            con.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            con.execute("CREATE VIRTUAL TABLE facts_fts USING fts5(id UNINDEXED, text)")
            con.execute("INSERT INTO metadata VALUES ('schema','an-kla/index-v1')")
            con.execute("INSERT INTO metadata VALUES ('revision', ?)", (self.current,))
            con.execute("INSERT INTO facts_fts VALUES ('f-ix-1','facto indexable')")
            con.commit()
        finally:
            con.close()
        payload = synthetic.read_bytes()
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        target = directory / (bare_digest(digest) + ".sqlite")
        os.replace(synthetic, target)
        reference = directory / "CURRENT"
        # Point CURRENT at the synthetic v1 file.
        reference.write_bytes((digest + "\n").encode("ascii"))
        resolution = index_resolution(self.store, self.current)
        self.assertEqual(resolution.status, "index_obsolete")
        self.assertIsNone(resolution.path)

    def test_retrieve_with_index_profile_uses_all_streams(self):
        build_index(self.store)
        out = retrieve(
            self.store,
            "indexable",
            5000,
            profile=INDEX_PROFILE,
            streams=("facts", "events", "episodes"),
        )
        self.assertEqual(out["profile"], INDEX_PROFILE)
        self.assertEqual(out["degradation"], "none")
        ids = {s["id"] for s in out["selected"]}
        self.assertEqual(ids, {"f-ix-1", "e-ix-1", "ep-ix-1"})


if __name__ == "__main__":
    unittest.main()
