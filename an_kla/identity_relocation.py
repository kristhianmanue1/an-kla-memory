"""Record that a project moved after an adoption plan (ADR-0048 §2)."""

from __future__ import annotations

from typing import Any, Mapping

from .identity import (
    IdentityError,
    _custody_guard,
    _validate_plan,
    identity_lock,
    identity_status,
)
from .relocation_receipts import (
    RelocationReceiptError,
    project_relocation_expectation,
    write_relocation_receipt,
)


def record_project_relocation(
    store: Any, plan: Mapping[str, Any], expected_current: str
) -> dict[str, Any]:
    """Register the move from the plan's observed root to the current one.

    The receipt binds the plan's identity, the exact CURRENT and both
    observed roots; ``identity.adopt`` then accepts the plan at the new root.
    """

    checked = _validate_plan(plan)
    if checked["expected_current"] != expected_current:
        raise IdentityError("identity_adoption_base_changed")
    if checked["canonical_project_root_observed"] == str(store.project_root):
        raise IdentityError("relocation_receipt_not_required")
    with identity_lock(store):
        with store.write_lock():
            if store.read_current() != expected_current:
                raise IdentityError("identity_adoption_base_changed")
            if identity_status(store)["identity_status"] != "legacy_unadopted":
                raise IdentityError("identity_adoption_plan_invalid")
            _custody_guard(store, None)
            expected = project_relocation_expectation(
                str(store.project_root), checked, expected_current
            )
            try:
                receipt = write_relocation_receipt(
                    store,
                    kind="project_root",
                    store_identity=expected["store_identity"],
                    current_observed=expected_current,
                    from_root=expected["from_root_observed"],
                    to_root=expected["to_root_observed"],
                )
            except RelocationReceiptError as exc:
                raise IdentityError(str(exc)) from exc
    return {
        "schema": "an-kla/relocation-record-result-v1",
        "kind": "project_root",
        "relocation_receipt": receipt,
        "current_observed": expected_current,
    }


__all__ = ["record_project_relocation"]
