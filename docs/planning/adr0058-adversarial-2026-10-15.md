# Ronda adversarial de ADR-0058 — paginación de context_view en el origen (2026-10-15)

## Alcance

ADR candidata `docs/architecture/0058-context-view-paginacion-origen-v1.md`
(dos pasadas: pasada ligera de referencias + proyección pesada perezosa de
la ventana servida, contrato observable byte a byte idéntico). Se revisó:
núcleo de decisión (`an_kla/context_view.py` completo), validador cerrado
de MCP (`an_kla/mcp.py::_validate_view_result`), CLI
(`an_kla/__main__.py`), `capabilities`/`cli_parser`/`inventory`, suite de
contrato (`tests/test_context_view.py`, `tests/test_context_view_cli.py`,
`tests/test_mcp_view.py`, `tests/test_agent_contracts.py`) y la
interacción con `snapshot()`/reader gate (ADR-0057). Precedida de spike de
sólo lectura el mismo día (6 hipótesis verificadas, veredicto `proceed`).

## Modelo de amenazas

Sin cambio en la frontera de confianza: `context_view` sirve datos
marcados `untrusted_memory_data: true` y no eleva autoridad. El cambio es
de rendimiento en el camino de lectura; no toca escritura gobernada, CAS
ni contratos de export. El validador cerrado de MCP actúa como red de
paridad: cualquier deriva de forma del payload degrada a `internal_error`
en la superficie MCP.

## Hallazgos y correcciones

| Hallazgo | Riesgo | Corrección |
|---|---|---|
| H1 (MEDIUM): registro crudo no serializable fuera de ventana pasaba de `view_rule_ambiguous` a éxito sin declaración | Deriva de clasificación silenciosa en `Snapshot` directo (inalcanzable vía `MemoryStore`) | Declarada en Consecuencias de la ADR; test que fija el comportamiento nuevo (NaN fuera → éxito, en ventana → `view_rule_ambiguous`); preservar el fail-closed universal se rechaza porque exige re-canonicalizar el universo |
| H2 (MEDIUM): el canario de `record_text` sólo cubría el camino feliz | Sin memo en caminos de error de presupuesto, `record_text`/`digest_json` se recomputarían decenas de veces — justo el régimen de 3,2–5,1 s medido | Memoización exigida en la ADR para `_minimum_budget` y payload final; sonda de conteo en la matriz (1 llamada por registro en reanudación tras `view_subject_exceeds_budget`, 0 en `view_envelope_exceeds_budget`) |
| H3 (LOW/MEDIUM): contenido duplicado con ids distintos refutado por digest, ausente de la matriz | Una implementación que clave refutaciones por id rompería paridad en silencio | Caso añadido a la matriz (dos ids, mismo digest → ambos `refuted`) |
| H4 (LOW): detalles de orden no fijados (construcciones previas al bucle, orden de warnings simultáneos, validación antes del filtro con `subject_filter`) | Regresiones de orden no cazadas por tests | Incorporados a "Detalles de paridad" de la Decisión y a la matriz |
| H5 (LOW): cita de motivación imprecisa (5,1 s es el régimen de error, no el feliz) | Motivación mal atribuida | Corregida: 0,442 s feliz / 3,2–5,1 s en `view_subject_exceeds_budget` a 20k registros — refuerza la ADR |

## Verificación de canonicidad / determinismo

Los 7 invariantes verificados con evidencia `archivo:línea` (ver informe
completo de la ronda en la sesión adversarial del 2026-10-15): contrato
`an-kla/context-view-v1` sin campo huérfano frente al validador cerrado;
orden semántico (primer ref inválido; missing sobre universo completo;
namespaces sobre filtrado; refuted>superseded); unicidad de proyección con
memo; `budget_used_bytes` y clasificación de errores de presupuesto
inmutables (`exact_sized_payload` es función pura de los bytes); cursor
idéntico sobre la misma lista ordenada `refs`; dos pasadas dentro del
mismo hold de `shared_reader_gate` con fuente `raw_records` pre-overlay;
ningún camino empeora (incluidos `subject_filter`+`full`, stores con
refutaciones y budgets chicos). Línea base: 35 tests
context_view+mcp_view OK en el árbol previo.

## Límites declarados

- La pasada ligera sigue siendo O(N): la mejora es de constante, no
  asintótica; el "tiempo independiente del N" estricto queda para el
  sustrato P3 (#168) si la batería v2 lo exige.
- En stores con refutaciones, `snapshot()` conserva sus propios pases de
  digest (`validate_lifecycle` + overlay): techo de mejora acotado, coste
  del snapshot fuera del alcance de esta ADR.
- El estrechamiento H1 es una deriva de clasificación aceptada y
  documentada, no un bug: sólo observable con `Snapshot` forjado a mano.

## Decisión

- [ ] proceed
- [x] fix-and-retry — absorbido el 2026-10-15 (H1–H5 incorporados a la
  ADR antes de escribir código; la ronda prescribe `proceed` una vez
  absorbidos)
- [ ] escalate

Sin `proceed` no se publica el tag. La implementación posterior requiere
la matriz de regresión de esta acta en verde.
