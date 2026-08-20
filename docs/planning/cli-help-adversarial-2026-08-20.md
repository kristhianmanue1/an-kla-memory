# Ronda adversarial — ayuda completa del CLI (P3, 2026-08-20)

Punto 3 de la revisión de documentación (rama `docs/revision-post-beta15`).
Revisor independiente con verificación de fidelidad contra código y prueba
de inyección. Una pasada: fix-and-retry → corregido.

## Hallazgos y correcciones

| Hallazgo | Corrección |
|---|---|
| Alta — el test central era inerte: la técnica "aparecer en la sección detallada" no distinguía comando con help de comando sin help (demostrado inyectando `nuevo-sin-help`) | Test reescrito: cada comando de primer nivel exige **fila propia** (misma línea o envuelta); incluye un test que vigila al guard (muestra sin help no cuenta) |
| Media — asserts por nombre de flag eran vacuos (el nombre siempre aparece) | Asserts por texto distintivo ("bytes UTF-8", "denominadores", "ISO-8601", "framing del host no se mide") |
| Media — `evaluate (legado)` afirmaba estado sin ancla documental | "Evaluar recuperación (v1); para ranking usa evaluate-v2" |
| Media — subcomandos/flags mutantes sin help | No-goal declarado para enumeración de subcomandos; ayuda añadida a los peores: `transaction repair-durability` (MUTATIVO) y `upgrade apply` (positional `expected_fingerprint`) |
| Baja — asimetría de precisión en assemble | "el framing del host no se mide" |

## Fidelidad verificada por el revisor

`recover` read-only (`store.py:520-543`); `rebuild-index` default CURRENT;
presupuestos bytes UTF-8 exactos (`retrieval.py:211`, `context.py`);
gates de upgrade de `plan-write`/`commit-write-plan` intactos (asserts por
substring; sin golden byte a byte del help). Suite: 588/588 OK.

## Decisión

- [x] proceed
- [ ] fix-and-retry
- [ ] escalate
