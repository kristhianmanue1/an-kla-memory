"""ADR-0041: physical inventory per revision (read-only, metadata-only)."""

from __future__ import annotations

import json
from typing import Any

from .canonical import canonical_json, digest_bytes
from .compaction import archived_revision_link_under_gate
from .context_view import MAX_CURSOR_CHARS
from .reader_gate import shared_reader_gate
from .store import ID_FIELDS, IntegrityError, MemoryStore
from .subject_ref import parse_subject_ref, SubjectRefError

INVENTORY_SCHEMA = "an-kla/inventory-v1"
STREAMS = ("facts", "events", "episodes")
DEFAULT_LIMIT = 200
MAX_LIMIT = 1000
_PHYSICAL_DEFAULT = "vigente"


def _cursor_encode(revision: str, offset: int) -> str:
    import base64

    payload = json.dumps({"revision": revision, "offset": offset})
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def _cursor_decode(cursor: Any, revision: str, total: int) -> int:
    import base64

    if not isinstance(cursor, str) or not cursor or len(cursor) > MAX_CURSOR_CHARS:
        raise ValueError("inventory_cursor_invalid")
    try:
        document = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
    except (ValueError, UnicodeError):
        raise ValueError("inventory_cursor_invalid") from None
    if (
        not isinstance(document, dict)
        or set(document) != {"revision", "offset"}
        or document.get("revision") != revision
        or not isinstance(document.get("offset"), int)
        or isinstance(document.get("offset"), bool)
        or not 0 <= document["offset"] < total
    ):
        raise ValueError("inventory_cursor_invalid")
    return document["offset"]


def _physical_status(raw: dict[str, Any]) -> str:
    value = raw.get("status", raw.get("nu", _PHYSICAL_DEFAULT))
    return value if isinstance(value, str) and value else _PHYSICAL_DEFAULT


def inventory(
    store: MemoryStore,
    revision: str,
    *,
    streams: tuple[str, ...] | list[str] | None = None,
    cursor: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Enumerate the physical population of one revision (ADR-0041).

    Read-only; holds the shared reader gate while serving the page. The
    archived check runs BEFORE serving (pattern of ``verify_revision``),
    so a compacted revision never surfaces as a misleading
    ``segment_missing``. Metadata-only: no renders, no payloads, no
    absolute paths.
    """

    if not isinstance(revision, str) or not revision:
        raise ValueError("inventory_revision_required")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError("inventory_limit_invalid")
    selected = tuple(streams) if streams is not None else STREAMS
    if not selected or any(s not in STREAMS for s in selected):
        raise ValueError("unsupported_inventory_stream")
    # de-dup preserving caller order
    seen: set[str] = set()
    deduped: list[str] = []
    for s in selected:
        if s not in seen:
            seen.add(s)
            deduped.append(s)
    selected = tuple(deduped)

    with shared_reader_gate(store):
        # Archived check FIRST, catalog consulted ALWAYS (verify_revision
        # pattern): the committed_cleanup_incomplete window can leave the
        # archived manifest present on disk, and a read-failure-only check
        # would serve it.
        from .canonical import bare_digest

        bare_digest(revision)
        current = store.read_current()
        current_manifest = store._read_json_object("revisions", current)
        if current_manifest.get("schema") == "an-kla/revision-v3":
            try:
                archived = archived_revision_link_under_gate(store, revision)
            except Exception as exc:
                raise IntegrityError("compaction_catalog_invalid") from exc
            if archived is not None:
                raise IntegrityError("revision_archived_by_compaction")
        snapshot = store.snapshot(revision)
        rows: list[dict[str, Any]] = []
        counts: dict[str, dict[str, int]] = {}
        total = 0
        for stream in selected:
            overlaid = snapshot.records[stream]
            raws = snapshot.raw_records[stream]
            stream_counts = {
                "total": 0, "vigente": 0, "sustituida": 0, "refutada": 0,
                "eliminada": 0,
            }
            for raw, observed in zip(raws, overlaid):
                record_id = str(raw.get(ID_FIELDS[stream], ""))
                if not record_id:
                    continue  # invalid rows are snapshot-level failures already
                raw_bytes = canonical_json(dict(raw))
                physical = _physical_status(dict(raw))
                observable = str(observed.get("status", physical))
                source = "physical"
                if observable != physical:
                    source = (
                        "supersede_overlay"
                        if observable == "sustituida"
                        else "refute_overlay"
                    )
                try:
                    has_subject = isinstance(raw.get("subject_ref"), str) and (
                        parse_subject_ref(raw["subject_ref"]) is not None
                    )
                except SubjectRefError:
                    has_subject = False
                rows.append(
                    {
                        "stream": stream,
                        "id": record_id,
                        "record_sha256": digest_bytes(raw_bytes),
                        "physical_status": physical,
                        "status": observable,
                        "status_source": source,
                        "has_subject_ref": has_subject,
                        "bytes": len(raw_bytes),
                    }
                )
                stream_counts["total"] += 1
                if observable == "total":
                    # "total" is a reserved key: a physical status claiming
                    # it must not corrupt the invariant (counts as exotic).
                    stream_counts["status:total"] = stream_counts.get("status:total", 0) + 1
                elif observable in stream_counts:
                    stream_counts[observable] += 1
                else:
                    # Unrecognized physical status: still observable, still
                    # counted (bucket keeps the total = sum invariant).
                    stream_counts[observable] = 1
                total += 1
            counts[stream] = stream_counts

        offset = _cursor_decode(cursor, revision, total) if cursor is not None else 0
        page = rows[offset : offset + limit]
        next_offset = offset + limit
        complete = next_offset >= total
        return {
            "schema": INVENTORY_SCHEMA,
            "revision": snapshot.revision_id,
            "streams_searched": list(selected),
            "untrusted_memory_data": True,
            "counts": counts,
            "pagination": {
                "complete": complete,
                "next_cursor": (
                    None
                    if complete
                    else _cursor_encode(revision, next_offset)
                ),
                "served_records": len(page),
                "total_records": total,
            },
            "records": page,
        }


__all__ = [
    "DEFAULT_LIMIT",
    "INVENTORY_SCHEMA",
    "MAX_LIMIT",
    "STREAMS",
    "inventory",
]
