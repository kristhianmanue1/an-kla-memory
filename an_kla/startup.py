"""Read-only startup diagnostic over independent axes (ADR-0036).

Every axis is total: it has a defined value for any filesystem state, including
the impossibility of observing it.  The result never asserts currency — an
intact store can still describe a stale project state (issue #79).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .identity import IdentityError, identity_status
from .reader_gate import ReaderGateError
from .store import StoreError


SCHEMA = "an-kla/startup-diagnostic-v1"


def _code(exc: Exception) -> str:
    """Stable code without the absolute path (§11.1).

    ``StoreError``/``IdentityError`` carry closed codes such as
    ``compaction_catalog_invalid``.  ``OSError`` stringifies as
    ``[Errno 13] Permission denied: '/abs/path'``, so only its type travels.
    """
    if isinstance(exc, OSError):
        return type(exc).__name__
    return str(exc)


def _presence(store: Any) -> tuple[str, str | None]:
    """Presence never raises: ``Path.exists()`` does, under ``EACCES``."""
    try:
        if store.current_path.exists() or store.root.exists():
            return "present", None
        return "absent", None
    except OSError as exc:
        # The message would carry the absolute path; only the code travels.
        return "unreadable", type(exc).__name__


def _integrity(store: Any, presence: str) -> tuple[str, str | None]:
    if presence != "present":
        return "not_evaluated", "store_not_present"
    try:
        store.verify()
    except ReaderGateError as exc:
        # A read-only tree cannot take the gate.  That is not a broken store.
        return "not_evaluated", str(exc)
    except (StoreError, IdentityError, OSError, ValueError) as exc:
        return "failed", _code(exc)
    return "verified", None


def _identity(store: Any, presence: str) -> dict[str, Any]:
    empty = {"identity_status": None, "root_relocated": None, "error_code": None}
    if presence == "unreadable":
        return {**empty, "error_code": "store_unreadable"}
    try:
        observed = identity_status(store)
    except (StoreError, IdentityError, OSError, ValueError) as exc:
        return {**empty, "error_code": _code(exc)}
    return {
        "identity_status": observed.get("identity_status"),
        "root_relocated": observed.get("root_relocated"),
        "error_code": observed.get("error_code"),
    }


def _repo_context(project_root: Path) -> str:
    """Classify the checkout without executing Git.

    A linked worktree carries ``.git`` as a file holding ``gitdir:``; a main
    checkout carries it as a directory.  Reading that is enough, and keeps the
    diagnostic free of subprocesses, ``PATH`` lookups and Git configuration.
    """
    marker = project_root / ".git"
    try:
        if marker.is_dir():
            return "main_checkout"
        if marker.is_file():
            return "linked_worktree"
        return "not_a_repo"
    except OSError:
        return "git_unavailable"


def startup_diagnostic(store: Any) -> dict[str, Any]:
    """Classify the memory available under this project root.

    Read-only with respect to memory content.  The integrity axis takes the
    shared reader gate, which materialises ``.reader-gate``; no other write
    occurs, and a tree that rejects it yields ``not_evaluated``.
    """
    presence, presence_detail = _presence(store)
    integrity, integrity_detail = _integrity(store, presence)
    return {
        "schema": SCHEMA,
        "untrusted_memory_data": True,
        "store_presence": presence,
        "store_integrity": integrity,
        "integrity_detail": presence_detail or integrity_detail,
        "identity": _identity(store, presence),
        "repo_context": _repo_context(store.project_root),
        # No external axis in v1: absence means "not evaluated", never
        # "there is none".  Declaring a store_root belongs to issue #57.
        "external_memory_evaluated": False,
    }
