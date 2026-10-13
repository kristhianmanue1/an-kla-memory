# M0 — ensayo condicionado del método Muse: cerrado como «no transferir»

- **Tarea:** M0 del plan `docs/plans/2026-10-10-g3-discovery-agent-roadmap.md` (P4, condicionado).
- **Decisión:** **no transferir**. La condición de entrada del paso 1 no se
  cumplió: no se encontró un consumidor que confunda una proyección o
  recuperación parcial con una completa sin que los tests lo detecten.
- **Fecha:** 2026-10-13.
- **Ejecutor:** agente Claude Code (modelo efectivo `unknown`). Decisión de
  cierre tomada bajo la delegación del maintainer.
- **Revisión:** autorrevisión; sin revisor independiente.

## Qué se revisó

| Consumidor | Señal de parcialidad | Detección actual |
| --- | --- | --- |
| `context_view` (`an_kla/context_view.py:333-454`) | `pagination.complete`, `next_cursor`, `truncated_subjects` | `tests/test_context_view.py:262-268` (paginación) y `:385`, que marca `complete: false` en una página completa → schema inválido (mutación que falla) |
| MCP `an_kla_view` (`an_kla/mcp.py:184-195`) | Valida la forma cerrada de `pagination` y la coherencia con los inputs | Validación estricta de la salida |
| `retrieval` (`an_kla/retrieval.py:275-299`) | `excluded_summary` y `excluded_detail.truncated` por categoría; `empty_reason` (ADR-0049) | Tests de ADR-0049 (`zero_score`, selección vacía) |

## Límites

- La búsqueda fue dirigida a los tres consumidores que el plan nombra, no
  exhaustiva sobre todo el código.
- No se ejecutó ningún fixture ni protocolo Muse, ni se copió ningún
  material externo.
- Reabrir M0 requiere un caso reproducible con control positivo, como pide
  el plan.
