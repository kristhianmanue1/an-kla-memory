"""Closed JSON contracts for governed refutation (ADR-0026)."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Mapping

from .canonical import bare_digest, canonical_json, digest_json


STREAMS = ("facts", "events", "episodes")
AUTHORITY_CLASSES = (
    "tool_observed", "channel_confirmed", "model_derived",
    "derived_from_retrieval", "unresolved",
)
PRIVILEGED = ("channel_confirmed", "tool_observed")
REASONS = (
    "evidence_contradicts_record", "source_retracted", "integrity_violation",
)
PROFILE = re.compile(r"^[a-z][a-z0-9-]{0,63}/v[1-9][0-9]{0,9}$")


class RefutePolicyError(ValueError):
    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


def exact(value: Any, keys: set[str], code: str, detail: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise RefutePolicyError(code, detail)
    return value


def digest(value: Any, code: str, detail: str) -> str:
    if not isinstance(value, str):
        raise RefutePolicyError(code, detail)
    try:
        bare_digest(value)
    except ValueError as exc:
        raise RefutePolicyError(code, detail) from exc
    return value


def profile(value: Any, code: str, detail: str) -> str:
    if (
        not isinstance(value, str)
        or len(value.encode("ascii", "ignore")) != len(value)
        or len(value.encode("ascii")) > 128
        or PROFILE.fullmatch(value) is None
    ):
        raise RefutePolicyError(code, detail)
    return value


def validate_proposal(value: Mapping[str, Any]) -> dict[str, Any]:
    code = "invalid_refute_proposal"
    out = exact(
        value,
        {"schema", "base_revision", "stream", "target_record_sha256", "reason"},
        code,
        "shape",
    )
    if out["schema"] != "an-kla/refute-proposal-v1" or out["stream"] not in STREAMS:
        raise RefutePolicyError(code, "schema_or_stream")
    digest(out["base_revision"], code, "base_revision")
    digest(out["target_record_sha256"], code, "target_record_sha256")
    if out["reason"] not in REASONS:
        raise RefutePolicyError(code, "reason")
    return deepcopy(out)


def validate_evidence(value: Any, code: str = "invalid_refute_authority_claim") -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RefutePolicyError(code, "evidence")
    kind = value.get("kind")
    if kind in {"fact", "event", "episode"}:
        out = exact(value, {"kind", "record_sha256"}, code, "evidence")
        digest(out["record_sha256"], code, "evidence.record_sha256")
    elif kind == "revision":
        out = exact(value, {"kind", "revision_sha256"}, code, "evidence")
        digest(out["revision_sha256"], code, "evidence.revision_sha256")
    elif kind in {"artifact", "external"}:
        out = exact(value, {"kind", "content_sha256"}, code, "evidence")
        digest(out["content_sha256"], code, "evidence.content_sha256")
    else:
        raise RefutePolicyError(code, "evidence.kind")
    return deepcopy(out)


def validate_claim(value: Mapping[str, Any]) -> dict[str, Any]:
    code = "invalid_refute_authority_claim"
    out = exact(
        value,
        {"schema", "proposal_sha256", "base_revision", "requested_authority_class",
         "issuer_claim", "evidence", "scope"},
        code,
        "shape",
    )
    if out["schema"] != "an-kla/refute-authority-claim-v1":
        raise RefutePolicyError(code, "schema")
    digest(out["proposal_sha256"], code, "proposal_sha256")
    digest(out["base_revision"], code, "base_revision")
    if out["requested_authority_class"] not in AUTHORITY_CLASSES:
        raise RefutePolicyError(code, "requested_authority_class")
    issuer = exact(
        out["issuer_claim"], {"kind", "subject_sha256", "configuration_fingerprint"},
        code, "issuer_claim",
    )
    if issuer["kind"] not in {"tool", "channel", "model", "resolver", "unknown"}:
        raise RefutePolicyError(code, "issuer_claim.kind")
    digest(issuer["subject_sha256"], code, "issuer_claim.subject_sha256")
    digest(issuer["configuration_fingerprint"], code, "issuer_claim.configuration_fingerprint")
    if not isinstance(out["evidence"], list) or not 1 <= len(out["evidence"]) <= 16:
        raise RefutePolicyError(code, "evidence")
    evidence = [validate_evidence(item, code) for item in out["evidence"]]
    ordered = sorted(evidence, key=canonical_json)
    if evidence != ordered or len({canonical_json(item) for item in evidence}) != len(evidence):
        raise RefutePolicyError(code, "evidence.order_or_duplicate")
    scope = exact(
        out["scope"], {"operation", "stream", "target_record_sha256"}, code, "scope"
    )
    if scope["operation"] != "refute" or scope["stream"] not in STREAMS:
        raise RefutePolicyError(code, "scope")
    digest(scope["target_record_sha256"], code, "scope.target_record_sha256")
    return deepcopy(out)


def validate_descriptor(value: Any, code: str = "invalid_refute_attestation") -> dict[str, Any]:
    out = exact(
        value, {"profile", "subject_sha256", "configuration_fingerprint"}, code,
        "resolver",
    )
    profile(out["profile"], code, "resolver.profile")
    digest(out["subject_sha256"], code, "resolver.subject_sha256")
    digest(out["configuration_fingerprint"], code, "resolver.configuration_fingerprint")
    return deepcopy(out)


def _evidence_digest(item: Mapping[str, Any]) -> str:
    if item["kind"] in {"fact", "event", "episode"}:
        return str(item["record_sha256"])
    if item["kind"] == "revision":
        return str(item["revision_sha256"])
    return str(item["content_sha256"])


def validate_observations(value: Mapping[str, Any], claim: Mapping[str, Any]) -> dict[str, Any]:
    code = "invalid_refute_attestation"
    out = exact(value, {"schema", "base_revision", "items"}, code, "observations")
    if out["schema"] != "an-kla/refute-observations-v1" or out["base_revision"] != claim["base_revision"]:
        raise RefutePolicyError(code, "observations.binding")
    if not isinstance(out["items"], list) or len(out["items"]) != len(claim["evidence"]):
        raise RefutePolicyError(code, "observations.items")
    for raw, evidence in zip(out["items"], claim["evidence"]):
        item = exact(
            raw, {"schema", "evidence", "store_resolution", "observed_sha256"},
            code, "observation",
        )
        if item["schema"] != "an-kla/refute-observation-v1" or item["evidence"] != evidence:
            raise RefutePolicyError(code, "observation.binding")
        kind = evidence["kind"]
        resolution = item["store_resolution"]
        observed = item["observed_sha256"]
        if kind in {"artifact", "external"}:
            if resolution != "unavailable" or observed is not None:
                raise RefutePolicyError(code, "observation.external")
        elif resolution == "present":
            if observed != _evidence_digest(evidence):
                raise RefutePolicyError(code, "observation.present")
        elif resolution != "missing" or observed is not None:
            raise RefutePolicyError(code, "observation.missing")
    return deepcopy(out)


def validate_attestation(
    value: Mapping[str, Any], proposal: Mapping[str, Any], claim: Mapping[str, Any],
    observations: Mapping[str, Any], descriptor: Mapping[str, Any],
) -> dict[str, Any]:
    code = "invalid_refute_attestation"
    out = exact(
        value,
        {"schema", "proposal_sha256", "authority_claim_sha256", "base_revision",
         "resolver", "authority_class", "issuer", "observations_sha256",
         "evidence_resolutions", "scope", "proof"},
        code, "shape",
    )
    if (
        out["schema"] != "an-kla/refute-authority-attestation-v1"
        or out["proposal_sha256"] != digest_json(proposal)
        or out["authority_claim_sha256"] != digest_json(claim)
        or out["base_revision"] != proposal["base_revision"]
        or out["resolver"] != descriptor
        or out["observations_sha256"] != digest_json(observations)
        or out["scope"] != claim["scope"]
        or out["authority_class"] != claim["requested_authority_class"]
    ):
        raise RefutePolicyError(code, "binding")
    validate_descriptor(out["resolver"], code)
    if out["authority_class"] not in PRIVILEGED:
        raise RefutePolicyError(code, "authority_class")
    issuer = exact(
        out["issuer"], {"kind", "subject_sha256", "configuration_fingerprint"},
        code, "issuer",
    )
    expected_kind = "tool" if out["authority_class"] == "tool_observed" else "channel"
    if issuer["kind"] != expected_kind:
        raise RefutePolicyError(code, "issuer.kind")
    digest(issuer["subject_sha256"], code, "issuer.subject_sha256")
    digest(issuer["configuration_fingerprint"], code, "issuer.configuration_fingerprint")
    if not isinstance(out["evidence_resolutions"], list) or len(out["evidence_resolutions"]) != len(claim["evidence"]):
        raise RefutePolicyError(code, "evidence_resolutions")
    for resolution, evidence, observation in zip(
        out["evidence_resolutions"], claim["evidence"], observations["items"]
    ):
        expected = {**evidence, "resolution": "verified", "observation_sha256": digest_json(observation)}
        if resolution != expected:
            raise RefutePolicyError(code, "evidence_resolutions.binding")
        if evidence["kind"] not in {"artifact", "external"} and observation["store_resolution"] != "present":
            raise RefutePolicyError(code, "evidence_resolutions.missing")
    proof = exact(out["proof"], {"profile", "proof_sha256"}, code, "proof")
    profile(proof["profile"], code, "proof.profile")
    digest(proof["proof_sha256"], code, "proof.proof_sha256")
    if proof["profile"] != descriptor["profile"]:
        raise RefutePolicyError(code, "proof.profile")
    return deepcopy(out)


__all__ = [
    "AUTHORITY_CLASSES", "PRIVILEGED", "REASONS", "RefutePolicyError", "STREAMS",
    "digest", "exact", "profile", "validate_attestation", "validate_claim",
    "validate_descriptor", "validate_evidence", "validate_observations",
    "validate_proposal",
]
