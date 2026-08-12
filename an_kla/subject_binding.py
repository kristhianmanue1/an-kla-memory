"""Pure ``subject_ref`` namespace binding guard (ADR-0033 §Decisión 5).

This module performs no I/O.  After the write-policy core has verified a plan,
the store calls ``check_subject_ref_binding`` under ``write_lock`` to confirm
that each record carrying a ``subject_ref`` declares the namespace derived from
the project-identity bytes materialized in ``binding``.
"""

from __future__ import annotations

from typing import Mapping

from .subject_ref import SubjectRefError, derive_namespace, parse_subject_ref
from .write_policy import WritePolicyError


def check_subject_ref_binding(checked_plan: Mapping, binding: Mapping) -> None:
    """Validate ``subject_ref`` namespaces against the bound project identity.

    ``binding`` is the project-identity binding captured by ``mutation_preflight``
    and revalidated by ``assert_unchanged``; its ``project_bytes`` is the
    canonical JSON of ``project-identity-v1``.  Records without ``subject_ref``
    are a no-op (legacy compatibility), so a plan with no ``subject_ref`` never
    touches ``binding``.  Malformed values are translated to the stable
    ``WritePolicyError`` contract before any namespace derivation and never
    surface a raw ``SubjectRefError``, ``IndexError`` or ``KeyError``.
    """

    expected_namespace: str | None = None
    for item in checked_plan["records"]:
        record = item["record"]
        if "subject_ref" not in record:
            continue
        try:
            parsed = parse_subject_ref(record["subject_ref"])
        except SubjectRefError as exc:
            raise WritePolicyError(
                "invalid_write_proposal", "record.subject_ref"
            ) from exc
        # Derive lazily: only after the first well-formed subject_ref is parsed,
        # so legacy plans and malformed values never touch binding["project_bytes"].
        if expected_namespace is None:
            expected_namespace = derive_namespace(binding["project_bytes"])
        if parsed["namespace"] != expected_namespace:
            raise WritePolicyError("subject_ref_namespace_mismatch")


__all__ = ["check_subject_ref_binding"]
