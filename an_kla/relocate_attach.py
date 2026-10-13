"""Bind an existing external vault to a checkout at another root (ADR-0048
Enmienda 5, G3).

A vault created for ``/old/project`` and kept outside the checkout survives
deleting or re-cloning the project somewhere else.  ``init`` refuses to bind
it there (``store_root_project_mismatch``, Enmienda 4 §3) because by bytes a
re-cloned checkout and a different project look the same.  ``attach`` is the
governed answer: the operator names the vault and the exact CURRENT, the
vault records a ``project_root`` relocation receipt (old root -> this root)
and only then the checkout gets its pointer.  The receipt is evidence of the
operator's declaration, not proof that both roots are "the same project".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .canonical import digest_bytes
from .custody import (
    CustodyError, clear_bind_intent, custody_fingerprint, default_store_root,
    project_local_vault_present, read_bind_intent, read_pointer, relocate_pointer_locator,
    vault_present, write_pointer,
)
from .identity import IdentityError, identity_lock, mutation_preflight
from .relocation_receipts import (
    RelocationReceiptError, chain_head, load_relocation_receipt, write_relocation_receipt,
)
from .store_errors import StoreError


RESULT_SCHEMA = "an-kla/relocate-attach-result-v1"


class AttachError(StoreError):
    """Stable attach failure; ``str(exc)`` is the error code."""


def bound_project_root(store: Any, binding: Mapping[str, Any]) -> str:
    """Project root the vault was last bound to: receipt chain head or init."""

    head = chain_head(store, binding["store_identity"], "project_root")
    if head is None:
        return str(binding["store"]["canonical_project_root_at_init"])
    return str(load_relocation_receipt(store, head)["to_root_observed"])


def _result(
    binding: Mapping[str, Any], revision: str, receipt: str | None, *, replayed: bool
) -> dict[str, Any]:
    return {
        "schema": RESULT_SCHEMA,
        "revision": revision,
        "custody_fingerprint": custody_fingerprint(binding),
        "relocation_receipt": receipt,
        "replayed": replayed,
    }


def _require_no_live_twin(store: Any, binding: Mapping[str, Any], previous: str) -> None:
    """Refuse when the previously bound checkout still holds another copy.

    A copied vault is indistinguishable by bytes from a moved one, so the
    old root is the only witness: a pointer there with this fingerprint whose
    locator still holds a vault at another path, or a project-local vault
    with this identity, means attaching would fork custody into two live
    vaults (beta.30 release round 2, N-01).  The same vault shared by two
    checkouts stays the declared limit of Enmienda 5 §5.
    """

    pointer = read_pointer(previous)
    if pointer is not None and pointer["custody_fingerprint"] == custody_fingerprint(binding):
        located = Path(pointer["store_root"]).resolve()
        if located != store.store_root and vault_present(located):
            raise AttachError("relocate_attach_source_live")
    local = default_store_root(previous)
    if local != store.store_root and vault_present(local):
        try:
            identity = digest_bytes((local / "memory" / "identity.json").read_bytes())
        except OSError:
            identity = None
        if identity in (None, binding["store_identity"]):
            raise AttachError("relocate_attach_source_live")


def attach_store(store: Any, expected_current: str) -> dict[str, Any]:
    """Write the receipt (when the root changed), then the pointer.

    Idempotent: a crash between receipt and pointer, or a repeated call,
    finds the chain head already at this root and only writes the pointer.
    """

    if not store.store_external:
        raise AttachError("relocate_attach_not_external")
    if project_local_vault_present(store.project_root):
        raise CustodyError("store_root_divergence")
    pending = read_bind_intent(store.project_root)
    if pending is not None and pending != str(store.store_root):
        # An unfinished ``init`` toward another vault (#147, m1).
        raise CustodyError("store_root_bind_pending")
    target = str(store.project_root)
    try:
        existing = read_pointer(store.project_root)
        binding = mutation_preflight(store)
        bound = bound_project_root(store, binding)
    except (IdentityError, RelocationReceiptError) as exc:
        raise AttachError(str(exc)) from exc
    replay = existing is not None and bound == target
    if not replay:
        checked = store.verify()
        if checked["revision"] != expected_current:
            raise AttachError("relocate_attach_base_changed")
    receipt: str | None = None
    with identity_lock(store):
        with store.write_lock():
            # The replay also requires the exact CURRENT (round 1, H-02).
            if store.read_current() != expected_current:
                raise AttachError("relocate_attach_base_changed")
            binding = mutation_preflight(store)
            try:
                previous = bound_project_root(store, binding)
                if replay and previous != target:
                    raise AttachError("relocate_attach_base_changed")
                if previous != target:
                    # A pointer copied into this checkout is no replay: the
                    # binding to this root still needs its receipt (N-02).
                    _require_no_live_twin(store, binding, previous)
                    receipt = write_relocation_receipt(
                        store,
                        kind="project_root",
                        store_identity=binding["store_identity"],
                        current_observed=expected_current,
                        from_root=previous,
                        to_root=target,
                    )
            except RelocationReceiptError as exc:
                raise AttachError(str(exc)) from exc
            if existing is not None:
                # A vault moved away from the pointer's locator: point at it.
                relocate_pointer_locator(store, binding)
            else:
                write_pointer(store, binding)
            clear_bind_intent(store.project_root, store.store_root)
    return _result(binding, expected_current, receipt, replayed=replay)


__all__ = ["AttachError", "RESULT_SCHEMA", "attach_store", "bound_project_root"]
