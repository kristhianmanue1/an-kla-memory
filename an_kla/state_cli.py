"""Despacho del CLI de ``state show`` e ``history`` (ADR-0065): la salida son bytes ya serializados."""

from __future__ import annotations

from typing import Any

from .anchors_read import AnchorServer
from .history import history
from .state_show import render, state_show
from .store import StoreError


def run(store: Any, args: Any) -> bytes:
    """``state show`` o ``history`` según ``args.command``; JSON canónico con salto de línea final (el presupuesto lo mide)."""

    if args.command == "state":
        return render(state_show(
            store, slot=args.slot, all_slots=args.all_slots, scope=args.scope, budget=args.budget,
            anchor_limit=args.anchor_limit,
        ))
    try:
        snapshot = store.snapshot()
    except OSError:  # nunca el mensaje crudo del SO (lleva la ruta)
        raise StoreError("storage_io_failed") from None
    with AnchorServer(store, snapshot, args.anchor_limit) as server:
        return render(history(snapshot, args.id, limit=args.limit, budget=args.budget, anchors=server))
