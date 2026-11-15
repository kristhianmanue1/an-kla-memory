"""Puntos de corte del criterio 3 (ADR-0063), instalados desde la prueba y nunca en producción.

Cada punto parchea un método de la instancia de ``MemoryStore`` (o ``os.unlink``) del proceso
trabajador del test y ejecuta ``action`` justo en ese punto: ``kill -9`` sobre el propio proceso
en el arnés real (``inbox_crash_worker``) o ``raise Crash`` en las pruebas en proceso. El código
de ``an_kla`` no tiene ganchos ni variables de entorno para esto.

Los puntos del ADR, en orden: 1 ``enq_tmp`` (tras el fsync en ``tmp/``, antes de publicar),
2 ``post_marker`` (marcador escrito, antes del journal ``prepared``), 3 ``pre_replace_current``
(objetos escritos, antes de ``_replace_current``), 4 ``post_replace_current`` (tras él, antes del
recibo ``current-durable``), 5 ``pre_committed_journal`` (recibos escritos, antes del journal
``committed``), 6 ``post_journal`` (journal cerrado, antes de borrar ``pending/``), 7 ``mid_delete``
(a medio borrar ``pending/``), 8 ``post_entries_deleted`` (entradas borradas, marcador vivo). Más
``one_by_one``: el último recurso, en el segundo commit uno a uno.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Any, Callable, Iterator
from unittest import mock

from an_kla.store_errors import StoreError

POINTS = (
    "enq_tmp", "post_marker", "pre_replace_current", "post_replace_current", "pre_committed_journal",
    "post_journal", "mid_delete", "post_entries_deleted",
)
EXTRA_POINTS = ("one_by_one",)


def enqueue_replace(action: Callable[[], None]) -> Callable[[Any, Any], None]:
    """``replace`` inyectable de ``enqueue``: corta tras el fsync del temporal y antes de publicar."""

    def replace(source: Any, destination: Any) -> None:
        action()
        os.replace(source, destination)

    return replace


@contextlib.contextmanager
def install(store: Any, point: str, action: Callable[[], None]) -> Iterator[None]:
    """Instala ``point`` sobre ``store`` (y ``os.unlink``) mientras dure el bloque."""

    patches: list[Any] = []
    real_write, real_replace = store._write_transaction, store._replace_current
    real_unlink = os.unlink
    seen = {"prepared": 0, "unlinked": 0}

    def write_transaction(txid: str, body: Any) -> None:
        stage = body.get("stage")
        if point == "post_marker" and stage == "prepared":
            action()
        if point == "one_by_one" and stage == "prepared":
            seen["prepared"] += 1
            if seen["prepared"] == 2:  # el segundo commit uno a uno (el primero ya está hecho)
                action()
        if point == "pre_committed_journal" and stage == "committed" and body.get("observed_log") is None:
            action()
        real_write(txid, body)
        if point == "post_journal" and stage == "committed" and isinstance(body.get("observed_log"), str):
            action()

    def replace_current(identifier: str) -> None:
        if point == "pre_replace_current":
            action()
        real_replace(identifier)
        if point == "post_replace_current":
            action()

    def unlink(path: Any, *args: Any, **kwargs: Any) -> None:
        parent, name = Path(path).parent.name, Path(path).name
        if point == "post_entries_deleted" and parent == "inflight" and not name.startswith("."):
            action()
        real_unlink(path, *args, **kwargs)
        if point == "mid_delete" and parent == "pending":
            seen["unlinked"] += 1
            if seen["unlinked"] == 1:
                action()

    patches.append(mock.patch.object(store, "_write_transaction", write_transaction))
    patches.append(mock.patch.object(store, "_replace_current", replace_current))
    patches.append(mock.patch.object(os, "unlink", unlink))
    if point == "one_by_one":
        real_assign = store._assign_records

        def assign(base: Any, pending: Any) -> Any:
            if len(pending["facts"]) > 1:
                raise StoreError("duplicate_facts_id")  # fuerza el último recurso
            return real_assign(base, pending)

        patches.append(mock.patch.object(store, "_assign_records", assign))
    with contextlib.ExitStack() as stack:
        for patch in patches:
            stack.enter_context(patch)
        yield
