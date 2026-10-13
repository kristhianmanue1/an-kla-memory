"""Custody root resolution and pointer checks for G3 (ADR-0048 §1).

The custody root (``store_root``) holds the vault: ``memory/``, the identity
anchor, ``attest.*`` and ``hook-runs/``.  By default it is
``project_root/.an-kla``.  An external custody root leaves a project-local
pointer whose fingerprint binds identity bytes; the path inside the pointer
is a locator, never authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .canonical import canonical_json, digest_json
from .storage_primitives import fsync_directory, write_immutable
from .store_errors import StoreError


ENV_VAR = "AN_KLA_STORE_ROOT"
POINTER_SCHEMA = "an-kla/store-root-pointer-v1"
BINDING_SCHEMA = "an-kla/custody-binding-v1"
POINTER_NAME = "store-root.txt"


class CustodyError(StoreError):
    """Stable custody failure; ``str(exc)`` is the error code."""


def default_store_root(project_root: str | Path) -> Path:
    return Path(project_root).resolve() / ".an-kla"


def pointer_path(project_root: str | Path) -> Path:
    return default_store_root(project_root) / POINTER_NAME


def custody_fingerprint(binding: Mapping[str, Any]) -> str:
    """Digest of the bound identity bytes; contains no path."""

    return digest_json(
        {
            "schema": BINDING_SCHEMA,
            "project_uuid": binding["store"]["project_uuid"],
            "store_identity": binding["store_identity"],
        }
    )


def read_pointer(project_root: str | Path) -> dict[str, Any] | None:
    """Return the validated pointer, ``None`` when absent."""

    path = pointer_path(project_root)
    anchor = path.parent
    if anchor.is_symlink() or path.is_symlink():
        raise CustodyError("store_root_pointer_invalid")
    try:
        payload = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CustodyError("store_root_pointer_invalid") from exc
    try:
        value = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CustodyError("store_root_pointer_invalid") from exc
    if (
        not isinstance(value, dict)
        or canonical_json(value) != payload
        or set(value) != {"schema", "store_root", "custody_fingerprint"}
        or value["schema"] != POINTER_SCHEMA
        or not isinstance(value["store_root"], str)
        or not Path(value["store_root"]).is_absolute()
        or not isinstance(value["custody_fingerprint"], str)
        or not value["custody_fingerprint"].startswith("sha256:")
    ):
        raise CustodyError("store_root_pointer_invalid")
    return value


@dataclass(frozen=True)
class Resolution:
    store_root: Path
    source: str
    warnings: tuple[str, ...] = field(default_factory=tuple)


def resolve_store_root(
    project_root: str | Path,
    flag: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Resolution:
    """Apply flag > env > pointer > project-local (ADR-0048 §1, H11)."""

    env_value = (os.environ if environ is None else environ).get(ENV_VAR) or None
    warnings: list[str] = []
    if flag is not None:
        flag_root = Path(flag).resolve()
        if env_value is not None and Path(env_value).resolve() != flag_root:
            warnings.append("store_root_flag_env_divergence")
        return Resolution(flag_root, "flag", tuple(warnings))
    if env_value is not None:
        return Resolution(Path(env_value).resolve(), "env", ())
    pointer = read_pointer(project_root)
    if pointer is not None:
        return Resolution(Path(pointer["store_root"]), "pointer", ())
    return Resolution(default_store_root(project_root), "project_local", ())


def check_custody(store: Any, *, binding: Mapping[str, Any] | None) -> None:
    """Fail closed when a pointer disagrees with the opened custody.

    ``binding`` is the identity binding read at ``store.store_root`` or
    ``None`` when no identity exists there yet (fresh ``init``).
    """

    pointer = read_pointer(store.project_root)
    if pointer is None:
        if store.store_external and project_local_vault_present(store.project_root):
            # The project-local vault is the authority (never relocated, or
            # relocated back): an external root opened by flag/env without
            # a pointer is a stale or twin copy and must not accept writes.
            raise CustodyError("store_root_divergence")
        return
    if not store.store_external or binding is None:
        # A pointer exists only for external custody: opening the
        # project-local root, or creating a fresh vault, would fork it.
        raise CustodyError("store_root_divergence")
    if custody_fingerprint(binding) != pointer["custody_fingerprint"]:
        raise CustodyError("store_root_divergence")


def project_local_vault_present(project_root: str | Path) -> bool:
    anchor = default_store_root(project_root)
    return any(
        os.path.lexists(anchor / name)
        for name in ("project-identity.json", "memory/refs/CURRENT")
    )


def write_pointer(store: Any, binding: Mapping[str, Any]) -> dict[str, Any]:
    """Create the pointer for an external custody, or match the existing one."""

    if not store.store_external:
        raise CustodyError("store_root_pointer_not_external")
    value = {
        "schema": POINTER_SCHEMA,
        "store_root": str(store.store_root),
        "custody_fingerprint": custody_fingerprint(binding),
    }
    existing = read_pointer(store.project_root)
    if existing is not None:
        if existing["custody_fingerprint"] != value["custody_fingerprint"]:
            raise CustodyError("store_root_divergence")
        return existing
    path = pointer_path(store.project_root)
    path.parent.mkdir(parents=True, exist_ok=True)

    def conflict(_target: Path) -> None:
        raise CustodyError("store_root_divergence")

    write_immutable(
        path, canonical_json(value), conflict=conflict, fsync_directory=fsync_directory
    )
    return value


__all__ = [
    "BINDING_SCHEMA",
    "CustodyError",
    "ENV_VAR",
    "POINTER_SCHEMA",
    "Resolution",
    "check_custody",
    "custody_fingerprint",
    "default_store_root",
    "pointer_path",
    "project_local_vault_present",
    "read_pointer",
    "resolve_store_root",
    "write_pointer",
]
