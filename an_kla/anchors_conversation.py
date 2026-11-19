"""``conversation`` anchors: the view of their resolution and their checks (C3; ADR-0066 §6bis).

An anchor is born ``resolution: pending`` and an append-only store never mutates
it.  The resolver of C2 (not part of this release) will write an *annotation*
record (``an-kla/anchor-resolution-v1``); the read view applies the latest one of
each anchor.  Without annotations and without a verifier every conversation
anchor stays ``pending``, which is a valid anchor.  Reading never starts a
resolver.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol

from .anchors import AnchorRejected
from .anchors_freshness import UNVERIFIABLE, VERIFIED, anchor_result
from .anchors_search import find_quote

RESOLUTION_SCHEMA = "an-kla/anchor-resolution-v1"
_SOURCE_NOT_VERIFIED = (UNVERIFIABLE, "source_not_verified")


@dataclass(frozen=True)
class TurnView:
    """What a verifier says about one sealed turn: ``ok``, ``purged`` or ``missing``."""

    state: str
    text: str | None = None
    raw: bool = True
    seal_ok: bool = True


class ConversationVerifier(Protocol):
    """Reads a turn of a session.  An-kla ships none; a test or the C2 resolver may."""

    def turn(self, session: str, turn_id: str) -> TurnView: ...


def resolution_invalid() -> AnchorRejected:
    return AnchorRejected("anchor_resolution_invalid")


def validate_resolution(
    resolution: Mapping[str, Any], target_record: Mapping[str, Any] | None
) -> None:
    """Invariants of §6bis, checked on draining; ``anchor_resolution_invalid`` otherwise."""
    if not isinstance(resolution, Mapping) or resolution.get("schema") != RESOLUTION_SCHEMA:
        raise resolution_invalid()
    target = resolution.get("target")
    if not isinstance(target, Mapping) or target_record is None:
        raise resolution_invalid()
    index = target.get("anchor_index")
    anchors = target_record.get("anchors") or []
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(anchors):
        raise resolution_invalid()
    anchor = anchors[index]
    if anchor.get("source", {}).get("kind") != "conversation":
        raise resolution_invalid()
    if anchor.get("quote_sha256") != target.get("quote_sha256"):
        raise resolution_invalid()
    turn_id, seal = resolution.get("turn_id"), resolution.get("seal")
    kind = resolution.get("resolution")
    if kind == "resolved":
        if not (isinstance(turn_id, str) and turn_id and isinstance(seal, str) and seal):
            raise resolution_invalid()
    elif kind == "not_found":
        if turn_id is not None or seal is not None:
            raise resolution_invalid()
    else:
        raise resolution_invalid()


def apply_resolution(
    anchor: Mapping[str, Any],
    record_id: str,
    index: int,
    annotations: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """The anchor as read: the latest annotation (``enqueued_at``, then id) wins."""
    latest: tuple[tuple[str, str], Mapping[str, Any]] | None = None
    for note in annotations:
        res = note.get("anchor_resolution") or {}
        target = res.get("target") or {}
        if (
            target.get("record_id") == record_id
            and target.get("anchor_index") == index
            and target.get("quote_sha256") == anchor.get("quote_sha256")
        ):
            key = (str(note.get("enqueued_at") or ""), str(note.get("id") or ""))
            if latest is None or key > latest[0]:
                latest = (key, res)
    view = {**anchor, "source": dict(anchor["source"])}
    if latest is not None:
        res = latest[1]
        view["source"].update(
            resolution=res["resolution"], turn_id=res.get("turn_id"), seal=res.get("seal")
        )
    return view


def check_conversation(
    anchor: Mapping[str, Any], verifier: ConversationVerifier | None = None
) -> dict[str, Any]:
    """The three checks of a conversation anchor as read (``anchor`` is already the view)."""
    source = anchor["source"]
    resolution = source.get("resolution", "pending")
    extra = {"resolution": resolution, "turn_id": source.get("turn_id")}
    if resolution == "pending":
        state = (UNVERIFIABLE, "resolution_pending")
        out = anchor_result(
            "conversation", state, _SOURCE_NOT_VERIFIED, state, resolution=resolution
        )
        return out | extra
    if resolution == "not_found":
        state = (UNVERIFIABLE, "session_lacks_quote")
        out = anchor_result(
            "conversation", state, _SOURCE_NOT_VERIFIED, state, resolution=resolution
        )
        return out | extra
    turn_id = source.get("turn_id")
    if turn_id is None:
        view = TurnView("missing")
    elif verifier is None:
        state = (UNVERIFIABLE, "no_verifier")
        return anchor_result(
            "conversation", state, _SOURCE_NOT_VERIFIED, state, resolution=resolution
        ) | extra
    else:
        view = verifier.turn(source["session"], turn_id)
    if view.state != "ok" or view.text is None:
        gone = ("not_found", "turn_purged")
        return anchor_result(
            "conversation", gone, _SOURCE_NOT_VERIFIED, (UNVERIFIABLE, "turn_purged"),
            resolution=resolution,
        ) | extra
    match, matched = find_quote(anchor["quote"], view.text)
    quote = (VERIFIED, None) if match else ("not_found", "quote_absent")
    if not view.raw:
        integrity = (UNVERIFIABLE, "raw_lost")
    elif not view.seal_ok:
        integrity = ("not_found", "seal_mismatch")
    else:
        integrity = (VERIFIED, None)
    return anchor_result(
        "conversation", (VERIFIED, None), quote, integrity,
        match=match, matched_text=matched, resolution=resolution,
    ) | extra
