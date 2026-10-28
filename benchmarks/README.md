# Benchmarks

La batería de benchmarks se divide entre `calibration/` y `public-test/`. Los
fixtures son sintéticos: no incluyen hechos, eventos, rutas ni artefactos de
memoria de producción.

## Evaluación de recuperación

```bash
python3 -m an_kla --project-root . evaluate \
  --queries benchmarks/public-test/queries.jsonl --budget 1200
```

Este benchmark mide recuperación (precision/recall sobre consultas
sintéticas), **no** valor decisional. Los pares con/sin memoria se
incorporarán antes de declarar eficacia.

## Batería de escala P0 (issue #149)

`benchmarks/scale/` mide el coste O(historia) del store por la vía gobernada
pública (columna gobernada, con aborto por umbral) y por lotes internos
(columna diagnóstica, etiquetada `internal_commit_diagnostic`). Umbrales
normativos en `benchmarks/scale/thresholds-v1.json`, commiteados antes de
correr; resultados oficiales versionados en `benchmarks/scale/results/`.

```bash
python3 -m benchmarks.scale.battery --scenario all     # corrida oficial
python3 -m benchmarks.scale.battery --scenario crash --smoke   # cableado
```

Los abortos por umbral son resultados falsables, no fallos de la batería.

## Batería de escala v2 (issue #167)

Segunda fase (#149/P0b): las cinco familias que la v1 dejó como deuda.
Umbrales en `benchmarks/scale/thresholds-v2.json` (incluye las secciones v1
verbatim; aprobación de maintainer pendiente para corrida oficial). Escenarios
(`--scenario all-v2` los lanza todos):

| Escenario | Familia del issue | Qué registra |
|---|---|---|
| `ingest-cli` | Ingesta gobernada por CLI | `plan-write` + `commit-write-plan` reales por subproceso, con aborto por latencia sostenida pre-corrida y línea base del coste fijo del CLI |
| `concurrency-v2` | Concurrencia 4×8 | tasa de `LockBusyError` (fracción de intentos y por segundo) contra el deadline de lock (10 s), throughput de lectores |
| `rare-query-index` | Término raro índice sí/no | misma consulta en fase sin índice (degradación observable) y con índice (`rebuild-index` por CLI), control scan y speedup |
| `crash-mid-commit` | Crash mid-commit en store grande | SIGKILL con retardo calibrado tras marcador pre-commit; evidencia por intento (`verify`/`doctor`/`recover`/`transaction inspect`) y escritura post-crash |
| `compaction-large` | Compactación a ~20k | duración por fase, ventana de indisponibilidad (escritura sonda concurrente al `compact commit`), `snapshot()` resultante |

```bash
python3 -m benchmarks.scale.battery --scenario all-v2           # corrida oficial v2
python3 -m benchmarks.scale.battery --scenario crash-mid-commit --smoke   # cableado
```

Limitaciones declaradas (registradas también en cada resultado): el aterrizaje
del SIGKILL y el disparo de la sonda de indisponibilidad son probabilísticos
con retardo calibrado; cada intento registra su evidencia en vez de afirmar el
punto de muerte. La espera de lock de un escritor durante `compact commit` no
agotó el deadline de 10 s en las corridas observadas (sonda bloqueada 52-198 s
sin `LockBusyError`): hallazgo observacional, no corregido.

### Corridas full-scale pendientes

La corrida oficial v2 a escala completa no se ha ejecutado (presupuesto de
horas; `compact plan` medido a 244 s con sólo 500 revisiones). Comando exacto,
desde la raíz del repo con Python 3.12+:

```bash
python3 -m benchmarks.scale.battery --scenario all-v2
```

Umbrales por defecto: `thresholds-v2.json` (ingest 120 escrituras CLI,
concurrencia 4×8×60 s con preload 2000, rare-query 5000 registros,
crash 5 intentos con preload 5000, compactación 20.000 revisiones). La
compactación a 20k es la parte dominante: el build de revisiones es cuadrático
(~121 s a 500 revisiones observados). Validación reducida comprometida en
`results/20261028-101508/` (los cinco escenarios ok).

## Notas

- A partir de `v0.1.0-beta.4`, los fixtures pueden cubrir los tres streams
  (`facts`, `events`, `episodes`) usando el flag `--streams` o el parámetro
  Python equivalente. Los fixtures históricos sólo cubren `facts` y siguen
  sirviendo para regresión.
- Los resultados dependen del backend FTS5 disponible; en sistemas sin
  extensión FTS5 el benchmark cae al perfil `scan-fallback/v1`.
