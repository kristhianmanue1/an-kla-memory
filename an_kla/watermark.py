"""Watermark de verificación incremental (ADR-0053, issue #149 P1).

Caché derivada "verificado-hasta-R": nunca autoridad, mismo precedente que
el CURRENT del índice FTS. La lectura normal valida el sufijo R→pedida; la
auditoría completa (`verify`) ignora el watermark. Un watermark corrupto,
atrasado o ajeno nunca cambia el resultado: sólo degrada a recorrido
completo (equivalencia) o ya venía fallando cerrado.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from .canonical import canonical_json

WATERMARK_SCHEMA = "an-kla/watermark-v1"


def watermark_path(store: Any):
    return store.root / "watermarks" / "CURRENT"


def epoch_of(manifest: Mapping[str, Any]) -> str | None:
    epoch = manifest.get("compaction_epoch")
    if isinstance(epoch, Mapping):
        value = epoch.get("epoch_id")
        return value if isinstance(value, str) else None
    return None


def write_watermark(store: Any, revision_id: str, manifest: Mapping[str, Any]) -> None:
    """Escribe el sidecar derivado bajo el lock del escritor (ADR-0053 §4).

    Sólo el escritor llama esta función, dentro de la transacción que acaba
    de validar la cadena hasta ``revision_id``. No es estado CAS: es caché.
    """
    payload = canonical_json(
        {
            "schema": WATERMARK_SCHEMA,
            "revision": revision_id,
            "parent": manifest.get("parent"),
            "epoch_id": epoch_of(manifest),
        }
    )
    target = watermark_path(store)
    target.parent.mkdir(parents=True, exist_ok=True)
    store._atomic_write(target, payload)


def usable_watermark(store: Any) -> dict[str, Any] | None:
    """Shape-válido o None. La existencia de la revisión se comprueba al caminar.

    Cualquier malformación se ignora (degradación a recorrido completo),
    nunca se eleva a error: el watermark es caché, no contrato.
    """
    try:
        raw = watermark_path(store).read_bytes()
    except OSError:
        return None
    try:
        parsed = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(parsed, dict) or parsed.get("schema") != WATERMARK_SCHEMA:
        return None
    revision = parsed.get("revision")
    parent = parsed.get("parent")
    epoch_id = parsed.get("epoch_id")
    if not isinstance(revision, str) or not revision.startswith("sha256:"):
        return None
    if parent is not None and not (
        isinstance(parent, str) and parent.startswith("sha256:")
    ):
        return None
    if epoch_id is not None and not isinstance(epoch_id, str):
        return None
    return {"revision": revision, "parent": parent, "epoch_id": epoch_id}


def binding_matches(stop: Mapping[str, Any] | None, child_id: str, child: Mapping[str, Any]) -> bool:
    """El watermark sólo detiene el recorrido si el nodo lo liga exactamente."""
    if stop is None or child_id != stop.get("revision"):
        return False
    return (
        child.get("parent") == stop.get("parent")
        and epoch_of(child) == stop.get("epoch_id")
    )
