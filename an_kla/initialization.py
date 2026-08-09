"""Transactional creation of a root revision."""

from __future__ import annotations

from typing import Any

from .canonical import digest_bytes, digest_json
from .storage_primitives import storage_error
from .transactions import (
    TransactionError,
    _journal,
    _manifest_candidates,
    _stage_attempts,
    begin_transaction,
    candidate_relation,
    inspect_transaction,
    make_outcome,
    protected_directory,
    protected_file,
    write_receipt,
)


def initialize_locked(
    store: Any,
    *,
    transaction_id: str | None = None,
    store_identity: str | None = None,
) -> tuple[str | None, dict[str, Any]]:
    """Create a root while the caller owns the write lock."""

    checkpoint = {
        "schema": "an-kla/checkpoint-v1",
        "revision": 0,
        "goal": None,
        "next": None,
        "decisions": [],
        "blockers": [],
    }
    binding = {"checkpoint": checkpoint, "store_identity": store_identity}
    attempt = begin_transaction(
        "initialize",
        transaction_id=transaction_id,
        initialization_fingerprint=digest_json(binding),
    )
    txid = attempt["transaction_id"]
    journal = _journal(store, txid)
    candidates = _manifest_candidates(store, txid)
    if len(candidates) > 1:
        raise TransactionError("transaction_candidate_ambiguous")
    evidence_attempts = _stage_attempts(store, txid)
    if journal is not None and not journal.get("corrupt"):
        prior = journal.get("attempt")
        if prior != attempt:
            raise TransactionError("transaction_binding_conflict")
        evidence_attempts.append(prior)
    elif journal is not None and not evidence_attempts and not candidates:
        raise TransactionError("transaction_evidence_missing_or_invalid")
    if any(prior != attempt for prior in evidence_attempts):
        raise TransactionError("transaction_binding_conflict")
    if candidates:
        inspected = inspect_transaction(store, txid)
        if inspected.get("committed") is True:
            return candidates[0], inspected
    candidate = None
    candidate_receipt = None
    current_receipt = None
    recorded = False
    audit = "not_started"
    try:
        store._write_transaction(
            txid, {"stage": "prepared", "parent": None, "attempt": attempt}
        )
        recorded = True
        audit = "prepared"
        checkpoint_id = store._write_json_object("checkpoints", checkpoint)
        manifest = {
            "schema": "an-kla/revision-v1",
            "revision": 0,
            "parent": None,
            "facts_segments": [],
            "events_segments": [],
            "episodes_segments": [],
            "checkpoint": checkpoint_id,
            "transaction_id": txid,
            "canonicalization": "canonical-json/v1",
            "integrity_claim": "content_identity_not_truth_or_authorship",
        }
        if store_identity is not None:
            manifest["store_identity"] = store_identity
        store._validate_manifest(manifest)
        candidate = store._write_json_object("revisions", manifest)
        stage = {
            "schema": "an-kla/transaction-stage-v1",
            "stage": "candidate_prepared",
            "parent": None,
            "candidate": candidate,
            "attempt": attempt,
        }
        stage_id = store._write_json_object(f"transactions/{txid}/stages", stage)
        audit = "incomplete"
        store._write_transaction(
            txid,
            {
                **stage,
                "stage_object": stage_id,
                "candidate_receipt": None,
                "current_receipt": None,
            },
        )
        candidate_receipt = write_receipt(
            store,
            attempt=attempt,
            kind="candidate-data-durable",
            candidate_revision=candidate,
            protected=[
                protected_file(
                    f"checkpoints/sha256/{checkpoint_id.removeprefix('sha256:')}.json",
                    checkpoint_id,
                ),
                protected_file(
                    f"revisions/sha256/{candidate.removeprefix('sha256:')}.json",
                    candidate,
                ),
                protected_file(
                    f"transactions/{txid}/stages/sha256/{stage_id.removeprefix('sha256:')}.json",
                    stage_id,
                ),
                protected_directory("checkpoints/sha256"),
                protected_directory("revisions/sha256"),
                protected_directory(f"transactions/{txid}/stages/sha256"),
            ],
        )
        store._write_transaction(
            txid,
            {
                **stage,
                "stage_object": stage_id,
                "candidate_receipt": candidate_receipt,
                "current_receipt": None,
            },
        )
        store._replace_current(candidate)
        current_receipt = write_receipt(
            store,
            attempt=attempt,
            kind="current-durable",
            candidate_revision=candidate,
            predecessor_receipt=candidate_receipt,
            protected=[
                protected_file(
                    "refs/CURRENT", digest_bytes((candidate + "\n").encode("ascii"))
                ),
                protected_directory("refs"),
            ],
        )
        try:
            confirmed_current = store.read_current()
        except Exception as exc:
            raise storage_error("current_reread_failed", exc) from exc
        if confirmed_current != candidate:
            raise storage_error("current_reread_mismatch", OSError("CURRENT mismatch"))
        store._write_transaction(
            txid,
            {
                "stage": "committed",
                "parent": None,
                "candidate": candidate,
                "attempt": attempt,
                "stage_object": stage_id,
                "candidate_receipt": candidate_receipt,
                "current_receipt": current_receipt,
            },
        )
        audit = "complete"
    except OSError as exc:
        current = None
        if recorded:
            try:
                current = store.read_current()
            except Exception:
                current = None
        relation = candidate_relation(store, candidate, current)
        outcome = make_outcome(
            attempt=attempt,
            parent_revision=None,
            candidate_revision=candidate,
            current_observed=current,
            candidate_relation=relation,
            recorded=recorded,
            audit_state=audit if audit != "not_started" else "incomplete",
            durability_state=(
                "complete"
                if (
                    current_receipt is not None
                    if relation in {"current", "ancestor"}
                    else candidate_receipt is not None
                )
                else "incomplete"
            ),
            operation_error_code=getattr(exc, "code", "storage_io_failed"),
            warnings=[
                *(["transaction_not_recorded"] if not recorded else []),
                *(["cleanup_incomplete"] if getattr(exc, "cleanup_incomplete", False) else []),
                *(["close_incomplete"] if getattr(exc, "close_incomplete", False) else []),
            ],
        )
        return candidate, outcome
    return candidate, make_outcome(
        attempt=attempt,
        parent_revision=None,
        candidate_revision=candidate,
        current_observed=candidate,
        candidate_relation="current",
        recorded=True,
        audit_state="complete",
        durability_state="complete",
        operation_error_code=None,
    )


def existing_initialization(store: Any, transaction_id: str | None) -> dict[str, Any] | None:
    """Return an existing root outcome when it is bound to the requested txid."""

    if not store.current_path.exists():
        return None
    current = store.read_current()
    manifest = store._read_json_object("revisions", current)
    existing_txid = manifest.get("transaction_id")
    if manifest.get("parent") is not None:
        return {"revision": current, "outcome": None}
    if transaction_id is not None and existing_txid != transaction_id:
        return {"revision": current, "outcome": None}
    if isinstance(existing_txid, str) and existing_txid != "root":
        try:
            outcome = inspect_transaction(store, existing_txid)
            if outcome.get("candidate_revision") != current:
                outcome = None
        except Exception:
            outcome = None
    else:
        outcome = None
    return {"revision": current, "outcome": outcome}


__all__ = ["existing_initialization", "initialize_locked"]
