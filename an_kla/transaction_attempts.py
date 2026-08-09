"""No-I/O transaction-attempt construction and validation."""

from __future__ import annotations

import uuid
from typing import Any, Mapping

from .canonical import bare_digest, digest_json


ATTEMPT_SCHEMA = "an-kla/transaction-attempt-v1"


class TransactionError(RuntimeError):
    pass


def canonical_uuid(value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, ValueError) as exc:
        raise TransactionError("invalid_transaction_id") from exc
    if (
        str(parsed) != value
        or parsed.version not in {1, 2, 3, 4, 5}
        or parsed.variant != uuid.RFC_4122
    ):
        raise TransactionError("invalid_transaction_id")
    return value


def begin_transaction(
    operation: str, *, transaction_id: str | None = None,
    base_revision: str | None = None, plan_fingerprint: str | None = None,
    initialization_fingerprint: str | None = None,
    mutation_fingerprint: str | None = None,
) -> dict[str, Any]:
    txid = canonical_uuid(transaction_id or str(uuid.uuid4()))
    core: dict[str, Any] = {"schema": ATTEMPT_SCHEMA, "operation": operation}
    if operation in {"write", "checkpoint", "refute", "compact"}:
        if base_revision is None or plan_fingerprint is None:
            raise TransactionError("invalid_transaction_binding")
        bare_digest(base_revision)
        bare_digest(plan_fingerprint)
        core.update({"base_revision": base_revision, "plan_fingerprint": plan_fingerprint})
    elif operation == "initialize":
        if initialization_fingerprint is None:
            raise TransactionError("invalid_transaction_binding")
        bare_digest(initialization_fingerprint)
        core.update({"expected_current": None, "initialization_fingerprint": initialization_fingerprint})
    elif operation == "internal_commit":
        if base_revision is None or mutation_fingerprint is None:
            raise TransactionError("invalid_transaction_binding")
        bare_digest(base_revision)
        bare_digest(mutation_fingerprint)
        core.update({"base_revision": base_revision, "mutation_fingerprint": mutation_fingerprint})
    else:
        raise TransactionError("invalid_transaction_operation")
    core["transaction_id"] = txid
    core["execution_fingerprint"] = digest_json(core)
    return core


def validate_attempt(attempt: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(attempt, dict):
        raise TransactionError("invalid_transaction_attempt")
    rebuilt = begin_transaction(
        str(attempt.get("operation")), transaction_id=attempt.get("transaction_id"),
        base_revision=attempt.get("base_revision"),
        plan_fingerprint=attempt.get("plan_fingerprint"),
        initialization_fingerprint=attempt.get("initialization_fingerprint"),
        mutation_fingerprint=attempt.get("mutation_fingerprint"),
    )
    if rebuilt != attempt:
        raise TransactionError("invalid_transaction_attempt")
    return rebuilt


__all__ = [
    "ATTEMPT_SCHEMA", "TransactionError", "begin_transaction", "canonical_uuid",
    "validate_attempt",
]
