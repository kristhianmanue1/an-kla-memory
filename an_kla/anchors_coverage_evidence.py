"""The evidence a record's coverage is measured against, one per anchor (erratum 7 of ``memoria/ancla/v1``; ADR-0073 §8).

For ``repo-file`` and ``conversation`` it is the quote, as always.  For a ``document`` anchor (schema v1 or v2) of valid form::

    quote
    + "\\n" + str(locator.page)    if the locator is an object with an integer ``page``
    + "\\n" + copy.path            if it carries a ``copy``

``item_id`` and ``item_ids`` do not enter.  An anchor of ``document`` with an error of form contributes nothing (not even its quote) and
sets no mark.  The rules of elements (``fact-checks-rules/v2``) and their function do not change and never receive the anchor: they get
strings.  An evidence over 16 384 bytes is a ``coverage_error`` that voids the coverage of the whole record; it is never truncated.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .anchors import ANCHOR_SCHEMA_V2, AnchorRejected, validate_anchor
from .anchors_repo_file import validate_path

EVIDENCE = "ancla-document/v1"
MAX_EVIDENCE_BYTES = 16384
COVERAGE_ERROR = "invalid_fact_quotes"


def document_evidence(anchor: Any, record_type: str = "fact") -> str | None:
    """The evidence of a ``document`` anchor, or ``None`` if its form is not valid (it then adds nothing)."""
    if not isinstance(anchor, Mapping) or not isinstance(anchor.get("source"), Mapping) or anchor["source"].get("kind") != "document":
        return None
    try:
        checked = validate_anchor({**anchor, "schema": ANCHOR_SCHEMA_V2}, record_type)  # the form of v2, also for a v1 anchor
        copy = checked["source"].get("copy")
        if copy is not None:
            validate_path(copy["path"])
    except (AnchorRejected, KeyError, TypeError):
        return None
    evidence = checked["quote"]
    locator = checked["source"].get("locator")
    if isinstance(locator, Mapping) and type(locator.get("page")) is int:
        evidence += "\n" + str(locator["page"])
    if copy is not None:
        evidence += "\n" + copy["path"]
    return evidence


def evidence_quotes(anchors: Sequence[Mapping[str, Any]], record_type: str = "fact") -> tuple[list[str], bool] | None:
    """``(evidences, marked)``: one string per anchor that counts and whether a valid ``document`` anchor put the mark; ``None`` when an
    evidence is over the limit (``coverage_error``)."""
    quotes: list[str] = []
    marked = False
    for anchor in anchors:
        if isinstance(anchor.get("source"), Mapping) and anchor["source"].get("kind") == "document":
            evidence = document_evidence(anchor, record_type)
            if evidence is None:
                continue
            if len(evidence.encode("utf-8")) > MAX_EVIDENCE_BYTES:
                return None
            marked = True
            quotes.append(evidence)
        else:
            quotes.append(anchor["quote"])
    return quotes, marked
