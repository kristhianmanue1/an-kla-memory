# ADR-0015: Transparencia en exclusiones de recuperación

- **Estado:** Aceptada
- **Fecha:** 2026-08-03
- **Cierra:** issue #10 (parte B)

## Contexto

`retrieve()` sólo reportaba contadores en `excluded_summary`
(`{zero_score: N, budget: M, ...}`). El operador **no podía saber qué
registros concretos habían sido excluidos**, especialmente por `budget` —
el bug más reportado por consumidores con registros largos. El reporte del
issue #10 lo ejemplificaba: un fact de 1407 bytes con `budget=1500` era
dropped silenciosamente.

## Decisión

- Añadir `excluded_detail` al resultado con la estructura siguiente:

```json
{
  "ids": {
    "zero_score": ["f-…", "f-…"],
    "budget":     ["f-…", "f-…"],
    "inactive":   ["f-…"],
    "no_text":    ["f-…"],
    "invalid_record": ["f-…"]
  },
  "truncated": {
    "zero_score": false,
    "budget": true
  },
  "cap": 50
}
```

- Se trackean los 5 motivos de exclusión, no sólo `zero_score`/`budget`. Los
  contadores sin IDs simplemente no aparecen en `ids`.
- `cap = 50` (constante `EXCLUDED_DETAIL_CAP`): máximos IDs por razón.
- `truncated[reason] = excluded_summary[reason] > len(ids[reason])`.
- `excluded_summary` se mantiene sin cambios (compatibilidad hacia atrás).

## Por qué truncar a 50

Una memoria con 1000 facts y query ruidosa podría tener 990 zero_score. Sin
truncar, el JSON resultante se inflaría a ~30 KB. 50 IDs es suficiente para
diagnóstico; `truncated: true` avisa al operador que hay más. El cap es
constante, no configurable, para mantener determinismo.

## Consecuencias

- `an-kla/retrieval-result-v1` gana un campo aditivo `excluded_detail`.
- Coste máximo: ~3 KB extra en el peor caso (5 razones × 50 IDs × ~12 bytes/ID).
- No afecta a la selección real, sólo al diagnóstico.

## Test de regresión

`tests/test_excluded_detail.py`:

1. Memoria con 100 facts grandes, `budget` pequeño → verificar `budget` con
   `truncated: true` y 50 IDs.
2. Memoria con 1 fact sin texto → verificar `no_text` con 1 ID.
3. Memoria con 1 fact inactivo → verificar `inactive` con 1 ID.
