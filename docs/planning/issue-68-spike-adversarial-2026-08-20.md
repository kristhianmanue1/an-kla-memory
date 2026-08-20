# Ronda adversarial — spike #68 inventario físico (2026-08-20)

Punto 9 del plan `plan-backlog-2026-08-20.md`. Revisor independiente con
lectura directa de `store.py`/`compaction.py`/`reader_gate.py`/
`context_view.py` y tests. Una pasada: fix-and-retry (1 Alta, 2 Medias)
→ corregidas en el doc. Cierre: **proceed** con veredicto ADR-needed.

## Hallazgos y correcciones

| Hallazgo | Corrección aplicada al doc |
|---|---|
| Alta — caso compactación falso: la ventana `committed_cleanup_incomplete` (`compaction.py:626-672`) deja una revisión archivada con manifest presente (snapshot la serviría válida porque `store.py:177-186` sólo actúa si la lectura falla) o parcialmente borrada (`segment_missing` engañoso) | Caso reescrito: chequeo archived ANTES de servir, patrón `verify_revision` (`compaction.py:691-702`); ventana y comportamiento entre páginas declarados para el ADR |
| Media — "eliminada → no existe camino físico" falso: es estado físico autodeclarado en segmentos; lo no gobernado es la operación | Reformulado: enumerable como `physical_status` untrusted |
| Media — schema mezclaba planos físico/observable en un solo `status` | `physical_status` + `status` compuesto + `status_source` (misma separación que G-VIEW); counts sobre el observable |
| Baja — threat model no citaba el digest-oracle preexistente de G-VIEW ni la población nueva (records sin `subject_ref`, hoy invisibles para G-VIEW) | Añadido; MCP diferido como condición |
| Baja — `bytes` mal redactado (digest ≠ longitud) | `bytes = len(canonical_json(row))` (huella en disco, `store.py:672`); newline a decisión del ADR |
| Info — deriva de citas (231-244, 245, 156-181; "tal cual" sobrestimado) | Citas corregidas |

## Lo que sostuvo el ataque

Mapa código:línea sustancialmente real; `raw_records` ya expuesto en
`Snapshot` (cero cambios de formato); concurrencia confirmada
(`exclusive_reader_gate` + `write_lock` vs `flock` compartido
inter-proceso); cursor inmune a `rebuild-index`; veredicto ADR-needed
justificado (G-VIEW no enumera records sin `subject_ref`; `verify
--revision` da disponibilidad, no contenido; `doctor` es salud).

## Decisión

- [x] proceed (spike como base del ADR; implementación NO autorizada)
- [ ] fix-and-retry
- [ ] escalate
