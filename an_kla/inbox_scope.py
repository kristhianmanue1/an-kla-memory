"""Ámbito y directivas al encolar (ADR-0069 §1–§3): lo que ``remember`` comprueba antes de crear nada.

Todo lo que puede fallar sin tocar disco falla aquí, antes de pedir ningún candado: los rechazos de §2 y §3 en su
orden. Una revocación hereda ``subject`` y ``audience`` del destino, que se lee del snapshot sin candado (el vaciado
lo revalida bajo ``write_lock``). Nada de esto lee Git ni la identidad del lector.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from . import directive
from .audience import ScopeError
from .store_errors import StoreError
from .reader_gate import ReaderGateError


def _target(store: Any, target_id: str) -> Mapping[str, Any] | None:
    """La fila vigente de ``facts`` con ese id, o ``None`` (ilegible, ausente o no vigente)."""

    try:
        rows = [r for r in store.snapshot().records.get("facts", []) if isinstance(r, Mapping) and str(r.get("id", "")) == target_id]
    except (StoreError, ReaderGateError, OSError, ValueError, KeyError, AttributeError):
        return None
    return rows[0] if len(rows) == 1 else None


def entry_scope(
    store: Any, identity: Mapping[str, Any], kind: str, target_id: str | None, anchors: Sequence[Mapping[str, Any]] | None,
    *, subject: str | None, audience: str | None, valid_until: str | None, until_revoked: bool, revoke: bool,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Los campos de ámbito de la entrada (vacío si no hay ninguno); ``ScopeError`` con el primer rechazo."""

    fields: dict[str, Any] = {}
    for key, value in (("subject", subject), ("audience", audience), ("valid_until", valid_until)):
        if value is not None:
            fields[key] = value
    if until_revoked:
        fields["until_revoked"] = True
    if revoke:
        fields["revokes"] = True
        if target_id is None:
            raise ScopeError("directive_revoke_without_target", "--revoke exige --supersedes <id de la directive>")
    if not fields and kind != directive.KIND:
        return fields
    data = {"kind": kind, "envelope": {"writer": identity}, "anchors": list(anchors or []), **fields}
    inherited = revoke and kind == directive.KIND
    if inherited:
        row = _target(store, target_id) if target_id is not None else None
        if row is None:
            raise ScopeError("invalid_supersede_target", "target_missing")
        if not directive.is_directive(row):
            raise ScopeError("remember_kind_mismatch", "kind_explicit")
        for key in ("subject", "audience"):
            if key not in fields and key in row:
                data[key] = fields[key] = row[key]  # §3: el acta hereda el ámbito del destino, no lo decide
    directive.check_entry(data, now=clock or (lambda: datetime.now(timezone.utc)))
    if kind == directive.KIND and target_id is not None and not inherited:
        row = _target(store, target_id)
        if row is not None and directive.is_directive(row):
            directive.check_target(data, row)
    if inherited:
        directive.check_target(data, row)
    return fields


__all__ = ["entry_scope"]
