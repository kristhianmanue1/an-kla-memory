"""Casilla de un ``state`` (ADR-0065 §1-3): quién es la cabeza, qué jubila un ``state`` nuevo y cuándo es un reintento.

Funciones puras sobre un snapshot: no leen ni escriben el store. El vaciado
(:mod:`an_kla.inbox_drain`) las llama bajo ``write_lock`` contra el snapshot de ``CURRENT`` que va a
comprometer; ``state show`` (:mod:`an_kla.state_show`) y ``history`` las usan para leer.

Una casilla es el par (``repo.id`` del sobre, ``slot``), no el escritor. Pertenecen a ella los registros
de ``episodes`` con sobre válido de ``kind: state`` y ``slot`` bien formado (sin ``slot`` = ``main``).
Un ``state`` legado sin sobre, o con sobre inválido, no pertenece a ninguna casilla.
"""

from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from .disputes import RememberOp
from .identity_c0 import DEFAULT_SLOT, SLOT_PATTERN, validate_envelope
from .reader_gate import ReaderGateError
from .store import STREAMS
from .store_errors import StoreError
from .vigency import is_active
from .write_policy import WritePolicyError

STATE_STREAM = "episodes"
FACT_STREAM = "facts"


@dataclass(frozen=True)
class StateRow:
    """Un registro ``state`` de una casilla, con lo que el orden y la idempotencia necesitan."""

    id: str
    slot: str
    repo_id: str
    agent: str
    enqueued_at: str
    key: str
    text: Any
    active: bool
    row: Mapping[str, Any]

    @property
    def order(self) -> tuple[str, str]:
        """Orden de cabeza: ``enqueued_at`` y después ``id`` (ADR-0065 §1)."""

        return self.enqueued_at, self.id

    @property
    def writer(self) -> Mapping[str, Any]:
        return self.row["an_kla_envelope"]["writer"]


def slot_of(row: Mapping[str, Any]) -> str | None:
    """Casilla declarada de un registro (``main`` si no lleva ``slot``) o ``None`` si está mal formada."""

    slot = row.get("slot", DEFAULT_SLOT)
    return slot if isinstance(slot, str) and SLOT_PATTERN.fullmatch(slot) else None


def target_slot(store: Any, target_id: str | None) -> str | None:
    """Casilla del ``state`` que es el target de un ``--supersedes`` (o ``None``): lectura sin candado, como ``resolve_kind``."""

    if target_id is None:
        return None
    try:
        rows = [r for r in store.snapshot().records.get(STATE_STREAM, []) if str(r.get("id", "")) == target_id]
    except (StoreError, ReaderGateError, OSError, ValueError, KeyError, AttributeError):
        return None
    return slot_of(rows[0]) if len(rows) == 1 else None


def as_state_row(row: Mapping[str, Any]) -> StateRow | None:
    """El registro como miembro de una casilla, o ``None`` si queda fuera de casilla (§1 «Fuera de casilla»)."""

    envelope = row.get("an_kla_envelope")
    if not isinstance(envelope, dict) or validate_envelope(envelope) or envelope.get("kind") != "state":
        return None
    slot = slot_of(row)
    if slot is None:
        return None
    writer = envelope["writer"]
    return StateRow(
        id=str(row.get("id", "")), slot=slot, repo_id=writer["repo"]["id"], agent=writer["agent"]["name"],
        enqueued_at=envelope["enqueued_at"], key=envelope["idempotency_key"], text=row.get("text"),
        active=is_active(row), row=row,
    )


def state_rows(snapshot: Any, *, repo_id: str | None = None) -> list[StateRow]:
    """Todos los ``state`` con casilla de la revisión (vigentes o no), de un repo si se pide, en orden de cabeza."""

    rows = [m for row in snapshot.records[STATE_STREAM] if (m := as_state_row(row)) is not None]
    if repo_id is not None:
        rows = [m for m in rows if m.repo_id == repo_id]
    return sorted(rows, key=lambda m: m.order)


def active_by_slot(rows: list[StateRow]) -> dict[str, list[StateRow]]:
    """Vigentes por casilla, cada lista en orden de cabeza (el último es la cabeza); casillas en orden de ``slot``."""

    grouped: dict[str, list[StateRow]] = {}
    for member in rows:
        if member.active:
            grouped.setdefault(member.slot, []).append(member)
    return {slot: grouped[slot] for slot in sorted(grouped)}


def superseded_by(snapshot: Any) -> dict[tuple[str, str], str]:
    """``(stream, id jubilado) -> id de quien lo jubiló``, de ``supersedes_map`` (nuevo → antiguo)."""

    result: dict[tuple[str, str], str] = {}
    for entry in snapshot.manifest.get("supersedes_map", []):
        if isinstance(entry, dict) and entry.get("stream") in STREAMS:
            target, by = entry.get("target_id"), entry.get("sustituida_por")
            if isinstance(target, str) and isinstance(by, str) and target and by:
                result[(entry["stream"], target)] = by
    return result


def state_record_id(key: str, retired_head: str | None) -> str:
    """``ep-r-`` + 24 hex de ``sha256(clave + ":" + (id de la cabeza jubilada o "none"))`` (§3)."""

    digest = hashlib.sha256(f"{key}:{retired_head or 'none'}".encode("utf-8")).hexdigest()
    return f"ep-r-{digest[:24]}"


@dataclass(frozen=True)
class StateAlready:
    """El ``state`` ya está comprometido: reintento de la última entrada del mismo escritor en la casilla."""

    record_id: str
    retired_by: str | None


def _check_target(snapshot: Any, target_id: str, repo_id: str, slot: str, head: StateRow | None) -> None:
    """Reglas de ``--supersedes`` para un ``state`` (§2). Lanza ``WritePolicyError``; si pasa, equivale a no pasarlo."""

    found = [s for s in STREAMS if any(str(r.get("id", "")) == target_id for r in snapshot.raw_records[s])]
    if not found:
        raise WritePolicyError("invalid_supersede_target", "target_missing")
    if len(found) > 1:
        raise WritePolicyError("remember_target_ambiguous", ",".join(found))
    stream = found[0]
    if stream == FACT_STREAM:
        raise WritePolicyError("remember_state_over_fact")
    if stream != STATE_STREAM:
        raise WritePolicyError("remember_kind_mismatch", "kind_explicit")
    projected = next(r for r in snapshot.records[stream] if str(r.get("id", "")) == target_id)
    if not is_active(projected):
        raise WritePolicyError("invalid_supersede_target", "target_not_vigente")
    member = as_state_row(projected)
    if member is None:
        raise WritePolicyError("remember_state_slot_mismatch", "target_without_slot")
    if member.repo_id != repo_id or member.slot != slot:
        raise WritePolicyError("remember_state_slot_mismatch", "other_slot")
    if head is None or member.id != head.id:
        raise WritePolicyError("remember_state_slot_mismatch", "target_not_head")


def resolve_state(
    snapshot: Any,
    *,
    envelope: Mapping[str, Any],
    text: str,
    key: str,
    slot: str,
    target_id: str | None,
    fields: Mapping[str, Any] | None = None,
) -> RememberOp | StateAlready:
    """Qué hace un ``state`` nuevo contra la casilla ``slot`` del repo del sobre (ADR-0065 §1-3).

    Devuelve :class:`StateAlready` si es el reintento de la última entrada del mismo escritor en la casilla;
    si no, la operación que lo escribe: ``add`` si la casilla no tiene cabeza, ``supersede`` de la cabeza si
    la tiene (``retired`` dice a quién; ``conflict_remaining``, qué otros vigentes quedan). Lanza
    ``WritePolicyError`` con ``remember_state_over_fact``, ``remember_state_slot_mismatch``,
    ``invalid_supersede_target``, ``remember_target_ambiguous``, ``remember_kind_mismatch`` o
    ``remember_id_collision``.
    """

    writer = envelope["writer"]
    repo_id, agent = writer["repo"]["id"], writer["agent"]["name"]
    members = [m for m in state_rows(snapshot, repo_id=repo_id) if m.slot == slot]
    actives = [m for m in members if m.active]
    head = actives[-1] if actives else None
    if target_id is not None and not any(
        str(r.get("id", "")) == target_id for s in STREAMS for r in snapshot.raw_records[s]
    ):
        raise WritePolicyError("invalid_supersede_target", "target_missing")
    mine = [m for m in members if m.agent == agent]
    last = mine[-1] if mine else None
    if last is not None and last.key == key:
        if last.text != text:
            raise WritePolicyError("remember_id_collision", "idempotency_key_other_payload")
        if (last.row.get("anchors") or None) != ((fields or {}).get("anchors") or None):  # ADR-0066 §2
            raise WritePolicyError("remember_id_collision", "idempotency_key_other_anchors")
        retired_by = None if last.active else superseded_by(snapshot).get((STATE_STREAM, last.id))
        return StateAlready(last.id, retired_by)
    if target_id is not None:
        _check_target(snapshot, target_id, repo_id, slot, head)
    new_id = state_record_id(key, head.id if head is not None else None)
    if any(str(r.get("id", "")) == new_id for r in snapshot.raw_records[STATE_STREAM]):
        raise WritePolicyError("remember_id_collision", "id_exists_in_snapshot")
    record: dict[str, Any] = {"id": new_id, "text": text, "an_kla_envelope": deepcopy(dict(envelope)), "slot": slot, **(fields or {})}
    if head is None:
        return RememberOp(STATE_STREAM, "add", record)
    retired = {"id": head.id, "writer": deepcopy(dict(head.writer)), "enqueued_at": head.enqueued_at}
    conflict = [m.id for m in actives[:-1]]
    return RememberOp(STATE_STREAM, "supersede", record, head.id, retired=retired, conflict_remaining=conflict)


__all__ = [
    "StateAlready", "StateRow", "active_by_slot", "as_state_row", "resolve_state", "slot_of", "state_record_id",
    "state_rows", "superseded_by", "target_slot",
]
