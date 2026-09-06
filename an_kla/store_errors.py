"""Excepciones estables del store (#117: partición de store.py).

Re-exportadas desde ``an_kla.store`` para compatibilidad con todos los
consumidores existentes.
"""

from __future__ import annotations


class StoreError(RuntimeError):
    pass


class ConcurrentUpdateError(StoreError):
    pass


class IntegrityError(StoreError):
    pass


class LockBusyError(StoreError):
    pass


__all__ = ["ConcurrentUpdateError", "IntegrityError", "LockBusyError", "StoreError"]
