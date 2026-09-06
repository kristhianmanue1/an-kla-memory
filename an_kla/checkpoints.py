"""Store-facing governed checkpoint operations (ADR-0023)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .canonical import digest_json
from .checkpoint_policy import (
    CheckpointPolicyError,
    FIELDS,
    build_plan,
    evaluate,
    validate_working_state,
    verify_plan,
)
from .identity import assert_unchanged, mutation_preflight
from .transactions import begin_transaction


_DEFAULT_ISSUER_CONFIG = {
    "kind": "model",
    "id": "agent-local",
    "profile": "manual-cli/v1",
}


def emit_authority_template(
    store: Any, working_state: Mapping[str, Any]
) -> dict[str, Any]:
    """Plantilla de authority sin leer código interno (issue #120).

    Read-only: valida el working_state, arma el proposal interno
    exactamente como ``plan_checkpoint`` y devuelve la authority con
    ``proposal_sha256``/``base_revision`` ya calculados. El caller edita
    ``issuer`` si su clase/config difiere del default documentado
    (``model_derived`` con config saneada ``manual-cli/v1``).
    """
    validate_working_state(working_state)
    observed = store.read_current()
    snapshot = store.snapshot(observed)
    proposal = {
        "schema": "an-kla/checkpoint-proposal-v1",
        "base_revision": observed,
        "parent_checkpoint": snapshot.manifest["checkpoint"],
        "working_state": deepcopy(dict(working_state)),
    }
    return {
        "schema": "an-kla/checkpoint-authority-v1",
        "proposal_sha256": digest_json(proposal),
        "base_revision": observed,
        "authority_class": "model_derived",
        "issuer": {
            "kind": "model",
            "id": "agent-local",
            "configuration_fingerprint": digest_json(_DEFAULT_ISSUER_CONFIG),
        },
        "evidence": [],
        "scope": {
            "operation": "checkpoint",
            "fields": sorted(FIELDS, key=lambda item: item.encode("utf-8")),
        },
    }


def show_checkpoint(store: Any) -> dict[str, Any]:
    snapshot = store.snapshot()
    return {
        "schema": "an-kla/checkpoint-show-v1",
        "untrusted_memory_data": True,
        "revision": snapshot.revision_id,
        "checkpoint_digest": snapshot.manifest["checkpoint"],
        "checkpoint": deepcopy(dict(snapshot.checkpoint)),
    }


def plan_checkpoint(
    store: Any,
    working_state: Mapping[str, Any],
    authority: Mapping[str, Any],
) -> dict[str, Any]:
    validate_working_state(working_state)
    observed = store.read_current()
    snapshot = store.snapshot(observed)
    proposal = {
        "schema": "an-kla/checkpoint-proposal-v1",
        "base_revision": observed,
        "parent_checkpoint": snapshot.manifest["checkpoint"],
        "working_state": deepcopy(dict(working_state)),
    }
    decision = evaluate(proposal, authority)
    if (
        snapshot.checkpoint.get("schema") == "an-kla/checkpoint-v2"
        and snapshot.checkpoint.get("working_state") == working_state
        and decision["decision"] == "write"
    ):
        decision = {**decision, "decision": "skip", "reasons": ["checkpoint_unchanged"]}
    plan = build_plan(
        proposal,
        authority,
        decision,
        revision=int(snapshot.manifest["revision"]) + 1,
    )
    return {
        "schema": "an-kla/checkpoint-planning-result-v1",
        "current_revision": observed,
        "proposal": proposal,
        "authority": deepcopy(dict(authority)),
        "decision": decision,
        "plan": plan,
    }


def _planning(value: Mapping[str, Any], expected: str) -> tuple[dict[str, Any], ...]:
    if (
        not isinstance(value, dict)
        or set(value) != {
            "schema", "current_revision", "proposal", "authority", "decision", "plan"
        }
        or value.get("schema") != "an-kla/checkpoint-planning-result-v1"
        or value.get("current_revision") != expected
    ):
        raise CheckpointPolicyError("invalid_checkpoint_plan")
    return tuple(
        deepcopy(dict(value[name]))
        for name in ("proposal", "authority", "decision", "plan")
    )


def commit_checkpoint(
    store: Any,
    planning_result: Mapping[str, Any],
    expected_current: str,
    *,
    transaction_id: str | None = None,
) -> dict[str, Any]:
    proposal, authority, decision, plan = _planning(
        planning_result, expected_current
    )
    if decision.get("decision") == "write" and transaction_id is None:
        raise CheckpointPolicyError("checkpoint_transaction_id_required")
    binding = mutation_preflight(store)
    snapshot = store.snapshot(expected_current)
    if (
        proposal.get("base_revision") != expected_current
        or proposal.get("parent_checkpoint") != snapshot.manifest["checkpoint"]
        or proposal.get("working_state", {}).get("supersedes_checkpoint")
        != snapshot.manifest["checkpoint"]
    ):
        raise CheckpointPolicyError("checkpoint_parent_mismatch")
    verify_plan(
        plan,
        proposal,
        authority,
        decision,
        revision=int(snapshot.manifest["revision"]) + 1,
    )
    if decision["reasons"] == ["checkpoint_unchanged"] and not (
        snapshot.checkpoint.get("schema") == "an-kla/checkpoint-v2"
        and snapshot.checkpoint.get("working_state") == proposal["working_state"]
    ):
        raise CheckpointPolicyError("invalid_checkpoint_plan")
    attempt = (
        begin_transaction(
            "checkpoint",
            transaction_id=transaction_id,
            base_revision=expected_current,
            plan_fingerprint=plan["plan_fingerprint"],
        )
        if decision["decision"] == "write"
        else None
    )
    with store.write_lock() as lock_result:
        observed = store.read_current()
        identity_digest = assert_unchanged(store, binding, expected_current)
        if observed != expected_current:
            if attempt is None or transaction_id is None:
                raise CheckpointPolicyError("checkpoint_plan_base_changed")
            inspected = store.inspect_transaction(transaction_id)
            if inspected.get("committed") is not True:
                raise CheckpointPolicyError("checkpoint_plan_base_changed")
            revision, outcome = store._commit_locked(
                observed=expected_current,
                checkpoint_patch=plan["checkpoint"],
                pending={"facts": [], "events": [], "episodes": []},
                attempt=attempt,
                store_identity=identity_digest,
            )
        elif decision["decision"] == "skip":
            return {
                "schema": "an-kla/checkpoint-commit-result-v1",
                "committed": False,
                "revision": observed,
                "checkpoint": snapshot.manifest["checkpoint"],
                "plan_fingerprint": plan["plan_fingerprint"],
                "outcome": None,
            }
        else:
            revision, outcome = store._commit_locked(
                observed=observed,
                checkpoint_patch=plan["checkpoint"],
                pending={"facts": [], "events": [], "episodes": []},
                attempt=attempt,
                store_identity=identity_digest,
            )
    if lock_result.release_error is not None:
        outcome = deepcopy(outcome)
        outcome["audit_state"] = "incomplete"
        outcome["warnings"] = sorted(
            set([*outcome["warnings"], lock_result.release_error])
        )
        if outcome["committed"] is True:
            outcome["state"] = "committed_audit_incomplete"
            outcome["operation_error_code"] = "lock_release_incomplete"
    checkpoint_digest = (
        store.snapshot(revision).manifest["checkpoint"]
        if outcome["committed"] is True
        else snapshot.manifest["checkpoint"]
    )
    return {
        "schema": "an-kla/checkpoint-commit-result-v1",
        "committed": outcome["committed"] is True,
        "revision": revision,
        "checkpoint": checkpoint_digest,
        "plan_fingerprint": plan["plan_fingerprint"],
        "outcome": outcome,
    }


__all__ = ["commit_checkpoint", "plan_checkpoint", "show_checkpoint"]
