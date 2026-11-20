"""Records the drain builds for the operations of an entry other than a plain ``remember`` (ADR-0066).

``dispute``: a ``kind: fact`` ``add`` in ``facts`` with ADR-0063 D3's ``disputes`` object and a top-level
``verdict``; it is never a ``state``, so it never touches a slot head.  ``anchor_resolution``: an annotation in
``events`` that the read view applies (§6bis).  Pure over a snapshot; nothing here reads Git.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .anchor_checks import validate_annotation
from .anchors import AnchorRejected
from .anchors_conversation import validate_resolution
from . import directive
from .audience import ScopeError, scope_row_fields
from .canonical import digest_json
from .disputes import RememberOp, TargetResolution, record_id
from .inbox_anchors import record_fields, stored_anchors
from .store import STREAMS
from .vigency import is_active
from .write_policy import WritePolicyError


SCOPE_ROW_KEYS = ("subject", "audience", "valid_until", "valid_until_input", "until_revoked", "revokes")


def _find(snapshot: Any, target_id: str) -> list[tuple[str, Mapping[str, Any]]]:
    return [
        (stream, row)
        for stream in STREAMS
        for row in snapshot.raw_records[stream]
        if str(row.get("id", "")) == target_id
    ]


def build_dispute_op(snapshot: Any, envelope: Mapping[str, Any], data: Mapping[str, Any]) -> RememberOp:
    """The dispute record of ``data`` (an entry): the target stays vigent, nothing is superseded."""

    target_id = data["target_id"]
    found = _find(snapshot, target_id)
    if not found:
        raise WritePolicyError("dispute_target_missing", "target_missing")
    if len(found) > 1:
        raise WritePolicyError("remember_target_ambiguous", ",".join(stream for stream, _ in found))
    stream, raw = found[0]
    projected = next((r for r in snapshot.records[stream] if str(r.get("id", "")) == target_id), None)
    if projected is None or not is_active(projected):
        raise WritePolicyError("dispute_target_missing", "target_not_vigente")
    target = TargetResolution(stream, target_id, False, digest_json(raw))
    record: dict[str, Any] = {
        "id": record_id("facts", envelope["idempotency_key"]),
        "text": data["text"],
        "an_kla_envelope": deepcopy(dict(envelope)),
        "disputes": target.disputes(),
        **record_fields(data),
    }
    return RememberOp("facts", "add", record)


def build_resolution_op(snapshot: Any, envelope: Mapping[str, Any], data: Mapping[str, Any]) -> RememberOp:
    """The annotation record of an ``anchor_resolution`` entry, after the invariants of §6bis."""

    resolution = data["anchor_resolution"]
    target = resolution.get("target") if isinstance(resolution, Mapping) else None
    stream = target.get("stream") if isinstance(target, Mapping) else None
    rows = [r for r in snapshot.raw_records.get(stream, []) if str(r.get("id", "")) == target.get("record_id")] if stream in STREAMS else []
    try:
        validate_resolution(resolution, rows[0] if len(rows) == 1 else None)
    except AnchorRejected as refused:
        raise WritePolicyError(refused.code, "target_invalid") from None
    record = {
        "id": record_id("events", envelope["idempotency_key"]),
        "kind": "anchor_resolution",
        "anchor_resolution": deepcopy(dict(resolution)),
        "an_kla_envelope": deepcopy(dict(envelope)),
    }
    return RememberOp("events", "add", record)


def build_check_op(snapshot: Any, envelope: Mapping[str, Any], data: Mapping[str, Any]) -> RememberOp:
    """The annotation record of an ``anchor_check`` entry (ADR-0071 §5), after its invariants: the target exists in the
    snapshot and is vigent, each ``index`` is a ``document`` anchor of it with that ``quote_sha256``, each result has its form."""

    annotation = data["anchor_check"]
    ref = annotation.get("target") if isinstance(annotation, Mapping) else None
    stream = ref.get("stream") if isinstance(ref, Mapping) else None
    rows = [r for r in snapshot.records.get(stream, []) if str(r.get("id", "")) == ref.get("record_id")] if stream in STREAMS else []
    try:
        validate_annotation(annotation, rows[0] if len(rows) == 1 and is_active(rows[0]) else None)
    except AnchorRejected as refused:
        raise WritePolicyError(refused.code, "target_invalid") from None
    record = {
        "id": record_id("events", envelope["idempotency_key"]),
        "kind": "anchor_check",
        "anchor_check": deepcopy(dict(annotation)),
        "an_kla_envelope": deepcopy(dict(envelope)),
    }
    return RememberOp("events", "add", record)


def intent_mismatch(row: Mapping[str, Any], data: Mapping[str, Any]) -> str | None:
    """Why a record with the same key and text is not the same intention as the entry, if it is not.

    The anchors (and a dispute's verdict) are part of the intention: reusing an explicit key with others is a
    collision, not a retry (``idempotency_key_other_anchors``).
    """

    if (row.get("anchors") or None) != (stored_anchors(data.get("anchors")) or None):
        return "idempotency_key_other_anchors"
    if row.get("verdict") != data.get("verdict"):
        return "idempotency_key_other_verdict"
    scope = scope_row_fields(data)  # ADR-0069 §1: the scope and the validity are part of the intention too
    if any(row.get(key) != scope.get(key) for key in SCOPE_ROW_KEYS):
        return "idempotency_key_other_scope"
    return None


def check_directive_target(data: Mapping[str, Any], row: Mapping[str, Any] | None) -> None:
    """ADR-0069 §3: a directive replaces or revokes a directive of the same ``subject`` (a revocation, of its audience too)."""

    try:
        if row is None or not directive.is_directive(row):
            raise WritePolicyError("remember_kind_mismatch", "kind_explicit")
        directive.check_target(data, row)
    except ScopeError as refused:
        raise WritePolicyError(refused.code, refused.hint) from None


def target_exists(store: Any, target_id: str) -> bool:
    """Whether ``target_id`` is in the current revision (checked at enqueue, again by the drain)."""

    return bool(_find(store.snapshot(), target_id))
