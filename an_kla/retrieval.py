"""Deterministic beta retrieval with a byte budget."""

from __future__ import annotations

from datetime import datetime, timezone
from contextlib import nullcontext
import re
import sqlite3
from typing import Any, Mapping

from .index import (
    INDEX_PROFILE,
    detect_fts5,
    index_integrity_status,
    index_resolution,
    record_text,
)
from .store import MemoryStore, STREAMS
from .reader_gate import shared_reader_gate
from .temporal import (
    FRESHNESS_PROFILE,
    FRESHNESS_SEMANTICS,
    FRESHNESS_SOURCE_FIELD,
    TemporalError,
    format_utc,
    normalize_freshness_now,
    project_record_freshness,
    validate_stale_after_days,
)


TOKEN = re.compile(r"[\w]+", re.UNICODE)
SCAN_PROFILE = "scan-fallback/v1"
SUPPORTED_PROFILES = frozenset({SCAN_PROFILE, INDEX_PROFILE})
# Default keeps the historical beta contract so existing consumers (e.g.
# argos-epistemic) keep seeing ``streams_searched == ["facts"]``.  Multi-stream
# retrieval is opt-in via the ``streams`` argument.
DEFAULT_STREAMS = ("facts",)
EXCLUDED_DETAIL_CAP = 50


def _terms(text: str) -> set[str]:
    return {item.casefold() for item in TOKEN.findall(text)}


def _render(record: Mapping[str, Any]) -> str:
    return record_text(dict(record))


def _match_clause(query: str) -> str | None:
    tokens = TOKEN.findall(query)
    return " OR ".join(f'"{token}"' for token in tokens) if tokens else None


def _narrow_with_index(
    index_path: Any, revision_id: str, clause: str, streams: tuple[str, ...]
) -> set[str] | None:
    try:
        con = sqlite3.connect(f"file:{index_path}?mode=ro", uri=True)
        try:
            claimed = con.execute("SELECT value FROM metadata WHERE key = ?", ("revision",)).fetchone()
            if not claimed or claimed[0] != revision_id:
                return None
            narrowed: set[str] = set()
            for stream in streams:
                table = f"{stream}_fts"
                try:
                    rows = con.execute(
                        f"SELECT id FROM {table} WHERE {table} MATCH ?", (clause,)
                    ).fetchall()
                except sqlite3.DatabaseError:
                    # Index v1 only exposed ``facts_fts``; missing tables for
                    # other streams degrade to scan for those streams.
                    continue
                narrowed.update(str(row[0]) for row in rows)
            return narrowed
        finally:
            con.close()
    except sqlite3.DatabaseError:
        return None


def _retrieve_under_gate(
    store: MemoryStore,
    query: str,
    budget: int,
    *,
    fixed_overhead_bytes: int = 0,
    per_record_overhead_bytes: int = 0,
    profile: str = SCAN_PROFILE,
    streams: tuple[str, ...] | list[str] | None = None,
    freshness_profile: str | None = None,
    now: datetime | None = None,
    stale_after_days: int | None = None,
    revision_id: str | None = None,
) -> dict[str, Any]:
    """Retrieve deterministically, reserving any caller-owned envelope cost.

    ``fixed_overhead_bytes`` and ``per_record_overhead_bytes`` let a transport
    reserve its JSON wrapper before selection.  They must be conservative: the
    transport remains responsible for proving its serialized response fits.

    ``streams`` selects which record streams are scanned.  Defaults to
    ``("facts",)`` to preserve the historical beta contract; pass e.g.
    ``("facts", "events", "episodes")`` for multi-stream retrieval.
    """

    if budget < 0:
        raise ValueError("negative_budget")
    if fixed_overhead_bytes < 0 or per_record_overhead_bytes < 0:
        raise ValueError("negative_overhead")
    if fixed_overhead_bytes > budget:
        raise ValueError("fixed_overhead_exceeds_budget")
    if profile not in SUPPORTED_PROFILES:
        raise ValueError("unsupported_retrieval_profile")
    freshness_now: datetime | None = None
    freshness_threshold: int | None = None
    if freshness_profile is None:
        if now is not None or stale_after_days is not None:
            raise TemporalError("freshness_profile_required")
    elif freshness_profile != FRESHNESS_PROFILE:
        raise TemporalError("unsupported_freshness_profile")
    else:
        freshness_now = normalize_freshness_now(
            datetime.now(timezone.utc) if now is None else now
        )
        freshness_threshold = validate_stale_after_days(stale_after_days)
    selected_streams = tuple(streams) if streams is not None else DEFAULT_STREAMS
    if not selected_streams or any(s not in STREAMS for s in selected_streams):
        raise ValueError("unsupported_retrieval_stream")
    # De-duplicate while preserving caller order: ``--streams facts,facts``
    # must not produce duplicate records in the output.
    seen_streams: set[str] = set()
    deduped: list[str] = []
    for s in selected_streams:
        if s not in seen_streams:
            seen_streams.add(s)
            deduped.append(s)
    selected_streams = tuple(deduped)
    snapshot = store.snapshot() if revision_id is None else store.snapshot(revision_id)
    query_terms = _terms(query)
    ranked: list[tuple[int, str, Mapping[str, Any], str, str]] = []
    excluded: dict[str, int] = {
        "inactive": 0,
        "zero_score": 0,
        "budget": 0,
        "invalid_record": 0,
        "no_text": 0,
    }
    # Track IDs for every exclusion reason so the operator can debug silent
    # drops uniformly; counters without an entry here simply aren't tracked.
    excluded_detail: dict[str, list[str]] = {
        "inactive": [],
        "zero_score": [],
        "budget": [],
        "invalid_record": [],
        "no_text": [],
    }
    for stream in selected_streams:
        for record in snapshot.records[stream]:
            if record.get("status", record.get("nu", "vigente")) not in {"vigente", "active", None}:
                excluded["inactive"] += 1
                if len(excluded_detail["inactive"]) < EXCLUDED_DETAIL_CAP:
                    excluded_detail["inactive"].append(str(record.get("id", "")))
                continue
            if not record.get("id"):
                excluded["invalid_record"] += 1
                continue
            rendered = _render(record)
            if not rendered:
                excluded["no_text"] += 1
                if len(excluded_detail["no_text"]) < EXCLUDED_DETAIL_CAP:
                    excluded_detail["no_text"].append(str(record["id"]))
                continue
            score = len(query_terms & _terms(rendered))
            identifier = str(record["id"])
            ranked.append((score, identifier, record, rendered, stream))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    actual_profile = SCAN_PROFILE
    degradation = "none"
    clause = _match_clause(query)
    if profile == INDEX_PROFILE and query_terms and clause:
        if not detect_fts5():
            degradation = "fts5_unavailable"
        else:
            resolution = index_resolution(store, snapshot.revision_id)
            degradation = resolution.status
            if resolution.path is not None:
                integrity = index_integrity_status(resolution.path)
                if integrity != "none":
                    degradation = integrity
                else:
                    narrowed = _narrow_with_index(
                        resolution.path, snapshot.revision_id, clause, selected_streams
                    )
                    if narrowed is None:
                        degradation = "index_unresolvable"
                    elif any(
                        score > 0 and identifier not in narrowed
                        for score, identifier, _record, _rendered, _stream in ranked
                    ):
                        degradation = "index_candidate_mismatch"
                    else:
                        ranked = [item for item in ranked if item[1] in narrowed]
                        actual_profile = INDEX_PROFILE
                        degradation = "none"
    selected: list[dict[str, Any]] = []
    used = fixed_overhead_bytes
    for score, identifier, _record, rendered, stream in ranked:
        cost = len(rendered.encode("utf-8")) + per_record_overhead_bytes
        if score == 0:
            excluded["zero_score"] += 1
            if len(excluded_detail["zero_score"]) < EXCLUDED_DETAIL_CAP:
                excluded_detail["zero_score"].append(identifier)
            continue
        if used + cost > budget:
            excluded["budget"] += 1
            if len(excluded_detail["budget"]) < EXCLUDED_DETAIL_CAP:
                excluded_detail["budget"].append(identifier)
            continue
        item = {
            "id": identifier,
            "stream": stream,
            "score": score,
            "render": rendered,
            "cost_bytes": cost,
        }
        if freshness_now is not None:
            item.update(
                project_record_freshness(
                    _record,
                    freshness_now,
                    freshness_threshold,
                )
            )
        selected.append(item)
        used += cost
    excluded_summary = {key: value for key, value in excluded.items() if value}
    truncated: dict[str, bool] = {}
    visible_detail: dict[str, list[str]] = {}
    for key, ids in excluded_detail.items():
        if not ids:
            continue
        truncated[key] = excluded[key] > len(ids)
        visible_detail[key] = ids
    result = {
        "schema": "an-kla/retrieval-result-v1",
        "revision": snapshot.revision_id,
        "requested_profile": profile,
        "profile": actual_profile,
        "degradation": degradation,
        "streams_searched": list(selected_streams),
        "budget_bytes": budget,
        "used_bytes": used,
        "reserved_overhead_bytes": {
            "fixed": fixed_overhead_bytes,
            "per_record": per_record_overhead_bytes,
        },
        "excluded_summary": excluded_summary,
        "excluded_detail": {
            "ids": visible_detail,
            "truncated": truncated,
            "cap": EXCLUDED_DETAIL_CAP,
        },
        "selected": selected,
    }
    if freshness_now is not None:
        result["schema"] = "an-kla/retrieval-result-v2"
        result["freshness_profile"] = FRESHNESS_PROFILE
        result["freshness"] = {
            "semantics": FRESHNESS_SEMANTICS,
            "source_field": FRESHNESS_SOURCE_FIELD,
            "computed_at": format_utc(freshness_now),
            "stale_after_days": freshness_threshold,
        }
    return result


def retrieve(
    store: MemoryStore,
    query: str,
    budget: int,
    *,
    fixed_overhead_bytes: int = 0,
    per_record_overhead_bytes: int = 0,
    profile: str = SCAN_PROFILE,
    streams: tuple[str, ...] | list[str] | None = None,
    freshness_profile: str | None = None,
    now: datetime | None = None,
    stale_after_days: int | None = None,
    revision_id: str | None = None,
) -> dict[str, Any]:
    """Hold the archival reader lease through scan and index consumption."""

    gate = shared_reader_gate(store) if hasattr(store, "root") else nullcontext()
    with gate:
        return _retrieve_under_gate(
            store,
            query,
            budget,
            fixed_overhead_bytes=fixed_overhead_bytes,
            per_record_overhead_bytes=per_record_overhead_bytes,
            profile=profile,
            streams=streams,
            freshness_profile=freshness_profile,
            now=now,
            stale_after_days=stale_after_days,
            revision_id=revision_id,
        )
