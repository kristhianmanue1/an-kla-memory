"""Commit gobernado en lote — ``write-proposal/v2`` (ADR-0054, issue #149 P2d).

Un lote: registros homogéneos (mismo stream y operación), evaluados contra
el estado PRE-LOTE, con UNA decisión, UN plan, UNA revisión y UN CAS. La
escalera de autoridad es la de v1 (se re-evalúa vía gemelo, sin segunda
implementación); ``supersede`` intra-lote está prohibido y los targets
deben ser vigentes en el snapshot base (el commit re-resuelve bajo lock).
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .canonical import digest_json
from .write_policy import (
    WRITE_POLICY_PROFILE,
    WritePolicyError,
    _contains_self_asserted_authority,
    _POLICY_CONFIGURATION,
    evaluate_write,
    policy_fingerprint,
    record_text,
)

BATCH_SCHEMA = "an-kla/write-proposal-v2"


def _validate_one_record(record: Any, code: str, detail: str) -> None:
    if not isinstance(record, dict) or not record:
        raise WritePolicyError(code, detail)
    if not isinstance(record.get("id"), str) or not record["id"]:
        raise WritePolicyError(code, detail)


def validate_batch_proposal(proposal: Mapping[str, Any]) -> None:
    code = "invalid_write_proposal"
    if not isinstance(proposal, dict):
        raise WritePolicyError(code, "proposal:not_object")
    from .write_policy import _require_exact_keys

    _require_exact_keys(
        proposal,
        {
            "schema", "base_revision", "stream", "operation",
            "requested_representation", "records", "lineage",
        },
        {"supersedes"},
        code,
        "proposal:keys",
    )
    if proposal["schema"] != BATCH_SCHEMA:
        raise WritePolicyError(code, "proposal:schema")
    if proposal["stream"] not in ("facts", "events", "episodes"):
        raise WritePolicyError(code, "stream")
    if proposal["operation"] not in ("add", "supersede"):
        raise WritePolicyError(code, "operation")
    if proposal["requested_representation"] not in ("full", "summary"):
        raise WritePolicyError(code, "requested_representation")
    from .write_policy import _is_digest, _validate_json_value, _validate_reference

    if not _is_digest(proposal["base_revision"]):
        raise WritePolicyError(code, "base_revision:not_digest")
    records = proposal["records"]
    limit = int(_POLICY_CONFIGURATION["max_batch_records"])
    if not isinstance(records, list) or not records:
        raise WritePolicyError(code, "records:not_list")
    if len(records) > limit:
        raise WritePolicyError(code, "records:max_batch_records")
    ids: list[str] = []
    for index, record in enumerate(records):
        _validate_one_record(record, code, f"records[{index}]")
        ids.append(record["id"])
    if len(ids) != len(set(ids)):
        raise WritePolicyError(code, "records:duplicate_id")
    batch_ids = set(ids)
    if proposal["operation"] == "supersede":
        supersedes = proposal.get("supersedes")
        if (
            not isinstance(supersedes, dict)
            or not supersedes
            or set(supersedes) != batch_ids
        ):
            raise WritePolicyError(code, "supersedes:missing_for_supersede")
        targets = list(supersedes.values())
        if any(not isinstance(t, str) or not t for t in targets):
            raise WritePolicyError(code, "supersedes:target_invalid")
        if any(t == k for k, t in supersedes.items()):
            raise WritePolicyError(code, "supersedes:self_reference_forbidden")
        if any(t in batch_ids for t in targets):
            # ADR-0054 §2: superseder a otro registro del MISMO lote está
            # prohibido — elimina dependencia de orden interno.
            raise WritePolicyError(code, "supersedes:intra_batch_forbidden")
        if len(targets) != len(set(targets)):
            raise WritePolicyError(code, "supersedes:duplicate_target")
    elif "supersedes" in proposal:
        raise WritePolicyError(code, "supersedes:present_without_supersede")
    lineage = proposal["lineage"]
    if not isinstance(lineage, dict) or set(lineage) != {
        "derived_from_retrieval", "refs"
    }:
        raise WritePolicyError(code, "lineage")
    if not isinstance(lineage["derived_from_retrieval"], bool):
        raise WritePolicyError(code, "lineage.derived_from_retrieval")
    if not isinstance(lineage["refs"], list):
        raise WritePolicyError(code, "lineage.refs")
    for reference in lineage["refs"]:
        _validate_reference(reference, code, "lineage.refs[]:invalid")
    _validate_json_value(proposal, code, "proposal:invalid_json")


def _twin_v1(proposal: Mapping[str, Any]) -> dict[str, Any]:
    """Gemelo v1 del lote: la escalera de autoridad se evalúa UNA vez."""
    twin: dict[str, Any] = {
        "schema": "an-kla/write-proposal-v1",
        "base_revision": proposal["base_revision"],
        "stream": proposal["stream"],
        "operation": proposal["operation"],
        "requested_representation": proposal["requested_representation"],
        "record": deepcopy(proposal["records"][0]),
        "lineage": deepcopy(proposal["lineage"]),
    }
    if proposal["operation"] == "supersede":
        twin["supersedes"] = proposal["supersedes"][proposal["records"][0]["id"]]
    return twin


def _twin_authority(twin: Mapping[str, Any], authority: Mapping[str, Any]) -> dict[str, Any]:
    """Autoridad del gemelo: mismo contenido, digest ligado al gemelo."""
    return {**deepcopy(dict(authority)), "proposal_sha256": digest_json(twin)}


def evaluate_batch_write(
    proposal: Mapping[str, Any], authority: Mapping[str, Any]
) -> dict[str, Any]:
    validate_batch_proposal(proposal)
    from .write_policy import validate_write_authority

    validate_write_authority(authority)
    twin = _twin_v1(proposal)
    twin_decision = evaluate_write(twin, _twin_authority(twin, authority))
    proposal_sha256 = digest_json(proposal)
    authority_sha256 = digest_json(authority)
    reasons = set(twin_decision["reason_codes"])
    if (
        authority.get("proposal_sha256") != proposal_sha256
        or authority.get("base_revision") != proposal["base_revision"]
    ):
        # El digest de la autoridad REAL liga al lote, no al gemelo.
        reasons.add("authority_scope_mismatch")
        return {
            "schema": "an-kla/write-decision-v1",
            "proposal_sha256": proposal_sha256,
            "authority_sha256": authority_sha256,
            "policy_profile": WRITE_POLICY_PROFILE,
            "policy_fingerprint": policy_fingerprint(),
            "decision": "skip",
            "reason_codes": sorted(reasons),
        }
    for record in proposal["records"]:
        if _contains_self_asserted_authority(record):
            reasons.add("self_asserted_authority_ignored")
        if not record_text(record):
            reasons.add("record_without_indexable_text")
    return {
        "schema": "an-kla/write-decision-v1",
        "proposal_sha256": proposal_sha256,
        "authority_sha256": authority_sha256,
        "policy_profile": WRITE_POLICY_PROFILE,
        "policy_fingerprint": policy_fingerprint(),
        "decision": twin_decision["decision"],
        "reason_codes": sorted(reasons),
    }


def build_batch_write_plan(
    proposal: Mapping[str, Any],
    authority: Mapping[str, Any],
    decision: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    from .write_policy import build_write_plan, evaluate_write

    # La decisión v2 (digests del lote) se recalcula pura; si el caller
    # entregó una, _verified_decision ya la contrastó antes de llegar aquí.
    v2_decision = evaluate_write(proposal, authority)
    if v2_decision["decision"] == "skip":
        core = {
            "base_revision": proposal["base_revision"],
            "proposal_sha256": v2_decision["proposal_sha256"],
            "authority_sha256": v2_decision["authority_sha256"],
            "policy_fingerprint": v2_decision["policy_fingerprint"],
            "decision": "skip",
            "decision_sha256": digest_json(v2_decision),
            "planned_records_sha256": digest_json([]),
        }
        return {
            "schema": "an-kla/write-plan-v1",
            "core": core,
            "records": [],
            "plan_fingerprint": digest_json(core),
        }
    twin = _twin_v1(proposal)
    base_plan = build_write_plan(twin, _twin_authority(twin, authority), None)
    records: list[dict[str, Any]] = []
    for record in proposal["records"]:
        item: dict[str, Any] = {
            "stream": proposal["stream"],
            "operation": proposal["operation"],
            "representation": proposal["requested_representation"],
            "record": deepcopy(record),
        }
        if proposal["operation"] == "supersede":
            item["supersedes"] = proposal["supersedes"][record["id"]]
        records.append(item)
    event = deepcopy(
        next(
            item
            for item in base_plan["records"]
            if item["stream"] == "events"
            and item["record"].get("type") == "write_policy_decision"
        )
    )
    payload = event["record"]["payload"]
    payload["proposal_sha256"] = v2_decision["proposal_sha256"]
    payload["decision"] = v2_decision["decision"]
    payload["reason_codes"] = deepcopy(v2_decision["reason_codes"])
    payload["batch_records_sha256"] = sorted(
        digest_json(record) for record in proposal["records"]
    )
    records.append(event)
    core = {
        "base_revision": proposal["base_revision"],
        "proposal_sha256": v2_decision["proposal_sha256"],
        "authority_sha256": v2_decision["authority_sha256"],
        "policy_fingerprint": v2_decision["policy_fingerprint"],
        "decision": v2_decision["decision"],
        "decision_sha256": digest_json(v2_decision),
        "planned_records_sha256": digest_json(records),
    }
    return {
        "schema": "an-kla/write-plan-v1",
        "core": core,
        "records": records,
        "plan_fingerprint": digest_json(core),
    }


__all__ = [
    "BATCH_SCHEMA",
    "build_batch_write_plan",
    "evaluate_batch_write",
    "validate_batch_proposal",
]
