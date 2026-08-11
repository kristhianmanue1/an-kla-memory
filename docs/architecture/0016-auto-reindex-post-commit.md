# ADR-0016: Reindexado best-effort tras commit

- **Estado:** Aceptada
- **Fecha:** 2026-08-03
- **Cierra:** issue #10 (parte D)

## Contexto

`commit_write_plan` y `commit` movían `CURRENT` pero **no actualizaban el
índice FTS5**. El operador debía ejecutar `rebuild-index` manualmente tras
cada commit; hasta entonces, `retrieve --profile sqlite-fts5/v1` se degradaba
a `index_unavailable` (scan fallback). Esto estaba **documentado en ninguna
parte** y era la causa raíz del reporte "el índice parece no funcionar".

## Decisión

`store._maybe_reindex(parent_revision, candidate_revision)` se ejecuta
**fuera del write lock**, después de que `_commit_locked` retorna el nuevo
candidate. Comportamiento:

1. `index_resolution(self, parent_revision)` — si el padre no tenía índice,
   no se construye (el usuario debe `rebuild-index` una primera vez para
   bootstrap).
2. Si el padre tenía índice, `build_index(self, revision_id=candidate)`.
3. Cualquier excepción es silenciosa: la caché es derivada, no autoridad.

## Por qué fuera del lock

El lock de escritura protege `refs/CURRENT`, `transactions/`, y los
`revisions/`/`checkpoints/`/`segments/` inmutables. Mantenerlo durante un
`build_index` que puede costar 50-500 ms en memorias grandes bloquearía
todos los writes concurrentes por razones de caché.

El índice vive en `indexes/<revision_id>/sqlite-fts5-v1/`. Su inmutabilidad
está garantizada por `O_EXCL` (vía `_write_immutable`) y el hash SHA-256 del
nombre de archivo. No hay race posible: dos builds para el mismo revision_id
producen idénticos bytes.

## Race multi-machine

El lock de escritura es local. Dos máquinas que commitean concurrentemente
podrían generar dos builds de índice para distintos revision_ids, sin
colisión. El `CURRENT` autoritativo sigue siendo la fuente de verdad;
`index_resolution` valida `claimed_revision == actual_revision` antes de
narrowing. Si no coinciden, degradación `index_unavailable` → scan.

## Consecuencias

- Tras cada commit con padre indexado, el nuevo revision_id también tiene
  índice inmediatamente disponible.
- Si el primer commit ocurre sin índice previo, el usuario debe
  `rebuild-index` una vez. Esto está documentado en el release beta.4.
- `doctor()` no cambia; los índices stale (revisiones obsoletas) siguen
  apareciendo como huérfanos declarados (GC pendiente).

## Limitación

No hay `index_rebuild_failed` event en el journal. Un fallo de build es
invisible hasta el próximo `verify_index_deep`. Aceptable para beta; un
future ADR podría añadir un evento de best-effort.

## Test de regresión

`tests/test_auto_reindex.py`:

1. `init` + `rebuild-index` (bootstrap).
2. `commit-write-plan` con un nuevo fact.
3. `retrieve --profile sqlite-fts5/v1` recupera el fact sin `rebuild-index`
   manual y con `degradation: none`.
4. Si el build falla (mock), el commit sigue siendo autoritativo y retrieve
   degrada a scan sin crash.
