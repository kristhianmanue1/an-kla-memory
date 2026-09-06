"""vigency.py — predicado de vigencia tolerante a datos no confiables.

Issue #113/R1: `record.status`/`record.nu` no escalares (lista/dict)
admitidos por la superficie abierta del record hacían que la pertenencia
en un set lanzara TypeError en retrieve/index/evaluation, bloqueando la
lectura de todo el stream. Desde beta.22 la escritura rechaza no-cadena
(write-policy §record.status), y este predicado degrada fail-closed en
lectura para registros ya persistidos.
"""

from __future__ import annotations

_VIGENT = frozenset({"vigente", "active"})


def is_active(record: dict) -> bool:
    """True si el registro cuenta como vigente; nunca lanza.

    Un `status`/`nu` no hashable o no escalar no es vigente: el registro
    se excluye (bucket `inactive`) en vez de tumbar al lector.
    """
    try:
        value = record.get("status", record.get("nu", "vigente"))
        return value in _VIGENT or value is None
    except TypeError:
        return False


__all__ = ["is_active"]
