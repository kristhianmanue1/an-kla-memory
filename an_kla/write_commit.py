"""Flujo gobernado de escritura: ``commit_write_plan`` (#117 partición).

La composición completa vive aquí como función pura de ``store``; la
clase ``MemoryStore`` delega. Incluye el replay de ADR-0024 §API/CLI
(issue #115/T1): mismo txid + mismo binding reproduce el resultado del
commit ya reconciliado en lugar de chocar con el CAS; binding distinto
falla cerrado con ``transaction_binding_conflict``.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from . import attest as attest_module
from .identity import assert_unchanged, mutation_preflight
from .record_text import record_text
from .subject_binding import check_subject_ref_binding
from .supersede import resolve_supersede_targets
from .transactions import begin_transaction
from .write_policy import WritePolicyError, verify_write_plan

_EMPTY_PENDING: dict[str, list[dict[str, Any]]] = {
    "facts": [],
    "events": [],
    "episodes": [],
}


def commit_write_plan(
    store: Any,
    *,
    expected_current_hash: str,
    plan: Mapping[str, Any],
    proposal: Mapping[str, Any],
    authority: Mapping[str, Any],
    decision: Mapping[str, Any],
    transaction_id: str | None = None,
) -> dict[str, Any]:
    """Revalidate and commit one exact write plan under the store lock."""

    binding = mutation_preflight(store)
    store._make_layout()
    with store.write_lock() as lock_result:
        observed = store.read_current()
        if observed != expected_current_hash:
            # ADR-0024 §API/CLI (issue #115/T1): antes de rechazar por CAS,
            # un txid comprometido con el mismo plan binding se repliega
            # vía la reconciliación de _commit_locked (mismo attempt ->
            # resultado reproducido; attempt distinto ->
            # transaction_binding_conflict). Sin txid, CAS de siempre.
            if transaction_id is None:
                raise WritePolicyError("write_plan_base_changed")
            inspected = store.inspect_transaction(transaction_id)
            if inspected.get("committed") is not True:
                raise WritePolicyError("write_plan_base_changed")
            attempt = begin_transaction(
                "write",
                transaction_id=transaction_id,
                base_revision=expected_current_hash,
                plan_fingerprint=plan.get("plan_fingerprint"),
            )
            revision, outcome = store._commit_locked(
                observed=expected_current_hash,
                checkpoint_patch={},
                pending=deepcopy(_EMPTY_PENDING),
                attempt=attempt,
                store_identity=assert_unchanged(store, binding, observed),
            )
            outcome = _post_lock_outcome(outcome, lock_result.release_error)
            return {
                "schema": "an-kla/write-commit-result-v1",
                "committed": True,
                "revision": revision,
                "decision": decision["decision"],
                "reason_codes": deepcopy(decision["reason_codes"]),
                "plan_fingerprint": plan.get("plan_fingerprint"),
                "context_diagnostics": store._context_diagnostics(),
                "outcome": outcome,
                "replayed": True,
            }
        store_identity = assert_unchanged(store, binding, observed)

        # Callers retain their dictionaries and may share them with other
        # threads.  Snapshot every object while holding the store lock and
        # use only those detached values after verification; otherwise a
        # mutation between verify_write_plan() and pending construction
        # could change the bytes that reach the segment.
        checked_plan = deepcopy(plan)
        checked_proposal = deepcopy(proposal)
        checked_authority = deepcopy(authority)
        checked_decision = deepcopy(decision)

        # All policy validation intentionally occurs again inside the same
        # critical section that can move CURRENT.  The pure module remains
        # the only implementation of the policy.
        verify_write_plan(
            checked_plan,
            checked_proposal,
            checked_authority,
            checked_decision,
        )
        if (
            checked_proposal["base_revision"] != observed
            or checked_authority["base_revision"] != observed
            or checked_plan["core"]["base_revision"] != observed
        ):
            raise WritePolicyError("write_plan_base_changed")

        # ADR-0046: engine-level defense-in-depth bajo lock (detalle
        # en an_kla/attest.enforce_for_commit).
        if (
            checked_decision["decision"] != "skip"
            and checked_authority["authority_class"] == "tool_observed"
        ):
            attest_module.enforce_for_commit(store, checked_authority)

        if checked_decision["decision"] == "skip":
            return {
                "schema": "an-kla/write-commit-result-v1",
                "committed": False,
                "revision": observed,
                "decision": "skip",
                "reason_codes": deepcopy(checked_decision["reason_codes"]),
                "plan_fingerprint": checked_plan["plan_fingerprint"],
                "context_diagnostics": store._context_diagnostics(),
            }

        # ADR-0019 (PR-B): resolve supersede targets against the authoritative
        # snapshot under the lock, before any object/journal is written. A
        # failure here raises invalid_supersede_target (terminal) with no
        # side effects (no orphan objects, no prepared journal).
        pending_supersedes = resolve_supersede_targets(store, checked_plan, observed)

        # ADR-0033 §Decisión 5 (issue #59 Fase B): validate subject_ref
        # namespaces against the bound project identity, still under the
        # write lock and before any object/journal is written. ``binding``
        # is the snapshot captured by mutation_preflight and revalidated by
        # assert_unchanged; the guard never re-reads project identity.
        check_subject_ref_binding(checked_plan, binding)

        pending: dict[str, list[dict[str, Any]]] = {
            "facts": [],
            "events": [],
            "episodes": [],
        }
        for item in checked_plan["records"]:
            # The policy core (write_policy.py) is the only implementation of
            # the policy; refute/decay never reach here (they skip). add and
            # supersede both append the new record to its stream; supersede
            # additionally records the target's vigency flip above.
            op = item["operation"]
            if op == "add":
                pending[item["stream"]].append(deepcopy(item["record"]))
            elif op == "supersede":
                pending[item["stream"]].append(deepcopy(item["record"]))
            else:
                raise WritePolicyError(
                    "invalid_write_plan",
                    "records[]:operation:not_committable",
                )

        policy_metadata = {
            "schema": "an-kla/write-policy-transaction-v1",
            "plan_fingerprint": checked_plan["plan_fingerprint"],
            "proposal_sha256": checked_decision["proposal_sha256"],
            "authority_sha256": checked_decision["authority_sha256"],
            "policy_fingerprint": checked_decision["policy_fingerprint"],
            "decision": checked_decision["decision"],
            "reason_codes": deepcopy(checked_decision["reason_codes"]),
        }
        attempt = begin_transaction(
            "write",
            transaction_id=transaction_id,
            base_revision=observed,
            plan_fingerprint=checked_plan["plan_fingerprint"],
        )
        revision, outcome = store._commit_locked(
            observed=observed,
            checkpoint_patch={},
            pending=pending,
            attempt=attempt,
            policy_metadata=policy_metadata,
            supersedes=pending_supersedes or None,
            store_identity=store_identity,
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
    if outcome["committed"] is True and revision != observed:
        store._maybe_reindex(observed, revision)
    if outcome["committed"] is True and not record_text(
        checked_proposal["record"]
    ):
        # Issue #104 (H2): warning visible en el outcome (el reason ya
        # viaja en la decisión; ADR-0018/issue #15).
        outcome = deepcopy(outcome)
        outcome["warnings"] = sorted(
            set([*outcome["warnings"], "record_without_indexable_text"])
        )
    return {
        "schema": "an-kla/write-commit-result-v1",
        "committed": outcome["committed"] is True,
        "revision": revision,
        "decision": checked_decision["decision"],
        "reason_codes": deepcopy(checked_decision["reason_codes"]),
        "plan_fingerprint": checked_plan["plan_fingerprint"],
        "context_diagnostics": store._context_diagnostics(),
        "outcome": outcome,
    }


def _post_lock_outcome(outcome: dict[str, Any], release_error: str | None) -> dict[str, Any]:
    if release_error is not None:
        outcome = deepcopy(outcome)
        outcome["audit_state"] = "incomplete"
        outcome["warnings"] = sorted(
            set([*outcome["warnings"], release_error])
        )
        if outcome["committed"] is True:
            outcome["state"] = "committed_audit_incomplete"
            outcome["operation_error_code"] = "lock_release_incomplete"
    return outcome
