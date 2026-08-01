"""Deterministic alpha retrieval with a byte budget."""

from __future__ import annotations

import re
from typing import Any, Mapping

from .store import MemoryStore


TOKEN = re.compile(r"[\w]+", re.UNICODE)


def _terms(text: str) -> set[str]:
    return {item.casefold() for item in TOKEN.findall(text)}


def _render(record: Mapping[str, Any]) -> str:
    payload = record.get("payload", record)
    return str(payload.get("text", payload.get("summary", payload.get("p", "")))) if isinstance(payload, Mapping) else str(payload)


def retrieve(store: MemoryStore, query: str, budget: int) -> dict[str, Any]:
    if budget < 0:
        raise ValueError("negative_budget")
    snapshot = store.snapshot()
    query_terms = _terms(query)
    ranked: list[tuple[int, str, Mapping[str, Any], str]] = []
    for record in snapshot.records["facts"]:
        if record.get("status", record.get("nu", "vigente")) not in {"vigente", "active", None}:
            continue
        rendered = _render(record)
        score = len(query_terms & _terms(rendered))
        identifier = str(record["id"])
        ranked.append((score, identifier, record, rendered))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    selected: list[dict[str, Any]] = []
    used = 0
    for score, identifier, _record, rendered in ranked:
        cost = len(rendered.encode("utf-8"))
        if score == 0 or used + cost > budget:
            continue
        selected.append({"id": identifier, "score": score, "render": rendered, "cost_bytes": cost})
        used += cost
    return {
        "schema": "an-kla/retrieval-result-v1",
        "revision": snapshot.revision_id,
        "profile": "scan-fallback/v1",
        "budget_bytes": budget,
        "used_bytes": used,
        "selected": selected,
    }
