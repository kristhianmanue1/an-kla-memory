"""Relocate-back: external custody to project-local (ADR-0048 §3.5, R2b).

The destination ``<project>/.an-kla`` already exists (pointer, context,
host hooks, journals, locks), so there is no single ``rename``: the staged
copy is published **per subtree** with ``rename_noreplace``, journaled, and
the commit point is removing the pointer.  Only then are the planned files
deleted from the external root.  Shares plan, journal and reconcile entry
points with :mod:`an_kla.relocate`.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import Any, Mapping
import uuid

from .canonical import digest_bytes, digest_json
from .custody import (
    CustodyError, custody_fingerprint, default_store_root, pointer_path, read_pointer,
)
from .export_io import ExportIOError, rename_noreplace
from .identity import identity_lock, mutation_preflight, read_binding
from .relocation_receipts import write_relocation_receipt
from . import relocate as forward
from .relocate import RelocateError
from .storage_primitives import fsync_directory


DIRECTION = "external_to_project_local"


def _units(entries: list[Mapping[str, Any]]) -> list[str]:
    """Top-level subtrees to publish; ``memory/`` itself may already exist."""

    units = set()
    for entry in entries:
        parts = entry["path"].removeprefix("anchor/").split("/")
        units.add("/".join(parts[:2]) if parts[0] == "memory" else parts[0])
    units.add("relocation-receipts")
    return sorted(units)


def _staging(project_root: Path, txid: str) -> Path:
    # Inside the project but outside ``.an-kla``: a valid custody root for
    # ``verify`` and on the destination's filesystem for ``rename``.
    return project_root / f".an-kla.staging-{txid}"


def _occupied(anchor: Path, units: list[str]) -> list[str]:
    return [unit for unit in units if os.path.lexists(anchor / unit)]


def plan_back(store: Any) -> dict[str, Any]:
    if not getattr(store, "store_external", False):
        raise RelocateError("relocate_source_not_external")
    anchor = store.store_root
    destination = default_store_root(store.project_root)
    with identity_lock(store):
        with store.write_lock():
            binding = mutation_preflight(store)
            if read_pointer(store.project_root) is None:
                raise RelocateError("relocate_pointer_required")
            verified = store.verify()
            if verified["identity_status"] != "complete":
                raise RelocateError("relocate_source_identity_incomplete")
            current = store.read_current()
            entries = []
            for relative, _path in forward._move_set(anchor):
                payload = forward._read(anchor, relative)
                entries.append(
                    {"path": relative, "size": len(payload), "content_sha256": digest_bytes(payload)}
                )
    occupied = _occupied(destination, _units(entries))
    if occupied:
        raise RelocateError("relocate_destination_occupied")
    core = {
        "direction": DIRECTION,
        "transaction_id": str(uuid.uuid4()),
        "project_root": str(store.project_root),
        "source_store_root": str(anchor),
        "destination_store_root": str(destination),
        "base_revision": current,
        "custody_fingerprint": custody_fingerprint(binding),
        "store_identity": binding["store_identity"],
        "entries": entries,
    }
    return {"schema": forward.PLAN_SCHEMA, "core": core, "plan_sha256": digest_json(core)}


def _publish_units(staging: Path, anchor: Path, units: list[str]) -> None:
    (anchor / "memory").mkdir(mode=0o700, exist_ok=True)
    for unit in units:
        source = staging / unit
        target = anchor / unit
        if not os.path.lexists(source):
            if os.path.lexists(target):
                continue  # published before a crash
            raise RelocateError("relocate_staging_incomplete")
        try:
            rename_noreplace(source, target)
        except ExportIOError as exc:
            raise RelocateError("relocate_destination_occupied") from exc
        fsync_directory(target.parent)
        forward._point(f"published:{unit}")


def _unit_is_planned_copy(core: Mapping[str, Any], unit: str, receipt: str | None) -> bool:
    """Every file under ``unit`` at the destination is a planned copy."""

    anchor = Path(core["destination_store_root"])
    expected = {entry["path"]: entry["content_sha256"] for entry in core["entries"]}
    if receipt is not None:
        expected["anchor/relocation-receipts/sha256/" + receipt.removeprefix("sha256:") + ".json"] = receipt
    root = anchor / unit
    paths = [root] if not root.is_dir() else [path for path in root.rglob("*") if not path.is_dir()]
    for path in paths:
        relative = "anchor/" + path.relative_to(anchor).as_posix()
        if path.is_symlink() or relative not in expected:
            return False
        if digest_bytes(forward._read(anchor, relative)) != expected[relative]:
            return False
    return True


def _remove_units(core: Mapping[str, Any], units: list[str], receipt: str | None) -> None:
    anchor = Path(core["destination_store_root"])
    present = [unit for unit in units if os.path.lexists(anchor / unit)]
    if not all(_unit_is_planned_copy(core, unit, receipt) for unit in present):
        raise RelocateError("relocate_destination_unrecognized")
    for unit in present:
        target = anchor / unit
        shutil.rmtree(target) if target.is_dir() else target.unlink()
        fsync_directory(target.parent)


def _published_matches(core: Mapping[str, Any], receipt: str) -> bool:
    anchor = Path(core["destination_store_root"])
    for entry in core["entries"]:
        try:
            payload = forward._read(anchor, entry["path"])
        except RelocateError:
            return False
        if digest_bytes(payload) != entry["content_sha256"]:
            return False
    own = anchor / "relocation-receipts" / "sha256" / (receipt.removeprefix("sha256:") + ".json")
    return own.is_file() and not own.is_symlink()


def _remove_pointer(core: Mapping[str, Any]) -> None:
    pointer = read_pointer(core["project_root"])
    if pointer is None:
        return
    if pointer["custody_fingerprint"] != core["custody_fingerprint"]:
        raise RelocateError("store_root_divergence")
    path = pointer_path(core["project_root"])
    path.unlink()
    fsync_directory(path.parent)


def _finish(core: Mapping[str, Any], journal: dict[str, Any], source: Any) -> None:
    """Commit point (pointer removal), project-local verify, then cleanup."""

    from .store import MemoryStore

    root = Path(core["project_root"])
    committed_before = journal["stage"] == "pointer_removed"
    if journal["stage"] == "published":
        if not _published_matches(core, journal["relocation_receipt"]):
            raise RelocateError("relocate_destination_unrecognized")
        _remove_pointer(core)
        forward._write_journal(root, journal, "pointer_removed")
        forward._point("after_pointer")
    local = MemoryStore(root)
    checked = local.verify()
    if custody_fingerprint(read_binding(local)) != core["custody_fingerprint"]:
        raise RelocateError("relocate_destination_unrecognized")
    # After the commit point the project-local vault is live and may have
    # advanced; cleanup still deletes only byte-matching planned files.
    if not committed_before and checked["revision"] != core["base_revision"]:
        raise RelocateError("relocate_destination_unrecognized")
    journal["cleanup"] = forward._cleanup(source, core)
    forward._write_journal(root, journal, "cleaned")


def commit_back(store: Any, plan: Mapping[str, Any]) -> dict[str, Any]:
    from .store import MemoryStore

    core = plan["core"]
    root = Path(store.project_root)
    anchor = Path(core["destination_store_root"])
    units = _units(core["entries"])
    with identity_lock(store):
        with store.write_lock():
            replayed = forward._replay(root, plan)
            if replayed is not None:
                return replayed
            if not store.store_external or str(store.store_root) != core["source_store_root"]:
                raise RelocateError("relocate_plan_root_mismatch")
            binding = mutation_preflight(store)
            if read_pointer(root) is None:
                raise RelocateError("relocate_pointer_required")
            if (
                custody_fingerprint(binding) != core["custody_fingerprint"]
                or binding["store_identity"] != core["store_identity"]
            ):
                raise RelocateError("relocate_identity_changed")
            if store.read_current() != core["base_revision"]:
                raise RelocateError("relocate_base_changed")
            if _occupied(anchor, units):
                raise RelocateError("relocate_destination_occupied")
            extra = forward._check_source_set(store.store_root, core)
            staging = _staging(root, core["transaction_id"])
            if os.path.lexists(staging):
                raise RelocateError("relocate_staging_exists")
            journal: dict[str, Any] = {
                "schema": forward.JOURNAL_SCHEMA,
                "transaction_id": core["transaction_id"],
                "plan": plan,
                "stage": "staging",
                "relocation_receipt": None,
                "lock_free_residue": extra,
                "cleanup": None,
            }
            forward._write_journal(root, journal, "staging")
            forward._point("journal_staging")
            try:
                forward._copy_to_staging(store.store_root, staging, core["entries"])
                staged = MemoryStore(root, store_root=staging)
                journal["relocation_receipt"] = write_relocation_receipt(
                    staged,
                    kind="store_root",
                    store_identity=binding["store_identity"],
                    current_observed=core["base_revision"],
                    from_root=core["source_store_root"],
                    to_root=core["destination_store_root"],
                )
                checked = staged.verify()
                if checked["revision"] != core["base_revision"]:
                    raise RelocateError("relocate_staging_verify_failed")
                # Journal the receipt before any subtree is published so a
                # crash mid-publication is reconcilable.
                forward._write_journal(root, journal, "staging")
                forward._point("before_publish")
            except Exception:
                forward._discard_staging(staging)
                forward._write_journal(root, journal, "aborted")
                raise
            _publish_units(staging, anchor, units)
            forward._point("after_rename")
            shutil.rmtree(staging)
            forward._write_journal(root, journal, "published")
            forward._point("after_publish")
            _finish(core, journal, store)
    return forward._result(journal)


def reconcile_back(journal: dict[str, Any], *, abort: bool) -> dict[str, Any]:
    from .store import MemoryStore

    core = journal["plan"]["core"]
    root = Path(core["project_root"])
    anchor = Path(core["destination_store_root"])
    staging = _staging(root, core["transaction_id"])
    units = _units(core["entries"])
    source = MemoryStore(root, store_root=core["source_store_root"])
    with identity_lock(source):
        with source.write_lock():
            if journal["stage"] == "staging":
                receipt = journal["relocation_receipt"]
                published = [
                    unit for unit in units
                    if os.path.lexists(anchor / unit) and not os.path.lexists(staging / unit)
                ]
                if receipt is None or abort or not published:
                    # Remove only subtrees that are exact planned copies.
                    _remove_units(core, published, receipt)
                    forward._discard_staging(staging)
                    forward._write_journal(root, journal, "aborted")
                    return forward._result(journal)
                _publish_units(staging, anchor, units)
                forward._discard_staging(staging)
                forward._write_journal(root, journal, "published")
            if journal["stage"] == "published":
                if abort:
                    if not _published_matches(core, journal["relocation_receipt"]):
                        raise RelocateError("relocate_destination_unrecognized")
                    _remove_units(core, units, journal["relocation_receipt"])
                    forward._write_journal(root, journal, "aborted")
                    return forward._result(journal)
                if forward._raw_current(Path(core["source_store_root"])) != core["base_revision"]:
                    raise RelocateError("relocate_source_advanced")
            elif abort:
                raise RelocateError("relocate_abort_too_late")
            _finish(core, journal, source)
    return forward._result(journal)


__all__ = ["DIRECTION", "commit_back", "plan_back", "reconcile_back"]
