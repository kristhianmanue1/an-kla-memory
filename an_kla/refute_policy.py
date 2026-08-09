"""Deterministic governed-refute policy for ADR-0026."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .canonical import digest_json
from .refute_contracts import (
    PRIVILEGED,
    RefutePolicyError,
    digest,
    exact,
    validate_attestation,
    validate_claim,
    validate_observations,
    validate_proposal,
)


REFUTE_POLICY_PROFILE = "refute-policy/v1"
_CONFIG = {
    "schema": "an-kla/refute-policy-config-v1",
    "profile": REFUTE_POLICY_PROFILE,
    "supported_operations": ["refute"],
    "allowed_authority_classes": ["channel_confirmed", "tool_observed"],
    "evidence_kinds": ["artifact", "event", "fact", "episode", "revision", "external"],
    "reason_codes": [
        "authority_scope_mismatch", "refute_accepted",
        "refute_authority_resolver_unavailable",
        "refute_requires_privileged_authority", "verified_evidence_required",
    ],
    "terminal_error_codes": [
        "invalid_refute_attestation", "invalid_refute_authority_claim",
        "invalid_refute_decision", "invalid_refute_plan",
        "invalid_refute_planning_result", "invalid_refute_proposal",
        "invalid_refute_target", "lifecycle_chain_invalid",
        "lifecycle_chain_limit_exceeded", "refute_content_hash_mismatch",
        "refute_plan_base_changed", "refute_policy_fingerprint_mismatch",
        "revision_schema_downgrade", "revision_transition_invalid",
    ],
    "overlay_format": "refutations/v1",
    "revision_schema": "an-kla/revision-v2",
    "resolver_required": True,
}


def policy_configuration() -> dict[str, Any]:
    return deepcopy(_CONFIG)


def policy_fingerprint() -> str:
    return digest_json(_CONFIG)


def _decision(
    proposal: Mapping[str, Any], claim: Mapping[str, Any], *, decision: str,
    reason: str, attestation: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema": "an-kla/refute-decision-v1",
        "proposal_sha256": digest_json(proposal),
        "authority_claim_sha256": digest_json(claim),
        "authority_attestation_id": (
            digest_json(attestation) if attestation is not None else None
        ),
        "policy_profile": REFUTE_POLICY_PROFILE,
        "policy_fingerprint": policy_fingerprint(),
        "decision": decision,
        "reason_codes": [reason],
    }


def evaluate(
    proposal: Mapping[str, Any], claim: Mapping[str, Any],
    observations: Mapping[str, Any], resolver: Any | None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    checked_proposal = validate_proposal(proposal)
    checked_claim = validate_claim(claim)
    checked_observations = validate_observations(observations, checked_claim)
    if (
        checked_claim["proposal_sha256"] != digest_json(checked_proposal)
        or checked_claim["base_revision"] != checked_proposal["base_revision"]
        or checked_claim["scope"] != {
            "operation": "refute",
            "stream": checked_proposal["stream"],
            "target_record_sha256": checked_proposal["target_record_sha256"],
        }
    ):
        return _decision(
            checked_proposal, checked_claim, decision="skip",
            reason="authority_scope_mismatch", attestation=None,
        ), None
    if checked_claim["requested_authority_class"] not in PRIVILEGED:
        return _decision(
            checked_proposal, checked_claim, decision="skip",
            reason="refute_requires_privileged_authority", attestation=None,
        ), None
    if resolver is None:
        return _decision(
            checked_proposal, checked_claim, decision="skip",
            reason="refute_authority_resolver_unavailable", attestation=None,
        ), None
    if any(
        evidence["kind"] not in {"artifact", "external"}
        and observation["store_resolution"] != "present"
        for evidence, observation in zip(
            checked_claim["evidence"], checked_observations["items"]
        )
    ):
        return _decision(
            checked_proposal, checked_claim, decision="skip",
            reason="verified_evidence_required", attestation=None,
        ), None
    descriptor = deepcopy(resolver.descriptor)
    raw = resolver.resolve(
        deepcopy(checked_proposal), deepcopy(checked_claim),
        deepcopy(checked_observations),
    )
    if raw is None:
        return _decision(
            checked_proposal, checked_claim, decision="skip",
            reason="verified_evidence_required", attestation=None,
        ), None
    attestation = validate_attestation(
        raw, checked_proposal, checked_claim, checked_observations, descriptor
    )
    if resolver.verify(
        deepcopy(attestation), deepcopy(checked_proposal), deepcopy(checked_claim),
        deepcopy(checked_observations),
    ) is not True:
        raise RefutePolicyError("invalid_refute_attestation", "resolver_verification_failed")
    return _decision(
        checked_proposal, checked_claim, decision="refute",
        reason="refute_accepted", attestation=attestation,
    ), attestation


def validate_decision(
    value: Mapping[str, Any], *, enforce_installed_policy: bool = True
) -> dict[str, Any]:
    code = "invalid_refute_decision"
    out = exact(
        value,
        {"schema", "proposal_sha256", "authority_claim_sha256",
         "authority_attestation_id", "policy_profile", "policy_fingerprint",
         "decision", "reason_codes"},
        code, "shape",
    )
    if (
        out["schema"] != "an-kla/refute-decision-v1"
        or out["policy_profile"] != REFUTE_POLICY_PROFILE
        or out["decision"] not in {"skip", "refute"}
        or not isinstance(out["reason_codes"], list)
        or len(out["reason_codes"]) != 1
    ):
        raise RefutePolicyError(code, "values")
    digest(out["proposal_sha256"], code, "proposal_sha256")
    digest(out["authority_claim_sha256"], code, "authority_claim_sha256")
    digest(out["policy_fingerprint"], code, "policy_fingerprint")
    if enforce_installed_policy and out["policy_fingerprint"] != policy_fingerprint():
        raise RefutePolicyError("refute_policy_fingerprint_mismatch")
    if out["decision"] == "refute":
        digest(out["authority_attestation_id"], code, "authority_attestation_id")
        if out["reason_codes"] != ["refute_accepted"]:
            raise RefutePolicyError(code, "reason_codes")
    else:
        skip_reasons = {
            "authority_scope_mismatch", "refute_authority_resolver_unavailable",
            "refute_requires_privileged_authority", "verified_evidence_required",
        }
        if (
            out["authority_attestation_id"] is not None
            or out["reason_codes"][0] not in skip_reasons
        ):
            raise RefutePolicyError(code, "reason_codes")
    return deepcopy(out)


def build_plan(
    proposal: Mapping[str, Any], claim: Mapping[str, Any],
    attestation: Mapping[str, Any] | None, decision: Mapping[str, Any],
    *, enforce_installed_policy: bool = True,
) -> dict[str, Any]:
    checked_proposal = validate_proposal(proposal)
    checked_claim = validate_claim(claim)
    checked_decision = validate_decision(
        decision, enforce_installed_policy=enforce_installed_policy
    )
    attestation_id = digest_json(attestation) if attestation is not None else None
    if (
        checked_decision["proposal_sha256"] != digest_json(checked_proposal)
        or checked_decision["authority_claim_sha256"] != digest_json(checked_claim)
        or checked_decision["authority_attestation_id"] != attestation_id
        or (checked_decision["decision"] == "skip") != (attestation is None)
    ):
        raise RefutePolicyError("invalid_refute_plan", "binding")
    core = {
        "base_revision": checked_proposal["base_revision"],
        "proposal_sha256": digest_json(checked_proposal),
        "authority_claim_sha256": digest_json(checked_claim),
        "authority_attestation_id": attestation_id,
        "policy_fingerprint": checked_decision["policy_fingerprint"],
        "decision": checked_decision["decision"],
        "decision_sha256": digest_json(checked_decision),
        "target": {
            "stream": checked_proposal["stream"],
            "record_sha256": checked_proposal["target_record_sha256"],
        },
        "reason": checked_proposal["reason"],
        "evidence_sha256": digest_json(checked_claim["evidence"]),
    }
    return {
        "schema": "an-kla/refute-plan-v1",
        "core": core,
        "plan_fingerprint": digest_json(core),
    }


def verify_plan(
    plan: Mapping[str, Any], proposal: Mapping[str, Any], claim: Mapping[str, Any],
    attestation: Mapping[str, Any] | None, decision: Mapping[str, Any],
    *, enforce_installed_policy: bool = True,
) -> dict[str, Any]:
    expected = build_plan(
        proposal, claim, attestation, decision,
        enforce_installed_policy=enforce_installed_policy,
    )
    if not isinstance(plan, dict) or plan != expected:
        raise RefutePolicyError("invalid_refute_plan", "content")
    return deepcopy(expected)


__all__ = [
    "REFUTE_POLICY_PROFILE", "RefutePolicyError", "build_plan", "evaluate",
    "policy_configuration", "policy_fingerprint", "validate_decision", "verify_plan",
]
