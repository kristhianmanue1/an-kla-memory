# Ronda adversarial — P2c tanda: poda de índices + ADR-0056 (2026-10-15)

Artefacto atacado: `an_kla/index_maintenance.py` (nuevo; `index.py`,
`store.py`, `retrieval.py`, `write_policy.py` intactos), despacho CLI
`rebuild-index --prune`, `tests/test_index_prune.py`, ADR-0055 (aceptada) y
ADR-0056 (propuesta). No toca la lista obligatoria de AGENTS.md: ronda
disciplinaria breve por ser adyacente a almacenamiento.

## Hallazgos y correcciones

| Hallazgo | Riesgo | Corrección |
|---|---|---|
| P1 — el resultado de `retrieve` usa `selected` (lista), no `records`; el primer test asumió mal la forma | test midiendo su propio error de forma | aserciones sobre `selected` con presupuesto amplio (65536) |
| P2 — poda con `--revision` explícita podría eliminar el índice de la vigente si el caller pide otra | sorpresa operativa | documentado en el ADR y el help: `--prune` conserva la revisión objetivo (explícita o vigente); test con keep explícito |
| P3 — la ganancia real de disco depende del historial indexado | expectativa inflada | el 89 % del issue es a 20k; en stores pequeños la poda es proporcionalmente menor (el resultado reporta bytes reales) |

## Decisión de alcance (lo más importante de esta ronda)

La **caché de segmentos materializados** (mitad "fusión" de P2c) se detuvo
ANTES de implementarse: sirve datos y no sólo profundidad de validación —
un atacante de disco autoconsistente haría que la lectura normal sirva
filas distintas de las ancladas por los segmentos content-addressed. Eso
debilita tamper-evidence del camino caliente, propiedad que este repo
declara central; quedó como ADR-0056 **Propuesta** con el tradeoff
explícito, pendiente de decisión del maintainer. Las palancas que no
debilitan nada (lotes con segmentos grandes — efecto ya medido del
ADR-0054 — y compactación) cubren el F2 a las escalas medidas.

## Verificación (comando → resultado)

`tests.test_index_prune` → 4 OK (poda conserva vigente; keep explícito;
`retrieve` scan e índice sobreviven a la poda; CLI reporta `pruned_count`).
Gates: check_adr_registry 56 OK (51/5), check_sizes 553 OK, check_plans 4
OK. Suite completa: línea final del reporte de sesión.

## Decisión

- [x] proceed (poda); ADR-0056 queda en propuesta para el maintainer
- [ ] fix-and-retry
- [ ] escalate
