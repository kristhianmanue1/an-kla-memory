"""Deterministic, revision-consistent assembly of globally budgeted context."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .canonical import exact_sized_payload
from .retrieval import retrieve
from .store import MemoryStore
from .temporal import (
    FRESHNESS_PROFILE,
    FRESHNESS_PROJECTION_KEYS,
    summarize_freshness,
)


ASSEMBLY_PROFILE = "context-assembly/v1"
ASSEMBLY_PROFILE_V2 = "context-assembly/v2"


def assemble_context(
    store: MemoryStore,
    query: str,
    budget: int,
    *,
    new_information: str | None = None,
    freshness_profile: str | None = None,
    now: datetime | None = None,
    stale_after_days: int | None = None,
) -> dict[str, Any]:
    """Assemble checkpoint, caller information and retrieval under one budget.

    The checkpoint and ``new_information`` are indivisible required sections.
    Retrieved records are optional and fill the remaining exact UTF-8 budget.
    All memory objects are read from the revision selected by retrieval.
    """
    if not isinstance(query, str):
        raise ValueError("invalid_context_query")
    if not isinstance(budget, int) or isinstance(budget, bool):
        raise ValueError("invalid_context_budget")
    if budget < 0:
        raise ValueError("negative_budget")
    if new_information is not None and not isinstance(new_information, str):
        raise ValueError("invalid_new_information")

    if freshness_profile is None and now is None and stale_after_days is None:
        source = retrieve(store, query, 2**63 - 1)
    else:
        source = retrieve(
            store,
            query,
            2**63 - 1,
            freshness_profile=freshness_profile,
            now=now,
            stale_after_days=stale_after_days,
        )
    snapshot = store.snapshot(source["revision"])
    candidates = source["selected"]
    freshness_enabled = source["schema"] == "an-kla/retrieval-result-v2"
    records: list[dict[str, Any]] = []
    # Reserve the largest possible diagnostic before selecting.  Decreasing
    # this count as records enter keeps every intermediate payload feasible and
    # avoids evicting a record at the end without reconsidering skipped items.
    budget_excluded = len(candidates)

    def build(used: int = 0) -> dict[str, Any]:
        exclusions = dict(source["excluded_summary"])
        if budget_excluded:
            exclusions["budget"] = exclusions.get("budget", 0) + budget_excluded
        payload = {
            "schema": (
                "an-kla/context-assembly-v2"
                if freshness_enabled
                else "an-kla/context-assembly-v1"
            ),
            "profile": ASSEMBLY_PROFILE_V2 if freshness_enabled else ASSEMBLY_PROFILE,
            "canonicalization": "canonical-json/v1",
            "untrusted_memory_data": True,
            "host_framing_unmeasured": True,
            "revision": source["revision"],
            "budget_bytes": budget,
            "used_bytes": used,
            "section_provenance": {
                "working_state": "memory_store",
                "new_information": "caller",
                "retrieved_records": "memory_store",
            },
            "sections": {
                "working_state": snapshot.checkpoint,
                "new_information": new_information,
                "retrieved_records": records,
            },
            "excluded_summary": exclusions,
        }
        if freshness_enabled:
            payload["freshness_profile"] = FRESHNESS_PROFILE
            # ADR-0037: counts must describe the records this payload
            # actually serves after the global budget cut, not the
            # unbounded retrieval population.
            payload["freshness"] = {
                **source["freshness"],
                **summarize_freshness(records),
            }
        return payload

    _required, required_size = exact_sized_payload(build)
    if required_size > budget:
        raise ValueError("budget_too_small_for_required_context")

    for item in candidates:
        budget_excluded -= 1
        record = {"id": item["id"], "text": item["render"], "score": item["score"]}
        if freshness_enabled:
            record.update(
                {key: item[key] for key in FRESHNESS_PROJECTION_KEYS if key in item}
            )
        records.append(record)
        _payload, measured = exact_sized_payload(build)
        if measured > budget:
            records.pop()
            budget_excluded += 1

    payload, measured = exact_sized_payload(build)
    if measured > budget:
        raise ValueError("budget_too_small_for_required_context")
    return payload
