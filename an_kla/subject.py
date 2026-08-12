"""Subject namespace resolution (ADR-0033 §10, plan issue-59 Fase C).

Read-only command surface that derives the project namespace from the live
identity binding.  Performs no I/O mutation, never acquires ``write_lock``,
never creates ``.an-kla/``, never moves ``CURRENT``.  The namespace returned
here is **input** for building proposals; the commit still revalidates the
binding under the write lock (ADR-0033 §5).
"""

from __future__ import annotations

from typing import Any

from .identity import IdentityError, identity_status, read_binding
from .subject_ref import derive_namespace


SCHEMA = "an-kla/subject-namespace-result-v1"

# Controlled IdentityError catalogue from ``read_binding`` after a complete
# status (ADR-0033 §10 / plan §8): the identity migrated between the two
# read-only calls.  ``identity_uuid_invalid`` was added in beta.12 (Fase C L-3):
# a concurrent UUID corruption between the two reads must surface as
# fail-closed ``namespace_unavailable`` / exit 3, not as an uncaught exit 1.
# Any other exception (``StoreError``, ``IntegrityError``, ``OSError`` or an
# out-of-catalogue ``IdentityError``) propagates to the CLI's general handler
# as exit 1 — error layering must not mix hierarchies.
_BINDING_DRIFT_CODES = frozenset(
    (
        "project_identity_missing",
        "project_identity_invalid",
        "store_identity_missing",
        "store_identity_invalid",
        "project_identity_mismatch",
        "identity_uuid_invalid",
    )
)


def resolve_namespace(store: Any) -> dict[str, Any]:
    """Resolve the project namespace read-only.

    Flow (ADR-0033 §10 N5b):

    1. ``identity_status(store)`` without ``include_ids``.
    2. Non-``complete`` → ``namespace_unavailable`` / null namespace.
    3. ``complete`` → ``read_binding(store)``; a controlled ``IdentityError``
       (drift catalogue above) maps to ``namespace_unavailable``.  Any other
       exception is NOT caught: it propagates to the CLI general handler.
    4. Derive ``namespace = derive_namespace(binding["project_bytes"])``.
    """

    status = identity_status(store)
    if status["identity_status"] != "complete":
        return {
            "schema": SCHEMA,
            "result": "namespace_unavailable",
            "namespace": None,
        }
    try:
        binding = read_binding(store)
    except IdentityError as exc:
        if str(exc) in _BINDING_DRIFT_CODES:
            return {
                "schema": SCHEMA,
                "result": "namespace_unavailable",
                "namespace": None,
            }
        raise
    namespace = derive_namespace(binding["project_bytes"])
    return {
        "schema": SCHEMA,
        "result": "namespace_available",
        "namespace": namespace,
    }


__all__ = ["resolve_namespace"]
