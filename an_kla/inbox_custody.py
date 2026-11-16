"""Custodia de la bandeja para ``export``, ``--seal`` y ``relocate commit`` (ADR-0063 D1, fase B4).

Separado de ``inbox.py`` por tamaño. Sólo usa las piezas públicas de la bandeja: el candado, las
definiciones de «vacío» y la inspección de la raíz.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
import stat
from typing import Any, Iterator

from . import inbox, lock_order

CUSTODY_LOCK_WAIT_SECONDS = 2.0


@contextlib.contextmanager
def custody_guard(store: Any, *, wait_seconds: float | None = None) -> Iterator[None]:
    """Candado exclusivo de bandeja para ``export``, ``--seal`` y ``relocate commit`` (D1 «no es estado durable», punto 2).

    Se toma al principio de la orden, antes de crear nada y de ``identity_lock``, y se suelta
    al final. Exige ``pending/`` e ``inflight/`` vacíos (``pending/`` primero): si no, falla con
    ``inbox_pending`` o ``inbox_inflight`` (pista ``inbox drain``). Ocupado, ``inbox_busy``.
    Sin ``memory/inbox/`` no hace nada: no crea la bandeja ni el ``.lock`` y la orden recorre
    el camino de hoy. Con una raíz enlazada tampoco: la orden la rechaza como siempre
    (``export_unsafe_link``) al recorrer el ancla; con un archivo (no directorio ni enlace)
    exactamente en ``memory/inbox`` falla con ``inbox_unsafe_path`` (R2-05). Nunca crea la
    estructura (R1-02): con la raíz presente sólo crea el ``.lock`` si falta, y un
    subdirectorio ausente cuenta como vacío.
    """

    state = inbox.root_state(store)
    if state == "unsafe" and _is_foreign_file(inbox.inbox_paths(store).root):
        raise inbox.InboxError("inbox_unsafe_path")  # R2-05: algo que no es directorio ni enlace en `memory/inbox`
    if state != "present":
        lock_order.require_inbox_allowed(store)
        yield
        return
    wait = CUSTODY_LOCK_WAIT_SECONDS if wait_seconds is None else wait_seconds
    with inbox.inbox_lock(store, exclusive=True, wait_seconds=wait, layout=False):
        require_empty(store)
        yield


def _is_foreign_file(root: Path) -> bool:
    try:
        mode = os.lstat(root).st_mode
    except OSError:
        return False
    return not stat.S_ISDIR(mode) and not stat.S_ISLNK(mode)


def require_empty(store: Any) -> None:
    """Falla con ``inbox_pending`` o ``inbox_inflight`` si la bandeja tiene entradas o marcadores.

    Sólo lectura: sin bandeja (o raíz insegura) no hay nada que comprobar y no crea nada. La
    repite ``relocate commit`` bajo ``identity_lock``: ``enqueue`` publica bajo ese mismo
    candado, así que toda entrada es visible aquí o se publica después y su preflight falla (R2-01).
    """

    if inbox.root_state(store) != "present":
        return
    if not inbox.pending_is_empty(store):
        raise inbox.InboxError("inbox_pending", "vacía la bandeja con `inbox drain` y reintenta")
    if not inbox.inflight_is_empty(store):
        raise inbox.InboxError("inbox_inflight", "hay un vaciado interrumpido; ejecuta `inbox drain` y reintenta")


__all__ = ["CUSTODY_LOCK_WAIT_SECONDS", "custody_guard", "require_empty"]
