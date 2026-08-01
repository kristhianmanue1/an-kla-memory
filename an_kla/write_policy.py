"""Pure deterministic write-policy core.

This module performs no I/O.  It validates a candidate proposal and a separate
authority object, emits a deterministic decision, and binds an executable plan
by canonical hashes.  Moving ``CURRENT`` remains the store's responsibility.
"""

from __future__ import annotations

from copy import deepcopy
import math
import re
from typing import Any, Mapping

from .canonical import canonical_json, digest_json


WRITE_POLICY_PROFILE = "write-policy/v1"
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_REASON_CODE = re.compile(r"^[a-z][a-z0-9_]*$")
_STREAMS = frozenset({"facts", "events", "episodes"})
_OPERATIONS = frozenset({"add", "supersede", "refute", "decay"})
_REPRESENTATIONS = frozenset({"full", "summary"})
_AUTHORITY_CLASSES = frozenset(
    {
        "tool_observed",
        "channel_confirmed",
        "model_derived",
        "derived_from_retrieval",
        "unresolved",
    }
)
_SELF_ASSERTED_AUTHORITY_KEYS = frozenset(
    {
        "authority",
        "authority_class",
        "candidate_risk",
        "confidence",
        "human_confirmed",
        "risk",
        "trusted",
        "verified",
    }
)
_MAX_JSON_DEPTH = 64
_MAX_JSON_NODES = 10_000

_POLICY_CONFIGURATION = {
    "schema": "an-kla/write-policy-config-v1",
    "profile": WRITE_POLICY_PROFILE,
    "supported_operations": ["add"],
    "reason_codes": [
        "authority_scope_mismatch",
        "channel_confirmation_resolved",
        "derived_authority_capped",
        "derived_from_retrieval",
        "operation_not_supported",
        "representation_accepted",
        "self_asserted_authority_ignored",
        "summary_required_for_authority_ceiling",
        "tool_evidence_verified",
        "unresolved_authority",
    ],
    "terminal_error_codes": [
        "invalid_write_authority",
        "invalid_write_decision",
        "invalid_write_plan",
        "invalid_write_proposal",
        "write_content_hash_mismatch",
        "write_plan_base_changed",
        "write_plan_hash_mismatch",
        "write_policy_fingerprint_mismatch",
    ],
    "derived_authority": {
        "allowed_operations": ["add"],
        "maximum_representation": "summary",
    },
    "require_verified_tool_evidence": True,
    "self_asserted_authority_keys": sorted(_SELF_ASSERTED_AUTHORITY_KEYS),
}


class WritePolicyError(ValueError):
    """A stable terminal error raised before any storage operation."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def policy_configuration() -> dict[str, Any]:
    """Return a detached copy of the frozen v1 policy configuration."""

    return deepcopy(_POLICY_CONFIGURATION)


def policy_fingerprint() -> str:
    return digest_json(_POLICY_CONFIGURATION)


def _require_exact_keys(
    value: Mapping[str, Any], required: set[str], optional: set[str], code: str
) -> None:
    keys = set(value)
    if not required.issubset(keys) or not keys.issubset(required | optional):
        raise WritePolicyError(code)


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and bool(_DIGEST.fullmatch(value))


def _validate_json_value(value: Any, code: str) -> None:
    nodes = 0

    def visit(item: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > _MAX_JSON_NODES or depth > _MAX_JSON_DEPTH:
            raise WritePolicyError(code)
        if item is None or isinstance(item, (str, bool, int)):
            return
        if isinstance(item, float):
            if not math.isfinite(item):
                raise WritePolicyError(code)
            return
        if isinstance(item, list):
            for child in item:
                visit(child, depth + 1)
            return
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise WritePolicyError(code)
            for key in sorted(item):
                visit(item[key], depth + 1)
            return
        raise WritePolicyError(code)

    visit(value, 0)
    try:
        canonical_json(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise WritePolicyError(code) from exc


def _validate_reference(value: Any, code: str) -> None:
    if not isinstance(value, dict):
        raise WritePolicyError(code)
    _require_exact_keys(value, {"kind", "id"}, {"sha256"}, code)
    if value["kind"] not in {"artifact", "event", "fact", "episode", "revision", "external"}:
        raise WritePolicyError(code)
    if not isinstance(value["id"], str) or not value["id"]:
        raise WritePolicyError(code)
    if "sha256" in value and not _is_digest(value["sha256"]):
        raise WritePolicyError(code)


def validate_write_proposal(proposal: Mapping[str, Any]) -> None:
    code = "invalid_write_proposal"
    if not isinstance(proposal, dict):
        raise WritePolicyError(code)
    _require_exact_keys(
        proposal,
        {
            "schema",
            "base_revision",
            "stream",
            "operation",
            "requested_representation",
            "record",
            "lineage",
        },
        set(),
        code,
    )
    if proposal["schema"] != "an-kla/write-proposal-v1":
        raise WritePolicyError(code)
    if not _is_digest(proposal["base_revision"]):
        raise WritePolicyError(code)
    if proposal["stream"] not in _STREAMS:
        raise WritePolicyError(code)
    if proposal["operation"] not in _OPERATIONS:
        raise WritePolicyError(code)
    if proposal["requested_representation"] not in _REPRESENTATIONS:
        raise WritePolicyError(code)
    record = proposal["record"]
    if not isinstance(record, dict) or not record:
        raise WritePolicyError(code)
    if not isinstance(record.get("id"), str) or not record["id"]:
        raise WritePolicyError(code)
    lineage = proposal["lineage"]
    if not isinstance(lineage, dict):
        raise WritePolicyError(code)
    _require_exact_keys(lineage, {"derived_from_retrieval", "refs"}, set(), code)
    if not isinstance(lineage["derived_from_retrieval"], bool):
        raise WritePolicyError(code)
    if not isinstance(lineage["refs"], list):
        raise WritePolicyError(code)
    for reference in lineage["refs"]:
        _validate_reference(reference, code)
    _validate_json_value(proposal, code)


def _validate_evidence(value: Any, code: str) -> None:
    if not isinstance(value, dict):
        raise WritePolicyError(code)
    _require_exact_keys(value, {"kind", "id", "resolution"}, {"sha256"}, code)
    if value["kind"] not in {"artifact", "event", "revision", "external"}:
        raise WritePolicyError(code)
    if not isinstance(value["id"], str) or not value["id"]:
        raise WritePolicyError(code)
    if value["resolution"] not in {"verified", "unresolved", "invalid"}:
        raise WritePolicyError(code)
    if "sha256" in value and not _is_digest(value["sha256"]):
        raise WritePolicyError(code)
    if value["resolution"] == "verified" and "sha256" not in value:
        raise WritePolicyError(code)


def _validate_scope_list(value: Any, allowed: frozenset[str], code: str) -> None:
    if not isinstance(value, list) or not value:
        raise WritePolicyError(code)
    if any(not isinstance(item, str) or item not in allowed for item in value):
        raise WritePolicyError(code)
    if len(value) != len(set(value)):
        raise WritePolicyError(code)


def validate_write_authority(authority: Mapping[str, Any]) -> None:
    code = "invalid_write_authority"
    if not isinstance(authority, dict):
        raise WritePolicyError(code)
    _require_exact_keys(
        authority,
        {
            "schema",
            "proposal_sha256",
            "base_revision",
            "authority_class",
            "issuer",
            "evidence",
            "scope",
        },
        set(),
        code,
    )
    if authority["schema"] != "an-kla/write-authority-v1":
        raise WritePolicyError(code)
    if not _is_digest(authority["proposal_sha256"]) or not _is_digest(
        authority["base_revision"]
    ):
        raise WritePolicyError(code)
    if authority["authority_class"] not in _AUTHORITY_CLASSES:
        raise WritePolicyError(code)
    issuer = authority["issuer"]
    if not isinstance(issuer, dict):
        raise WritePolicyError(code)
    _require_exact_keys(
        issuer, {"kind", "id", "configuration_fingerprint"}, set(), code
    )
    if issuer["kind"] not in {"tool", "channel", "model", "resolver", "unknown"}:
        raise WritePolicyError(code)
    if not isinstance(issuer["id"], str) or not issuer["id"]:
        raise WritePolicyError(code)
    if not _is_digest(issuer["configuration_fingerprint"]):
        raise WritePolicyError(code)
    allowed_issuer_kinds = {
        "tool_observed": {"tool"},
        "channel_confirmed": {"channel"},
        "model_derived": {"model"},
        "derived_from_retrieval": {"model", "resolver"},
        "unresolved": {"unknown", "resolver"},
    }
    if issuer["kind"] not in allowed_issuer_kinds[authority["authority_class"]]:
        raise WritePolicyError(code)
    evidence = authority["evidence"]
    if not isinstance(evidence, list):
        raise WritePolicyError(code)
    for item in evidence:
        _validate_evidence(item, code)
    scope = authority["scope"]
    if not isinstance(scope, dict):
        raise WritePolicyError(code)
    _require_exact_keys(
        scope, {"streams", "representations", "operations"}, set(), code
    )
    _validate_scope_list(scope["streams"], _STREAMS, code)
    _validate_scope_list(scope["representations"], _REPRESENTATIONS, code)
    _validate_scope_list(scope["operations"], _OPERATIONS, code)
    _validate_json_value(authority, code)


def _contains_self_asserted_authority(value: Any) -> bool:
    if isinstance(value, dict):
        if any(key.casefold() in _SELF_ASSERTED_AUTHORITY_KEYS for key in value):
            return True
        return any(_contains_self_asserted_authority(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_self_asserted_authority(item) for item in value)
    return False


def _decision(
    proposal_sha256: str,
    authority_sha256: str,
    decision: str,
    reasons: set[str],
) -> dict[str, Any]:
    if decision != "skip":
        reasons.add("representation_accepted")
    return {
        "schema": "an-kla/write-decision-v1",
        "proposal_sha256": proposal_sha256,
        "authority_sha256": authority_sha256,
        "policy_profile": WRITE_POLICY_PROFILE,
        "policy_fingerprint": policy_fingerprint(),
        "decision": decision,
        "reason_codes": sorted(reasons),
    }


def evaluate_write(
    proposal: Mapping[str, Any], authority: Mapping[str, Any]
) -> dict[str, Any]:
    """Evaluate one proposal and authority without reading or writing state."""

    validate_write_proposal(proposal)
    validate_write_authority(authority)
    proposal_sha256 = digest_json(proposal)
    authority_sha256 = digest_json(authority)
    reasons: set[str] = set()
    if _contains_self_asserted_authority(proposal["record"]):
        reasons.add("self_asserted_authority_ignored")

    scope = authority["scope"]
    if (
        authority["proposal_sha256"] != proposal_sha256
        or authority["base_revision"] != proposal["base_revision"]
        or proposal["stream"] not in scope["streams"]
        or proposal["requested_representation"] not in scope["representations"]
        or proposal["operation"] not in scope["operations"]
    ):
        reasons.add("authority_scope_mismatch")
        return _decision(proposal_sha256, authority_sha256, "skip", reasons)

    if proposal["operation"] not in _POLICY_CONFIGURATION["supported_operations"]:
        reasons.add("operation_not_supported")
        return _decision(proposal_sha256, authority_sha256, "skip", reasons)

    authority_class = authority["authority_class"]
    if proposal["lineage"]["derived_from_retrieval"]:
        reasons.add("derived_from_retrieval")

    if authority_class == "unresolved":
        reasons.add("unresolved_authority")
        return _decision(proposal_sha256, authority_sha256, "skip", reasons)
    if authority_class == "tool_observed":
        if not any(item["resolution"] == "verified" for item in authority["evidence"]):
            reasons.add("unresolved_authority")
            return _decision(proposal_sha256, authority_sha256, "skip", reasons)
        reasons.add("tool_evidence_verified")
    elif authority_class == "channel_confirmed":
        reasons.add("channel_confirmation_resolved")
    else:
        reasons.add("derived_authority_capped")
        if proposal["operation"] not in _POLICY_CONFIGURATION["derived_authority"][
            "allowed_operations"
        ]:
            return _decision(proposal_sha256, authority_sha256, "skip", reasons)
        if proposal["requested_representation"] == "full":
            reasons.add("summary_required_for_authority_ceiling")
            return _decision(proposal_sha256, authority_sha256, "skip", reasons)

    decision = (
        "write-full"
        if proposal["requested_representation"] == "full"
        else "write-summary"
    )
    return _decision(proposal_sha256, authority_sha256, decision, reasons)


def validate_write_decision(decision: Mapping[str, Any]) -> None:
    code = "invalid_write_decision"
    if not isinstance(decision, dict):
        raise WritePolicyError(code)
    _require_exact_keys(
        decision,
        {
            "schema",
            "proposal_sha256",
            "authority_sha256",
            "policy_profile",
            "policy_fingerprint",
            "decision",
            "reason_codes",
        },
        set(),
        code,
    )
    if decision["schema"] != "an-kla/write-decision-v1":
        raise WritePolicyError(code)
    if not _is_digest(decision["proposal_sha256"]) or not _is_digest(
        decision["authority_sha256"]
    ):
        raise WritePolicyError(code)
    if decision["policy_profile"] != WRITE_POLICY_PROFILE or not _is_digest(
        decision["policy_fingerprint"]
    ):
        raise WritePolicyError(code)
    if decision["decision"] not in {"skip", "write-full", "write-summary"}:
        raise WritePolicyError(code)
    reasons = decision["reason_codes"]
    if (
        not isinstance(reasons, list)
        or not reasons
        or any(not isinstance(item, str) or not _REASON_CODE.fullmatch(item) for item in reasons)
        or reasons != sorted(set(reasons))
    ):
        raise WritePolicyError(code)
    _validate_json_value(decision, code)


def _verified_decision(
    proposal: Mapping[str, Any],
    authority: Mapping[str, Any],
    decision: Mapping[str, Any] | None,
) -> dict[str, Any]:
    expected = evaluate_write(proposal, authority)
    if decision is None:
        return expected
    validate_write_decision(decision)
    if decision["policy_fingerprint"] != expected["policy_fingerprint"]:
        raise WritePolicyError("write_policy_fingerprint_mismatch")
    if (
        decision["proposal_sha256"] != expected["proposal_sha256"]
        or decision["authority_sha256"] != expected["authority_sha256"]
    ):
        raise WritePolicyError("write_content_hash_mismatch")
    if canonical_json(decision) != canonical_json(expected):
        raise WritePolicyError("invalid_write_decision")
    return deepcopy(dict(decision))


def build_write_plan(
    proposal: Mapping[str, Any],
    authority: Mapping[str, Any],
    decision: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a content-bound plan; skipped decisions contain no records."""

    checked_decision = _verified_decision(proposal, authority, decision)
    records: list[dict[str, Any]] = []
    if checked_decision["decision"] != "skip":
        records.append(
            {
                "stream": proposal["stream"],
                "operation": proposal["operation"],
                "representation": proposal["requested_representation"],
                "record": deepcopy(proposal["record"]),
            }
        )
        records.append(
            {
                "stream": "events",
                "operation": "add",
                "representation": "summary",
                "record": {
                    "schema": "an-kla/event-v1",
                    "id": "e-write-policy-" + checked_decision["proposal_sha256"][7:],
                    "type": "write_policy_decision",
                    "payload": {
                        "authority_class": authority["authority_class"],
                        "authority_sha256": checked_decision["authority_sha256"],
                        "decision": checked_decision["decision"],
                        "policy_fingerprint": checked_decision["policy_fingerprint"],
                        "policy_profile": checked_decision["policy_profile"],
                        "proposal_sha256": checked_decision["proposal_sha256"],
                        "reason_codes": deepcopy(checked_decision["reason_codes"]),
                    },
                },
            }
        )
    core = {
        "base_revision": proposal["base_revision"],
        "proposal_sha256": checked_decision["proposal_sha256"],
        "authority_sha256": checked_decision["authority_sha256"],
        "policy_fingerprint": checked_decision["policy_fingerprint"],
        "decision": checked_decision["decision"],
        "decision_sha256": digest_json(checked_decision),
        "planned_records_sha256": digest_json(records),
    }
    return {
        "schema": "an-kla/write-plan-v1",
        "core": core,
        "records": records,
        "plan_fingerprint": digest_json(core),
    }


def validate_write_plan(plan: Mapping[str, Any]) -> None:
    code = "invalid_write_plan"
    if not isinstance(plan, dict):
        raise WritePolicyError(code)
    _require_exact_keys(plan, {"schema", "core", "records", "plan_fingerprint"}, set(), code)
    if plan["schema"] != "an-kla/write-plan-v1" or not _is_digest(
        plan["plan_fingerprint"]
    ):
        raise WritePolicyError(code)
    core = plan["core"]
    if not isinstance(core, dict):
        raise WritePolicyError(code)
    _require_exact_keys(
        core,
        {
            "base_revision",
            "proposal_sha256",
            "authority_sha256",
            "policy_fingerprint",
            "decision",
            "decision_sha256",
            "planned_records_sha256",
        },
        set(),
        code,
    )
    for field in (
        "base_revision",
        "proposal_sha256",
        "authority_sha256",
        "policy_fingerprint",
        "decision_sha256",
        "planned_records_sha256",
    ):
        if not _is_digest(core[field]):
            raise WritePolicyError(code)
    if core["decision"] not in {"skip", "write-full", "write-summary"}:
        raise WritePolicyError(code)
    records = plan["records"]
    if not isinstance(records, list):
        raise WritePolicyError(code)
    for item in records:
        if not isinstance(item, dict):
            raise WritePolicyError(code)
        _require_exact_keys(
            item, {"stream", "operation", "representation", "record"}, set(), code
        )
        if item["stream"] not in _STREAMS or item["operation"] not in _OPERATIONS:
            raise WritePolicyError(code)
        if item["representation"] not in _REPRESENTATIONS:
            raise WritePolicyError(code)
        if not isinstance(item["record"], dict) or not item["record"]:
            raise WritePolicyError(code)
    _validate_json_value(plan, code)


def verify_write_plan(
    plan: Mapping[str, Any],
    proposal: Mapping[str, Any],
    authority: Mapping[str, Any],
    decision: Mapping[str, Any] | None = None,
) -> None:
    """Rebuild and compare a plan without mutating any input or external state."""

    try:
        validate_write_plan(plan)
        checked_decision = _verified_decision(proposal, authority, decision)
        if plan["plan_fingerprint"] != digest_json(plan["core"]):
            raise WritePolicyError("write_plan_hash_mismatch")
        if plan["core"]["planned_records_sha256"] != digest_json(plan["records"]):
            raise WritePolicyError("write_content_hash_mismatch")
        expected = build_write_plan(proposal, authority, checked_decision)
        if canonical_json(plan) != canonical_json(expected):
            raise WritePolicyError("write_plan_hash_mismatch")
    except WritePolicyError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise WritePolicyError("invalid_write_plan") from exc


__all__ = [
    "WRITE_POLICY_PROFILE",
    "WritePolicyError",
    "build_write_plan",
    "evaluate_write",
    "policy_configuration",
    "policy_fingerprint",
    "validate_write_authority",
    "validate_write_decision",
    "validate_write_plan",
    "validate_write_proposal",
    "verify_write_plan",
]
