"""Optional SQLite FTS5 index generations for one immutable revision."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any

from .canonical import bare_digest
from .store import MemoryStore


def detect_fts5() -> bool:
    try:
        con = sqlite3.connect(":memory:")
        try:
            con.execute("CREATE VIRTUAL TABLE probe USING fts5(text)")
            con.execute("INSERT INTO probe(text) VALUES ('an-kla')")
            return bool(con.execute("SELECT rowid FROM probe WHERE probe MATCH 'an-kla'").fetchone())
        finally:
            con.close()
    except sqlite3.DatabaseError:
        return False


def build_index(store: MemoryStore, *, revision_id: str | None = None) -> dict[str, Any]:
    snapshot = store.snapshot(revision_id)
    if not detect_fts5():
        return {
            "profile": "scan-fallback/v1",
            "revision": snapshot.revision_id,
            "index": None,
            "degradation": "fts5_unavailable",
        }
    profile = "sqlite-fts5-v1"
    directory = store.root / "indexes" / bare_digest(snapshot.revision_id) / profile
    directory.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".build-", suffix=".sqlite", dir=directory)
    temporary = Path(name)
    try:
        os.close(descriptor)
        con = sqlite3.connect(temporary)
        try:
            con.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            con.execute("CREATE VIRTUAL TABLE facts_fts USING fts5(id UNINDEXED, text)")
            con.executemany(
                "INSERT INTO metadata VALUES (?,?)",
                [
                    ("schema", "an-kla/index-v1"),
                    ("revision", snapshot.revision_id),
                    ("profile", "sqlite-fts5/v1"),
                ],
            )
            for record in snapshot.records["facts"]:
                payload = record.get("payload", record)
                text = payload.get("text", payload.get("summary", payload.get("p", ""))) if isinstance(payload, dict) else str(payload)
                con.execute("INSERT INTO facts_fts VALUES (?,?)", (record["id"], str(text)))
            con.commit()
        finally:
            con.close()
        payload = temporary.read_bytes()
        index_hash = "sha256:" + hashlib.sha256(payload).hexdigest()
        target = directory / (bare_digest(index_hash) + ".sqlite")
        store._write_immutable(target, payload)  # package-private by design
        return {
            "profile": "sqlite-fts5/v1",
            "revision": snapshot.revision_id,
            "index": str(target.relative_to(store.root)),
            "index_hash": index_hash,
        }
    finally:
        if temporary.exists():
            temporary.unlink()
