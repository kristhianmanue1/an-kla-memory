# ADR-0013: Recuperación multi-stream opt-in

- **Estado:** Aceptado
- **Fecha:** 2026-08-03
- **Cierra:** issue #10 (parte A)
- **Actualiza:** ADR-0004 (índice de referencia)

## Contexto

`retrieve()` iteraba únicamente `snapshot.records["facts"]` (hard-coded). Los
streams `events` y `episodes` eran **totalmente no recuperables** vía CLI o
Python API, contradiciendo el modelo operativo declarado en `AN-KLA.md`
(3 streams: facts/events/episodes). El consumidor `argos-epistemic` lo reportó
como bug de recall.

La hipótesis del reporter (FTS5/BM25 penaliza por longitud) resultó
**incorrecta**: el ranking siempre fue overlap-count puro
(`len(query_terms & _terms(rendered))`). FTS5 sólo se usa para filtrar.

## Decisión

- `retrieve()` acepta parámetro `streams: tuple[str, ...] | list[str] | None`
  (default `("facts",)` para preservar la promesa histórica de la beta).
- Deduplica streams en input preservando el orden del caller.
- `selected[i]` añade campo `stream` para indicar el origen de cada registro.
- El CLI expone `--streams facts,episodes,events` (CSV).
- `assemble-context` sigue usando el default (facts-only) para no romper su
  esquema de presupuesto.

## Por qué opt-in y no default ampliado

`capabilities().retrieval.profiles[].streams_searched` estaba ya declarado
como `["facts"]`. Cambiar el default rompería:

- consumidores que esperan exactamente `len(selected)` facts,
- el presupuesto `assemble-context` calibrado contra facts cortos,
- la superficie de telemetría implícita de argos-epistemic.

Hacerlo opt-in evita el breaking change y deja al operador decidir cuándo
ampliar el ámbito.

## Consecuencias

- `an-kla/retrieval-result-v1` gana dos campos aditivos: `streams_searched`
  (lista) y `selected[i].stream` (string). Consumers estrictos del JSON
  deben aceptar campos nuevos.
- La deduplicación garantiza que `--streams facts,facts` no produzca IDs
  duplicados.
- El coste máximo de una consulta sube proporcionalmente al número de streams
  activos; la API de presupuesto (bytes UTF-8) no cambia.

## Test de regresión

`tests/test_retrieval_streams.py` debe escribir 1 registro en cada stream y
verificar:

1. Default devuelve sólo facts.
2. `--streams facts,episodes` recupera ambos.
3. Streams duplicados no duplican IDs.
4. Streams inválidos → `ValueError("unsupported_retrieval_stream")`.
