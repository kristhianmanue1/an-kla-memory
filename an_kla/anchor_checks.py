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


CHECK_SCHEMA_V2 = "an-kla/anchor-check-v2"  # ADR-0073 §2: the same, with entries of ``conversation`` (v1 only describes ``document``)
CONVERSATION_KEYS = frozenset({
    "index", "quote_sha256", "checked_at", "source", "source_reason", "integrity", "integrity_reason", "quote", "quote_reason", "match",
    "freshness", "reason", "resolution", "turn_id", "seal", "speaker", "candidates", "detail",
})
_CONVERSATION_FRESHNESS = _FRESHNESS + ("pending",)


def check_kind(check: Mapping[str, Any]) -> str:
    """``conversation`` for an entry that carries the resolver's ``resolution``; ``document`` otherwise."""
    return "conversation" if "resolution" in check else "document"


def stored_check(index: int, quote_sha256: str, out: Mapping[str, Any]) -> dict[str, Any]:
    """One entry of ``anchor_checks`` (or of an annotation's ``checks``) from the result of ``decide`` (or of the resolver's decision)."""
    if "resolution" in out:
        return {
            "index": index, "quote_sha256": quote_sha256, "checked_at": out["checked_at"], "source": out["source"], "source_reason": out["source_reason"],
            "integrity": out["integrity"], "integrity_reason": out["integrity_reason"], "quote": out["quote"], "quote_reason": out["quote_reason"],
            "match": out["match"], "freshness": out["freshness"], "reason": out["reason"], "resolution": out["resolution"], "turn_id": out["turn_id"],
            "seal": out["seal"], "speaker": out["speaker"], "candidates": out["candidates"], "detail": out["detail"],
        }
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


def _valid_conversation(check: dict[str, Any]) -> bool:
    if set(check) != CONVERSATION_KEYS or type(check["index"]) is not int or check["index"] < 0:
        return False
    if not (isinstance(check["quote_sha256"], str) and _HEX64.fullmatch(check["quote_sha256"])):
        return False
    if not (isinstance(check["checked_at"], str) and _CHECKED_AT.fullmatch(check["checked_at"])) or check["match"] not in _MATCHES:
        return False
    if any(check[key] not in _STATES for key in ("source", "integrity", "quote")) or check["freshness"] not in _CONVERSATION_FRESHNESS:
        return False
    if check["resolution"] not in ("pending", "resolved", "not_found") or not all(
        _opt_str(check[key]) for key in ("source_reason", "integrity_reason", "quote_reason", "reason", "turn_id", "seal", "speaker", "detail")
    ):
        return False
    candidates = check["candidates"]
    return candidates is None or (
        isinstance(candidates, dict) and set(candidates) == {"user", "pasted", "other"} and all(type(v) is int and v >= 0 for v in candidates.values())
    )


def valid_check(check: Any) -> bool:
    """The form of one stored result (a ``document``'s, or a ``conversation``'s when it carries ``resolution``)."""
    if isinstance(check, dict) and "resolution" in check:
        return _valid_conversation(check)
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
    if not isinstance(annotation, Mapping) or annotation.get("schema") not in (CHECK_SCHEMA, CHECK_SCHEMA_V2) or set(annotation) != {"schema", "target", "checks"}:
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
        kind = check_kind(check)  # ADR-0073 §2: a ``document`` entry for a ``document`` anchor, a ``conversation`` one (v2 only) for a conversation
        if not (isinstance(anchor, Mapping) and (anchor.get("source") or {}).get("kind") == kind):
            raise AnchorRejected(INVALID)
        envelope = target.get("an_kla_envelope")
        if kind == "conversation" and (annotation["schema"] != CHECK_SCHEMA_V2 or (isinstance(envelope, Mapping) and envelope.get("kind") == "directive")):
            raise AnchorRejected(INVALID)  # v1 describes only ``document``; the anchors of a ``directive`` are never resolved (§5)
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
    that of the record or the annotation, as strings.

    ADR-0072 §1 (erratum 6 of ``memoria/ancla/v2``): among the candidates the latest **conclusive** one wins, with that same order; only
    if none is conclusive, the latest at all.  An attempt that did not conclude never covers a result that did."""
    record_id = str(row.get("id", ""))
    envelope = row.get("an_kla_envelope")
    own_at = envelope.get("enqueued_at") if isinstance(envelope, dict) else None
    best: list[tuple[tuple[str, int, str, str], dict[str, Any]] | None] = [None, None]  # [latest conclusive, latest at all]

    def consider(checks: Any, origin: int, at: str, ident: str) -> None:
        for check in checks if isinstance(checks, list) else []:
            if valid_check(check) and check["index"] == index and check["quote_sha256"] == anchor.get("quote_sha256"):
                key = (normalized(check["checked_at"]), origin, at, ident)
                for slot in ((0, 1) if is_conclusive(check) else (1,)):
                    if best[slot] is None or key > best[slot][0]:  # type: ignore[index]
                        best[slot] = (key, check)

    consider(row.get("anchor_checks"), 0, own_at if isinstance(own_at, str) else "", record_id)
    for note in notes.get((stream, record_id), ()):
        consider(note["checks"], 1, note["enqueued_at"], note["id"])
    chosen = best[0] or best[1]
    return None if chosen is None else chosen[1]


NOT_CONCLUSIVE = ("no_adapter", "adapter_error")


def is_conclusive(check: Mapping[str, Any], kind: str | None = None) -> bool:
    """One rule, the criterion of each contract (ADR-0073 §3): ``document``, ADR-0072; ``conversation``, the resolver's README."""
    if (kind or check_kind(check)) == "conversation":
        from .conversation_resolver import is_conclusive_conversation

        return is_conclusive_conversation(check)
    return _is_conclusive_document(check)


def _is_conclusive_document(check: Mapping[str, Any]) -> bool:
    """ADR-0072 §1: a stored result does not conclude when its ``integrity_reason`` is ``no_adapter`` or ``adapter_error`` (A3 puts
    ``copy_sha_mismatch`` before both, so a contradicting copy does conclude).  Derived from what is stored: no new field, and it
    holds for what beta.39 already wrote.  A table that cannot be read is an ``adapter_error`` too."""
    return check.get("integrity_reason") not in NOT_CONCLUSIVE


def has_checks(item: Any) -> bool:
    """True if a served record or node carries an anchor result with its date: the trigger of the sparse schema versions."""
    anchors = item.get("anchors") if isinstance(item, dict) else None
    return isinstance(anchors, list) and any(isinstance(a, dict) and "checked_at" in a for a in anchors)


def has_conversation_result(item: Any) -> bool:
    """True if a served record or node carries a conversation result of the resolver (it has a ``speaker`` key): the trigger of the sparse versions."""
    anchors = item.get("anchors") if isinstance(item, dict) else None
    return isinstance(anchors, list) and any(isinstance(a, dict) and "speaker" in a and "resolution" in a for a in anchors)


def is_directive_row(row: Mapping[str, Any]) -> bool:
    """True for a ``directive`` record (its envelope says so): its ``conversation`` anchors are never resolved (ADR-0073 §5)."""
    envelope = row.get("an_kla_envelope")
    return isinstance(envelope, Mapping) and envelope.get("kind") == "directive"
