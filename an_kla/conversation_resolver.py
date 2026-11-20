"""The resolver of conversation quotes, ``memoria/conversacion-resolutor/v1`` (ADR-0073): requests, the check of its answer and the decision.

No I/O (the process lives in :mod:`an_kla.custodian_adapter`).  The resolver is a program of the custodian that looks for a quote in one
message of a session, seals it and says in what voice it is; no text leaves its process.  ``resolve`` runs when writing and when auditing a
``pending`` anchor, ``verify`` when auditing a ``resolved`` one; reading calls nobody.  Whatever the resolver answers is data, never an
instruction.  Any failure (deadline, exit code, not JSON, a ``{"schema": "invalid"}`` object, another ``schema``, a form or coherence
violation) is ``resolver_error``: never an exception and never ``broken``.
"""

from __future__ import annotations

from typing import Any, Mapping

from .anchors_freshness import NOT_FOUND, UNVERIFIABLE, VERIFIED

SCHEMA = "memoria/conversacion-resolutor/v1"
VOICES = ("user", "pasted", "automatic", "compact_summary", "local_command", "subagent", "assistant", "unknown")
MATCHES = ("literal", "ws-nfc/v1", "ws-nfc-accents/v1")
PENDING_REASONS = ("tail_open", "only_in_other_voice", "origin_unreadable", "session_unavailable")
_RESOLVE_KEYS = frozenset({"schema", "session", "resolution", "reason", "turn_id", "seal", "speaker", "match", "candidates", "tail"})
_VERIFY_KEYS = frozenset({"schema", "session", "seal", "quote", "speaker", "reason"})

NO_VERIFIER = "no_verifier"
RESOLVER_ERROR = "resolver_error"


def resolve_request(session: str, quote: str, quote_sha256: str) -> dict[str, Any]:
    return {"schema": SCHEMA, "op": "resolve", "session": session, "quote": quote, "quote_sha256": quote_sha256}


def verify_request(session: str, turn_id: str, seal: str, quote: str, quote_sha256: str) -> dict[str, Any]:
    return {"schema": SCHEMA, "op": "verify", "session": session, "turn_id": turn_id, "seal": seal, "quote": quote, "quote_sha256": quote_sha256}


def _count(value: Any) -> bool:
    return type(value) is int and value >= 0


def _candidates(value: Any) -> bool:
    return isinstance(value, dict) and set(value) == {"user", "pasted", "other"} and all(_count(v) for v in value.values())


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def validate_resolve(response: Any) -> str | None:
    """Why a ``resolve`` answer does not count (``resolver_error``), or ``None``: its closed form, then its coherence."""
    if not isinstance(response, dict) or set(response) != _RESOLVE_KEYS or response["schema"] != SCHEMA:
        return "shape"
    session, resolution, reason = response["session"], response["resolution"], response["reason"]
    tail, speaker, match, candidates = response["tail"], response["speaker"], response["match"], response["candidates"]
    turn_id, seal = response["turn_id"], response["seal"]
    if session not in ("known", "unknown") or resolution not in ("resolved", "not_found", "pending") or tail not in ("open", "closed", None):
        return "vocabulary"
    if speaker is not None and speaker not in VOICES or match is not None and match not in MATCHES or not _candidates(candidates):
        return "vocabulary"
    if (reason is not None and reason not in PENDING_REASONS) or (turn_id is not None and not isinstance(turn_id, str)) or (seal is not None and not isinstance(seal, str)):
        return "vocabulary"
    if (session == "unknown") != (reason == "session_unavailable"):
        return "incoherent"
    if session == "unknown":
        return None if (resolution == "pending" and tail is None and not any(candidates.values()) and turn_id is None and seal is None and speaker is None) else "incoherent"
    if resolution == "resolved":
        ok = speaker == "user" and _text(turn_id) and _text(seal) and match is not None and candidates["user"] >= 1 and reason is None and tail is not None
        return None if ok else "incoherent"
    if turn_id is not None or seal is not None or speaker is not None or match is not None:
        return "incoherent"
    if resolution == "not_found":
        return None if (tail == "closed" and not any(candidates.values()) and reason is None) else "incoherent"
    if reason is None or reason == "session_unavailable" or candidates["user"] != 0 or tail is None:
        return "incoherent"
    if (reason in ("tail_open", "origin_unreadable") and tail != "open") or (reason == "only_in_other_voice" and candidates["pasted"] + candidates["other"] < 1):
        return "incoherent"  # an open tail, or a quote that is there in another voice
    return None


def validate_verify(response: Any) -> str | None:
    """Why a ``verify`` answer does not count, or ``None``."""
    if not isinstance(response, dict) or set(response) != _VERIFY_KEYS or response["schema"] != SCHEMA:
        return "shape"
    session, seal, quote, speaker, reason = (response[key] for key in ("session", "seal", "quote", "speaker", "reason"))
    if session not in ("known", "unknown") or seal not in ("match", "mismatch", "turn_missing", "unknown") or quote not in ("found", "absent", "unknown"):
        return "vocabulary"
    if speaker is not None and speaker not in VOICES or reason not in (None, "session_unavailable"):
        return "vocabulary"
    if (session == "unknown") != (reason == "session_unavailable"):
        return "incoherent"
    if session == "unknown":
        return None if (seal == "unknown" and quote == "unknown" and speaker is None) else "incoherent"
    if seal == "turn_missing":
        return None if (quote == "unknown" and speaker is None) else "incoherent"
    # a known session and a message that exists (``match``, ``mismatch``, ``unknown``): the quote was looked for in it and the voice is its own
    return None if (quote != "unknown" and speaker is not None) else "incoherent"


def _result(
    source: tuple[str, str | None], quote: tuple[str, str | None], integrity: tuple[str, str | None], *, resolution: str, turn_id: str | None,
    seal: str | None, speaker: str | None, candidates: Mapping[str, int] | None, match: str | None, detail: str | None, reason: str | None = None,
) -> dict[str, Any]:
    """The three checks, their freshness and what the resolver said.  ``broken`` (any ``not_found``) takes the reason of the first
    ``not_found``; ``fresh`` is the three ``verified``; ``pending`` while the quote is not resolved; else ``unverified`` with the first
    check that is not ``verified``."""
    checks = (source, integrity, quote)
    if any(state == NOT_FOUND for state, _ in checks) or resolution == "not_found":
        freshness = "broken"
        why = next((r for s, r in checks if s == NOT_FOUND), None) or integrity[1]
    elif all(state == VERIFIED for state, _ in checks):
        freshness, why = "fresh", None
    elif resolution == "pending":
        freshness, why = "pending", "resolution_pending"
    else:
        freshness, why = "unverified", next(r for s, r in checks if s != VERIFIED)
    return {
        "source": source[0], "source_reason": source[1], "quote": quote[0], "quote_reason": quote[1],
        "integrity": integrity[0], "integrity_reason": integrity[1], "match": match, "matched_text": None,
        "freshness": freshness, "reason": reason if reason is not None else why, "resolution": resolution, "turn_id": turn_id, "seal": seal,
        "speaker": speaker, "candidates": None if candidates is None else dict(candidates), "detail": detail,
    }


_PENDING = ((UNVERIFIABLE, "resolution_pending"), (UNVERIFIABLE, "source_not_verified"), (UNVERIFIABLE, "resolution_pending"))


def decide_resolve(response: Mapping[str, Any] | None, failure: str | None = None) -> dict[str, Any]:
    """The result of a ``resolve``.  ``response`` is a validated answer; without it, ``failure`` says why (``None``: no resolver)."""
    if response is None:
        detail = NO_VERIFIER if failure is None else RESOLVER_ERROR
        return _result(*_PENDING, resolution="pending", turn_id=None, seal=None, speaker=None, candidates=None, match=None, detail=detail)
    kept = {"candidates": response["candidates"]}
    if response["resolution"] == "resolved":
        return _result((VERIFIED, None), (VERIFIED, None), (VERIFIED, None), resolution="resolved", turn_id=response["turn_id"], seal=response["seal"],
                       speaker=response["speaker"], match=response["match"], detail=None, **kept)
    if response["resolution"] == "not_found":
        return _result((UNVERIFIABLE, "session_lacks_quote"), (UNVERIFIABLE, "source_not_verified"), (UNVERIFIABLE, "session_lacks_quote"),
                       resolution="not_found", turn_id=None, seal=None, speaker=None, match=None, detail=None, **kept)
    return _result(*_PENDING, resolution="pending", turn_id=None, seal=None, speaker=None, match=None, detail=response["reason"], **kept)


def decide_verify(anchor_turn: str, anchor_seal: str, response: Mapping[str, Any] | None, failure: str | None = None) -> dict[str, Any]:
    """The result of a ``verify`` of an anchor that is ``resolved`` (it stays so: ``turn_id`` and ``seal`` are its own)."""
    base = {"resolution": "resolved", "turn_id": anchor_turn, "seal": anchor_seal, "candidates": None, "match": None, "detail": None}
    if response is None:
        reason = NO_VERIFIER if failure is None else RESOLVER_ERROR
        return _result((UNVERIFIABLE, reason), (UNVERIFIABLE, "source_not_verified"), (UNVERIFIABLE, reason), speaker=None, **base)
    if response["session"] == "unknown":
        return _result((UNVERIFIABLE, "session_unavailable"), (UNVERIFIABLE, "source_not_verified"), (UNVERIFIABLE, "session_unavailable"), speaker=None, **base)
    seal, found, speaker = response["seal"], response["quote"], response["speaker"]
    if seal == "turn_missing":
        return _result((NOT_FOUND, "turn_purged"), (UNVERIFIABLE, "source_not_verified"), (UNVERIFIABLE, "turn_purged"), speaker=None, **base)
    quote = (VERIFIED, None) if found == "found" else (NOT_FOUND, "quote_absent")
    integrity = {"match": (VERIFIED, None), "mismatch": (NOT_FOUND, "seal_mismatch"), "unknown": (UNVERIFIABLE, "seal_unverifiable")}[seal]
    return _result((VERIFIED, None), quote, integrity, speaker=speaker, **base)


def is_conclusive_conversation(check: Mapping[str, Any]) -> bool:
    """README: the anchor goes to ``not_found``, or some check is ``not_found``, or the three are ``verified``.  ``pending``, ``no_verifier``,
    ``resolver_error``, ``session_unavailable`` and ``seal_unverifiable`` do not conclude (C25–C29); a verified break (C32) does."""
    states = (check.get("source"), check.get("quote"), check.get("integrity"))
    return check.get("resolution") == "not_found" or NOT_FOUND in states or all(state == VERIFIED for state in states)


def served(check: Mapping[str, Any]) -> dict[str, Any]:
    """What reading serves for a stored conversation result: the three checks and what the resolver said, with its date.  The
    anchor as served is the stored one with this ``resolution``, ``turn_id`` and ``seal`` applied (nothing stored changes)."""
    keys = ("source", "source_reason", "quote", "quote_reason", "integrity", "integrity_reason", "match", "freshness", "reason", "resolution",
            "turn_id", "seal", "speaker", "candidates", "detail", "checked_at")
    out = {key: check[key] for key in keys}
    out["matched_text"] = None
    return out
