# ADR-0055: Poda de índices derivados huérfanos

- **Estado:** Aceptada
- **Implementación:** Implementada (`an_kla/index_maintenance.py`, CLI `rebuild-index --prune`)
- **Fecha:** 2026-10-15
- **Decide sobre:** la eliminación gobernada de índices FTS de revisiones no vigentes (P2c del issue #149).

## Contexto

Cada revisión indexada materializa un SQLite FTS completo bajo
`memory/indexes/<rev>/` con su propio `CURRENT` (caché derivada, nunca
autoridad — `an_kla/index.py`). El issue #149 midió los índices como el
89 % del disco a 20k registros, sin poda (sólo conteo en `doctor`). La
batería P0 confirmó que el FTS no acelera `retrieve` (F4): su valor es la
paridad diagnóstica #118, no el rendimiento.

## Decisión

`rebuild-index --prune` elimina los directorios de índice de todas las
revisiones excepto la vigente (o la explícita con `--revision`). Es
operación sobre caché derivada: sin efecto en corrección (un índice
ausente degrada a `scan-fallback/v1` con diagnóstico honesto), sin
escritura de store, sin journal. El resultado reporta revisiones podadas
y bytes liberados.

## Por qué no [alternativa]

- **Poda automática post-commit**: acopla el camino caliente de escritura
  al mantenimiento; una poda fallida no debe poder fallar un commit.
- **Retención por edad**: la vigencia relevante es "es la revisión actual",
  no cuándo se construyó.
- **No podar**: el 89 % del disco medido crece sin límite por revisión
  indexada.

## Consecuencias

- Positivas: el disco de índices deja de crecer por historia; operación
  explícita y auditable.
- Negativas: recuperar un índice de una revisión antigua exige
  reconstruirlo (barato, derivado).
- Neutras: `doctor` sigue contando índices; la poda es opt-in por flag.

## Test de regresión

- Índices de dos revisiones → poda conserva sólo la vigente; `retrieve`
  sigue funcionando tras la poda; el resultado reporta revisiones y bytes.

## Referencias

Issue #149 (P2c); `an_kla/index.py` (CURRENT derivado); batería P0
`results/20261014-182904` (F4, 89 % disco); orden del maintainer
(2026-10-15: "adelante con recomendaciones").
