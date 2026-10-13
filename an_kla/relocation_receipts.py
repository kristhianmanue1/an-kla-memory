"""Chained relocation receipts (ADR-0048 §2).

A relocation receipt records that a root moved: the project root
(``kind = "project_root"``, consumed by ``identity adopt``) or the custody
root (``kind = "store_root"``, produced by ``relocate`` in R2).  It is
evidence, not authority: callers decide what a valid receipt allows.
Receipts live under ``<store_root>/relocation-receipts/sha256/`` and travel
with the vault.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .canonical import bare_digest, canonical_json, digest_bytes, digest_json
from .storage_primitives import fsync_directory, write_immutable


SCHEMA = "an-kla/relocation-receipt-v1"
KINDS = frozenset({"project_root", "store_root"})
_KEYS = frozenset(
    {
        "schema",
        "kind",
        "store_identity",
        "current_observed",
        "from_root_observed",
        "to_root_observed",
        "predecessor_receipt",
    }
)
_MAX_CHAIN = 10000


class RelocationReceiptError(ValueError):
    pass


def receipts_dir(store: Any) -> Path:
    return store.store_root / "relocation-receipts" / "sha256"


def _reject_symlink(path: Path, root: Path) -> None:
    cursor = path
    while cursor != root:
        if cursor.is_symlink() or root not in cursor.parents:
            raise RelocationReceiptError("relocation_receipt_invalid")
        cursor = cursor.parent


def _path(store: Any, identifier: str) -> Path:
    try:
        hexpart = bare_digest(identifier)
    except (TypeError, ValueError) as exc:
        raise RelocationReceiptError("relocation_receipt_invalid") from exc
    return receipts_dir(store) / (hexpart + ".json")


def _load_one(store: Any, identifier: str) -> dict[str, Any]:
    path = _path(store, identifier)
    _reject_symlink(path, store.custody_walk_root)
    try:
        payload = path.read_bytes()
        value = json.loads(payload)
    except FileNotFoundError as exc:
        raise RelocationReceiptError("relocation_receipt_missing") from exc
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RelocationReceiptError("relocation_receipt_invalid") from exc
    if (
        not isinstance(value, dict)
        or canonical_json(value) != payload
        or digest_bytes(payload) != identifier
        or set(value) != _KEYS
        or value["schema"] != SCHEMA
        or value["kind"] not in KINDS
        or not all(
            isinstance(value[key], str)
            for key in (
                "store_identity",
                "current_observed",
                "from_root_observed",
                "to_root_observed",
            )
        )
        or value["from_root_observed"] == value["to_root_observed"]
        or not (
            value["predecessor_receipt"] is None
            or isinstance(value["predecessor_receipt"], str)
        )
    ):
        raise RelocationReceiptError("relocation_receipt_invalid")
    for key in ("store_identity", "current_observed"):
        try:
            bare_digest(value[key])
        except ValueError as exc:
            raise RelocationReceiptError("relocation_receipt_invalid") from exc
    return value


def load_relocation_receipt(store: Any, identifier: str) -> dict[str, Any]:
    """Load one receipt and validate its whole predecessor chain."""

    head = _load_one(store, identifier)
    seen = {identifier}
    cursor = head
    for _ in range(_MAX_CHAIN):
        predecessor = cursor["predecessor_receipt"]
        if predecessor is None:
            return head
        if predecessor in seen:
            raise RelocationReceiptError("relocation_receipt_chain_invalid")
        seen.add(predecessor)
        previous = _load_one(store, predecessor)
        if (
            previous["store_identity"] != cursor["store_identity"]
            or previous["kind"] != cursor["kind"]
            or previous["to_root_observed"] != cursor["from_root_observed"]
        ):
            raise RelocationReceiptError("relocation_receipt_chain_invalid")
        cursor = previous
    raise RelocationReceiptError("relocation_receipt_chain_invalid")


def chain_head(store: Any, store_identity: str, kind: str) -> str | None:
    """Return the single unreferenced receipt for this binding and kind."""

    directory = receipts_dir(store)
    if not directory.exists():
        return None
    _reject_symlink(directory, store.custody_walk_root)
    members: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        identifier = "sha256:" + path.stem
        value = _load_one(store, identifier)
        if value["store_identity"] == store_identity and value["kind"] == kind:
            members[identifier] = value
    referenced = {value["predecessor_receipt"] for value in members.values()}
    heads = [identifier for identifier in members if identifier not in referenced]
    if len(heads) > 1:
        raise RelocationReceiptError("relocation_receipt_chain_invalid")
    return heads[0] if heads else None


def write_relocation_receipt(
    store: Any,
    *,
    kind: str,
    store_identity: str,
    current_observed: str,
    from_root: str,
    to_root: str,
) -> str:
    """Append one receipt to the chain; callers hold the identity lock."""

    if kind not in KINDS or from_root == to_root:
        raise RelocationReceiptError("relocation_receipt_invalid")
    predecessor = chain_head(store, store_identity, kind)
    if predecessor is not None:
        previous = load_relocation_receipt(store, predecessor)
        if previous["to_root_observed"] != from_root:
            raise RelocationReceiptError("relocation_receipt_chain_invalid")
    value = {
        "schema": SCHEMA,
        "kind": kind,
        "store_identity": store_identity,
        "current_observed": current_observed,
        "from_root_observed": from_root,
        "to_root_observed": to_root,
        "predecessor_receipt": predecessor,
    }
    payload = canonical_json(value)
    identifier = digest_bytes(payload)
    target = _path(store, identifier)
    _reject_symlink(target, store.custody_walk_root)

    def conflict(_target: Path) -> None:
        raise RelocationReceiptError("relocation_receipt_invalid")

    write_immutable(target, payload, conflict=conflict, fsync_directory=fsync_directory)
    return identifier


def project_relocation_expectation(
    project_root: str, plan: Mapping[str, Any], expected_current: str
) -> dict[str, str]:
    """Fields a ``project_root`` receipt must carry for an adoption plan."""

    return {
        "kind": "project_root",
        "store_identity": digest_json(plan["store_identity"]),
        "current_observed": expected_current,
        "from_root_observed": plan["canonical_project_root_observed"],
        "to_root_observed": project_root,
    }


def require_matching_receipt(
    store: Any, identifier: str, expected: Mapping[str, str]
) -> dict[str, Any]:
    """Load ``identifier`` and require every ``expected`` field to match."""

    value = load_relocation_receipt(store, identifier)
    if any(value.get(key) != item for key, item in expected.items()):
        raise RelocationReceiptError("relocation_receipt_mismatch")
    return value


__all__ = [
    "RelocationReceiptError",
    "SCHEMA",
    "chain_head",
    "load_relocation_receipt",
    "project_relocation_expectation",
    "receipts_dir",
    "require_matching_receipt",
    "write_relocation_receipt",
]
