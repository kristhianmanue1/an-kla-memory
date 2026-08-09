# Benchmark de referencia retrieval v2 — 2026-08-08

## Alcance y decisión

Esta ejecución local materializa ADR-0025 sobre el fixture saneado
`retrieval-benchmark-v2/1`. Mide ranking y selección bajo presupuesto; no mide
verdad, autoridad ni calidad decisional. La conclusión normativa permanece:

```json
{"ranking_change_authorized":false,"reason":"metrics_require_future_adr"}
```

No se midió latencia. BM25 es experimental y sus bytes no son contractuales
entre runtimes porque dependen de `libm`. La revisión humana del corpus está
`passed`, ligada al digest exacto y atestiguada por el maintainer. Esto cierra
el gate de privacidad; no autoriza por sí solo un cambio de ranking.

## Identidad reproducible

| Artefacto | Digest |
|---|---|
| Revisión R3 | `sha256:ddc8ffd48427ce0f5b2b2742469c04e5743eabc7c695278bdc30bbf15b57519e` |
| Fixture | `sha256:d6e1d6c7fda20b7f88a8ff6018a026d61a9f006f4d90b8f9772c6d6643376a8f` |
| Records | `sha256:7ce058c17169065f0d673e4e9d1d5dfe387d1d702d8720aec8ae8ce4036c22a8` |
| Queries | `sha256:7fdf89605cc2e61c2fdd33698a8cc62653a6b038437c1da17922ba755e9b6bbb` |
| Corpus | `sha256:f7738e6b5d05915a2d85c68dbe474667f0fac8e89698018e48d7fd0e11764aba` |
| Manifest de procedencia | `sha256:4659abccb017c7f6496e0228e4f4702db8221bd6e5ca2b5ca2364d3449df524e` |
| Configuración | `sha256:6655ce7d6b7afe30442a87095bcd8711cbb5f792afb497d805a8c9f884c76441` |

Configuración: cinco queries; budgets `256,512,1024,4096`; k-values
`1,3,5,10`; perfiles `scan-fallback/v1,sqlite-fts5/v1`; estados de índice
`absent,fresh,corrupt,stale`.

## Resultado agregado

| Estrategia | MRR | P@1 | R@1 | R@3 | Recall por budget 256/512/1024/4096 |
|---|---:|---:|---:|---:|---|
| overlap productivo | 0.7 | 0.6 | 0.5 | 0.8 | 0.7 / 0.7 / 0.7 / 0.7 |
| BM25 experimental | 0.8 | 0.8 | 0.6 | 0.8 | 0.7 / 0.7 / 0.7 / 0.7 |
| summary-indexed experimental | 0.4 | 0.4 | 0.3 | 0.4 | 0.2 / 0.2 / 0.4 / 0.4 |

Overlap y BM25 excluyen un relevante largo en cada budget, incluido 4096,
pero el relevante sí aparece en el ranking independiente del budget. Summary
excluye uno en 256 y 512; su recall menor también refleja relevantes que no
entran al ranking por ausencia del campo summary/indexable correspondiente.

La ventaja observada de BM25 en MRR/P@1 es sólo una señal sobre un corpus
pequeño y fijo. No justifica cambiar retrieval sin un corpus ampliado, revisión
humana aprobada y un ADR posterior.

## Paridad de índice

| Estado | Ranking exacto | Budgets exactos | Ejecuciones con índice real | Degradadas |
|---|---:|---:|---:|---:|
| absent | 5/5 | 20/20 | 0 | 25 |
| fresh | 5/5 | 20/20 | 25 | 0 |
| corrupt | 5/5 | 20/20 | 0 | 25 |
| stale | 5/5 | 20/20 | 0 | 25 |

`fresh` ejerció FTS5 real. Los otros tres estados degradaron de manera segura
al scan y conservaron IDs, conjuntos, orden común y scores comunes.

## Evidencia de ejecución

```text
python3 -m an_kla --no-update-check benchmark-reference
→ schema=an-kla/reference-benchmark-v1
→ ranking_change_authorized=false
→ parity mismatches=0 en 20 rankings y 80 selecciones presupuestadas

python3 scripts/check_benchmark_corpus.py
→ check_benchmark_corpus: OK — corpus saneado y ligado; human_review=passed

python3 scripts/check_clean_wheel.py
→ check_clean_wheel: OK — instalación nueva, contexto, identidad, recursos y
  benchmark-reference desde wheel aislado (an-kla-memory 0.1.0b11)
```

Los gates completos de tests, schemas, tamaños y ronda adversarial se registran
en `docs/releases/v0.1.0-beta.11-adversarial.md`.
