"""Pure subject reference primitives (ADR-0033).

This module is a leaf in the dependency DAG: it imports only ``canonical``.  It
defines the single normative grammar for ``subject_ref`` and the namespace
derivation bound to project identity.  It performs no I/O and never imports the
write-policy core, store or identity modules.
"""

from __future__ import annotations

import re
from typing import Any

from .canonical import digest_bytes


# Single normative grammar (ADR-0033 §Decisión 1).  Anchored, with the closed
# kind enum embedded, so a single ``fullmatch`` validates form AND enum
# membership.  No backslashes: the string is identical byte-for-byte as a Python
# raw string and as the JSON Schema ``pattern`` value.
SUBJECT_REF_PATTERN = (
    r"^an-kla:subject:v1:"
    r"(?:actor|api|decision|dependency|doc|environment|integration|issue|project|service|system)"
    r":p-[0-9a-f]{32}:[a-z0-9._-]{1,64}$"
)
_SUBJECT_REF = re.compile(SUBJECT_REF_PATTERN)


class SubjectRefError(ValueError):
    """Stable subject reference validation failure.

    ``code`` is the stable, machine-readable contract.  The optional ``detail``
    is informative and evolutive: it names the offending cause to aid operators
    but is NOT a stability contract.  ``str(error)`` keeps equaling ``code``.
    """

    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


def parse_subject_ref(value: Any) -> dict[str, str]:
    """Validate a ``subject_ref`` and return its typed components.

    Validation is a single ``fullmatch`` against ``SUBJECT_REF_PATTERN``.  The
    regex guarantees exactly six ``:``-separated components, so positional
    unpacking after validation never raises ``IndexError``.
    """

    if not isinstance(value, str) or not _SUBJECT_REF.fullmatch(value):
        raise SubjectRefError("invalid_subject_ref")
    _, _, _, kind, namespace, subject_id = value.split(":")
    return {"kind": kind, "namespace": namespace, "id": subject_id}


def derive_namespace(project_bytes: bytes) -> str:
    """Derive the host-bound namespace from project-identity bytes (ADR-0033 §2).

    ``project_bytes`` is the canonical JSON of ``project-identity-v1`` already
    materialized by the caller (the binding captured under lock).  The slice
    ``[7:39]`` drops the ``sha256:`` prefix and yields 32 hex chars (128 bits).
    """

    return "p-" + digest_bytes(project_bytes)[7:39]


__all__ = [
    "SUBJECT_REF_PATTERN",
    "SubjectRefError",
    "derive_namespace",
    "parse_subject_ref",
]
