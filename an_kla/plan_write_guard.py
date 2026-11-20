"""``plan-write`` no escribe ámbito ni directivas (ADR-0069 §2, R69-03).

El ámbito (``subject``, ``audience``) y la vigencia de una ``directive`` sólo se escriben por el camino que los valida:
``remember``. Esta guarda vive aparte de ``write_policy`` (que está en su tope de líneas) y la llaman las dos entradas
públicas de planificación, la orden ``plan-write`` y ``MemoryStore.plan_write``. El vaciado de la bandeja arma sus
propias propuestas con las funciones puras de ``write_policy`` y no pasa por aquí: sus registros sí llevan estos campos.
"""

from __future__ import annotations

from typing import Any, Mapping

from .audience import scope_violation
from .write_policy import WritePolicyError

CODE = "plan_write_scope_fields_not_allowed"


def reject_scope_fields(proposal: Any) -> None:
    """``plan_write_scope_fields_not_allowed`` si algún registro lleva ``kind: directive`` o un campo de ámbito."""

    if not isinstance(proposal, Mapping):
        return
    records = proposal.get("records") if isinstance(proposal.get("records"), list) else [proposal.get("record")]
    for index, record in enumerate(records):
        if isinstance(record, Mapping) and scope_violation(record):
            raise WritePolicyError(CODE, f"record[{index}]")


__all__ = ["CODE", "reject_scope_fields"]
