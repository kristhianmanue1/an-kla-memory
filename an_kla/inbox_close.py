"""Paso 0 del vaciado (ADR-0063 D1): reconciliar los lotes en vuelo y cerrar su journal.

Corre con ``write_lock`` tomado, antes de leer ``pending/``. Por cada marcador de
``inflight/`` (``<transaction_id>.json`` con ``{txid, base_revision, entries}``) pregunta
a ``inspect_transaction`` (sólo lectura) y sigue las tres ramas del ADR: ``committed is
True`` cierra el journal, repara la durabilidad y borra entradas y marcador (en ese
orden); ``committed is False`` borra sólo el marcador; ``committed is None`` borra el
marcador sólo si la transacción no dejó rastro y en cualquier otro caso aborta. Nada de
esto va a ``rejected/``. Los journals de otras órdenes no se tocan.
"""

from __future__ import annotations

import contextlib
import json
import os
import stat
from pathlib import Path
from typing import Any

from . import transactions as tx
from .canonical import canonical_json, digest_json
from .inbox import InboxError, inbox_paths, is_entry_name, is_marker_name
from .storage_primitives import fsync_directory
from .transaction_repair import repair_durability

AUDIT_INCOMPLETE = "inbox_audit_incomplete"
_MAX_MARKER_BYTES = 1024 * 1024


class DrainAbort(Exception):
    """El vaciado se detiene sin tocar marcador ni entradas; ``code`` es el ``drain_error``."""

    def __init__(self, code: str, *, unknown: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.unknown = unknown


# --- cierre del journal ------------------------------------------------------


def _usable_journal(store: Any, txid: str) -> dict[str, Any] | None:
    journal = tx._journal(store, txid)
    return None if journal is None or journal.get("corrupt") else dict(journal)


def _attempt_of(journal: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return tx.validate_attempt(journal.get("attempt"))
    except Exception:
        return None


def _completed_journal(store: Any, txid: str, candidate: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Journal existente con lo que le falte tomado del objeto inmutable de ``stages/``.

    Devuelve ``(journal, attempt)``. Si el journal falta, está corrupto o no trae un intento
    válido se parte de la evidencia de ``stages/``; sin ella no hay con qué cerrar.
    """

    journal = _usable_journal(store, txid) or {}
    attempt = _attempt_of(journal)
    stage = tx._stage_evidence(store, txid, candidate)
    if attempt is None:
        if stage is None:
            raise DrainAbort("transaction_evidence_missing_or_invalid")
        journal = {"stage": "candidate_prepared", "candidate_receipt": None, "current_receipt": None}
        attempt = tx.validate_attempt(stage["attempt"])
        journal["attempt"] = stage["attempt"]
    if not isinstance(journal.get("candidate"), str):
        journal["candidate"] = candidate
    if stage is not None:
        if not isinstance(journal.get("parent"), str):
            journal["parent"] = stage["parent"]
        if not isinstance(journal.get("stage_object"), str):
            journal["stage_object"] = digest_json(stage)
        if "write_policy" not in journal and "write_policy" in stage:
            journal["write_policy"] = stage["write_policy"]
    return journal, attempt


def close_committed_journal(store: Any, txid: str) -> dict[str, Any]:
    """Reescribe ``transactions/<txid>.json`` como ``committed`` con los campos de ``commit_locked``.

    Conserva ``parent``, ``candidate``, ``attempt``, ``stage_object`` y ``write_policy`` del
    journal existente (o los reconstruye de ``stages/``); enlaza ``observed_log`` escribiendo los
    ref-logs ``intent`` y ``observed_commit`` (direccionados por contenido: idempotente) y enlaza
    **sólo** los recibos que existen y validan, sin fabricar ninguno. Un segundo cierre es un no-op.
    """

    info = tx.inspect_transaction(store, txid)
    if info.get("committed") is not True:
        raise DrainAbort(f"transaction_{info.get('state')}")
    candidate = info["candidate_revision"]
    journal, attempt = _completed_journal(store, txid, candidate)
    if journal.get("stage") == "committed" and isinstance(journal.get("observed_log"), str):
        return {"closed": False, "reason": "already_committed"}
    parent = journal.get("parent") if isinstance(journal.get("parent"), str) else attempt.get("base_revision")
    for receipt_id in tx._receipt_ids(store, txid):
        for kind, field in (("candidate-data-durable", "candidate_receipt"), ("current-durable", "current_receipt")):
            linked = journal.get(field)
            if linked is not None and tx._valid_receipt(store, txid, linked, attempt, candidate, kind):
                continue
            if tx._valid_receipt(store, txid, receipt_id, attempt, candidate, kind):
                journal[field] = receipt_id
    journal["stage"] = "committed"
    if not isinstance(journal.get("observed_log"), str):
        intent_id = store._write_ref_log(
            {"schema": "an-kla/ref-log-v1", "kind": "intent", "transaction_id": txid,
             "parent": parent, "candidate": candidate}
        )
        journal["observed_log"] = store._write_ref_log(
            {"schema": "an-kla/ref-log-v1", "kind": "observed_commit", "transaction_id": txid,
             "parent": parent, "candidate": candidate, "intent": intent_id}
        )
    store._write_transaction(txid, journal)
    return {"closed": True}


def has_no_trace(store: Any, txid: str) -> bool:
    """«Sin rastro» (rama ``committed is None``): ni journal, ni manifiesto, ni ``transactions/<txid>/``.

    El journal ``prepared`` es lo primero que escribe ``commit_locked``: su ausencia prueba que
    no se escribió nada. Un journal ilegible cuenta como rastro.
    """

    if tx._journal(store, txid) is not None:
        return False
    if tx._manifest_candidates(store, txid):
        return False
    return not (Path(store.root) / "transactions" / txid).exists()


# --- marcadores --------------------------------------------------------------


def read_marker(store: Any, name: str) -> dict[str, Any]:
    """Lee y valida un marcador (``regular``, acotado, ``txid`` = nombre, entradas con nombre de entrada).

    Un marcador que no se puede leer o validar aborta el vaciado conservándolo todo: no hay
    evidencia de qué lote era y no se adivina.
    """

    path = inbox_paths(store).inflight / name
    try:
        info = os.lstat(path)
    except OSError:
        raise DrainAbort("inflight_marker_unreadable") from None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise DrainAbort("inflight_marker_unsafe")
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        raise DrainAbort("inflight_marker_unreadable") from None
    try:
        raw = os.read(fd, _MAX_MARKER_BYTES + 1)
    finally:
        os.close(fd)
    try:
        data = json.loads(raw) if len(raw) <= _MAX_MARKER_BYTES else None
    except (ValueError, UnicodeError):
        data = None
    txid = name[: -len(".json")]
    entries = data.get("entries") if isinstance(data, dict) else None
    if (
        not isinstance(data, dict)
        or data.get("txid") != txid
        or not isinstance(data.get("base_revision"), str)
        or not isinstance(entries, list)
        or not all(isinstance(item, str) and is_entry_name(item) for item in entries)
    ):
        raise DrainAbort("inflight_marker_invalid")
    return data


def write_marker(store: Any, txid: str, base_revision: str, entries: list[str]) -> Path:
    """Escribe con fsync ``inflight/<txid>.json``; debe ir antes del commit."""

    marker = inbox_paths(store).inflight / f"{txid}.json"
    store._atomic_write(marker, canonical_json({"txid": txid, "base_revision": base_revision, "entries": entries}))
    return marker


def delete_marker(store: Any, txid: str) -> None:
    inflight = inbox_paths(store).inflight
    with contextlib.suppress(FileNotFoundError):
        os.unlink(inflight / f"{txid}.json")
    fsync_directory(inflight)


def delete_entries(store: Any, names: list[str]) -> None:
    """Borra de ``pending/`` las entradas de un lote y hace fsync del directorio."""

    pending = inbox_paths(store).pending
    for name in names:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(pending / name)
    fsync_directory(pending)


# --- reconciliación ----------------------------------------------------------


def settle_committed(store: Any, txid: str, entries: list[str], warnings: list[str]) -> dict[str, Any]:
    """Rama ``committed is True``: cierra, repara, comprueba el predicado y borra entradas y marcador."""

    closed = close_committed_journal(store, txid)
    if tx.inspect_transaction(store, txid).get("durability_state") == "incomplete":
        try:
            repair_durability(store, txid)
        except Exception:
            raise DrainAbort("transaction_durability_repair_failed") from None
    final = tx.inspect_transaction(store, txid)
    if final.get("committed") is not True or final.get("durability_state") != "complete":
        raise DrainAbort(f"transaction_{final.get('state')}")
    if final.get("audit_state") != "complete" and AUDIT_INCOMPLETE not in warnings:
        warnings.append(AUDIT_INCOMPLETE)
    delete_entries(store, entries)
    delete_marker(store, txid)
    return {"txid": txid, "branch": "committed", "journal_closed": bool(closed["closed"])}


def reconcile_markers(store: Any, warnings: list[str]) -> list[dict[str, Any]]:
    """Paso 0 completo; devuelve un resumen por marcador o lanza ``DrainAbort``."""

    try:
        names = sorted(name for name in os.listdir(inbox_paths(store).inflight) if is_marker_name(name))
    except FileNotFoundError:
        return []
    except OSError:
        raise InboxError("inbox_unavailable") from None
    summary: list[dict[str, Any]] = []
    for name in names:
        marker = read_marker(store, name)
        txid = marker["txid"]
        info = tx.inspect_transaction(store, txid)
        committed = info.get("committed")
        if committed is True:
            summary.append(settle_committed(store, txid, marker["entries"], warnings))
        elif committed is False:
            delete_marker(store, txid)
            summary.append({"txid": txid, "branch": "not_committed"})
        elif has_no_trace(store, txid):
            delete_marker(store, txid)
            summary.append({"txid": txid, "branch": "no_trace"})
        else:
            raise DrainAbort(f"transaction_{info.get('operation_error_code') or info.get('state')}", unknown=True)
    return summary


__all__ = [
    "AUDIT_INCOMPLETE", "DrainAbort", "close_committed_journal", "delete_entries", "delete_marker",
    "has_no_trace", "read_marker", "reconcile_markers", "settle_committed", "write_marker",
]
