# ADR-0014: Índice SQLite FTS5 multi-stream (index-v2)

- **Estado:** Aceptado
- **Fecha:** 2026-08-03
- **Cierra:** issue #10 (parte C)
- **Actualiza:** ADR-0004

## Contexto

`build_index()` sólo creaba la tabla virtual `facts_fts`. Aunque el ADR-0013
habilita recuperación multi-stream, el perfil `INDEX_PROFILE` seguía devolviendo
sólo facts desde el índice. El formato SQLite del índice no tenía versión
explícita: detectar un índice v1 vs v2 era imposible sin abrir el archivo.

## Decisión

- `an_kla/index.py` crea tres tablas: `facts_fts`, `events_fts`, `episodes_fts`.
- `metadata` del SQLite ahora lleva dos claves nuevas:
  - `schema = "an-kla/index-v2"` (antes `an-kla/index-v1`),
  - `index_version = "2"`.
- `INDEX_VERSION`, `INDEX_VERSION_KEY` e `INDEX_SCHEMA` constantes públicas.
- `index_resolution()` compara `index_version`: si no coincide con `INDEX_VERSION`,
  devuelve `IndexResolution(None, "index_obsolete")` para que el caller caiga
  al scan fallback.
- `_narrow_with_index()` en `retrieval.py` itera por stream consultado y
  tolera tablas FTS5 ausentes (`try/except sqlite3.DatabaseError`) — defensa
  en profundidad.

## Incompatibilidad con índices v1

Los índices generados por versiones anteriores quedan como caches obsoletos:

- No se borran automáticamente (conservador; GC declarado fuera de la beta).
- El primer `retrieve` tras el upgrade reporta `degradation: index_obsolete`.
- El operador debe correr `python -m an_kla rebuild-index` para regenerar.

## Consecuencias

- `schema: an-kla/index-v2` es el nuevo identificador del índice.
- El tamaño del SQLite sube proporcionalmente al número de registros en los
  tres streams; sigue siendo cache derivado, no commit authority.
- `index_obsolete` es un nuevo status de degradación que aparece en
  `retrieve` cuando los índices v1 aún no se regeneran.

## Defensa en profundidad

Si un atacante con acceso de escritura al directorio `.an-kla/indexes/`
sustituye un índice v2 por uno v1, `index_resolution` lo rechaza por
versión → scan. Si lo sustituye por uno v2 malicioso con tablas ausentes,
`_narrow_with_index` ignora las tablas faltantes y la integridad se mantiene
vía `index_integrity_status` (hash SHA-256 por contenido).

## Test de regresión

`tests/test_index_streams.py` debe:

1. Crear memoria con 1 fact, 1 event, 1 episode.
2. `build_index` → verificar `indexed_per_stream = {facts:1, events:1, episodes:1}`.
3. Simular un índice v1 (sin `index_version`) y verificar `index_obsolete`.
4. `retrieve` con `INDEX_PROFILE` y `streams=facts,episodes` recupera ambos.
