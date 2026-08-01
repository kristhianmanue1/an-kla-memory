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

INDEX_PROFILE = "sqlite-fts5/v1"
INDEX_DIR_NAME = "sqlite-fts5-v1"


def record_text(record: dict[str, Any]) -> str:
    """Return supported textual fields; an empty result is never indexed."""
    payload = record.get("payload", record)
    if not isinstance(payload, dict):
        return str(payload).strip()
    return str(payload.get("text", payload.get("render", payload.get("summary", payload.get("p", ""))))).strip()


def detect_fts5() -> bool:
    try:
        con = sqlite3.connect(":memory:")
        try:
            con.execute("CREATE VIRTUAL TABLE probe USING fts5(text)")
            con.execute("INSERT INTO probe(text) VALUES ('ankla')")
            return bool(con.execute("SELECT rowid FROM probe WHERE probe MATCH 'ankla'").fetchone())
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
    profile = INDEX_DIR_NAME
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
            skipped_no_text = 0
            for record in snapshot.records["facts"]:
                text = record_text(dict(record))
                if not text:
                    skipped_no_text += 1
                    continue
                con.execute("INSERT INTO facts_fts VALUES (?,?)", (record["id"], text))
            con.commit()
        finally:
            con.close()
        payload = temporary.read_bytes()
        index_hash = "sha256:" + hashlib.sha256(payload).hexdigest()
        target = directory / (bare_digest(index_hash) + ".sqlite")
        store._write_immutable(target, payload)  # package-private by design
        # CURRENT is a derived-cache reference, never a commit authority. It
        # prevents accidental selection by hash order or abandoned temporaries.
        reference = directory / "CURRENT"
        store._atomic_write(reference, (index_hash + "\n").encode("ascii"))
        return {
            "profile": INDEX_PROFILE,
            "revision": snapshot.revision_id,
            "index": str(target.relative_to(store.root)),
            "index_hash": index_hash,
            "index_reference": str(reference.relative_to(store.root)),
            "skipped_no_text": skipped_no_text,
        }
    finally:
        if temporary.exists():
            temporary.unlink()


def resolve_index(store: MemoryStore, revision_id: str) -> Path | None:
    """Resolve and verify the one index selected for this revision/profile."""
    directory = store.root / "indexes" / bare_digest(revision_id) / INDEX_DIR_NAME
    reference = directory / "CURRENT"
    try:
        raw = reference.read_bytes()
        identifier = raw[:-1].decode("ascii") if raw.endswith(b"\n") else ""
        bare_digest(identifier)
        target = directory / (bare_digest(identifier) + ".sqlite")
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != bare_digest(identifier):
            return None
        return target
    except (OSError, UnicodeDecodeError, ValueError):
        return None
