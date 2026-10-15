# Batería P0 de escala — corrida (issue #149)

- Huella de entorno: Python `3.12.12` sobre `macOS-26.6.2-arm64-arm-64bit` (arm64), SQLite 3.53.4, FTS5=True, git `eba9c086ed42`.
- Umbrales: `benchmarks/scale/thresholds-v1.json` (aprobados por el maintainer antes de correr; copia exacta en `thresholds-used.json`).

| Escenario | ok | wall s | Nota |
|---|---|---:|---|
| compaction | True | 0.0 |  |
| concurrency | True | 60.9 |  |
| crash | True | 0.0 |  |
| ingest-governed | True | 0.0 | sin abortos |
| reads-diagnostic | True | 0.0 | columna interna (commit), etiquetada |

Los abortos por umbral son resultados falsables, no fallos de la
batería. Los números absolutos dependen de la máquina: la forma de
la curva es el hallazgo (frontera de confianza del informe origen).
