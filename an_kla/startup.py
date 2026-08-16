"""Read-only startup diagnostic over independent axes (ADR-0036).

Every axis is total: it has a defined value for any filesystem state, including
the impossibility of observing it.  The result never asserts currency — an
intact store can still describe a stale project state (issue #79).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from .identity import IdentityError, identity_status
from .reader_gate import ReaderGateError
from .store import StoreError


SCHEMA = "an-kla/startup-diagnostic-v1"
GIT_TIMEOUT_SECONDS = 5


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
    except FileNotFoundError:
        # Removed between the presence check and this one.  Reporting `failed`
        # would call a store that no longer exists "broken".
        return "not_evaluated", "store_disappeared"
    except ReaderGateError as exc:
        # A read-only tree cannot take the gate.  That is not a broken store.
        return "not_evaluated", str(exc)
    except (StoreError, IdentityError, OSError, ValueError) as exc:
        return "failed", _code(exc)
    return "verified", None


def _identity(store: Any, presence: str) -> dict[str, Any]:
    """Re-express `identity-status-v1` verbatim, or declare it unevaluated.

    ``evaluated: false`` is what carries "could not observe".  The nine
    published values keep their meaning exactly; none is reused to stand in for
    a failure, because inventing an identity is worse than admitting none.
    """
    empty = {
        "evaluated": False,
        "identity_status": None,
        "root_relocated": None,
        "error_code": None,
    }
    if presence == "unreadable":
        return {**empty, "error_code": "store_unreadable"}
    try:
        observed = identity_status(store)
    except (StoreError, IdentityError, OSError, ValueError) as exc:
        return {**empty, "error_code": _code(exc)}
    return {
        "evaluated": True,
        "identity_status": observed.get("identity_status"),
        "root_relocated": observed.get("root_relocated"),
        "error_code": observed.get("error_code"),
    }


def _repo_context(project_root: Path) -> str:
    """Classify the checkout by asking Git, as ADR-0036 specifies.

    An earlier version inspected whether ``.git`` was a file or a directory to
    avoid a subprocess.  It misclassified a submodule as a linked worktree (its
    ``.git`` is a gitlink file) and any subdirectory of a repository as
    ``not_a_repo``.  Git resolves both correctly, so the ADR's mechanism stands.

    ``GIT_*`` variables are stripped so the answer describes the path given and
    not the ambient environment.
    """
    environment = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--git-dir", "--git-common-dir"],
            cwd=str(project_root), env=environment, capture_output=True,
            timeout=GIT_TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        # Git absent from PATH, not executable, or timed out.
        return "git_unavailable"
    if completed.returncode != 0:
        return "not_a_repo"
    lines = completed.stdout.decode("utf-8", "replace").splitlines()
    if len(lines) != 2:
        return "git_unavailable"
    try:
        resolved = [Path(project_root, line).resolve() for line in lines]
    except OSError:
        return "git_unavailable"
    return "main_checkout" if resolved[0] == resolved[1] else "linked_worktree"


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
