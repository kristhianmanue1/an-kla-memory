"""Durability evidence and lineage checks for ADR-0022 identity."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .canonical import canonical_json, digest_bytes, digest_json
from .storage_primitives import fsync_directory, sync_protected, write_immutable


RECEIPT_SCHEMA = "an-kla/identity-durability-receipt-v1"


class IdentityEvidenceError(ValueError):
    pass


def _receipts(store: Any) -> Path:
    return store.project_root / ".an-kla" / "identity-receipts" / "sha256"


def _reject_symlink(path: Path, root: Path) -> None:
    cursor = path
    while cursor != root:
        if cursor.is_symlink() or root not in cursor.parents:
            raise IdentityEvidenceError("store_identity_invalid")
        cursor = cursor.parent


def _write_create(path: Path, payload: bytes, root: Path) -> None:
    _reject_symlink(path, root)

    def conflict(_target: Path) -> None:
        raise IdentityEvidenceError("identity_bootstrap_conflict")

    write_immutable(path, payload, conflict=conflict, fsync_directory=fsync_directory)


def _read_canonical(path: Path) -> tuple[dict[str, Any], bytes]:
    payload = path.read_bytes()
    value = json.loads(payload)
    if not isinstance(value, dict) or canonical_json(value) != payload:
        raise IdentityEvidenceError("identity_receipt_invalid")
    return value, payload


def _is_ancestor(store: Any, candidate: str, current: str) -> bool:
    cursor = current
    seen: set[str] = set()
    for _ in range(10000):
        if cursor == candidate:
            return True
        if cursor in seen:
            return False
        seen.add(cursor)
        try:
            parent = store._read_json_object("revisions", cursor).get("parent")
        except Exception:
            return False
        if not isinstance(parent, str):
            return False
        cursor = parent
    return False


def validate_bound_descendants(
    store: Any,
    current: str,
    captured: str,
    identity_digest: str,
    *,
    allow_captured_legacy: bool = False,
) -> None:
    cursor = current
    seen: set[str] = set()
    for _ in range(10000):
        if cursor == captured:
            try:
                manifest = store._read_json_object("revisions", captured)
            except Exception as exc:
                raise IdentityEvidenceError(
                    "store_identity_lineage_mismatch"
                ) from exc
            if (
                not allow_captured_legacy
                and manifest.get("store_identity") != identity_digest
            ):
                raise IdentityEvidenceError("store_identity_lineage_mismatch")
            return
        if cursor in seen:
            break
        seen.add(cursor)
        try:
            manifest = store._read_json_object("revisions", cursor)
        except Exception:
            break
        if manifest.get("store_identity") != identity_digest:
            break
        parent = manifest.get("parent")
        if not isinstance(parent, str):
            break
        cursor = parent
    raise IdentityEvidenceError("store_identity_lineage_mismatch")


def valid_identity_receipt(
    store: Any, intent: Mapping[str, Any], current: str
) -> str | None:
    identity_digest = digest_json(intent["store_identity"])
    required = {
        ".an-kla/identity-intents/sha256/"
        + intent["intent_sha256"].removeprefix("sha256:")
        + ".json",
        ".an-kla/project-identity.json",
        ".an-kla/memory/identity.json",
        ".an-kla/memory/identities/sha256/"
        + identity_digest.removeprefix("sha256:")
        + ".json",
        ".an-kla/memory/refs/CURRENT",
    }
    matches: list[str] = []
    for path in sorted(_receipts(store).glob("*.json")):
        try:
            _reject_symlink(path, store.project_root)
            value, payload = _read_canonical(path)
            identifier = "sha256:" + path.stem
            if digest_bytes(payload) != identifier or set(value) != {
                "schema", "operation", "intent_sha256", "current_observed",
                "predecessor_receipt", "protected",
            }:
                continue
            if (
                value["schema"] != RECEIPT_SCHEMA
                or value["operation"] not in {"initialize", "adopt", "repair"}
                or value["intent_sha256"] != intent["intent_sha256"]
                or not isinstance(value["protected"], list)
            ):
                continue
            receipt_current = value["current_observed"]
            if not isinstance(receipt_current, str) or not _is_ancestor(
                store, receipt_current, current
            ):
                continue
            validate_bound_descendants(
                store,
                current,
                receipt_current,
                identity_digest,
                allow_captured_legacy=(
                    intent["operation"] == "adopt"
                    and receipt_current == intent["current_observed"]
                ),
            )
            files: set[str] = set()
            directories: set[str] = set()
            normalized: list[tuple[str, str]] = []
            for item in value["protected"]:
                if not isinstance(item, dict) or set(item) != {
                    "path", "operation", "content_sha256",
                }:
                    raise IdentityEvidenceError("identity_receipt_invalid")
                relative = item["path"]
                if (
                    not isinstance(relative, str)
                    or Path(relative).is_absolute()
                    or "\\" in relative
                    or any(part in {"", ".", ".."} for part in relative.split("/"))
                ):
                    raise IdentityEvidenceError("identity_receipt_invalid")
                target = store.project_root.joinpath(*relative.split("/"))
                _reject_symlink(target, store.project_root)
                if item["operation"] == "file_fsync":
                    if relative == ".an-kla/memory/refs/CURRENT":
                        expected = digest_bytes((receipt_current + "\n").encode("ascii"))
                        if item["content_sha256"] != expected or not _is_ancestor(
                            store, receipt_current, store.read_current()
                        ):
                            raise IdentityEvidenceError("identity_receipt_invalid")
                    elif digest_bytes(target.read_bytes()) != item["content_sha256"]:
                        raise IdentityEvidenceError("identity_receipt_invalid")
                    files.add(relative)
                elif (
                    item["operation"] == "directory_fsync"
                    and item["content_sha256"] is None
                    and target.is_dir()
                ):
                    directories.add(relative)
                else:
                    raise IdentityEvidenceError("identity_receipt_invalid")
                normalized.append((relative, item["operation"]))
            if normalized != sorted(normalized) or not required.issubset(files):
                continue
            if any(item.rsplit("/", 1)[0] not in directories for item in files):
                continue
            matches.append(identifier)
        except Exception:
            continue
    return matches[-1] if matches else None


def write_identity_receipt(
    store: Any, intent: Mapping[str, Any], operation: str, current: str
) -> str:
    identity_digest = digest_json(intent["store_identity"])
    protected = [
        {"path": ".an-kla/identity-intents/sha256/" + intent["intent_sha256"].removeprefix("sha256:") + ".json", "operation": "file_fsync", "content_sha256": intent["intent_sha256"]},
        {"path": ".an-kla/project-identity.json", "operation": "file_fsync", "content_sha256": digest_json(intent["project_identity"])},
        {"path": ".an-kla/memory/identity.json", "operation": "file_fsync", "content_sha256": identity_digest},
        {"path": ".an-kla/memory/identities/sha256/" + identity_digest.removeprefix("sha256:") + ".json", "operation": "file_fsync", "content_sha256": identity_digest},
        {"path": ".an-kla/memory/refs/CURRENT", "operation": "file_fsync", "content_sha256": digest_bytes((current + "\n").encode("ascii"))},
    ]
    for directory in sorted({item["path"].rsplit("/", 1)[0] for item in protected}):
        protected.append({"path": directory, "operation": "directory_fsync", "content_sha256": None})
    protected.sort(key=lambda item: (item["path"], item["operation"]))
    for item in protected:
        _reject_symlink(
            store.project_root.joinpath(*item["path"].split("/")), store.project_root
        )
    sync_protected(store.project_root, protected)
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "operation": operation,
        "intent_sha256": intent["intent_sha256"],
        "current_observed": current,
        "predecessor_receipt": valid_identity_receipt(store, intent, current),
        "protected": protected,
    }
    payload = canonical_json(receipt)
    identifier = digest_bytes(payload)
    target = _receipts(store) / (identifier.removeprefix("sha256:") + ".json")
    _write_create(target, payload, store.project_root)
    return identifier


__all__ = [
    "IdentityEvidenceError",
    "valid_identity_receipt",
    "validate_bound_descendants",
    "write_identity_receipt",
]
