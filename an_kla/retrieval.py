"""Deterministic alpha retrieval with a byte budget."""

from __future__ import annotations

import re
import sqlite3
from typing import Any, Mapping

from .index import INDEX_PROFILE, detect_fts5, index_resolution, record_text
from .store import MemoryStore


TOKEN = re.compile(r"[\w]+", re.UNICODE)


def _terms(text: str) -> set[str]:
    return {item.casefold() for item in TOKEN.findall(text)}


def _render(record: Mapping[str, Any]) -> str:
    return record_text(dict(record))


def _match_clause(query: str) -> str | None:
    tokens = TOKEN.findall(query)
    return " OR ".join(f'"{token}"' for token in tokens) if tokens else None


def _narrow_with_index(index_path: Any, revision_id: str, clause: str) -> set[str] | None:
    try:
        con = sqlite3.connect(f"file:{index_path}?mode=ro", uri=True)
        try:
            claimed = con.execute("SELECT value FROM metadata WHERE key = ?", ("revision",)).fetchone()
            if not claimed or claimed[0] != revision_id:
                return None
            return {str(row[0]) for row in con.execute("SELECT id FROM facts_fts WHERE facts_fts MATCH ?", (clause,))}
        finally:
            con.close()
    except sqlite3.DatabaseError:
        return None


def retrieve(
    store: MemoryStore,
    query: str,
    budget: int,
    *,
    fixed_overhead_bytes: int = 0,
    per_record_overhead_bytes: int = 0,
) -> dict[str, Any]:
    """Retrieve deterministically, reserving any caller-owned envelope cost.

    ``fixed_overhead_bytes`` and ``per_record_overhead_bytes`` let a transport
    reserve its JSON wrapper before selection.  They must be conservative: the
    transport remains responsible for proving its serialized response fits.
    """
    if budget < 0:
        raise ValueError("negative_budget")
    if fixed_overhead_bytes < 0 or per_record_overhead_bytes < 0:
        raise ValueError("negative_overhead")
    snapshot = store.snapshot()
    query_terms = _terms(query)
    ranked: list[tuple[int, str, Mapping[str, Any], str]] = []
    excluded = {"inactive": 0, "zero_score": 0, "budget": 0, "invalid_record": 0, "no_text": 0}
    for record in snapshot.records["facts"]:
        if record.get("status", record.get("nu", "vigente")) not in {"vigente", "active", None}:
            excluded["inactive"] += 1
            continue
        if not record.get("id"):
            excluded["invalid_record"] += 1
            continue
        rendered = _render(record)
        if not rendered:
            excluded["no_text"] += 1
            continue
        score = len(query_terms & _terms(rendered))
        identifier = str(record["id"])
        ranked.append((score, identifier, record, rendered))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    profile = "scan-fallback/v1"
    degradation = "none"
    clause = _match_clause(query)
    if query_terms and clause:
        if not detect_fts5():
            degradation = "fts5_unavailable"
        else:
            resolution = index_resolution(store, snapshot.revision_id)
            degradation = resolution.status
            if resolution.path is not None:
                narrowed = _narrow_with_index(resolution.path, snapshot.revision_id, clause)
                if narrowed is None:
                    degradation = "index_unresolvable"
                else:
                    ranked = [item for item in ranked if item[1] in narrowed]
                    profile = INDEX_PROFILE
                    degradation = "none"
    selected: list[dict[str, Any]] = []
    used = fixed_overhead_bytes
    for score, identifier, _record, rendered in ranked:
        cost = len(rendered.encode("utf-8")) + per_record_overhead_bytes
        if score == 0:
            excluded["zero_score"] += 1
            continue
        if used + cost > budget:
            excluded["budget"] += 1
            continue
        selected.append({"id": identifier, "score": score, "render": rendered, "cost_bytes": cost})
        used += cost
    return {
        "schema": "an-kla/retrieval-result-v1",
        "revision": snapshot.revision_id,
        "profile": profile,
        "degradation": degradation,
        "budget_bytes": budget,
        "used_bytes": used,
        "reserved_overhead_bytes": {
            "fixed": fixed_overhead_bytes,
            "per_record": per_record_overhead_bytes,
        },
        "excluded_summary": {key: value for key, value in excluded.items() if value},
        "selected": selected,
    }
