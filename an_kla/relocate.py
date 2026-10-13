"""Governed relocation of the custody root (ADR-0048 §3, G3 R2a).

``plan`` binds the exact move set, observed revision and custody
fingerprint; ``commit`` copies that set to a sibling staging directory,
verifies it, publishes it with ``rename_noreplace``, writes the pointer and
only then deletes the planned files from the origin.  Every stage is
journaled under ``<project>/.an-kla/relocations/<txid>.json`` so a crash
leaves an identifiable state that ``reconcile`` finishes or aborts.  Never
automatic: ``commit`` needs the plan and the expected revision.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import stat
from typing import Any, Callable, Mapping
import uuid

from .canonical import canonical_json, digest_bytes, digest_json
from .custody import (
    CustodyError, custody_fingerprint, default_store_root, read_pointer, write_pointer,
)
from .export_io import ExportIOError, normalize_and_sync_tree, rename_noreplace, safe_read
from .export_restore import _allowed, _files
from .identity import identity_lock, mutation_preflight, read_binding
from .reader_gate import ReaderGateError, exclusive_reader_gate
from .relocation_receipts import write_relocation_receipt
from .storage_primitives import atomic_write, fsync_directory
from .store_errors import StoreError


PLAN_SCHEMA = "an-kla/relocate-plan-v1"
JOURNAL_SCHEMA = "an-kla/relocate-journal-v1"
DIRECTION = "project_local_to_external"
BACK_DIRECTION = "external_to_project_local"  # R2b, see relocate_back.py
# ``pointer_written`` is the forward commit point, ``pointer_removed`` the back one.
STAGES = ("staging", "published", "pointer_written", "pointer_removed", "cleaned", "aborted")
# attest receipts/nonces and hook-runs are minted with O_EXCL and no store
# lock (ADR-0048 §3, H7): files born there after the plan stay in the origin
# and are reported, never deleted and never silently moved.
_LOCK_FREE = ("anchor/receipts/", "anchor/hook-runs/")
# Project-side or derivable paths that remain in the origin anchor.
_KEPT = frozenset({
    ".identity.lock", "store-root.txt", "host-hooks.json",
    "memory/.write.lock", "memory/.reader-gate",
})
_KEPT_PREFIXES = ("context/", "relocations/")
_TXID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
_CORE_KEYS = frozenset({
    "direction", "transaction_id", "project_root", "source_store_root",
    "destination_store_root", "base_revision", "custody_fingerprint",
    "store_identity", "entries",
})

# Test-only crash injection: called with the name of each stage boundary.
# It raises ``SimulatedCrash`` (a ``BaseException``) so no cleanup handler
# runs, as with a killed process.
_fault: Callable[[str], None] | None = None
# Wait for local readers before deleting the origin (reader-gate budget).
_GATE_TIMEOUT = 10.0


class RelocateError(StoreError):
    """Stable relocation failure; ``str(exc)`` is the error code."""


class SimulatedCrash(BaseException):
    """Test-only stand-in for process death at a stage boundary."""


def _point(name: str) -> None:
    if _fault is not None:
        _fault(name)


def _journal_path(project_root: Path, txid: str) -> Path:
    return default_store_root(project_root) / "relocations" / f"{txid}.json"


def _read_journal(project_root: Path, txid: str) -> dict[str, Any] | None:
    if not _TXID.fullmatch(txid):
        raise RelocateError("relocate_transaction_invalid")
    path = _journal_path(project_root, txid)
    if path.parent.is_symlink() or path.is_symlink():
        raise RelocateError("relocate_journal_invalid")
    try:
        payload = path.read_bytes()
    except FileNotFoundError:
        return None
    try:
        value = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RelocateError("relocate_journal_invalid") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema") != JOURNAL_SCHEMA
        or value.get("stage") not in STAGES
        or value.get("transaction_id") != txid
    ):
        raise RelocateError("relocate_journal_invalid")
    validate_plan(value.get("plan"))
    return value


def _write_journal(project_root: Path, journal: dict[str, Any], stage: str) -> None:
    journal["stage"] = stage
    atomic_write(
        _journal_path(project_root, journal["transaction_id"]),
        canonical_json(journal),
        fsync_directory=fsync_directory,
    )


def _move_set(anchor: Path) -> list[tuple[str, Path]]:
    """Export allow-list plus ``attest.key`` (ADR-0048 §3, H5)."""

    try:
        rows = _files(anchor)
    except ExportIOError as exc:
        raise RelocateError(str(exc)) from exc
    key = anchor / "attest.key"
    if os.path.lexists(key):
        info = key.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RelocateError("export_unsafe_file")
        rows.append(("anchor/attest.key", key))
    return sorted(rows, key=lambda item: item[0].encode("utf-8"))


def _read(anchor: Path, relative: str) -> bytes:
    try:
        return safe_read(anchor, relative.removeprefix("anchor/"))
    except ExportIOError as exc:
        raise RelocateError(str(exc)) from exc


def _validate_destination(store: Any, destination: str | Path) -> Path:
    from .store import MemoryStore

    target = Path(destination)
    if not target.is_absolute():
        raise RelocateError("relocate_destination_invalid")
    target = target.resolve()
    try:
        MemoryStore(store.project_root, store_root=target)
    except StoreError as exc:
        raise RelocateError("relocate_destination_invalid") from exc
    if os.path.lexists(target):
        raise RelocateError("relocate_destination_exists")
    return target


def _require_source(store: Any) -> None:
    if getattr(store, "store_external", False):
        raise RelocateError("relocate_source_external_unsupported")
    try:
        pointer = read_pointer(store.project_root)
    except CustodyError as exc:
        raise RelocateError(str(exc)) from exc
    if pointer is not None:
        raise RelocateError("store_root_divergence")


def plan_relocation(store: Any, destination: str | Path) -> dict[str, Any]:
    """Bind the exact move set to the observed revision and identity."""

    _require_source(store)
    target = _validate_destination(store, destination)
    anchor = store.store_root
    with identity_lock(store):
        with store.write_lock():
            binding = mutation_preflight(store)
            verified = store.verify()
            if verified["identity_status"] != "complete":
                raise RelocateError("relocate_source_identity_incomplete")
            current = store.read_current()
            entries = []
            for relative, _path in _move_set(anchor):
                payload = _read(anchor, relative)
                entries.append(
                    {"path": relative, "size": len(payload), "content_sha256": digest_bytes(payload)}
                )
    core = {
        "direction": DIRECTION,
        "transaction_id": str(uuid.uuid4()),
        "project_root": str(store.project_root),
        "source_store_root": str(anchor),
        "destination_store_root": str(target),
        "base_revision": current,
        "custody_fingerprint": custody_fingerprint(binding),
        "store_identity": binding["store_identity"],
        "entries": entries,
    }
    return {"schema": PLAN_SCHEMA, "core": core, "plan_sha256": digest_json(core)}


def validate_plan(plan: Any) -> dict[str, Any]:
    if (
        not isinstance(plan, dict)
        or set(plan) != {"schema", "core", "plan_sha256"}
        or plan["schema"] != PLAN_SCHEMA
        or not isinstance(plan["core"], dict)
        or set(plan["core"]) != _CORE_KEYS
        or plan["core"]["direction"] not in {DIRECTION, BACK_DIRECTION}
        or not isinstance(plan["core"]["transaction_id"], str)
        or not _TXID.fullmatch(plan["core"]["transaction_id"])
        or not isinstance(plan["core"]["entries"], list)
    ):
        raise RelocateError("relocate_plan_invalid")
    try:
        digest = digest_json(plan["core"])
    except (TypeError, ValueError) as exc:
        raise RelocateError("relocate_plan_invalid") from exc
    if digest != plan["plan_sha256"]:
        raise RelocateError("relocate_plan_digest_mismatch")
    if plan["core"]["direction"] == BACK_DIRECTION and plan["core"]["destination_store_root"] != str(
        default_store_root(plan["core"]["project_root"])
    ):
        raise RelocateError("relocate_plan_invalid")
    seen = set()
    for entry in plan["core"]["entries"]:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"path", "size", "content_sha256"}
            or not isinstance(entry["path"], str)
            or entry["path"] in seen
            or not (_allowed(entry["path"]) or entry["path"] == "anchor/attest.key")
        ):
            raise RelocateError("relocate_plan_invalid")
        seen.add(entry["path"])
    return plan["core"]


def _staging(target: Path, txid: str) -> Path:
    return target.parent / f".staging-{txid}"


def _copy_to_staging(anchor: Path, staging: Path, entries: list[Mapping[str, Any]]) -> None:
    staging.mkdir(mode=0o700)
    written: list[Path] = []
    for entry in entries:
        payload = _read(anchor, entry["path"])
        if digest_bytes(payload) != entry["content_sha256"] or len(payload) != entry["size"]:
            raise RelocateError("relocate_source_changed")
        path = staging / entry["path"].removeprefix("anchor/")
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
        written.append(path)
    normalize_and_sync_tree(staging, written)


def _check_source_set(anchor: Path, core: Mapping[str, Any]) -> list[str]:
    planned = {entry["path"] for entry in core["entries"]}
    actual = {relative for relative, _path in _move_set(anchor)}
    if planned - actual:
        raise RelocateError("relocate_source_changed")
    extra = sorted(actual - planned)
    if any(not path.startswith(_LOCK_FREE) for path in extra):
        raise RelocateError("relocate_source_changed")
    return extra


def project_anchor_residue(anchor: Path) -> list[str]:
    """Files in a project anchor other than project-side and lock paths."""

    if not anchor.is_dir() or anchor.is_symlink():
        return []
    rows = []
    for path in sorted(anchor.rglob("*")):
        if path.is_dir() and not path.is_symlink():
            continue
        relative = path.relative_to(anchor).as_posix()
        if relative in _KEPT or relative.startswith(_KEPT_PREFIXES):
            continue
        rows.append(relative)
    return rows


def _prune_empty(anchor: Path) -> None:
    directories = [path for path in anchor.rglob("*") if path.is_dir() and not path.is_symlink()]
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            continue
    fsync_directory(anchor)


def _cleanup(source: Any, core: Mapping[str, Any]) -> dict[str, Any]:
    """Delete only the planned files whose bytes still match (H7)."""

    anchor = Path(core["source_store_root"])
    try:
        return _cleanup_under_gate(source, core, anchor)
    except ReaderGateError as exc:
        # The pointer already exists: reconcile finishes the cleanup.
        raise RelocateError("relocate_cleanup_readers_active") from exc


def _cleanup_under_gate(source: Any, core: Mapping[str, Any], anchor: Path) -> dict[str, Any]:
    kept_changed = []
    parents: set[Path] = set()
    with exclusive_reader_gate(source, timeout=_GATE_TIMEOUT):
        for entry in core["entries"]:
            relative = entry["path"].removeprefix("anchor/")
            path = anchor / relative
            if not os.path.lexists(path):
                continue
            try:
                payload = safe_read(anchor, relative)
            except ExportIOError:
                kept_changed.append(relative)
                continue
            if digest_bytes(payload) != entry["content_sha256"]:
                kept_changed.append(relative)
                continue
            path.unlink()
            parents.add(path.parent)
        for parent in parents:
            fsync_directory(parent)
        # Derivable search indexes hold record text: they do not stay in
        # the checkout and are rebuilt at the destination on demand.
        indexes = anchor / "memory" / "indexes"
        if indexes.is_dir() and not indexes.is_symlink():
            shutil.rmtree(indexes)
        _prune_empty(anchor)
    return {"changed_kept": kept_changed, "residue": project_anchor_residue(anchor)}


def _result(journal: Mapping[str, Any], *, replayed: bool = False) -> dict[str, Any]:
    core = journal["plan"]["core"]
    return {
        "schema": "an-kla/relocate-result-v1",
        "transaction_id": core["transaction_id"],
        "plan_sha256": journal["plan"]["plan_sha256"],
        "stage": journal["stage"],
        "revision": core["base_revision"],
        "custody_fingerprint": core["custody_fingerprint"],
        "relocation_receipt": journal.get("relocation_receipt"),
        "lock_free_residue": journal.get("lock_free_residue", []),
        "cleanup": journal.get("cleanup"),
        "replayed": replayed,
    }


def _source_store(core: Mapping[str, Any]) -> Any:
    from .store import MemoryStore

    return MemoryStore(core["project_root"])


def _raw_current(anchor: Path) -> str | None:
    try:
        return (anchor / "memory" / "refs" / "CURRENT").read_bytes()[:-1].decode("ascii")
    except (OSError, UnicodeDecodeError):
        return None


def _publish_pointer(core: Mapping[str, Any], binding: Mapping[str, Any]) -> None:
    from .store import MemoryStore

    destination = MemoryStore(core["project_root"], store_root=core["destination_store_root"])
    try:
        write_pointer(destination, binding)
    except CustodyError as exc:
        raise RelocateError(str(exc)) from exc


def _replay(project_root: Path, plan: Mapping[str, Any]) -> dict[str, Any] | None:
    existing = _read_journal(project_root, plan["core"]["transaction_id"])
    if existing is None:
        return None
    if existing["plan"] != plan:
        raise RelocateError("transaction_binding_conflict")
    if existing["stage"] == "cleaned":
        return _result(existing, replayed=True)
    if existing["stage"] == "aborted":
        raise RelocateError("relocate_transaction_aborted")
    raise RelocateError("relocate_reconcile_required")


def _discard_staging(staging: Path) -> None:
    if staging.is_dir() and not staging.is_symlink():
        shutil.rmtree(staging)
        fsync_directory(staging.parent)


def _stage_and_verify(
    project_root: Path, anchor: Path, staging: Path, core: Mapping[str, Any],
    binding: Mapping[str, Any],
) -> str:
    from .store import MemoryStore

    _copy_to_staging(anchor, staging, core["entries"])
    staged = MemoryStore(project_root, store_root=staging)
    receipt = write_relocation_receipt(
        staged,
        kind="store_root",
        store_identity=binding["store_identity"],
        current_observed=core["base_revision"],
        from_root=core["source_store_root"],
        to_root=core["destination_store_root"],
    )
    checked = staged.verify()
    if checked["revision"] != core["base_revision"] or checked["identity_status"] != "complete":
        raise RelocateError("relocate_staging_verify_failed")
    return receipt


def _publish(staging: Path, target: Path) -> None:
    """Rename only: a failure here means nothing was published."""

    try:
        rename_noreplace(staging, target)
    except ExportIOError as exc:
        code = (
            "relocate_destination_exists"
            if str(exc) == "restore_destination_conflict"
            else "relocate_publish_failed"
        )
        raise RelocateError(code) from exc


def commit_relocation(store: Any, plan: Any, expected_current: str) -> dict[str, Any]:
    """Execute an exact plan; a repeated call replays a finished commit."""

    core = validate_plan(plan)
    if expected_current != core["base_revision"]:
        raise RelocateError("relocate_expected_current_mismatch")
    project_root = Path(store.project_root)
    if str(project_root) != core["project_root"]:
        raise RelocateError("relocate_plan_root_mismatch")
    replayed = _replay(project_root, plan)
    if replayed is not None:
        return replayed
    if core["direction"] == BACK_DIRECTION:
        from .relocate_back import commit_back

        return commit_back(store, plan)
    if str(store.store_root) != core["source_store_root"]:
        raise RelocateError("relocate_plan_root_mismatch")
    target = Path(core["destination_store_root"])
    anchor = store.store_root
    with identity_lock(store):
        with store.write_lock():
            # A concurrent commit of the same plan may have finished while
            # this one waited for the locks: replay it, never redo it.
            replayed = _replay(project_root, plan)
            if replayed is not None:
                return replayed
            _require_source(store)
            binding = mutation_preflight(store)
            if (
                custody_fingerprint(binding) != core["custody_fingerprint"]
                or binding["store_identity"] != core["store_identity"]
            ):
                raise RelocateError("relocate_identity_changed")
            if store.read_current() != core["base_revision"]:
                raise RelocateError("relocate_base_changed")
            if os.path.lexists(target):
                raise RelocateError("relocate_destination_exists")
            extra = _check_source_set(anchor, core)
            staging = _staging(target, core["transaction_id"])
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if os.path.lexists(staging):
                raise RelocateError("relocate_staging_exists")
            journal: dict[str, Any] = {
                "schema": JOURNAL_SCHEMA,
                "transaction_id": core["transaction_id"],
                "plan": plan,
                "stage": "staging",
                "relocation_receipt": None,
                "lock_free_residue": extra,
                "cleanup": None,
            }
            _write_journal(project_root, journal, "staging")
            _point("journal_staging")
            try:
                journal["relocation_receipt"] = _stage_and_verify(
                    project_root, anchor, staging, core, binding
                )
                _point("before_publish")
                _publish(staging, target)
            except Exception:
                # Pre-publish failure: the origin is untouched.
                _discard_staging(staging)
                _write_journal(project_root, journal, "aborted")
                raise
            # Past the rename a failure is reconciled, never "aborted".
            fsync_directory(target.parent)
            _point("after_rename")
            _write_journal(project_root, journal, "published")
            _point("after_publish")
            _publish_pointer(core, binding)
            _write_journal(project_root, journal, "pointer_written")
            _point("after_pointer")
            journal["cleanup"] = _cleanup(store, core)
            _write_journal(project_root, journal, "cleaned")
    return _result(journal)


def _is_own_receipt(payload: bytes, core: Mapping[str, Any]) -> bool:
    try:
        value = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    return isinstance(value, dict) and all(
        value.get(key) == expected
        for key, expected in (
            ("kind", "store_root"),
            ("store_identity", core["store_identity"]),
            ("current_observed", core["base_revision"]),
            ("from_root_observed", core["source_store_root"]),
            ("to_root_observed", core["destination_store_root"]),
        )
    )


def _destination_receipt(core: Mapping[str, Any]) -> str | None:
    """The relocation receipt this plan published, or None when the vault
    at the destination is not exactly the planned copy plus that receipt."""

    target = Path(core["destination_store_root"])
    expected = {entry["path"]: entry["content_sha256"] for entry in core["entries"]}
    try:
        rows = _move_set(target)
    except RelocateError:
        return None
    own: list[str] = []
    found = set()
    for relative, _path in rows:
        payload = _read(target, relative)
        if relative in expected:
            if digest_bytes(payload) != expected[relative]:
                return None
            found.add(relative)
        elif relative.startswith("anchor/relocation-receipts/") and _is_own_receipt(payload, core):
            own.append(digest_bytes(payload))
        else:
            return None
    if found != set(expected) or len(own) != 1:
        return None
    return own[0]


# Created at the destination by ``verify``/locking, never by a writer.
_INERT = frozenset({".identity.lock", "memory/.write.lock", "memory/.reader-gate"})


def _only_planned_files(target: Path, core: Mapping[str, Any], receipt: str) -> bool:
    """Every file under ``target`` is a planned copy, our receipt or inert.

    ``_destination_receipt`` checks the export allow-list only; abort
    deletes the whole tree, so anything else (indexes, leases, quarantine)
    written by another process must stop it.
    """

    planned = {entry["path"].removeprefix("anchor/") for entry in core["entries"]}
    planned.add("relocation-receipts/sha256/" + receipt.removeprefix("sha256:") + ".json")
    for path in target.rglob("*"):
        if path.is_dir() and not path.is_symlink():
            continue
        relative = path.relative_to(target).as_posix()
        if path.is_symlink() or relative not in planned | _INERT:
            return False
    return True


def unfinished_relocations(project_root: str | Path) -> int:
    """Journals not yet ``cleaned`` or ``aborted`` (doctor, R3 m2)."""

    directory = default_store_root(project_root) / "relocations"
    if not directory.is_dir() or directory.is_symlink():
        return 0
    count = 0
    for path in directory.glob("*.json"):
        try:
            stage = json.loads(path.read_bytes()).get("stage")
        except (OSError, ValueError, AttributeError):
            stage = None
        if stage not in {"cleaned", "aborted"}:
            count += 1
    return count


def inspect_relocation(project_root: str | Path, transaction_id: str) -> dict[str, Any]:
    """Read-only: journal stage plus the observed filesystem facts."""

    root = Path(project_root).resolve()
    journal = _read_journal(root, transaction_id)
    if journal is None:
        raise RelocateError("relocate_transaction_unknown")
    core = journal["plan"]["core"]
    target = Path(core["destination_store_root"])
    staging = _staging(target, transaction_id)
    if core["direction"] == BACK_DIRECTION:
        from .relocate_back import _staging as back_staging

        staging = back_staging(root, transaction_id)
    try:
        pointer = read_pointer(root)
        pointer_state = "absent" if pointer is None else (
            "matches" if pointer["custody_fingerprint"] == core["custody_fingerprint"] else "divergent"
        )
    except CustodyError:
        pointer_state = "invalid"
    return {
        **_result(journal),
        "observed": {
            "staging_present": os.path.lexists(staging),
            "destination_present": os.path.lexists(target),
            "pointer": pointer_state,
            "source_current_matches_plan": _raw_current(Path(core["source_store_root"])) == core["base_revision"],
        },
    }


def reconcile_relocation(
    project_root: str | Path, transaction_id: str, *, abort: bool = False
) -> dict[str, Any]:
    """Finish (or, before the pointer exists, abort) an interrupted commit."""

    from .store import MemoryStore

    root = Path(project_root).resolve()
    journal = _read_journal(root, transaction_id)
    if journal is None:
        raise RelocateError("relocate_transaction_unknown")
    core = journal["plan"]["core"]
    if journal["stage"] in {"cleaned", "aborted"}:
        return _result(journal, replayed=True)
    if core["project_root"] != str(root):
        raise RelocateError("relocate_plan_root_mismatch")
    if core["direction"] == BACK_DIRECTION:
        from .relocate_back import reconcile_back

        return reconcile_back(journal, abort=abort)
    target = Path(core["destination_store_root"])
    staging = _staging(target, transaction_id)
    source = _source_store(core)
    with identity_lock(source):
        with source.write_lock():
            if journal["stage"] == "staging":
                receipt = _destination_receipt(core) if os.path.lexists(target) else None
                if receipt is None:
                    # Crashed before the rename: the origin is untouched and
                    # an occupied destination is someone else's.
                    _discard_staging(staging)
                    _write_journal(root, journal, "aborted")
                    return _result(journal)
                # The rename happened; the journal update did not.
                journal["relocation_receipt"] = receipt
                _write_journal(root, journal, "published")
            if journal["stage"] == "published":
                receipt = _destination_receipt(core)
                if receipt is None or receipt != journal["relocation_receipt"]:
                    raise RelocateError("relocate_destination_unrecognized")
                if abort:
                    if not _only_planned_files(target, core, receipt):
                        raise RelocateError("relocate_destination_unrecognized")
                    shutil.rmtree(target)
                    fsync_directory(target.parent)
                    _write_journal(root, journal, "aborted")
                    return _result(journal)
                if _raw_current(Path(core["source_store_root"])) != core["base_revision"]:
                    raise RelocateError("relocate_source_advanced")
                destination = MemoryStore(root, store_root=target)
                checked = destination.verify()
                binding = read_binding(destination)
                if (
                    checked["revision"] != core["base_revision"]
                    or custody_fingerprint(binding) != core["custody_fingerprint"]
                ):
                    raise RelocateError("relocate_destination_unrecognized")
                _publish_pointer(core, binding)
                _write_journal(root, journal, "pointer_written")
            if abort:
                raise RelocateError("relocate_abort_too_late")
            journal["cleanup"] = _cleanup(source, core)
            _write_journal(root, journal, "cleaned")
    return _result(journal)


__all__ = [
    "JOURNAL_SCHEMA", "PLAN_SCHEMA", "RelocateError", "commit_relocation",
    "inspect_relocation", "plan_relocation", "project_anchor_residue", "reconcile_relocation", "SimulatedCrash",
    "validate_plan",
]
