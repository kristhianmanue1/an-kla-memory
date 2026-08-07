"""Optional SQLite FTS5 index generations for one immutable revision."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
from dataclasses import dataclass
from typing import Any

from .canonical import bare_digest
from .record_text import record_text
from .store import MemoryStore, STREAMS

INDEX_PROFILE = "sqlite-fts5/v1"
INDEX_DIR_NAME = "sqlite-fts5-v1"
INDEX_VERSION = "2"
INDEX_VERSION_KEY = "index_version"
INDEX_SCHEMA = "an-kla/index-v2"


@dataclass(frozen=True)
class IndexResolution:
    path: Path | None
    status: str


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
    descriptor, name = tempfile.mkstemp(prefix="an-kla-index-", suffix=".sqlite")
    temporary = Path(name)
    try:
        os.close(descriptor)
        con = sqlite3.connect(temporary)
        try:
            con.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            for stream in STREAMS:
                con.execute(
                    f"CREATE VIRTUAL TABLE {stream}_fts USING fts5(id UNINDEXED, text)"
                )
            con.executemany(
                "INSERT INTO metadata VALUES (?,?)",
                [
                    ("schema", INDEX_SCHEMA),
                    ("revision", snapshot.revision_id),
                    ("profile", "sqlite-fts5/v1"),
                    (INDEX_VERSION_KEY, INDEX_VERSION),
                ],
            )
            skipped_no_text = 0
            indexed_per_stream: dict[str, int] = {stream: 0 for stream in STREAMS}
            for stream in STREAMS:
                for record in snapshot.records[stream]:
                    # ADR-0019 (PR-B): skip superseded records so the FTS stays
                    # consistent with snapshot()'s vigency overlay and with
                    # retrieve()'s filter (retrieval.py inactive predicate).
                    if record.get("status", record.get("nu", "vigente")) not in {
                        "vigente",
                        "active",
                        None,
                    }:
                        continue
                    text = record_text(dict(record))
                    if not text:
                        skipped_no_text += 1
                        continue
                    con.execute(
                        f"INSERT INTO {stream}_fts VALUES (?,?)",
                        (record["id"], text),
                    )
                    indexed_per_stream[stream] += 1
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
            "index_version": INDEX_VERSION,
            "indexed_per_stream": indexed_per_stream,
            "skipped_no_text": skipped_no_text,
        }
    finally:
        if temporary.exists():
            temporary.unlink()


def _read_metadata(path: Path, key: str) -> str | None:
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = con.execute(
                "SELECT value FROM metadata WHERE key = ?", (key,)
            ).fetchone()
            return str(row[0]) if row else None
        finally:
            con.close()
    except sqlite3.DatabaseError:
        return None


def index_resolution(store: MemoryStore, revision_id: str) -> IndexResolution:
    """Resolve an index reference without hashing a whole SQLite per query."""
    directory = store.root / "indexes" / bare_digest(revision_id) / INDEX_DIR_NAME
    reference = directory / "CURRENT"
    try:
        raw = reference.read_bytes()
    except FileNotFoundError:
        return IndexResolution(None, "index_unavailable")
    except OSError:
        return IndexResolution(None, "index_unresolvable")
    try:
        identifier = raw[:-1].decode("ascii") if raw.endswith(b"\n") else ""
        bare_digest(identifier)
        target = directory / (bare_digest(identifier) + ".sqlite")
        if not target.is_file():
            return IndexResolution(None, "index_unresolvable")
    except (UnicodeDecodeError, ValueError):
        return IndexResolution(None, "index_unresolvable")
    # An index built with the v1 layout only exposed ``facts_fts``.  Multi-
    # stream queries against such an index silently miss episodes/events; we
    # report it as obsolete and return no path so callers fall back to scan.
    version = _read_metadata(target, INDEX_VERSION_KEY)
    if version != INDEX_VERSION:
        return IndexResolution(None, "index_obsolete")
    return IndexResolution(target, "none")


def resolve_index(store: MemoryStore, revision_id: str) -> Path | None:
    return index_resolution(store, revision_id).path


def verify_index_deep(store: MemoryStore, revision_id: str | None = None) -> dict[str, Any]:
    """Hash the selected derived index on explicit diagnostic request only."""
    snapshot = store.snapshot(revision_id)
    resolution = index_resolution(store, snapshot.revision_id)
    if resolution.path is None:
        return {"ok": False, "revision": snapshot.revision_id, "degradation": resolution.status}
    try:
        payload = resolution.path.read_bytes()
    except OSError:
        return {"ok": False, "revision": snapshot.revision_id, "degradation": "index_unresolvable"}
    actual = "sha256:" + hashlib.sha256(payload).hexdigest()
    expected = "sha256:" + resolution.path.stem
    return {"ok": actual == expected, "revision": snapshot.revision_id, "index": str(resolution.path.relative_to(store.root)), "expected": expected, "actual": actual}


def index_integrity_status(path: Path) -> str:
    """Diagnose a content-addressed index before it narrows candidates."""
    try:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "index_unresolvable"
    return "none" if actual == path.stem else "index_hash_mismatch"


def orphan_index_temporaries(store: MemoryStore) -> int:
    """Count legacy temporaries left inside profile directories."""
    indexes = store.root / "indexes"
    return sum(1 for path in indexes.rglob(".build-*.sqlite") if path.is_file()) if indexes.exists() else 0
