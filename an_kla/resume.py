"""Revision-consistent governed resume projection (ADR-0023)."""

from __future__ import annotations

from copy import deepcopy
from contextlib import nullcontext
from typing import Any

from .canonical import canonical_json
from .checkpoint_policy import CheckpointPolicyError, validate_working_state
from .retrieval import SCAN_PROFILE, retrieve
from .reader_gate import shared_reader_gate


EXCLUDED = ("inactive", "zero_score", "budget", "invalid_record", "no_text")


def _size_at_fixed_point(value: dict[str, Any]) -> int:
    observed = -1
    for _ in range(32):
        value["used_bytes"] = max(observed, 0)
        actual = len(canonical_json(value))
        if actual == observed:
            return actual
        observed = actual
    raise ValueError("resume_size_not_convergent")


def _snapshot(snapshot: Any) -> tuple[dict[str, Any], list[str]]:
    checkpoint = snapshot.checkpoint
    digest = snapshot.manifest["checkpoint"]
    if checkpoint.get("schema") == "an-kla/checkpoint-v2":
        if set(checkpoint) != {"schema", "revision", "working_state"}:
            raise CheckpointPolicyError("invalid_working_state")
        if not isinstance(checkpoint["revision"], int) or isinstance(
            checkpoint["revision"], bool
        ):
            raise CheckpointPolicyError("invalid_working_state")
        if not 1 <= checkpoint["revision"] <= snapshot.manifest["revision"]:
            raise CheckpointPolicyError("invalid_working_state")
        validate_working_state(checkpoint["working_state"])
        return {
            "schema": "an-kla/resume-snapshot-v1",
            "checkpoint_digest": digest,
            "checkpoint_schema": "an-kla/checkpoint-v2",
            "checkpoint": deepcopy(dict(checkpoint)),
        }, []
    if checkpoint.get("schema") != "an-kla/checkpoint-v1":
        raise CheckpointPolicyError("invalid_working_state")
    return {
        "schema": "an-kla/resume-snapshot-v1",
        "checkpoint_digest": digest,
        "checkpoint_schema": "an-kla/checkpoint-v1",
        "legacy_checkpoint_json": canonical_json(checkpoint).decode("utf-8"),
    }, ["legacy_checkpoint_v1"]


def _resume_under_gate(
    store: Any,
    budget: int,
    *,
    query: str | None = None,
    profile: str = SCAN_PROFILE,
) -> dict[str, Any]:
    if not isinstance(budget, int) or isinstance(budget, bool) or budget < 0:
        raise ValueError("invalid_resume_budget")
    if query is not None and (not isinstance(query, str) or not query):
        raise ValueError("invalid_resume_query")
    revision = store.read_current()
    frozen = store.snapshot(revision)
    snapshot_value, warnings = _snapshot(frozen)
    retrieval = None
    if query is not None:
        retrieval = retrieve(
            store,
            query,
            budget,
            profile=profile,
            streams=("facts", "events", "episodes"),
            revision_id=revision,
        )
        if retrieval["degradation"] != "none":
            warnings.append("retrieval_degraded_to_scan")
    source = retrieval["profile"] if retrieval is not None else "disabled"
    result: dict[str, Any] = {
        "schema": "an-kla/resume-v1",
        "untrusted_memory_data": True,
        "revision": revision,
        "budget_bytes": budget,
        "used_bytes": 0,
        "snapshot": snapshot_value,
        "live_delta": None,
        "retrieved_evidence": [],
        "warnings": sorted(set(warnings)),
        "provenance": {
            "memory": {"source": "revision_snapshot", "revision": revision},
            "retrieval": {
                "source": source,
                "revision": revision if retrieval is not None else None,
                "query": "caller_asserted" if retrieval is not None else "disabled",
            },
            "live_delta": {"source": "unavailable"},
        },
        "excluded_summary": {
            key: int(retrieval["excluded_summary"].get(key, 0)) if retrieval else 0
            for key in EXCLUDED
        },
    }
    if _size_at_fixed_point(result) > budget:
        raise ValueError("budget_too_small_for_resume_snapshot")
    if retrieval is not None:
        for item in retrieval["selected"]:
            evidence = {
                "schema": "an-kla/resume-evidence-v1",
                "source": "retrieval-result-v1",
                "revision": revision,
                "id": item["id"],
                "stream": item["stream"],
                "score": item["score"],
                "render": item["render"],
                "cost_bytes": item["cost_bytes"],
            }
            candidate = deepcopy(result)
            candidate["retrieved_evidence"].append(evidence)
            if _size_at_fixed_point(candidate) <= budget:
                result = candidate
            else:
                result["excluded_summary"]["budget"] += 1
    size = _size_at_fixed_point(result)
    while size > budget and result["retrieved_evidence"]:
        result["retrieved_evidence"].pop()
        result["excluded_summary"]["budget"] += 1
        size = _size_at_fixed_point(result)
    if size > budget:
        raise ValueError("budget_too_small_for_resume_snapshot")
    return result


def resume(
    store: Any,
    budget: int,
    *,
    query: str | None = None,
    profile: str = SCAN_PROFILE,
) -> dict[str, Any]:
    """Hold one reader lease from CURRENT through checkpoint and evidence."""

    gate = shared_reader_gate(store) if hasattr(store, "root") else nullcontext()
    with gate:
        return _resume_under_gate(store, budget, query=query, profile=profile)


__all__ = ["resume"]
