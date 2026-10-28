# Batería de escala — corrida

- Huella de entorno: Python `3.12.12` sobre `macOS-27.2-arm64-arm-64bit` (arm64), SQLite 3.53.4, FTS5=True, git `283ebc013b62`.
- Umbrales: copia externa `thresholds-v2-reduced.json` (exacta en `thresholds-used.json`). v1 aprobados por el maintainer (sesión 2026-10-14); v2 (#167) pendientes de aprobación para corrida oficial.

| Escenario | ok | wall s | Nota |
|---|---|---:|---|
| compaction-large | True | 0.0 | revs=300, commit 52.8 s, ventana 52.3 s |
| concurrency-v2 | True | 10.4 | tasa LockBusyError 0.0000, deadline 10 s |
| crash-mid-commit | True | 2.7 | 3 kills, 3 con evidencia mid-commit, post-crash ok=True |
| ingest-cli | True | 8.6 | n=30 por CLI público |
| rare-query-index | True | 0.5 | índice sí/no: sin=scan-fallback/v1 con=sqlite-fts5/v1 |

Los abortos por umbral son resultados falsables, no fallos de la
batería. Los números absolutos dependen de la máquina: la forma de
la curva es el hallazgo (frontera de confianza del informe origen).
