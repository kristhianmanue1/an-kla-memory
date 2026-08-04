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

## Notas

- A partir de `v0.1.0-beta.4`, los fixtures pueden cubrir los tres streams
  (`facts`, `events`, `episodes`) usando el flag `--streams` o el parámetro
  Python equivalente. Los fixtures históricos sólo cubren `facts` y siguen
  sirviendo para regresión.
- Los resultados dependen del backend FTS5 disponible; en sistemas sin
  extensión FTS5 el benchmark cae al perfil `scan-fallback/v1`.
