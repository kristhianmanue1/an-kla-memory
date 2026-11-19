"""Freshness of an anchor, derived from its three checks (C3; ADR-0066 §4).

No model, no I/O.  ``fresh`` means "the quote is still there", never that the
fact is true.  The per-record aggregate ``anchors_freshness`` is an an-kla
presentation (C4a), not part of C3.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

VERIFIED = "verified"
NOT_FOUND = "not_found"
UNVERIFIABLE = "unverifiable"

# Closed vocabulary of ``reason`` per check (C3 README plus errata 1 E6).
SOURCE_NOT_FOUND = ("path_missing", "turn_purged", "copy_missing", "document_unknown")
SOURCE_UNVERIFIABLE = (
    "commit_not_in_clone", "commit_not_on_default_branch", "no_default_branch", "no_git",
    "repo_unavailable", "resolution_pending", "session_lacks_quote", "no_verifier",
    "custodian_offline", "kind_not_supported", "anchor_limit",
)
QUOTE_NOT_FOUND = ("quote_absent",)
QUOTE_UNVERIFIABLE = (
    "source_not_verified", "too_large", "binary", "not_utf8", "commit_not_in_clone",
    "commit_not_on_default_branch", "custodian_offline", "derived_modality",
    "kind_not_supported", "anchor_limit", "document_unknown",
)
INTEGRITY_NOT_FOUND = ("commit_blob_lacks_quote", "seal_mismatch", "copy_sha_mismatch", "manifest_mismatch")
INTEGRITY_UNVERIFIABLE = (
    "working_tree", "commit_not_in_clone", "source_not_verified", "too_large", "binary",
    "not_utf8", "raw_lost", "resolution_pending", "session_lacks_quote", "no_verifier",
    "turn_purged", "custodian_offline", "kind_not_supported", "anchor_limit", "document_unknown",
)

# Worst first: the order of the per-record aggregate.
FRESHNESS_ORDER = ("broken", "stale", "unverified", "pending", "fresh")


def derive_freshness(
    kind: str,
    source: str,
    quote: str,
    integrity: str,
    resolution: str | None = None,
    modality: str | None = None,
) -> tuple[str, str | None]:
    """The table of C3, in its order.  Returns ``(freshness, decided_by)``.

    ``decided_by`` names the row's deciding check (``source``, ``quote``,
    ``integrity``, ``resolution`` or ``modality``), ``None`` when ``fresh``.
    """
    if kind == "conversation" and resolution == "pending":
        return "pending", "resolution"
    if kind == "conversation" and resolution == "not_found":
        return "broken", "resolution"
    if source == NOT_FOUND:
        return "broken", "source"
    if integrity == NOT_FOUND:
        return "broken", "integrity"
    if source == VERIFIED and quote == NOT_FOUND:
        return ("stale" if kind == "repo-file" else "broken"), "quote"
    if kind == "repo-file" and source == VERIFIED and quote == VERIFIED:
        return "fresh", None
    all_verified = source == quote == integrity == VERIFIED
    if kind == "conversation" and all_verified:
        return "fresh", None
    if kind == "document" and all_verified:
        if modality == "native_text":
            return "fresh", None
        return "unverified", "modality"
    for name, state in (("source", source), ("quote", quote), ("integrity", integrity)):
        if state != VERIFIED:
            return "unverified", name
    return "unverified", "modality"


def anchor_result(
    kind: str,
    source: tuple[str, str | None],
    quote: tuple[str, str | None],
    integrity: tuple[str, str | None],
    *,
    at: str | None = None,
    match: str | None = None,
    matched_text: str | None = None,
    resolution: str | None = None,
    modality: str | None = None,
) -> dict[str, Any]:
    """Assemble the output of verifying one anchor, with its derived freshness.

    Each check is a ``(state, reason)`` pair.  ``at`` is only present for a
    ``repo-file``; ``resolution`` and ``modality`` feed the table.
    """
    freshness, decided_by = derive_freshness(
        kind, source[0], quote[0], integrity[0], resolution, modality
    )
    reasons = {"source": source[1], "quote": quote[1], "integrity": integrity[1]}
    if decided_by == "resolution":
        reason = "resolution_pending" if freshness == "pending" else reasons["source"]
    elif decided_by == "modality":
        reason = "derived_modality"
    else:
        reason = reasons.get(decided_by) if decided_by else None
    out: dict[str, Any] = {
        "source": source[0], "source_reason": source[1],
        "quote": quote[0], "quote_reason": quote[1],
        "integrity": integrity[0], "integrity_reason": integrity[1],
    }
    if kind == "repo-file":
        out["at"] = at
    out.update(match=match, matched_text=matched_text, freshness=freshness, reason=reason)
    return out


def unchecked_result(kind: str, reason: str = "anchor_limit") -> dict[str, Any]:
    """An anchor beyond ``--anchor-limit``: never read, ``unverified`` (A8)."""
    return anchor_result(
        kind,
        (UNVERIFIABLE, reason),
        (UNVERIFIABLE, reason),
        (UNVERIFIABLE, reason),
        at=None,
    ) | {"freshness": "unverified", "reason": reason}


def aggregate_freshness(results: Sequence[Mapping[str, Any]]) -> str | None:
    """The worst freshness of a record's anchors; ``None`` when it has none (A7)."""
    seen = {item["freshness"] for item in results}
    for level in FRESHNESS_ORDER:
        if level in seen:
            return level
    return None
