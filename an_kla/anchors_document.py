"""``document`` anchors (C3 "Documento fijado por hash"; ADR-0066 §2, A9).

This release validates the *shape* of a ``document`` anchor (in
:mod:`an_kla.anchors`) and stores it intact; it does not check its meaning, which
needs a custodian.  A well-formed one answers ``unverified`` with
``kind_not_supported`` and is never rejected.
"""

from __future__ import annotations

from typing import Any, Mapping

from .anchors_freshness import UNVERIFIABLE, anchor_result

SUPPORTED = False


def check_document(anchor: Mapping[str, Any]) -> dict[str, Any]:
    state = (UNVERIFIABLE, "kind_not_supported")
    modality = anchor["source"]["derivation"]["modality"]
    return anchor_result("document", state, state, state, modality=modality)
