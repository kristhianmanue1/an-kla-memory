"""Pre-guard reconciliation for operation-specific transaction commits."""

from __future__ import annotations

from typing import Any, Mapping

from .transaction_attempts import TransactionError, validate_attempt
from .transactions import (
    _journal,
    _manifest_candidates,
    _stage_attempts,
    inspect_transaction,
)


def reconcile_attempt(store: Any, attempt: Mapping[str, Any]) -> dict[str, Any]:
    checked = validate_attempt(attempt)
    txid = checked["transaction_id"]
    existing = _journal(store, txid)
    candidates = _manifest_candidates(store, txid)
    if len(candidates) > 1:
        raise TransactionError("transaction_candidate_ambiguous")
    attempts = _stage_attempts(store, txid)
    if existing is not None and not existing.get("corrupt"):
        prior = existing.get("attempt")
        if prior != checked:
            raise TransactionError("transaction_binding_conflict")
        attempts.append(validate_attempt(prior))
    elif existing is not None and not attempts and not candidates:
        raise TransactionError("transaction_evidence_missing_or_invalid")
    if any(prior != checked for prior in attempts):
        raise TransactionError("transaction_binding_conflict")
    if candidates and not attempts:
        raise TransactionError("transaction_evidence_missing_or_invalid")
    has_evidence = bool(existing is not None or attempts or candidates)
    return {
        "has_evidence": has_evidence,
        "outcome": inspect_transaction(store, txid) if has_evidence else None,
    }


__all__ = ["reconcile_attempt"]
