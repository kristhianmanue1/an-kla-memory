"""Explicit durability repair for ADR-0024 transactions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .canonical import digest_bytes
from .receipt_validation import required_candidate_files
from .storage_primitives import fsync_directory, fsync_file
from .transactions import (
    TransactionError,
    _journal,
    _manifest_candidates,
    _receipt_ids,
    _stage_evidence,
    candidate_relation,
    inspect_transaction,
    protected_directory,
    protected_file,
    validate_attempt,
    write_receipt,
)

def _candidate_paths(
    store: Any,
    transaction_id: str,
    candidate: str,
    attempt: dict[str, Any],
) -> list[Path]:
    try:
        required = required_candidate_files(store, transaction_id, candidate, attempt)
    except ValueError as exc:
        raise TransactionError(str(exc)) from exc
    return [store.root.joinpath(*relative.split("/")) for relative in sorted(required)]


def repair_durability(store: Any, transaction_id: str) -> dict[str, Any]:
    """Re-fsync every candidate dependency and emit a repair receipt."""

    journal = _journal(store, transaction_id)
    candidates = _manifest_candidates(store, transaction_id)
    if len(candidates) != 1:
        raise TransactionError("transaction_candidate_ambiguous")
    candidate = candidates[0]
    attempt = None
    if journal is not None and not journal.get("corrupt"):
        try:
            attempt = validate_attempt(journal.get("attempt"))
        except TransactionError:
            attempt = None
    if attempt is None:
        stage = _stage_evidence(store, transaction_id, candidate)
        if stage is None:
            raise TransactionError("transaction_evidence_missing_or_invalid")
        attempt = validate_attempt(stage["attempt"])
    current = store.read_current()
    relation = candidate_relation(store, candidate, current)
    if relation == "unknown":
        raise TransactionError("transaction_authority_unknown")

    protected: list[dict[str, Any]] = []
    directories: set[Path] = set()
    for path in _candidate_paths(store, transaction_id, candidate, attempt):
        fsync_file(path)
        directories.add(path.parent)
        protected.append(
            protected_file(
                path.relative_to(store.root).as_posix(), digest_bytes(path.read_bytes())
            )
        )
    repair_for = "candidate-data-durable"
    if relation in {"current", "ancestor"}:
        fsync_file(store.current_path)
        directories.add(store.current_path.parent)
        protected.append(
            protected_file(
                store.current_path.relative_to(store.root).as_posix(),
                digest_bytes(store.current_path.read_bytes()),
            )
        )
        repair_for = "current-durable"
    for directory in sorted(directories, key=lambda item: str(item)):
        fsync_directory(directory)
        protected.append(
            protected_directory(directory.relative_to(store.root).as_posix())
        )

    receipt_ids = _receipt_ids(store, transaction_id)
    write_receipt(
        store,
        attempt=attempt,
        kind="repair",
        candidate_revision=candidate,
        predecessor_receipt=receipt_ids[-1] if receipt_ids else None,
        repair_for_kind=repair_for,
        protected=protected,
    )
    return inspect_transaction(store, transaction_id)


__all__ = ["repair_durability"]
