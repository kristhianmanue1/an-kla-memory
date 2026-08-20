"""Pure governed checkpoint contracts for ADR-0023."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Mapping

from .canonical import bare_digest, canonical_json, digest_json
from .temporal import TemporalError, format_utc, parse_verified_at


PROFILE = "checkpoint-policy/v1"
FIELDS = (
    "objective", "phase", "next_step", "decisions", "blockers", "evidence",
    "source_state", "captured_at",
)
PROVENANCE = {"caller_asserted", "unavailable"}
SOURCE_PROFILES = ("none/v1", "git/v1")
# Full Git object id: SHA-1 (40 hex) or SHA-256 (64 hex) repositories.
GIT_OBJECT_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
REASONS = {
    "authority_binding_mismatch", "authority_scope_mismatch",
    "unresolved_authority", "invalid_checkpoint_provenance",
    "checkpoint_unchanged",
}
_CONFIG = {
    "schema": "an-kla/checkpoint-policy-config-v1",
    "profile": PROFILE,
    "fields": list(FIELDS),
    "accepted_provenance": sorted(PROVENANCE),
    "source_profiles": list(SOURCE_PROFILES),
    "maximum_items_per_list": 50,
    "maximum_item_bytes": 8192,
    "maximum_working_state_bytes": 65536,
    "tool_observed_adapter": False,
}


class CheckpointPolicyError(ValueError):
    pass


def policy_fingerprint() -> str:
    return digest_json(_CONFIG)


def _exact(value: Any, keys: set[str], code: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise CheckpointPolicyError(code)
    return value


def _digest(value: Any, code: str) -> str:
    if not isinstance(value, str):
        raise CheckpointPolicyError(code)
    try:
        bare_digest(value)
    except ValueError as exc:
        raise CheckpointPolicyError(code) from exc
    return value


def _field(value: Any, *, timestamp: bool = False) -> None:
    checked = _exact(value, {"value", "provenance"}, "invalid_working_state")
    if checked["provenance"] not in PROVENANCE:
        if checked["provenance"] == "tool_observed":
            raise CheckpointPolicyError("tool_observed_requires_adapter")
        raise CheckpointPolicyError("invalid_checkpoint_provenance")
    if checked["provenance"] == "unavailable":
        if checked["value"] is not None:
            raise CheckpointPolicyError("invalid_checkpoint_provenance")
        return
    if checked["value"] is None:
        return
    if not isinstance(checked["value"], str):
        raise CheckpointPolicyError("invalid_working_state")
    if timestamp:
        try:
            parsed = parse_verified_at(checked["value"])
        except TemporalError as exc:
            raise CheckpointPolicyError("invalid_working_state") from exc
        if format_utc(parsed) != checked["value"]:
            raise CheckpointPolicyError("invalid_working_state")


def _items(value: Any) -> None:
    if not isinstance(value, list) or len(value) > 50:
        raise CheckpointPolicyError("invalid_working_state")
    seen: set[str] = set()
    for raw in value:
        item = _exact(raw, {"id", "value", "provenance"}, "invalid_working_state")
        if not isinstance(item["id"], str) or not item["id"] or item["id"] in seen:
            raise CheckpointPolicyError("invalid_working_state")
        seen.add(item["id"])
        if item["provenance"] not in PROVENANCE:
            if item["provenance"] == "tool_observed":
                raise CheckpointPolicyError("tool_observed_requires_adapter")
            raise CheckpointPolicyError("invalid_checkpoint_provenance")
        if item["provenance"] == "unavailable" and item["value"] is not None:
            raise CheckpointPolicyError("invalid_checkpoint_provenance")
        try:
            if len(canonical_json(item["value"])) > 8192:
                raise CheckpointPolicyError("invalid_working_state")
        except (TypeError, ValueError, OverflowError) as exc:
            raise CheckpointPolicyError("invalid_working_state") from exc


def _git_source_field(value: Any, *, object_id: bool) -> None:
    """Validate a git/v1 source field: caller_asserted, never unavailable.

    ADR-0038: choosing profile git/v1 declares caller-observed values;
    ``unavailable`` belongs to none/v1. ``tool_observed`` still requires
    a host adapter.
    """

    checked = _exact(value, {"value", "provenance"}, "invalid_working_state")
    if checked["provenance"] == "tool_observed":
        raise CheckpointPolicyError("tool_observed_requires_adapter")
    if checked["provenance"] != "caller_asserted":
        raise CheckpointPolicyError("invalid_checkpoint_provenance")
    raw = checked["value"]
    if object_id:
        if not isinstance(raw, str) or not GIT_OBJECT_ID.fullmatch(raw):
            raise CheckpointPolicyError("invalid_working_state")
    elif raw is not None and not isinstance(raw, str):
        raise CheckpointPolicyError("invalid_working_state")


def validate_working_state(value: Mapping[str, Any]) -> None:
    state = _exact(
        value,
        {"schema", "objective", "phase", "next_step", "decisions", "blockers",
         "evidence", "source_state", "captured_at", "supersedes_checkpoint"},
        "invalid_working_state",
    )
    if state["schema"] != "an-kla/working-state-v2":
        raise CheckpointPolicyError("invalid_working_state")
    for name in ("objective", "phase", "next_step"):
        _field(state[name])
    for name in ("decisions", "blockers", "evidence"):
        _items(state[name])
    source = _exact(
        state["source_state"], {"profile", "head", "branch", "dirty_digest"},
        "invalid_working_state",
    )
    if source["profile"] == "none/v1":
        for name in ("head", "branch", "dirty_digest"):
            _field(source[name])
            if source[name] != {"value": None, "provenance": "unavailable"}:
                raise CheckpointPolicyError("invalid_checkpoint_provenance")
    elif source["profile"] == "git/v1":
        _git_source_field(source["head"], object_id=True)
        _git_source_field(source["branch"], object_id=False)
        _git_source_field(source["dirty_digest"], object_id=False)
    else:
        raise CheckpointPolicyError("invalid_working_state")
    _field(state["captured_at"], timestamp=True)
    _digest(state["supersedes_checkpoint"], "invalid_working_state")
    try:
        if len(canonical_json(state)) > 65536:
            raise CheckpointPolicyError("invalid_working_state")
    except (TypeError, ValueError, OverflowError) as exc:
        raise CheckpointPolicyError("invalid_working_state") from exc


def validate_proposal(proposal: Mapping[str, Any]) -> None:
    value = _exact(
        proposal,
        {"schema", "base_revision", "parent_checkpoint", "working_state"},
        "invalid_working_state",
    )
    if value["schema"] != "an-kla/checkpoint-proposal-v1":
        raise CheckpointPolicyError("invalid_working_state")
    _digest(value["base_revision"], "invalid_working_state")
    _digest(value["parent_checkpoint"], "invalid_working_state")
    validate_working_state(value["working_state"])
    if value["working_state"]["supersedes_checkpoint"] != value["parent_checkpoint"]:
        raise CheckpointPolicyError("checkpoint_parent_mismatch")


def _validate_evidence(value: Any) -> None:
    if not isinstance(value, dict) or not {"kind", "id", "resolution"}.issubset(value):
        raise CheckpointPolicyError("invalid_checkpoint_authority")
    if not set(value).issubset({"kind", "id", "resolution", "sha256"}):
        raise CheckpointPolicyError("invalid_checkpoint_authority")
    if value["kind"] not in {"artifact", "event", "revision", "external"}:
        raise CheckpointPolicyError("invalid_checkpoint_authority")
    if not isinstance(value["id"], str) or not value["id"]:
        raise CheckpointPolicyError("invalid_checkpoint_authority")
    if value["resolution"] not in {"verified", "unresolved", "invalid"}:
        raise CheckpointPolicyError("invalid_checkpoint_authority")
    if value["resolution"] == "verified" and "sha256" not in value:
        raise CheckpointPolicyError("invalid_checkpoint_authority")
    if "sha256" in value:
        _digest(value["sha256"], "invalid_checkpoint_authority")


def validate_authority(authority: Mapping[str, Any]) -> None:
    value = _exact(
        authority,
        {"schema", "proposal_sha256", "base_revision", "authority_class", "issuer",
         "evidence", "scope"},
        "invalid_checkpoint_authority",
    )
    if value["schema"] != "an-kla/checkpoint-authority-v1":
        raise CheckpointPolicyError("invalid_checkpoint_authority")
    _digest(value["proposal_sha256"], "invalid_checkpoint_authority")
    _digest(value["base_revision"], "invalid_checkpoint_authority")
    classes = {"tool_observed": "tool", "channel_confirmed": "channel",
               "model_derived": "model", "unresolved": "unknown"}
    if value["authority_class"] == "tool_observed":
        raise CheckpointPolicyError("tool_observed_requires_adapter")
    if value["authority_class"] not in classes:
        raise CheckpointPolicyError("invalid_checkpoint_authority")
    issuer = _exact(
        value["issuer"], {"kind", "id", "configuration_fingerprint"},
        "invalid_checkpoint_authority",
    )
    if issuer["kind"] != classes[value["authority_class"]]:
        raise CheckpointPolicyError("invalid_checkpoint_authority")
    if not isinstance(issuer["id"], str) or not issuer["id"]:
        raise CheckpointPolicyError("invalid_checkpoint_authority")
    _digest(issuer["configuration_fingerprint"], "invalid_checkpoint_authority")
    if not isinstance(value["evidence"], list):
        raise CheckpointPolicyError("invalid_checkpoint_authority")
    for item in value["evidence"]:
        _validate_evidence(item)
    scope = _exact(value["scope"], {"operation", "fields"}, "invalid_checkpoint_authority")
    if scope["operation"] != "checkpoint" or not isinstance(scope["fields"], list):
        raise CheckpointPolicyError("invalid_checkpoint_authority")
    if (
        not scope["fields"]
        or scope["fields"] != sorted(scope["fields"], key=lambda item: item.encode("utf-8"))
        or len(scope["fields"]) != len(set(scope["fields"]))
        or any(item not in FIELDS for item in scope["fields"])
    ):
        raise CheckpointPolicyError("invalid_checkpoint_authority")


def evaluate(proposal: Mapping[str, Any], authority: Mapping[str, Any]) -> dict[str, Any]:
    validate_proposal(proposal)
    validate_authority(authority)
    proposal_hash = digest_json(proposal)
    authority_hash = digest_json(authority)
    reasons: set[str] = set()
    if authority["proposal_sha256"] != proposal_hash or authority["base_revision"] != proposal["base_revision"]:
        reasons.add("authority_binding_mismatch")
    if set(authority["scope"]["fields"]) != set(FIELDS):
        reasons.add("authority_scope_mismatch")
    if authority["authority_class"] == "unresolved":
        reasons.add("unresolved_authority")
    decision = "skip" if reasons else "write"
    return {
        "schema": "an-kla/checkpoint-decision-v1",
        "proposal_sha256": proposal_hash,
        "authority_sha256": authority_hash,
        "decision": decision,
        "reasons": sorted(reasons),
    }


def build_plan(
    proposal: Mapping[str, Any], authority: Mapping[str, Any], decision: Mapping[str, Any],
    *, revision: int,
) -> dict[str, Any]:
    expected = evaluate(proposal, authority)
    unchanged_skip = (
        expected["decision"] == "write"
        and dict(decision) == {
            **expected,
            "decision": "skip",
            "reasons": ["checkpoint_unchanged"],
        }
    )
    if (
        (dict(decision) != expected and not unchanged_skip)
        or not isinstance(revision, int)
        or isinstance(revision, bool)
        or revision < 1
    ):
        raise CheckpointPolicyError("invalid_checkpoint_plan")
    checkpoint = {
        "schema": "an-kla/checkpoint-v2",
        "revision": revision,
        "working_state": deepcopy(dict(proposal["working_state"])),
    }
    core = {
        "base_revision": proposal["base_revision"],
        "parent_checkpoint": proposal["parent_checkpoint"],
        "proposal_sha256": digest_json(proposal),
        "authority_sha256": digest_json(authority),
        "policy_fingerprint": policy_fingerprint(),
        "decision_sha256": digest_json(decision),
        "checkpoint_sha256": digest_json(checkpoint),
    }
    return {
        "schema": "an-kla/checkpoint-plan-v1",
        "core": core,
        "checkpoint": checkpoint,
        "plan_fingerprint": digest_json(core),
    }


def verify_plan(
    plan: Mapping[str, Any], proposal: Mapping[str, Any], authority: Mapping[str, Any],
    decision: Mapping[str, Any], *, revision: int,
) -> None:
    expected = build_plan(proposal, authority, decision, revision=revision)
    if dict(plan) != expected:
        raise CheckpointPolicyError("invalid_checkpoint_plan")


__all__ = [
    "CheckpointPolicyError", "FIELDS", "PROFILE", "SOURCE_PROFILES",
    "build_plan", "evaluate", "policy_fingerprint", "validate_authority",
    "validate_proposal", "validate_working_state", "verify_plan",
]
