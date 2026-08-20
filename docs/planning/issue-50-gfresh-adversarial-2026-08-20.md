# Ronda adversarial — G-FRESH #50 / ADR-0037 (2026-08-20)

Punto 4 del plan `plan-backlog-2026-08-20.md`. Revisor independiente
(subagente) con sondas propias. Una pasada: **proceed** (H1–H4 plegados).

## Alcance

CORE (`temporal.summarize_freshness`, `retrieval`), CONTEXT y MCP
(recómputo tras recorte de presupuesto propio), CAP (`denominators`),
contratos (3 schemas v2 en docs/ y an_kla/), ADR-0037, spike y 16 tests
nuevos. `retrieval.py` es archivo gated: ronda obligatoria cubierta.

## Modelo de amenazas

Un conteo incorrecto es peor que la ausencia: convierte silencio en
afirmación falsa (p. ej. contar sobre la población sin recortar haría
creer evaluable lo que no se sirvió). Frontera memoria↔autoridad
intocada: los recuentos son observables de datos autodeclarados.

## Hallazgos y correcciones

Pre-ronda (hallazgo propio del desarrollo, corregido antes de la
revisión): CONTEXT y MCP re-recortan la selección con presupuesto propio
pero re-exponían `source["freshness"]` verbatim → los conteos habrían
descrito la población sin recortar, rompiendo el invariante. Corregido
recomputando sobre la población servida en cada capa.

Ronda del revisor:

| Hallazgo | Riesgo | Corrección |
|---|---|---|
| H1 (MED-BAJA): el sobre mínimo v2 crece ~58 B; presupuestos ajustados pueden pasar a `budget_too_small_*` sin cambio de datos; el ADR no lo decía | Costo de contrato no declarado | Límite explícito en ADR-0037 + test que fija la frontera del sobre mínimo |
| H2 (BAJA): ADR decía "re-expone verbatim" pero context/MCP recomputan (correcto, mal descrito) | Contradicción doc↔código | Prop. 6 reformulada: metadatos verbatim + recuento sobre selección servida |
| H3 (BAJA): "se afirman en el servidor MCP read-only" — el runtime no afirma nada | Sobre-afirmación documental | "Se afirman en pruebas sobre la salida de las tres capas; por construcción en runtime" |
| H4 (INFO): bordes sin test (selección vacía, corpus 100% unparseable, frontera de sobre) | Regresión silenciosa futura | Tests añadidos: `test_empty_selection_counts_zero`, `test_all_unparseable_corpus_declares_itself`, `test_minimum_v2_envelope_boundary_is_pinned` |

Verificación del revisor (evidencia propia): totalidad/exclusividad de
estados probada por fuerza bruta (21 entradas patológicas × 3 relojes ×
3 umbrales); schemas docs/≡an_kla/ byte a byte; v1 intacto (golden
byte-exact); presupuestos exactos en frontera; `_validate_view_result`
(view sin recuentos) sigue pasando.

## Verificación de canonicidad / determinismo

Conteos deterministas: función pura sobre la selección; sin reloj, sin
ranking, sin fingerprints. Suite: 560/560 OK (2026-08-20);
`check_adr_registry` OK (37 ADRs, 34/3); `check_sizes` OK.

## Límites declarados

- Crecimiento del sobre mínimo v2 (~58 B): costo del contrato, ahora
  declarado y fijado en test.
- Denominador de `view context` diferido (población paginada de
  subjects): requiere decisión propia; test impide añadirlo por accidente.
- MCP tool `an_kla_view` sigue validando el bloque view de 4 claves.

## Decisión

- [x] proceed
- [ ] fix-and-retry
- [ ] escalate
