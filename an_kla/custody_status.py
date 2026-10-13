"""Read-only custody observation for diagnostics (ADR-0048 §4, R1b).

Shared by ``startup-diagnostic-v3``, ``integration-status-v3`` and the
``doctor.custody_divergence`` axis.  Never mutates, never emits a path:
the descriptor carries ``store_external``, the custody fingerprint and
closed codes only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .custody import CustodyError, custody_fingerprint, read_pointer


DIVERGENCE_CODES = (
    "none",
    "external_without_pointer",
    "pointer_stale_locator",
    "pointer_fingerprint_mismatch",
    "pointer_invalid",
    "project_local_with_pointer",
    "custody_identity_unreadable",
)


def _fingerprint(store: Any) -> str | None:
    from .identity import read_binding

    try:
        return custody_fingerprint(read_binding(store))
    except Exception:
        # Identity or integrity failures are reported by their own axes;
        # here they only mean "not observable".
        return None


def custody_descriptor(store: Any) -> dict[str, Any]:
    """Total over filesystem states: every field has a defined value."""

    try:
        pointer = read_pointer(store.project_root)
        pointer_state = "absent" if pointer is None else "present"
    except CustodyError:
        pointer, pointer_state = None, "invalid"
    external = bool(getattr(store, "store_external", False))
    fingerprint = _fingerprint(store)
    if pointer_state == "invalid":
        divergence = "pointer_invalid"
    elif pointer is None:
        divergence = "external_without_pointer" if external else "none"
    elif not external:
        divergence = "project_local_with_pointer"
    elif fingerprint is None:
        divergence = "custody_identity_unreadable"
    elif fingerprint != pointer["custody_fingerprint"]:
        divergence = "pointer_fingerprint_mismatch"
    elif Path(pointer["store_root"]).resolve() != Path(store.store_root):
        divergence = "pointer_stale_locator"
    else:
        divergence = "none"
    return {
        "store_external": external,
        "custody_fingerprint": fingerprint,
        "pointer": pointer_state,
        "divergence": divergence,
    }


def custody_is_default(descriptor: dict[str, Any]) -> bool:
    """True when nothing about custody differs from the beta.29 layout."""

    return (
        descriptor["store_external"] is False
        and descriptor["pointer"] == "absent"
    )


def custody_divergence_axis(store: Any) -> dict[str, Any]:
    """``doctor`` axis: pointer vs resolved custody vs canonical root at init."""

    from .identity import read_binding
    from .relocate import unfinished_relocations

    descriptor = custody_descriptor(store)
    try:
        identity = read_binding(store)["store"]
        relocated: bool | None = (
            identity["canonical_project_root_at_init"] != str(store.project_root)
        )
    except Exception:
        relocated = None
    residue: int | None = None
    if descriptor["store_external"]:
        # ADR-0048 §3 (H7): evidence left in the project anchor after a
        # relocate (lock-free receipts minted after the plan, quarantine)
        # is reported, never deleted or silently moved.
        from .custody import default_store_root
        from .relocate import project_anchor_residue

        residue = len(project_anchor_residue(default_store_root(store.project_root)))
    return {
        "code": descriptor["divergence"],
        "store_external": descriptor["store_external"],
        "pointer": descriptor["pointer"],
        "project_root_relocated_since_init": relocated,
        "project_local_residue": residue,
        "relocations_unfinished": unfinished_relocations(store.project_root),
    }


__all__ = [
    "DIVERGENCE_CODES",
    "custody_descriptor",
    "custody_divergence_axis",
    "custody_is_default",
]
