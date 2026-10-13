"""Open the store an entry point should use (ADR-0048 §1, R1c).

CLI, MCP and upgrade share this helper so every entry resolves custody the
same way: flag > ``AN_KLA_STORE_ROOT`` > pointer > project-local.
"""

from __future__ import annotations

from typing import Any, TextIO

from .custody import CustodyError, read_pointer, resolve_store_root
from .custody_status import custody_descriptor
from .store import MemoryStore

_WARN_DIVERGENCE = {
    "pointer_fingerprint_mismatch",
    "pointer_invalid",
    "project_local_with_pointer",
}


def open_resolved_store(
    project_root: Any,
    flag: Any = None,
    warnings: TextIO | None = None,
    environ: Any = None,
) -> MemoryStore:
    """Return the resolved store; never raises for custody problems.

    An invalid pointer yields the project-local store, whose reads and
    mutations then fail closed (``store_root_divergence`` /
    ``store_root_pointer_invalid``) while project-local carve-outs such as
    the managed context keep working.
    """

    try:
        resolution = resolve_store_root(project_root, flag, environ)
    except CustodyError:
        if warnings is not None:
            warnings.write("an-kla warning: store_root_pointer_invalid\n")
        return MemoryStore(project_root)
    if warnings is not None:
        for code in resolution.warnings:
            warnings.write(f"an-kla warning: {code}\n")
    store_root = None if resolution.source == "project_local" else resolution.store_root
    store = MemoryStore(project_root, store_root=store_root)
    if warnings is not None and resolution.source in {"flag", "env"}:
        try:
            pointer_present = read_pointer(project_root) is not None
        except CustodyError:
            pointer_present = True
        if pointer_present:
            divergence = custody_descriptor(store)["divergence"]
            if divergence in _WARN_DIVERGENCE:
                warnings.write(f"an-kla warning: {divergence}\n")
        elif resolution.source == "env" and _bound_elsewhere(store):
            # A shell-wide env var can point a different project at this
            # vault; bytes, not paths, bind it, so only warn (ADR-0048 §1).
            warnings.write("an-kla warning: store_root_env_unbound_project\n")
    return store


def _bound_elsewhere(store: MemoryStore) -> bool:
    from .custody_status import custody_divergence_axis

    return custody_divergence_axis(store)["project_root_relocated_since_init"] is True


__all__ = ["open_resolved_store"]
