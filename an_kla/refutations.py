"""Store-facing governed refutation operations (ADR-0026)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .canonical import digest_json
from .identity import assert_unchanged, mutation_preflight
from .refute_contracts import (
    RefutePolicyError,
    digest,
    exact,
    validate_attestation,
    validate_claim,
    validate_descriptor,
    validate_observations,
    validate_proposal,
)
from .refute_policy import (
    REFUTE_POLICY_PROFILE,
    build_plan,
    evaluate,
    policy_fingerprint,
    validate_decision,
    verify_plan,
)
from .transactions import begin_transaction
from .transaction_reconcile import reconcile_attempt


_KIND_STREAM = {"fact": "facts", "event": "events", "episode": "episodes"}


def _ancestor_ids(store: Any, base_revision: str) -> set[str]:
    result: set[str] = set()
    cursor: str | None = base_revision
    while cursor is not None:
        if cursor in result:
            raise RefutePolicyError("invalid_refute_attestation", "revision_cycle")
        result.add(cursor)
        manifest = store._read_json_object("revisions", cursor)
        parent = manifest.get("parent")
        cursor = parent if isinstance(parent, str) else None
    return result


def build_observations(
    store: Any, snapshot: Any, claim: Mapping[str, Any]
) -> dict[str, Any]:
    checked = validate_claim(claim)
    ancestors: set[str] | None = None
    items = []
    for evidence in checked["evidence"]:
        kind = evidence["kind"]
        resolution = "unavailable"
        observed = None
        if kind in _KIND_STREAM:
            wanted = evidence["record_sha256"]
            matches = [
                row for row in snapshot.raw_records[_KIND_STREAM[kind]]
                if digest_json(row) == wanted
            ]
            if len(matches) > 1:
                raise RefutePolicyError("invalid_refute_attestation", "evidence_ambiguous")
            resolution = "present" if matches else "missing"
            observed = wanted if matches else None
        elif kind == "revision":
            ancestors = ancestors or _ancestor_ids(store, snapshot.revision_id)
            wanted = evidence["revision_sha256"]
            resolution = "present" if wanted in ancestors else "missing"
            observed = wanted if wanted in ancestors else None
        items.append(
            {
                "schema": "an-kla/refute-observation-v1",
                "evidence": deepcopy(evidence),
                "store_resolution": resolution,
                "observed_sha256": observed,
            }
        )
    observations = {
        "schema": "an-kla/refute-observations-v1",
        "base_revision": checked["base_revision"],
        "items": items,
    }
    return validate_observations(observations, checked)


def _resolver_descriptor(store: Any) -> dict[str, Any] | None:
    resolver = store.refute_authority_resolver
    if resolver is None:
        return None
    current = validate_descriptor(deepcopy(getattr(resolver, "descriptor", None)))
    if current != store._refute_resolver_descriptor:
        raise RefutePolicyError("invalid_refute_attestation", "resolver_descriptor_mismatch")
    return current


def plan_refute(
    store: Any, proposal: Mapping[str, Any], authority_claim: Mapping[str, Any]
) -> dict[str, Any]:
    checked_proposal = validate_proposal(proposal)
    checked_claim = validate_claim(authority_claim)
    observed = store.read_current()
    if checked_proposal["base_revision"] != observed:
        raise RefutePolicyError("refute_plan_base_changed")
    snapshot = store.snapshot(observed)
    observations = build_observations(store, snapshot, checked_claim)
    _resolver_descriptor(store)
    decision, attestation = evaluate(
        checked_proposal, checked_claim, observations,
        store.refute_authority_resolver,
    )
    plan = build_plan(
        checked_proposal, checked_claim, attestation, decision
    )
    return {
        "schema": "an-kla/refute-planning-result-v1",
        "current_revision": observed,
        "proposal": checked_proposal,
        "authority_claim": checked_claim,
        "authority_attestation": attestation,
        "decision": decision,
        "plan": plan,
    }


def _planning(
    value: Mapping[str, Any], *, enforce_installed_policy: bool = True
) -> tuple[dict[str, Any], ...]:
    checked = exact(
        value,
        {"schema", "current_revision", "proposal", "authority_claim",
         "authority_attestation", "decision", "plan"},
        "invalid_refute_planning_result",
        "shape",
    )
    if checked["schema"] != "an-kla/refute-planning-result-v1":
        raise RefutePolicyError("invalid_refute_planning_result", "schema")
    proposal = validate_proposal(deepcopy(checked["proposal"]))
    claim = validate_claim(deepcopy(checked["authority_claim"]))
    decision = validate_decision(
        deepcopy(checked["decision"]),
        enforce_installed_policy=enforce_installed_policy,
    )
    attestation = checked["authority_attestation"]
    if attestation is not None and not isinstance(attestation, dict):
        raise RefutePolicyError("invalid_refute_planning_result", "attestation")
    plan = verify_plan(
        deepcopy(checked["plan"]), proposal, claim,
        deepcopy(attestation), decision,
        enforce_installed_policy=enforce_installed_policy,
    )
    if not (
        checked["current_revision"] == proposal["base_revision"]
        == plan["core"]["base_revision"]
    ):
        raise RefutePolicyError("invalid_refute_planning_result", "base")
    if (
        claim["base_revision"] != proposal["base_revision"]
        and not (
            decision["decision"] == "skip"
            and decision["reason_codes"] == ["authority_scope_mismatch"]
        )
    ):
        raise RefutePolicyError("invalid_refute_planning_result", "claim_base")
    return (
        proposal, claim, deepcopy(attestation), decision, plan,
        {**deepcopy(checked), "proposal": proposal, "authority_claim": claim,
         "authority_attestation": deepcopy(attestation), "decision": decision,
         "plan": plan},
    )


def _result(
    decision: Mapping[str, Any], plan: Mapping[str, Any], *, revision: str | None,
    outcome: Mapping[str, Any] | None,
) -> dict[str, Any]:
    committed = False if outcome is None else outcome["committed"]
    if outcome is not None:
        if committed is True:
            revision = outcome["candidate_revision"]
        elif committed is False:
            revision = outcome["current_observed"] or outcome["parent_revision"]
        else:
            revision = outcome["current_observed"]
    return {
        "schema": "an-kla/refute-commit-result-v1",
        "committed": committed,
        "revision": revision,
        "decision": deepcopy(dict(decision)),
        "reason_codes": deepcopy(decision["reason_codes"]),
        "plan_fingerprint": plan["plan_fingerprint"],
        "outcome": deepcopy(dict(outcome)) if outcome is not None else None,
    }


def _target_guard(snapshot: Any, stream: str, record_sha256: str) -> Mapping[str, Any]:
    matches = [row for row in snapshot.raw_records[stream] if digest_json(row) == record_sha256]
    if not matches:
        raise RefutePolicyError("invalid_refute_target", "target_missing")
    if len(matches) != 1:
        raise RefutePolicyError("invalid_refute_target", "target_ambiguous")
    target = matches[0]
    target_id = str(target.get("id", ""))
    if any(
        entry["stream"] == stream and entry["target_id"] == target_id
        for entry in snapshot.manifest.get("supersedes_map", [])
    ) or any(
        entry["stream"] == stream and entry["target_record_sha256"] == record_sha256
        for entry in snapshot.manifest.get("refutations_map", [])
    ):
        raise RefutePolicyError("invalid_refute_target", "overlay_conflict")
    if target.get("status", target.get("nu", "vigente")) not in {"vigente", "active", None}:
        raise RefutePolicyError("invalid_refute_target", "target_not_active")
    return target


def _verify_commit_authority(
    store: Any, proposal: Mapping[str, Any], claim: Mapping[str, Any],
    attestation: Mapping[str, Any], observations: Mapping[str, Any],
) -> dict[str, Any]:
    resolver = store.refute_authority_resolver
    if resolver is None:
        raise RefutePolicyError("invalid_refute_attestation", "resolver_unavailable_at_commit")
    descriptor = _resolver_descriptor(store)
    if attestation.get("resolver") != descriptor:
        raise RefutePolicyError("invalid_refute_attestation", "resolver_descriptor_mismatch")
    if attestation.get("observations_sha256") != digest_json(observations):
        raise RefutePolicyError("invalid_refute_attestation", "observations_mismatch")
    checked = validate_attestation(
        attestation, proposal, claim, observations, descriptor
    )
    if resolver.verify(
        deepcopy(checked), deepcopy(proposal), deepcopy(claim), deepcopy(observations)
    ) is not True:
        raise RefutePolicyError("invalid_refute_attestation", "resolver_verification_failed")
    return checked


def commit_refute(
    store: Any, planning_result: Mapping[str, Any], expected_current: str, *,
    transaction_id: str | None = None,
) -> dict[str, Any]:
    proposal, claim, attestation, decision, plan, frozen = _planning(
        planning_result, enforce_installed_policy=False
    )
    digest(expected_current, "invalid_refute_planning_result", "expected_current")
    if expected_current != proposal["base_revision"]:
        raise RefutePolicyError("invalid_refute_planning_result", "expected_current")
    if decision["decision"] == "refute" and transaction_id is None:
        raise RefutePolicyError("invalid_refute_planning_result", "transaction_id_required")
    attempt = (
        begin_transaction(
            "refute", transaction_id=transaction_id, base_revision=expected_current,
            plan_fingerprint=plan["plan_fingerprint"],
        )
        if decision["decision"] == "refute" else None
    )
    binding = mutation_preflight(store)
    with store.write_lock() as lock_result:
        observed = store.read_current()
        identity_digest = assert_unchanged(store, binding, observed)
        if decision["decision"] == "skip":
            if observed != expected_current:
                raise RefutePolicyError("refute_plan_base_changed")
            verify_plan(plan, proposal, claim, None, decision)
            return _result(decision, plan, revision=observed, outcome=None)
        assert attempt is not None and attestation is not None
        reconciled = reconcile_attempt(store, attempt)
        prior = reconciled["outcome"]
        if prior is not None and prior.get("committed") is True:
            return _result(decision, plan, revision=None, outcome=prior)
        if observed != expected_current:
            if reconciled["has_evidence"] and prior is not None:
                return _result(decision, plan, revision=None, outcome=prior)
            raise RefutePolicyError("refute_plan_base_changed")
        proposal, claim, attestation, decision, plan, _ = _planning(
            frozen, enforce_installed_policy=True
        )
        verify_plan(plan, proposal, claim, attestation, decision)
        snapshot = store.snapshot(observed)
        observations = build_observations(store, snapshot, claim)
        checked_attestation = _verify_commit_authority(
            store, proposal, claim, attestation, observations
        )
        _target_guard(snapshot, proposal["stream"], proposal["target_record_sha256"])
        refutation = {
            "schema": "an-kla/refutation-v1",
            "target_revision": observed,
            "stream": proposal["stream"],
            "target_record_sha256": proposal["target_record_sha256"],
            "reason": proposal["reason"],
            "proposal_sha256": digest_json(proposal),
            "authority_claim_sha256": digest_json(claim),
            "authority_attestation_id": digest_json(checked_attestation),
            "policy_fingerprint": policy_fingerprint(),
            "decision_sha256": digest_json(decision),
            "evidence_sha256": digest_json(claim["evidence"]),
            "plan_fingerprint": plan["plan_fingerprint"],
        }
        refutation_id = digest_json(refutation)
        metadata = {
            "schema": "an-kla/refute-policy-transaction-v1",
            "proposal_sha256": digest_json(proposal),
            "authority_claim_sha256": digest_json(claim),
            "authority_attestation_id": digest_json(checked_attestation),
            "policy_fingerprint": policy_fingerprint(),
            "decision_sha256": digest_json(decision),
            "evidence_sha256": digest_json(claim["evidence"]),
            "plan_fingerprint": plan["plan_fingerprint"],
            "decision": "refute",
            "reason": proposal["reason"],
            "target": {
                "stream": proposal["stream"],
                "record_sha256": proposal["target_record_sha256"],
            },
            "refutation_id": refutation_id,
        }
        revision, outcome = store._commit_locked(
            observed=observed,
            checkpoint_patch={},
            pending={"facts": [], "events": [], "episodes": []},
            attempt=attempt,
            policy_metadata=metadata,
            refute_objects={
                "authority_claim": claim,
                "authority_attestation": checked_attestation,
                "refutation": refutation,
            },
            store_identity=identity_digest,
        )
    if lock_result.release_error is not None:
        outcome = deepcopy(outcome)
        outcome["audit_state"] = "incomplete"
        outcome["warnings"] = sorted(set([*outcome["warnings"], lock_result.release_error]))
        if outcome["committed"] is True:
            outcome["state"] = "committed_audit_incomplete"
            outcome["operation_error_code"] = "lock_release_incomplete"
    if outcome["committed"] is True:
        store._maybe_reindex(observed, revision)
    return _result(decision, plan, revision=revision, outcome=outcome)


def validate_refutation_storage(
    store: Any, value: Mapping[str, Any], entry: Mapping[str, Any]
) -> dict[str, Any]:
    code = "refute_content_hash_mismatch"
    out = exact(
        value,
        {"schema", "target_revision", "stream", "target_record_sha256", "reason",
         "proposal_sha256", "authority_claim_sha256", "authority_attestation_id",
         "policy_fingerprint", "decision_sha256", "evidence_sha256",
         "plan_fingerprint"},
        code, "refutation.shape",
    )
    if out["schema"] != "an-kla/refutation-v1" or any(
        out[name] != entry[name]
        for name in ("stream", "target_record_sha256")
    ):
        raise RefutePolicyError(code, "refutation.binding")
    for name in (
        "target_revision", "target_record_sha256", "proposal_sha256",
        "authority_claim_sha256", "authority_attestation_id", "policy_fingerprint",
        "decision_sha256", "evidence_sha256", "plan_fingerprint",
    ):
        digest(out[name], code, name)
    claim = store._read_json_object("authority-claims", out["authority_claim_sha256"])
    checked_claim = validate_claim(claim)
    proposal = validate_proposal(
        {
            "schema": "an-kla/refute-proposal-v1",
            "base_revision": out["target_revision"],
            "stream": out["stream"],
            "target_record_sha256": out["target_record_sha256"],
            "reason": out["reason"],
        }
    )
    if digest_json(proposal) != out["proposal_sha256"] or digest_json(checked_claim) != out["authority_claim_sha256"]:
        raise RefutePolicyError(code, "proposal_or_claim")
    from .reader_gate import reader_gate_mode

    parent = (
        store._snapshot_under_gate(out["target_revision"])
        if reader_gate_mode(store) == "exclusive"
        else store.snapshot(out["target_revision"])
    )
    observations = build_observations(store, parent, checked_claim)
    attestation = store._read_json_object("authority-attestations", out["authority_attestation_id"])
    descriptor = validate_descriptor(attestation.get("resolver"))
    checked_attestation = validate_attestation(
        attestation, proposal, checked_claim, observations, descriptor
    )
    decision = {
        "schema": "an-kla/refute-decision-v1",
        "proposal_sha256": out["proposal_sha256"],
        "authority_claim_sha256": out["authority_claim_sha256"],
        "authority_attestation_id": out["authority_attestation_id"],
        "policy_profile": REFUTE_POLICY_PROFILE,
        "policy_fingerprint": out["policy_fingerprint"],
        "decision": "refute",
        "reason_codes": ["refute_accepted"],
    }
    plan = build_plan(
        proposal, checked_claim, checked_attestation, decision,
        enforce_installed_policy=False,
    )
    if (
        out["decision_sha256"] != digest_json(decision)
        or out["evidence_sha256"] != digest_json(checked_claim["evidence"])
        or out["plan_fingerprint"] != plan["plan_fingerprint"]
    ):
        raise RefutePolicyError(code, "policy_binding")
    return deepcopy(out)


def inspect_refute(store: Any, **kwargs: Any) -> dict[str, Any]:
    from .refute_inspect import inspect_refute as implementation

    return implementation(store, **kwargs)


__all__ = [
    "build_observations", "commit_refute", "inspect_refute", "plan_refute",
    "validate_refutation_storage",
]
