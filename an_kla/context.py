"""Deterministic, revision-consistent assembly of globally budgeted context."""

from __future__ import annotations

from typing import Any

from .canonical import exact_sized_payload
from .retrieval import retrieve
from .store import MemoryStore


ASSEMBLY_PROFILE = "context-assembly/v1"


def assemble_context(
    store: MemoryStore,
    query: str,
    budget: int,
    *,
    new_information: str | None = None,
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

    source = retrieve(store, query, 2**63 - 1)
    snapshot = store.snapshot(source["revision"])
    candidates = source["selected"]
    records: list[dict[str, Any]] = []
    # Reserve the largest possible diagnostic before selecting.  Decreasing
    # this count as records enter keeps every intermediate payload feasible and
    # avoids evicting a record at the end without reconsidering skipped items.
    budget_excluded = len(candidates)

    def build(used: int = 0) -> dict[str, Any]:
        exclusions = dict(source["excluded_summary"])
        if budget_excluded:
            exclusions["budget"] = exclusions.get("budget", 0) + budget_excluded
        return {
            "schema": "an-kla/context-assembly-v1",
            "profile": ASSEMBLY_PROFILE,
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

    _required, required_size = exact_sized_payload(build)
    if required_size > budget:
        raise ValueError("budget_too_small_for_required_context")

    for item in candidates:
        budget_excluded -= 1
        records.append(
            {"id": item["id"], "text": item["render"], "score": item["score"]}
        )
        _payload, measured = exact_sized_payload(build)
        if measured > budget:
            records.pop()
            budget_excluded += 1

    payload, measured = exact_sized_payload(build)
    if measured > budget:
        raise ValueError("budget_too_small_for_required_context")
    return payload
