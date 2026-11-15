"""Orden total de candados (ADR-0063 D1) como invariante comprobable.

Orden: bandeja (``memory/inbox/.lock``) -> identidad (``identity_lock``) ->
``write_lock`` -> gate de lectores. Nadie pide uno anterior teniendo uno
posterior. Se elige *fallar cerrado en tiempo de ejecución* y no sólo
instrumentar en test: una inversión es un defecto de programación que, en
producción, acaba en interbloqueo entre procesos (el candado de bandeja lo
pide en exclusivo un ``export`` que ya espera al de identidad), y un error
inmediato es más barato que un plazo agotado a los 10 s.

Sólo se aplica donde se pide el candado de bandeja: ``identity_lock`` y ``store_locks.write_lock``
(el de módulo, que usan ``MemoryStore.write_lock`` y ``hook_runs``) se limitan a registrarse
(``holding``) para no cambiar el comportamiento de las órdenes existentes; el testigo
``store._active_write_lock`` se conserva como defensa en profundidad. Límite declarado: el
registro es un ``ContextVar``, es decir por hilo y por tarea; un candado tomado en otro hilo no
se ve desde éste (y entre procesos el orden lo sostiene el propio ``flock``, no este registro).
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

INBOX = "inbox"
IDENTITY = "identity"
WRITE = "write"

_HELD: ContextVar[tuple[str, ...]] = ContextVar("an_kla_held_locks", default=())


class LockOrderError(RuntimeError):
    """Se pidió un candado anterior teniendo uno posterior (defecto, no condición de uso)."""

    code = ERROR_CODE = "lock_order_violation"  # `ERROR_CODE`: el CLI lo muestra tal cual, sin cli_unexpected_failure

    def __init__(self, requested: str, held: tuple[str, ...]) -> None:
        super().__init__(f"{self.code}: {requested} while holding {','.join(held)}")
        self.requested = requested
        self.held = held


def held() -> tuple[str, ...]:
    return _HELD.get()


@contextmanager
def holding(name: str) -> Iterator[None]:
    """Registra ``name`` como tomado mientras dure el bloque (por contexto de ejecución)."""

    token = _HELD.set(_HELD.get() + (name,))
    try:
        yield
    finally:
        _HELD.reset(token)


def require_inbox_allowed(store: Any = None) -> None:
    """Falla cerrado si el contexto ya tiene ``identity_lock`` o ``write_lock``."""

    later = tuple(name for name in _HELD.get() if name in (IDENTITY, WRITE))
    if store is not None and getattr(store, "_active_write_lock", None) is not None:
        later += (WRITE,)
    if later:
        raise LockOrderError(INBOX, later)


__all__ = ["IDENTITY", "INBOX", "WRITE", "LockOrderError", "held", "holding", "require_inbox_allowed"]
