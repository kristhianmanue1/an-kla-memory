"""Durability evidence and lineage checks for ADR-0022 identity."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .canonical import canonical_json, digest_bytes, digest_json
from .storage_primitives import fsync_directory, sync_protected, write_immutable
from .revision_walk import _LineageSummary, walk_revisions


RECEIPT_SCHEMA = "an-kla/identity-durability-receipt-v1"


class IdentityEvidenceError(ValueError):
    pass


def _receipts(store: Any) -> Path:
    return store.store_root / "identity-receipts" / "sha256"


def _custody_target(store: Any, relative: str) -> Path:
    """Map a receipt path to disk: ``.an-kla/`` denotes the custody root.

    ADR-0048 §2 (H9) and Enmienda 1 §4: receipts keep their bytes when the
    vault moves, so the prefix is logical, not a directory under the project.
    """

    parts = relative.split("/")
    if parts[0] != ".an-kla":
        raise IdentityEvidenceError("identity_receipt_invalid")
    return store.store_root.joinpath(*parts[1:])


def _custody_relative(item: Mapping[str, Any]) -> dict[str, Any]:
    tail = str(item["path"]).split("/", 1)
    return {**item, "path": tail[1] if len(tail) == 2 else "."}


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
    try:
        return any(identifier == candidate for identifier, _ in walk_revisions(store, current))
    except Exception:
        return False


def validate_bound_descendants(
    store: Any, current: str, captured: str, identity_digest: str,
    *, allow_captured_legacy: bool = False,
) -> None:
    try:
        for identifier, manifest in walk_revisions(store, current):
            linked = manifest.get("store_identity")
            if identifier == captured:
                if linked == identity_digest or (allow_captured_legacy and linked is None):
                    return
                break
            if linked != identity_digest:
                break
    except Exception as exc:
        raise IdentityEvidenceError("store_identity_lineage_mismatch") from exc
    raise IdentityEvidenceError("store_identity_lineage_mismatch")


def valid_identity_receipt(
    store: Any, intent: Mapping[str, Any], current: str,
    *, _lineage: _LineageSummary | None = None,
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
    prepared: list[tuple[str, str]] = []
    for path in sorted(_receipts(store).glob("*.json")):
        try:
            _reject_symlink(path, store.custody_walk_root)
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
            if not isinstance(receipt_current, str):
                continue
            from .canonical import bare_digest
            bare_digest(receipt_current)
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
                target = _custody_target(store, relative)
                _reject_symlink(target, store.custody_walk_root)
                if item["operation"] == "file_fsync":
                    if relative == ".an-kla/memory/refs/CURRENT":
                        expected = digest_bytes((receipt_current + "\n").encode("ascii"))
                        if item["content_sha256"] != expected:
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
            prepared.append((identifier, receipt_current))
        except Exception:
            continue
    if not prepared:
        return None
    try:
        lineage = _lineage
        if lineage is None or lineage.current != current or lineage.identity != identity_digest:
            lineage = _LineageSummary(store, current, identity_digest)
    except Exception:
        return None
    matches: list[str] = []
    for identifier, captured in prepared:
        allow_legacy = intent["operation"] == "adopt" and captured == intent["current_observed"]
        if not lineage.bound(captured, allow_legacy=allow_legacy):
            continue
        # Observe protected CURRENT again, as before. A changed head requires
        # independent ancestry evidence; the old summary cannot certify it.
        try:
            latest = store.read_current()
            ancestor = lineage.contains(captured) if latest == current else _is_ancestor(store, captured, latest)
            if ancestor:
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
        _reject_symlink(_custody_target(store, item["path"]), store.custody_walk_root)
    sync_protected(store.store_root, [_custody_relative(item) for item in protected])
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
    _write_create(target, payload, store.custody_walk_root)
    return identifier


__all__ = [
    "IdentityEvidenceError",
    "valid_identity_receipt",
    "validate_bound_descendants",
    "write_identity_receipt",
]
