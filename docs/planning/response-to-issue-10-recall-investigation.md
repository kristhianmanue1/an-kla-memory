# Issue #10 — Investigación técnica del bug de recall

**Estado:** Diagnosticado, sin fix aplicado.
**Fecha:** 2026-08-03
**Repro reportado:** `assemble-context --query "an-kla-memory validacion L3 L4 cobertura sobre-optimista surrogate" --budget 1500` devuelve sólo `f-argos-integration`; un fact de 1407 chars y un episode de 1666 chars no aparecen, ni siquiera después de `rebuild-index`.

## Verificación in-vitro (HEAD `e4b38a9`, memoria actual)

```
retrieve("an-kla-memory validacion L3 L4 cobertura sobre-optimista surrogate", 1500)
→ selected: 3 facts (max score 3, coste 342-534 bytes)
→ excluded: {zero_score: 10, budget: 4}
→ degradation: none, profile: scan-fallback/v1
```

Es decir, en la memoria actual del propio repo (que no contiene los registros
que argos escribió) **ya se observan 4 hechos excluidos por budget** sin
necesidad de un registro de 1407 chars.

## Hallazgos (4 bugs reales, no los planteados)

### Bug A — `retrieve()` sólo itera `snapshot.records["facts"]`

`an_kla/retrieval.py:78` itera únicamente el stream `facts`. Las 6 entradas en
`episodes` y los 9 `events` **son totalmente no recuperables** por retrieval.
Esto contradice el modelo operativo declarado en `AN-KLA.md`
(`streams: facts, events, episodes`).

`capabilities()` ya lo declaraba parcialmente:
`"retrieval.profiles[].streams_searched": ["facts"]` — pero el operador leyó
"modelo operativo" y asumió paridad.

**Severidad:** alta. El reporte del issue lo atribuyó a longitud pero la causa
es que **el episode nunca fue considerado**.

### Bug B — Registros largos silently dropped por budget

`an_kla/retrieval.py:121-128`:

```python
for score, identifier, _record, rendered in ranked:
    cost = len(rendered.encode("utf-8")) + per_record_overhead_bytes
    if score == 0:
        excluded["zero_score"] += 1; continue
    if used + cost > budget:
        excluded["budget"] += 1; continue
```

Un fact de 1407 bytes con `assemble-context` reservando fixed_overhead queda
fuera con budget=1500. El `excluded_summary` lo reporta, pero el JSON de
salida NO incluye los IDs excluidos — el operador no tiene forma de saber qué
perdió.

**Severidad:** media. No es un bug de corrección, es un bug de transparencia.

### Bug C — `build_index()` sólo indexa `facts`

`an_kla/index.py:82` itera `snapshot.records["facts"]` exclusivamente. Mismo
bug que A pero en la ruta FTS5: aunque `retrieve()` se arregle para iterar
todos los streams, el INDEX_PROFILE seguirá devolviendo sólo facts.

**Severidad:** alta (bloquea el fix de A para FTS5).

### Bug D — `commit_write_plan` no actualiza el índice

`an_kla/store.py:282-295` escribe revisiones, segmentos, journal y CURRENT,
pero nunca invoca `build_index`. El índice queda ligado a una revisión
previa. En `retrieval.py:42-43`, si el `claimed` revision_id no coincide con
la actual, se devuelve `index_unavailable` y se cae al scan — comportamiento
correcto pero que **requiere `rebuild-index` manual después de cada commit**,
algo que no está documentado en `AN-KLA.md` ni en `README.md`.

**Severidad:** media. Se manifiesta como "el índice parece no funcionar".

## Refutación de la hipótesis del reporter

> "Sospecha: el ranking FTS5/BM25 **penaliza por longitud de documento**"

**No aplica aquí.** El ranking en `retrieval.py:89` siempre es
`len(query_terms & _terms(rendered))` (overlap count puro). FTS5 sólo se usa
para **filtrar** (`_narrow_with_index`), no para puntuar. Por tanto no hay
penalización BM25 por longitud en el código actual.

## Fix propuesto (NO aplicado en esta iteración)

1. **A+C:** parametrizar el bucle de `retrieve()` y `build_index()` por stream,
   manteniendo `streams_searched` declarativo en `capabilities()`.
2. **B:** exponer `excluded_ids` por razón (al menos para `budget`) en
   `retrieval-result-v1`, manteniendo el ancho mínimo.
3. **D:** invocar `build_index` al final de `_commit_locked` cuando exista un
   índice previo, o documentar explícitamente el step manual.

## Nota operativa

El diagnóstico vive en Git/issue tracker, no en memoria AN-KLA. Si se decide
persistir el hallazgo, debe hacerse con `plan-write` + `commit-write-plan`
siguiendo el flujo gobernado, declarando `derived_from_retrieval=true` y
autoridad `model_derived` (techo summary).
