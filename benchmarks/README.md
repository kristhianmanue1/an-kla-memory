# Benchmarks alfa

El benchmark se divide entre `calibration/` y `public-test/`. Los fixtures son
sintéticos: no incluyen hechos, eventos, rutas ni artefactos de
`memoria-agentica`.

La evaluación de recuperación se ejecuta con:

```bash
python3 -m an_kla evaluate --queries benchmarks/public-test/queries.jsonl --budget 1200
```

Este benchmark mide recuperación, no valor decisional. Los pares con/sin memoria
se incorporarán antes de declarar eficacia.
