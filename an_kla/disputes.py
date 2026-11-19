"""Dispute of a foreign fact instead of silencing it (ADR-0063 D3).

Pure functions over a store snapshot and the current writer's envelope
(:mod:`an_kla.identity_c0`).  ``remember`` supersedes the target when the
writer owns it and otherwise adds a record that points at it, so an agent never
deactivates another agent's fact by mistake.  Nothing here reads or writes the
store or the clock; the caller resolves under ``write_lock`` against the
snapshot of ``CURRENT`` it is about to commit on.

Nothing calls this from a write command yet: ``disputes list`` (read-only) is
the only entry point.  ``remember`` and the inbox drain are later phases.  The
envelope is an assertion by the emitter: "own" only chooses between superseding
and disputing, it never grants write permission.
"""

from __future__ import annotations

from copy import deepcopy
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .canonical import digest_json
from .identity_c0 import NAME_SENTINEL, validate_envelope
from .record_text import record_text
from .store import PREFIXES, STREAMS
from .vigency import is_active
from .write_policy import (
    WritePolicyError,
    build_write_plan,
    emit_write_authority_template,
    evaluate_write,
)

DISPUTES_LIST_SCHEMA = "an-kla/disputes-list-v1"
# ``--kind`` to the stream that holds it (ADR-0063 D1 "Orden": ``fact|decision|state``;
# not the ``fact|event|episode`` of ``refutations``).  ``kind`` arrives validated from
# the enqueue; a value outside D1 is never a "kind invalid" here, it matches no stream.
# ``events`` has no kind (``remember`` never writes it), so a target there never
# matches one (``remember_kind_mismatch``).
KIND_STREAMS = {"fact": "facts", "decision": "facts", "state": "episodes"}
_BATCH_SCHEMA = "an-kla/write-proposal-v2"
_PROPOSAL_SCHEMA = "an-kla/write-proposal-v1"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


@dataclass(frozen=True)
class TargetResolution:
    """Where a ``--supersedes`` target lives and what to do about it.

    ``own`` selects ``supersede`` (the target becomes ``sustituida``); otherwise
    the record is an ``add`` carrying ``disputes``.  ``target_record_sha256`` is
    the digest of the canonical record BEFORE overlays (``snapshot.raw_records``,
    the ADR-0026 selector), never of ``snapshot.records``.
    """

    stream: str
    target_id: str
    own: bool
    target_record_sha256: str

    def disputes(self) -> dict[str, str]:
        return {
            "stream": self.stream,
            "target_id": self.target_id,
            "target_record_sha256": self.target_record_sha256,
        }


@dataclass(frozen=True)
class RememberOp:
    """One record of a ``remember`` and the operation that commits it."""

    stream: str
    operation: str
    record: dict[str, Any]
    supersedes: str | None = None
    # ADR-0065: a ``state`` retiring the head of its slot says whom (``retired``) and which other vigent
    # states stay in conflict (``conflict_remaining``); both stay ``None`` for every other op.
    retired: dict[str, Any] | None = None
    conflict_remaining: list[str] | None = None

    def result_fields(self) -> dict[str, Any]:
        """Keys ``remember-result-v1`` adds for the target: ``disputed`` or ``superseded`` (+ ``retired``)."""

        if self.supersedes is not None:
            fields: dict[str, Any] = {"superseded": self.supersedes}
            if self.retired is not None:
                fields["retired"] = deepcopy(self.retired)
            if self.conflict_remaining:
                fields["conflict_remaining"] = list(self.conflict_remaining)
            return fields
        disputes = self.record.get("disputes")
        return {"disputed": deepcopy(disputes)} if disputes is not None else {}


def _writer_key(envelope: Mapping[str, Any] | None) -> tuple[str, str] | None:
    """``(repo.id, agent.name)`` of an envelope, or ``None`` without a usable writer.

    Both must be non-empty strings: two malformed envelopes never compare equal.
    """

    if not isinstance(envelope, Mapping):
        return None
    writer = envelope.get("writer")
    if not isinstance(writer, Mapping):
        return None
    repo, agent = writer.get("repo"), writer.get("agent")
    if not isinstance(repo, Mapping) or not isinstance(agent, Mapping):
        return None
    repo_id, name = repo.get("id"), agent.get("name")
    if not (isinstance(repo_id, str) and repo_id and isinstance(name, str) and name):
        return None
    return repo_id, name


def is_own(target_record: Mapping[str, Any], envelope: Mapping[str, Any]) -> bool:
    """True when the writer of ``envelope`` owns ``target_record`` (D3).

    The identity unit is the agent name, not the session.  A target without
    envelope (legacy) and any ``sin-nombre`` writer, on either side, are foreign.
    """

    current = _writer_key(envelope)
    target = _writer_key(target_record.get("an_kla_envelope"))
    if current is None or target is None:
        return False
    return current == target and current[1] != NAME_SENTINEL


def resolve_supersede_target(
    snapshot: Any,
    target_id: str,
    *,
    kind: str,
    kind_explicit: bool,
    envelope: Mapping[str, Any],
) -> TargetResolution:
    """Resolve ``--supersedes <target_id>`` against ``snapshot`` (D3).

    Raises ``WritePolicyError`` with ``invalid_supersede_target`` (absent or not
    vigente), ``remember_target_ambiguous`` (present in more than one stream) or
    ``remember_kind_mismatch`` (the stream of ``kind`` is not the target's).
    ``kind`` arrives resolved; ``kind_explicit`` only names the cause in the
    mismatch detail, because with it false the enqueue already took the target's
    kind and a mismatch is not expected.  ``envelope`` is the current writer's.
    """

    found = [
        stream
        for stream in STREAMS
        if any(str(row.get("id", "")) == target_id for row in snapshot.raw_records[stream])
    ]
    if not found:
        raise WritePolicyError("invalid_supersede_target", "target_missing")
    if len(found) > 1:
        raise WritePolicyError("remember_target_ambiguous", ",".join(found))
    stream = found[0]
    raw = next(
        row for row in snapshot.raw_records[stream] if str(row.get("id", "")) == target_id
    )
    # Vigency is read from the overlaid row found by id (as ``supersede.py``); the
    # digest, from the raw one.  No positional pairing between the two.
    projected = next(
        (row for row in snapshot.records[stream] if str(row.get("id", "")) == target_id),
        None,
    )
    if projected is None or not is_active(projected):
        raise WritePolicyError("invalid_supersede_target", "target_not_vigente")
    if KIND_STREAMS.get(kind) != stream:
        raise WritePolicyError(
            "remember_kind_mismatch", "kind_explicit" if kind_explicit else "kind_derived"
        )
    return TargetResolution(
        stream=stream,
        target_id=target_id,
        own=is_own(raw, envelope),
        target_record_sha256=digest_json(raw),
    )


def record_id(stream: str, idempotency_key: str) -> str:
    """``<prefix>-r-<24 hex of the key>`` (D1 "Idempotencia").

    ``idempotency_key`` must be ``sha256:`` plus 64 hex; anything else raises
    ``ValueError("invalid_idempotency_key")`` instead of collapsing ids.
    """

    if not isinstance(idempotency_key, str) or not _DIGEST.fullmatch(idempotency_key):
        raise ValueError("invalid_idempotency_key")
    return f"{PREFIXES[stream]}-r-{idempotency_key[len('sha256:'):][:24]}"


def build_remember_op(
    envelope: Mapping[str, Any],
    text: str,
    kind: str,
    target: TargetResolution | None = None,
) -> RememberOp:
    """The record ``remember`` writes and the operation that commits it.

    ``{"id", "text", "an_kla_envelope"}``, plus ``disputes`` for a foreign
    target.  Own target: ``supersede``.  Foreign target: ``add``, which writes
    neither ``supersedes_map`` nor ``refutations_map``.  Without target the
    stream is the one of ``kind``.

    ``target`` must come from :func:`resolve_supersede_target`, which already
    checked ``kind`` against the target's stream: this does not repeat it.  An
    invalid envelope raises ``WritePolicyError("invalid_record_envelope", <reasons>)``.
    """

    problems = validate_envelope(envelope)
    if problems:
        raise WritePolicyError("invalid_record_envelope", ",".join(problems))
    if target is None:
        stream = KIND_STREAMS.get(kind)
        if stream is None:
            raise ValueError("invalid_remember_kind")
    else:
        stream = target.stream
    record: dict[str, Any] = {
        "id": record_id(stream, envelope["idempotency_key"]),
        "text": text,
        "an_kla_envelope": deepcopy(dict(envelope)),
    }
    if target is not None and not target.own:
        record["disputes"] = target.disputes()
    if target is not None and target.own:
        return RememberOp(stream, "supersede", record, target.target_id)
    return RememberOp(stream, "add", record)


def resolve_remember(
    snapshot: Any,
    *,
    envelope: Mapping[str, Any],
    text: str,
    kind: str,
    kind_explicit: bool,
    target_id: str | None,
) -> RememberOp:
    """Resolve the optional target and build the op, in one call."""

    target = (
        None
        if target_id is None
        else resolve_supersede_target(
            snapshot, target_id, kind=kind, kind_explicit=kind_explicit, envelope=envelope
        )
    )
    return build_remember_op(envelope, text, kind, target)


def duplicate_supersede_targets(ops: Sequence[RememberOp]) -> list[int]:
    """Positions of the ops whose supersede target an earlier op already took.

    For the drain's step 4: with ``ops`` oldest first, keep the oldest per target
    and send the listed ones to ``rejected/`` with ``supersedes:duplicate_target``.
    Disputes (``add``) never collide.  Pure, O(n).
    """

    seen: set[str] = set()
    repeated: list[int] = []
    for position, op in enumerate(ops):
        if op.supersedes is None:
            continue
        if op.supersedes in seen:
            repeated.append(position)
        else:
            seen.add(op.supersedes)
    return repeated


def build_remember_proposal(base_revision: str, ops: Sequence[RememberOp]) -> dict[str, Any]:
    """``write-proposal-v1`` for one op, ``write-proposal-v2`` for a homogeneous batch.

    The batch is homogeneous in stream and operation (ADR-0054), as the drain
    builds it.  ``summary`` is the ceiling of ``model_derived``.  Two ops with the same
    supersede target raise ``WritePolicyError("supersedes:duplicate_target")``: defense
    in depth, the drain isolates them first with :func:`duplicate_supersede_targets`.
    """

    if not ops:
        raise ValueError("remember_batch_empty")
    first = ops[0]
    if any((op.stream, op.operation) != (first.stream, first.operation) for op in ops):
        raise ValueError("remember_batch_not_homogeneous")
    if duplicate_supersede_targets(ops):
        raise WritePolicyError("supersedes:duplicate_target")
    proposal: dict[str, Any] = {
        "schema": _PROPOSAL_SCHEMA if len(ops) == 1 else _BATCH_SCHEMA,
        "base_revision": base_revision,
        "stream": first.stream,
        "operation": first.operation,
        "requested_representation": "summary",
        "lineage": {"derived_from_retrieval": False, "refs": []},
    }
    if len(ops) == 1:
        proposal["record"] = deepcopy(first.record)
        if first.operation == "supersede":
            proposal["supersedes"] = first.supersedes
    else:
        proposal["records"] = [deepcopy(op.record) for op in ops]
        if first.operation == "supersede":
            proposal["supersedes"] = {op.record["id"]: op.supersedes for op in ops}
    return proposal


def build_remember_plan(proposal: Mapping[str, Any]) -> dict[str, Any]:
    """Authority (``model_derived`` template), decision and plan of a proposal.

    Pure and side-effect free: the same functions ``plan-write`` uses.  The
    result carries what ``commit_write_plan`` wants: ``proposal``, ``authority``,
    ``decision`` and ``plan``.
    """

    authority = emit_write_authority_template(proposal)
    decision = evaluate_write(proposal, authority)
    plan = build_write_plan(proposal, authority, decision)
    return {
        "proposal": deepcopy(dict(proposal)),
        "authority": authority,
        "decision": decision,
        "plan": plan,
    }


def _valid_disputes(value: Any) -> bool:
    """Shape of the ``disputes`` object; anything else is not a dispute."""

    return (
        isinstance(value, Mapping)
        and set(value) == {"stream", "target_id", "target_record_sha256"}
        and value["stream"] in STREAMS
        and isinstance(value["target_id"], str)
        and bool(value["target_id"])
        and isinstance(value["target_record_sha256"], str)
        and _DIGEST.fullmatch(value["target_record_sha256"]) is not None
    )


def _target_active(snapshot: Any, stream: str, target_id: str) -> bool | None:
    for row in snapshot.records[stream]:
        if str(row.get("id", "")) == target_id:
            return is_active(row)
    return None


def list_disputes(snapshot: Any, *, target: str | None = None) -> dict[str, Any]:
    """Vigent dispute records of ``snapshot`` (``disputes-list-v1``), read-only.

    A dispute is a vigent record with a well-formed ``disputes`` object; ``target`` keeps
    those aimed at that id.  ``target.active`` is ``None`` when the target is
    not in the snapshot.  ``writer`` is the envelope writer when the envelope is
    valid, else ``None``.  Everything is untrusted memory data.  An empty ``target``
    raises ``ValueError("invalid_disputes_target")`` (the schema requires ``minLength: 1``).
    """

    if target == "":
        raise ValueError("invalid_disputes_target")
    items: list[dict[str, Any]] = []
    for stream in STREAMS:
        for row in snapshot.records[stream]:
            disputes = row.get("disputes")
            if not _valid_disputes(disputes) or not is_active(row):
                continue
            if target is not None and disputes["target_id"] != target:
                continue
            envelope = row.get("an_kla_envelope")
            valid = isinstance(envelope, dict) and not validate_envelope(envelope)
            items.append(
                {
                    "id": str(row.get("id", "")),
                    "stream": stream,
                    "text": record_text(row),
                    "target": {
                        "stream": disputes["stream"],
                        "id": disputes["target_id"],
                        "record_sha256": disputes["target_record_sha256"],
                        "active": _target_active(
                            snapshot, disputes["stream"], disputes["target_id"]
                        ),
                    },
                    "writer": deepcopy(envelope["writer"]) if valid else None,
                    "enqueued_at": envelope["enqueued_at"] if valid else None,
                    **({"verdict": row["verdict"]} if row.get("verdict") in ("contradicted", "insufficient") else {}),
                }
            )
    return {
        "schema": DISPUTES_LIST_SCHEMA,
        "untrusted_memory_data": True,
        "revision": snapshot.revision_id,
        "target": target,
        "disputes": items,
    }


__all__ = [
    "DISPUTES_LIST_SCHEMA",
    "KIND_STREAMS",
    "RememberOp",
    "TargetResolution",
    "build_remember_op",
    "build_remember_plan",
    "build_remember_proposal",
    "duplicate_supersede_targets",
    "is_own",
    "list_disputes",
    "record_id",
    "resolve_remember",
    "resolve_supersede_target",
]
