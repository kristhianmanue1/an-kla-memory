"""Revision-consistent governed resume projection (ADR-0023)."""

from __future__ import annotations

from copy import deepcopy
from contextlib import nullcontext
from typing import Any

from .canonical import canonical_json
from .checkpoint_policy import CheckpointPolicyError, validate_working_state
from .retrieval import SCAN_PROFILE, retrieve
from .reader_gate import shared_reader_gate


# Same ceiling as ADR-0034 (context_view.MAX_BUDGET_BYTES).
MAX_BUDGET_BYTES = 1_000_000_000
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
            raise CheckpointPolicyError("invalid_working_state", "checkpoint:keys")
        if not isinstance(checkpoint["revision"], int) or isinstance(
            checkpoint["revision"], bool
        ):
            raise CheckpointPolicyError(
                "invalid_working_state", "checkpoint.revision")
        if not 1 <= checkpoint["revision"] <= snapshot.manifest["revision"]:
            raise CheckpointPolicyError(
                "invalid_working_state", "checkpoint.revision:out_of_range")
        validate_working_state(checkpoint["working_state"])
        return {
            "schema": "an-kla/resume-snapshot-v1",
            "checkpoint_digest": digest,
            "checkpoint_schema": "an-kla/checkpoint-v2",
            "checkpoint": deepcopy(dict(checkpoint)),
        }, []
    if checkpoint.get("schema") != "an-kla/checkpoint-v1":
        raise CheckpointPolicyError("invalid_working_state", "checkpoint.schema")
    return {
        "schema": "an-kla/resume-snapshot-v1",
        "checkpoint_digest": digest,
        "checkpoint_schema": "an-kla/checkpoint-v1",
        "legacy_checkpoint_json": canonical_json(checkpoint).decode("utf-8"),
    }, ["legacy_checkpoint_v1"]


class ResumeBudgetError(ValueError):
    """The snapshot (root, provenance, diagnostics) does not fit the budget.

    ``str(exc)`` keeps the canonical code from ADR-0023; ``detail`` adds the
    smallest budget that fits (#171), computed like ADR-0034's
    ``minimum_budget_bytes`` and never containing memory content.
    """

    def __init__(self, provided: int, minimum: int | None) -> None:
        super().__init__("budget_too_small_for_resume_snapshot")
        self.provided_budget_bytes = provided
        self.minimum_budget_bytes = minimum
        self.detail = (
            f"minimum_budget_bytes={minimum}, provided_budget_bytes={provided}"
            if minimum is not None
            else None
        )


def _minimum_budget(project: Any, provided: int) -> int | None:
    """Smallest budget > ``provided`` whose full projection fits.

    The size depends on the budget itself (``budget_bytes`` and its decimal
    width, plus the budget-driven retrieval), so each candidate is measured by
    running the complete projection.  Per decimal band the candidate only grows
    towards a fixed point; binary search is avoided as in ADR-0034.
    """

    lower = provided + 1
    while lower <= MAX_BUDGET_BYTES:
        band_end = min(MAX_BUDGET_BYTES, 10 ** len(str(lower)) - 1)
        candidate = lower
        for _ in range(64):
            _, size = project(candidate)
            if size <= candidate:
                return candidate
            if size > band_end:
                break
            candidate = size
        else:
            return None
        lower = band_end + 1
    return None


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
    snapshot_value, snapshot_warnings = _snapshot(frozen)

    def project(limit: int) -> tuple[dict[str, Any], int]:
        """Project at ``limit``; returns the result and its exact size."""

        warnings = list(snapshot_warnings)
        retrieval = None
        if query is not None:
            retrieval = retrieve(
                store,
                query,
                limit,
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
            "budget_bytes": limit,
            "used_bytes": 0,
            "snapshot": deepcopy(snapshot_value),
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
        # Root/snapshot that do not fit cannot be rescued by evidence: return
        # early, as before #171, instead of trying every candidate.  The base
        # size is a lower bound, so _minimum_budget still converges on the full
        # projection.
        base = _size_at_fixed_point(result)
        if base > limit:
            return result, base
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
                if _size_at_fixed_point(candidate) <= limit:
                    result = candidate
                else:
                    result["excluded_summary"]["budget"] += 1
        size = _size_at_fixed_point(result)
        while size > limit and result["retrieved_evidence"]:
            result["retrieved_evidence"].pop()
            result["excluded_summary"]["budget"] += 1
            size = _size_at_fixed_point(result)
        return result, size

    result, size = project(budget)
    if size > budget:
        raise ResumeBudgetError(budget, _minimum_budget(project, budget))
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


__all__ = ["ResumeBudgetError", "resume"]
