"""Deterministic child-manifest construction across revision generations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .canonical import bare_digest
from .transaction_attempts import TransactionError


def build_child_manifest(
    *, base: Mapping[str, Any], revision: int, parent: str,
    segment_ids: Mapping[str, list[str]], checkpoint: str, transaction_id: str,
    operation: str, store_identity: str | None,
    supersedes_map: list[dict[str, Any]], refutations_map: list[dict[str, Any]],
) -> dict[str, Any]:
    use_v3 = base.get("schema") == "an-kla/revision-v3"
    use_v2 = not use_v3 and (
        base.get("schema") == "an-kla/revision-v2" or operation == "refute"
    )
    manifest: dict[str, Any] = {
        "schema": (
            "an-kla/revision-v3" if use_v3
            else "an-kla/revision-v2" if use_v2
            else "an-kla/revision-v1"
        ),
        "revision": revision,
        "parent": parent,
        "facts_segments": segment_ids["facts"],
        "events_segments": segment_ids["events"],
        "episodes_segments": segment_ids["episodes"],
        "checkpoint": checkpoint,
        "transaction_id": transaction_id,
        "canonicalization": "canonical-json/v1",
        "integrity_claim": "content_identity_not_truth_or_authorship",
    }
    if store_identity is not None:
        bare_digest(store_identity)
        manifest["store_identity"] = store_identity
    if supersedes_map or use_v3:
        manifest["supersedes_map"] = supersedes_map
    if use_v2 or use_v3:
        if store_identity is None or (use_v2 and not refutations_map):
            raise TransactionError("revision_transition_invalid")
        manifest["features"] = (
            ["refutations/v1", "compaction/v1"] if use_v3
            else ["refutations/v1"]
        )
        manifest["refutations_map"] = refutations_map
    if use_v3:
        manifest["compaction_epoch"] = deepcopy(dict(base["compaction_epoch"]))
    return manifest


__all__ = ["build_child_manifest"]
