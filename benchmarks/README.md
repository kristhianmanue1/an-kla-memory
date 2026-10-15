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

## Notas

- A partir de `v0.1.0-beta.4`, los fixtures pueden cubrir los tres streams
  (`facts`, `events`, `episodes`) usando el flag `--streams` o el parámetro
  Python equivalente. Los fixtures históricos sólo cubren `facts` y siguen
  sirviendo para regresión.
- Los resultados dependen del backend FTS5 disponible; en sistemas sin
  extensión FTS5 el benchmark cae al perfil `scan-fallback/v1`.
