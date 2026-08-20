# Spike #67 — recall de registros largos (2026-08-20, read-only, v2)

Punto 7 del plan `plan-backlog-2026-08-20.md`. v2 tras ronda adversarial
que refutó tres afirmaciones de la v1. Sin cambios de motor; API pública
`retrieve`/MCP sobre corpus sintéticos en tempdir.

## Experimento 1 — término único (30 facts: 10 cortos ~115 B, 10 medios
~871 B, 10 largos ~6 487 B)

| budget | seleccionados | corto | medio | largo | excluidos_budget |
|---|---|---|---|---|---|
| 2 000 | 4 | 2 | 2 | **0** | 2 |
| 8 000 | 4 | 2 | 2 | **0** | 2 |
| 16 000 | 6 | 2 | 2 | 2 | 0 |

Con presupuesto holgado el orden es `(-score, id)` y el score es
solapamiento de conjuntos de términos (ciego a frecuencia: 50 apariciones
del término puntúan igual que 1).

## Experimento 2 — multi-término (v2): inversión de relevancia

Corpus: 8 facts (4 cortos score-1, 4 medios score-2) + 4 episodes largos
(~6.5 KB, score-3, contienen los tres términos). Consulta
`alpha beta gamma`:

- `retrieve facts, budget 2000` → servidos `r-04, r-05 (score 2), r-00,
  r-01 (score 1)`; **excluidos por budget: `r-06, r-07 (score 2)` y dos
  cortos**. El greedy por `(-score, id)` con presupuesto exacto sirve
  score-1 mientras excluye score-2: la inversión ocurre dentro del
  mismo stream.
- `retrieve episodes, budget 2000` → **cero seleccionados**: la clase
  más relevante desaparece por completo (silencio total del stream).
- MCP `an_kla_retrieve` mide el JSON exacto (no el render): a 2 000
  sirve 5 registros; 1 largo cabe desde ~7 KB y los 2 largos juntos
  exigen 13 474 B. Los umbrales del experimento 1 no transfieren 1:1 al
  transporte: la zona de exclusión es más ancha en MCP.

## Veredicto (corregido)

**Reproducido, en dos capas**: (1) asimetría de costo — comportamiento
especificado del contrato de presupuesto exacto; (2) **inversión de
relevancia bajo presupuesto**: la selección greedy sirve registros menos
relevantes cuando los más relevantes son largos, hasta silenciar un
stream entero. La v1 decía "ningún largo queda fuera por ranking": sólo
cierto en consultas de un término; el diseño de un término no podía ver
esta segunda capa. El desplazamiento además depende del artefacto
`(-score, id)`: con empates, la asignación de ids decide quién sobrevive.

## Recomendación (corregida)

1. **No cerrar #67 como "sin defecto"**: la inversión de relevancia es
   un hallazgo real del contrato actual, no un bug del motor. Cerrar el
   issue dejando registrada esta evidencia; cualquier cambio (selección
   density-aware, chunking, budget-aware ranking) es un ADR futuro con
   su propia ronda — no se autoriza aquí.
2. El remedio write-side **no es** la representación `summary`
   (corregido): es una etiqueta de representación sin semántica de
   tamaño (un "summary" puede pesar 6.5 KB y el render prioriza
   `text`), y `model_derived` ya está forzado a summary por techo de
   autoridad. El remedio operativo es texto conciso en `full` o
   `indexable_text` explícito (ADR-0018).
3. ADR-0029 (léxico/semántico) no atiende la exclusión por presupuesto:
   eje separado, confirmado.

## Script

Corpus: relleno literal (repetido 1/8/60 veces; ~112/866/6 436 B por
registro render):

```
"contexto adicional sin valor informativo para la consulta que ocupa
bytes y diluye la densidad del registro "
```

Experimento 1: 30 facts `needle{0..4}` + relleno. Experimento 2: 8
facts (4 con `"alpha"`+relleno×1, 4 con `"alpha beta"`+relleno×8) y 4
episodes `"alpha beta gamma"`+relleno×60; consultas
`retrieve(store, "alpha beta gamma", 2000, streams=...)` y
`ReadOnlyMcp._retrieve_payload(query, budget)`.

## Límites

- Sintético; la frecuencia relativa de registros largos en corpus reales
  varía (el corpus de referencia del benchmark ya trae f-long/f-short a
  propósito y sus métricas viven en ADR-0025).
- `evaluate-v2` por estrategia no se midió: el issue #67 lo exige como
  condición de salida ("métricas por estrategia"); el recorte procede
  del alcance del punto 7 del plan y la dispensa, si procede, es
  decisión del maintainer, no de este documento.
