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

from typing import Any, Mapping

from .custody import (
    CustodyError, clear_bind_intent, custody_fingerprint, project_local_vault_present,
    read_bind_intent, read_pointer, relocate_pointer_locator, write_pointer,
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
    try:
        existing = read_pointer(store.project_root)
        binding = mutation_preflight(store)
    except IdentityError as exc:
        raise AttachError(str(exc)) from exc
    if existing is not None:
        # mutation_preflight already proved the fingerprint matches and that
        # the pointer's locator holds no other live copy.  The replay still
        # requires the exact CURRENT (beta.30 release round, H-02).
        with identity_lock(store):
            with store.write_lock():
                if store.read_current() != expected_current:
                    raise AttachError("relocate_attach_base_changed")
                binding = mutation_preflight(store)
                # A vault moved away from the pointer's locator: point at it.
                relocate_pointer_locator(store, binding)
                clear_bind_intent(store.project_root, store.store_root)
        return _result(binding, expected_current, None, replayed=True)
    checked = store.verify()
    if checked["revision"] != expected_current:
        raise AttachError("relocate_attach_base_changed")
    receipt: str | None = None
    with identity_lock(store):
        with store.write_lock():
            if store.read_current() != expected_current:
                raise AttachError("relocate_attach_base_changed")
            binding = mutation_preflight(store)
            target = str(store.project_root)
            try:
                previous = bound_project_root(store, binding)
                if previous != target:
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
            write_pointer(store, binding)
            clear_bind_intent(store.project_root, store.store_root)
    return _result(binding, expected_current, receipt, replayed=False)


__all__ = ["AttachError", "RESULT_SCHEMA", "attach_store", "bound_project_root"]
