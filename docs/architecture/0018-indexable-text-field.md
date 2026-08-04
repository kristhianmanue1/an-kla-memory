# ADR-0018: Campo explícito `indexable_text` para FTS

- **Estado:** Aceptado
- **Fecha:** 2026-08-04
- **Cierra:** issue #14
- **Decide sobre:** cobertura de `record_text()` para FTS5

## Contexto

El issue #14 documentó que `rebuild-index` reportaba `skipped_no_text` para
records sin campos `text | render | summary | p`. En memorias ricas en
events y episodes estructurados (con `outcome`, `lessons`, `type`), esto
dejaba fuera del índice a la mayoría de los registros.

El reporter ofreció tres opciones:

- **A — Documentar** la limitación (más conservador).
- **B — Concatenar strings del payload** como fallback (más útil, peor
  signal-to-noise).
- **C — Campo explícito** `indexable_text` (writer decide).

## Decisión

**Opción C.** Añadir convención: records (cualquier stream) pueden llevar
campo `indexable_text` (opcional) que `record_text()` prioriza sobre
`text|render|summary|p`.

### Implementación

`an_kla/index.py:record_text`:

```python
for field in ("indexable_text", "text", "render", "summary", "p"):
```

`indexable_text` se busca en `record.indexable_text` y en
`record.payload.indexable_text` (mismo mecanismo que los otros campos).

### Por qué C y no A/B

- **vs A:** A deja sin recuperación gran parte de la memoria estructurada.
  Los events/episodes con `outcome`/`lessons`/`type` pero sin `text` no se
  recuperarían vía FTS. Mala UX, especialmente tras ADR-0013 (multi-stream
  retrieval) que motiva escribir más events/episodes.
- **vs B:** B indexa timestamps, ids, valores numéricos. El writer pierde
  control sobre qué se indexa; el signal-to-noise del FTS baja
  significativamente. Métricas de recall empeoran.
- **C:** el writer declara explícitamente qué quiere indexar. Es
  schema-discoverable, no ambiguo, y no rompe records existentes (campo
  opcional).

## Por qué no bump de schema `event-v1` / `episode-v1`

Los schemas `an-kla/event-v1` y `an-kla/episode-v1` **no existen como JSON
Schemas publicados** en `docs/schemas/`. Son strings declarativos en el campo
`schema` del record. La política de validación (`write_policy.py:validate_write_proposal`)
sólo exige `record.id` y `record` no vacío; otros campos son libres.

Por tanto, añadir `indexable_text` es **convención documentada**, no bump
formal. Lo que sí cambia:

- `capabilities()` añade nota en `retrieval.indexable_text_field`.
- `AN-KLA.md` menciona el campo en la sección "## Flujo gobernado de escritura".

## Consecuencias

- **Positivas:**
  - Records estructurados (events/episodes) ahora pueden indexarse sin
    reescribirlos para añadir `text`.
  - El writer retiene control total sobre qué se indexa.
  - No rompe records existentes: los que tienen `text|render|summary|p`
    siguen funcionando.
- **Negativas:**
  - Records antiguos sin `indexable_text` ni campos fallback siguen sin
    indexarse. Cada operador decide si reescribirlos.
- **Neutras:**
  - El campo es **opcional**. No aparece en los JSON Schemas formales
    (`write-proposal-v1`, etc.) porque es contenido libre del `record`.

## Migración

- Records existentes: sin acción obligatoria. Quien quiera mejorar recall de
  un record concreto puede `supersede`/`refute` cuando esas operaciones estén
  gobernadas, o aceptar el fallback actual.
- Nuevos records: añadir `indexable_text` (o `payload.indexable_text`) cuando
  el record sea estructural y no tenga un campo `text` natural.

## Tests

- `tests/test_index_streams.py::test_record_text_prefers_indexable_text`
- `tests/test_index_streams.py::test_record_text_falls_back_without_indexable_text`
- `tests/test_index_streams.py::test_build_index_covers_records_with_indexable_text_only`

## Referencias

- Issue #14: https://github.com/kristhianmanue1/an-kla-memory/issues/14
- ADR-0013 (multi-stream retrieval) — motivó escribir más events/episodes.
- ADR-0014 (index v2) — habilitó la indexación multi-stream que este ADR
  hace útil.
