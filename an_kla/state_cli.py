"""Despacho del CLI de ``state show``, ``history`` y ``list`` (ADR-0065, ADR-0067): la salida son bytes ya serializados."""

from __future__ import annotations

from typing import Any

from .anchors_read import AnchorServer
from .history import history
from .listing import list_records
from .scope_cli import reader_from_args
from .state_show import StateReadError, render, state_show
from .store import StoreError

SUBJECT_HINT = "un repo.id de C0 canónico (host[:puerto]/ruta, local:|remoto:<16 hex>)"


def run(store: Any, args: Any) -> bytes:
    """``state show``, ``history`` o ``list`` según ``args.command``; JSON canónico con salto de línea final (el presupuesto lo mide)."""

    if args.command == "list":
        try:
            snapshot = store.snapshot()
        except OSError:
            raise StoreError("storage_io_failed") from None
        return render(list_records(
            snapshot, streams=args.streams, status=args.status, kind=args.kind, slot=args.slot, limit=args.limit,
            budget=args.budget, after=args.after, text=args.text, store=store,
            reader=reader_from_args(store, args, lambda: StateReadError("list_subject_invalid", SUBJECT_HINT)),
        ))
    if args.command == "state":
        return render(state_show(
            store, slot=args.slot, all_slots=args.all_slots, scope=args.scope, budget=args.budget,
            anchor_limit=args.anchor_limit,
            reader=reader_from_args(store, args, lambda: StateReadError("state_subject_invalid", SUBJECT_HINT)),
        ))
    try:
        snapshot = store.snapshot()
    except OSError:  # nunca el mensaje crudo del SO (lleva la ruta)
        raise StoreError("storage_io_failed") from None
    with AnchorServer(store, snapshot, args.anchor_limit) as server:
        return render(history(snapshot, args.id, limit=args.limit, budget=args.budget, anchors=server, store=store))
