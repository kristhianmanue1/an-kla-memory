"""The stored result of a ``document`` anchor's check (ADR-0071 §5): its shape, its invariants and the order that serves it.

An append-only store keeps the result as data that is only added, in two places: ``anchor_checks`` in the record
(what writing found) and ``an-kla/anchor-check-v1`` annotations in ``events`` (what each audit found; the same
pattern as ``anchor-resolution-v1``, ADR-0066 §6bis).  Reading serves the latest of them and never calls anybody.
The anchor does not change: its digest, its idempotency key and its ``payload_sha256`` stay the entry's.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from .anchors import AnchorRejected
from .anchors_search import PROFILE_ACCENTS, PROFILE_LITERAL, PROFILE_WS
from .store import STREAMS
from .vigency import is_active

CHECK_SCHEMA = "an-kla/anchor-check-v1"
INVALID = "anchor_check_invalid"
CHECK_KEYS = frozenset({
    "index", "quote_sha256", "checked_at", "manifest_sha256", "derivation", "source", "source_reason", "integrity",
    "integrity_reason", "quote", "quote_reason", "match", "freshness", "reason", "custody",
})
_STATES = ("verified", "not_found", "unverifiable")
_FRESHNESS = ("fresh", "unverified", "broken")
_MATCHES = (None, PROFILE_LITERAL, PROFILE_WS, PROFILE_ACCENTS)
_DERIVATIONS = (None, "current", "superseded", "unsupported")
_CHECKED_AT = re.compile(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,6}))?Z")
_HEX64 = re.compile(r"[0-9a-f]{64}")


def stored_check(index: int, quote_sha256: str, out: Mapping[str, Any]) -> dict[str, Any]:
    """One entry of ``anchor_checks`` (or of an annotation's ``checks``) from the result of ``decide``."""
    return {
        "index": index, "quote_sha256": quote_sha256, "checked_at": out["checked_at"],
        "manifest_sha256": out["manifest_sha256"], "derivation": out["derivation"],
        "source": out["source"], "source_reason": out["source_reason"],
        "integrity": out["integrity"], "integrity_reason": out["integrity_reason"],
        "quote": out["quote"], "quote_reason": out["quote_reason"], "match": out["match"],
        "freshness": out["freshness"], "reason": out["reason"], "custody": out["custody"],
    }


def _opt_str(value: Any) -> bool:
    return value is None or isinstance(value, str)


def valid_check(check: Any) -> bool:
    """The form of one stored result."""
    if not isinstance(check, dict) or set(check) != CHECK_KEYS:
        return False
    if type(check["index"]) is not int or check["index"] < 0:
        return False
    if not (isinstance(check["quote_sha256"], str) and _HEX64.fullmatch(check["quote_sha256"])):
        return False
    if not (isinstance(check["checked_at"], str) and _CHECKED_AT.fullmatch(check["checked_at"])):
        return False
    if not _opt_str(check["manifest_sha256"]) or check["derivation"] not in _DERIVATIONS or check["match"] not in _MATCHES:
        return False
    if any(check[key] not in _STATES for key in ("source", "integrity", "quote")) or check["freshness"] not in _FRESHNESS:
        return False
    if not all(_opt_str(check[key]) for key in ("source_reason", "integrity_reason", "quote_reason", "reason")):
        return False
    custody = check["custody"]
    return custody is None or (isinstance(custody, dict) and set(custody) == {"retention"} and isinstance(custody["retention"], str))


def validate_annotation(annotation: Any, target: Mapping[str, Any] | None) -> None:
    """The invariants checked on draining: the target exists and is vigent; each ``index`` is a ``document`` anchor of it
    (v1 or v2) with that ``quote_sha256``; each result has its form.  ``anchor_check_invalid`` otherwise."""
    if not isinstance(annotation, Mapping) or annotation.get("schema") != CHECK_SCHEMA or set(annotation) != {"schema", "target", "checks"}:
        raise AnchorRejected(INVALID)
    ref, checks = annotation["target"], annotation["checks"]
    if not (isinstance(ref, Mapping) and set(ref) == {"stream", "record_id"} and ref["stream"] in STREAMS and isinstance(ref["record_id"], str)):
        raise AnchorRejected(INVALID)
    anchors = target.get("anchors") if target is not None else None
    if target is None or not isinstance(anchors, list) or not isinstance(checks, list) or not checks:
        raise AnchorRejected(INVALID)
    seen: set[int] = set()
    for check in checks:
        if not valid_check(check) or check["index"] in seen or check["index"] >= len(anchors):
            raise AnchorRejected(INVALID)
        seen.add(check["index"])
        anchor = anchors[check["index"]]
        if not (isinstance(anchor, Mapping) and (anchor.get("source") or {}).get("kind") == "document"):
            raise AnchorRejected(INVALID)
        if anchor.get("quote_sha256") != check["quote_sha256"]:
            raise AnchorRejected(INVALID)


def normalized(checked_at: str) -> str:
    """``checked_at`` with the fraction padded to microseconds, so dates written with different precision compare as dates."""
    found = _CHECKED_AT.fullmatch(checked_at)
    return f"{found.group(1)}.{(found.group(2) or '').ljust(6, '0')}Z" if found else checked_at


def check_annotations(snapshot: Any) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """The vigent ``anchor_check`` annotations of ``events``, by target ``(stream, record_id)``, with the ``enqueued_at``
    of their envelope (``""`` if there is none) that orders them."""
    notes: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in snapshot.records.get("events", []):
        content = row.get("anchor_check")
        if row.get("kind") != "anchor_check" or not is_active(row) or not isinstance(content, dict):
            continue
        target = content.get("target")
        if not (isinstance(target, dict) and isinstance(target.get("record_id"), str) and target.get("stream") in STREAMS):
            continue
        envelope = row.get("an_kla_envelope")
        at = envelope.get("enqueued_at") if isinstance(envelope, dict) else None
        notes.setdefault((target["stream"], target["record_id"]), []).append(
            {"id": str(row.get("id", "")), "enqueued_at": at if isinstance(at, str) else "", "checks": content.get("checks")}
        )
    return notes


def latest_check(
    row: Mapping[str, Any], stream: str, index: int, anchor: Mapping[str, Any],
    notes: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
) -> dict[str, Any] | None:
    """The stored result that reading serves for an anchor, or ``None``.  Candidates: the record's own ``anchor_checks``
    entry with that ``index`` and the vigent annotations of that target and ``index``, whenever the ``quote_sha256``
    is the anchor's.  The greatest ``(checked_at, origin, enqueued_at, id)`` wins: origin 0 for the record and 1 for an
    annotation (on the same date the audit rules); ``enqueued_at`` is the envelope's (``""`` without one); ``id``
    that of the record or the annotation, as strings."""
    record_id = str(row.get("id", ""))
    envelope = row.get("an_kla_envelope")
    own_at = envelope.get("enqueued_at") if isinstance(envelope, dict) else None
    best: tuple[tuple[str, int, str, str], dict[str, Any]] | None = None

    def consider(checks: Any, origin: int, at: str, ident: str) -> None:
        nonlocal best
        for check in checks if isinstance(checks, list) else []:
            if valid_check(check) and check["index"] == index and check["quote_sha256"] == anchor.get("quote_sha256"):
                key = (normalized(check["checked_at"]), origin, at, ident)
                if best is None or key > best[0]:
                    best = (key, check)

    consider(row.get("anchor_checks"), 0, own_at if isinstance(own_at, str) else "", record_id)
    for note in notes.get((stream, record_id), ()):
        consider(note["checks"], 1, note["enqueued_at"], note["id"])
    return None if best is None else best[1]


def has_checks(item: Any) -> bool:
    """True if a served record or node carries an anchor result with its date: the trigger of the sparse schema versions."""
    anchors = item.get("anchors") if isinstance(item, dict) else None
    return isinstance(anchors, list) and any(isinstance(a, dict) and "checked_at" in a for a in anchors)
