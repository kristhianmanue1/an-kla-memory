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


def is_canonical_vigency(record: dict) -> bool:
    """True si `status`/`nu` faltan, son None o son cadena (forma de escritura).

    #179: los lotes de b31/b32 pudieron persistir valores no escalares en
    records posteriores al primero; esto los identifica sin interpretarlos.
    """
    for field in ("status", "nu"):
        if field in record and not (record[field] is None or isinstance(record[field], str)):
            return False
    return True


__all__ = ["is_active", "is_canonical_vigency"]
