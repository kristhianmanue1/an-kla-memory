# ADR-0041: inventario físico por revisión (`inventory`)

- **Estado:** Aceptada
- **Implementación:** CORE+CLI+SCHEMAS+CAP en `feat/issue-68-inventario`
  (#68, post-beta.16)
- **Fecha:** 2026-08-20
- **Decide sobre:** la superficie read-only que enumera la población física
  de records por revisión sin query ni score; no decide relaciones entre
  subjects (#69, cerrado no-action), export (#46) ni cambio de formato
- **Autoriza:** la implementación encargada por el maintainer (decisión #68,
  2026-08-20) sobre el spike `issue-68-spike-inventario-2026-08-20.md`
  (veredicto `proceed`, ronda adversarial absorbida)

## Decisión

**Comando `inventory --revision <sha256:…>` con schema
`an-kla/inventory-v1`, paginación por cursor opaco, planos separados
físico/observable y chequeo de archivado ANTES de servir.**

### 1. Superficie CLI

- `inventory --revision <sha256> [--streams facts,events,episodes]
  [--cursor …] [--limit N]` — `--revision` **obligatorio** (nunca
  CURRENT implícito; el issue lo prohíbe); `--limit` por defecto 200,
  máximo 1000.

### 2. Schema `an-kla/inventory-v1`

```json
{
  "schema": "an-kla/inventory-v1",
  "revision": "sha256:…",
  "streams_searched": ["facts"],
  "untrusted_memory_data": true,
  "counts": {"facts": {"total": 23, "vigente": 20, "sustituida": 2,
                        "refutada": 1}},
  "pagination": {"complete": true, "next_cursor": null,
                 "served_records": 23, "total_records": 23},
  "records": [
    {"stream": "facts", "id": "f-…", "record_sha256": "sha256:…",
     "physical_status": "vigente",
     "status": "vigente", "status_source": "physical",
     "has_subject_ref": true, "bytes": 431}
  ]
}
```

- `physical_status`: estado crudo autodeclarado del segmento (untrusted:
  puede decir `eliminada` sin operación gobernada).
- `status` observable: composición de overlays (`physical` | 
  `supersede_overlay` | `refute_overlay`), con `status_source`.
- `counts` sobre el observable; invariante `counts.total = Σ estados`
  sobre **cinco** buckets: `vigente`, `sustituida`, `refutada`,
  `eliminada` (estado físico autodeclarado sin operación gobernada) y,
  para stores corruptos con estados exóticos, cualquier otro entero
  adicional (el schema exige los cinco canónicos y admite extras
  enteros). Decisión del maintainer 2026-08-20: nombrar `eliminada` en
  vez de degradar la invariante — esconder un estado observable al
  operador es lo contrario de para qué existe un inventario.
- `bytes = len(canonical_json(raw_record))` (huella en disco del
  contenido del record, sin la nueva línea del segmento).
- **Sin contenido**: no hay render/payload/texto ni flag para pedirlo en
  v1 (export encubierto prohibido por el spike). Sin rutas absolutas.

### 3. Comportamiento

- **Chequeo archived antes de servir** (patrón `verify_revision`,
  `compaction.py:691-702`): revisión archivada →
  `revision_archived_by_compaction`, nunca `segment_missing` engañoso.
- Success exit 0 siempre que se pudo inventariar (ausencia de records es
  estado, no error).
- Reader gate durante toda la página (como todo lector). El gate se
  libera entre páginas: el cursor es inválido si la revisión fue
  archivada mientras tanto (falla cerrado, mismo código).
- Legacy sin `subject_ref`: enumerado con `has_subject_ref: false`.
- Cursor opaco ligado a revisión + identidad (patrón G-VIEW), máximo el
  mismo límite de caracteres. El cursor NO liga la selección de
  `--streams`: el caller debe mantener la misma selección entre páginas
  o la continuación se desplaza silenciosamente (documentado en vez de
  engordar el cursor).

### 4. capabilities y schemas

`capabilities().storage.inventory`: schema, read-only, default/max del
límite, y `content: "metadata-only"` (anti export encubierto declarado).
Schema empaquetado en `docs/schemas/` + `an_kla/schemas/`. Sin MCP en v1
(spike: digest-oracle extendido a records sin `subject_ref` — riesgo
Medio si se abre; diferido).

## Por qué estas decisiones

Del spike y su ronda: (a) el chequeo de archivado ANTES de servir evita
servir revisiones de la ventana `committed_cleanup_incomplete`;
(b) `raw_records` del Snapshot ya expone ambos planos sin releer
segmentos (cero cambios de formato); (c) la separación físico/observable
evita reportar `eliminada` físico como "vigente"; (d) MCP queda fuera
porque extendería el oráculo de digests a la población hoy invisible
para G-VIEW sin un consumidor que lo pida.

## Límites

- Es un inventario de METADATA: no prueba vigencia externa ni autoridad;
  `untrusted_memory_data: true`.
- El costo de `bytes`/`record_sha256` es O(n) por página (digest por
  record); aceptable para operación de operador, no para hot-path.
- Entre páginas no hay transacción: la revisión es inmutable, pero el
  archivo de la misma puede avanzar (fail-closed documentado).

## Test de regresión (congelado)

1. happy path con mezcla vigente/sustituida/refutada/eliminada-físico +
   invariante de counts; 2. legacy sin subject_ref; 3. paginación con
   cursor (página 2 continúa exactamente); 4. revisión archivada →
   código correcto; 5. `--revision` ausente → error estable;
   6. schema valida instancias reales; 7. sin contenido ni rutas en el
   payload; 8. límites default/máx; 9. CLI e2e exit 0 con store ausente
   → error reader gate (nunca traceback); 10. suite completa + CI local.

## Referencias

- Issue #68; spike `docs/planning/issue-68-spike-inventario-2026-08-20.md`
  (mapa código:línea, threat model, casos compactación/concurrencia);
  ADR-0036 (patrón de ejes y "ausencia es estado"); ADR-0019/0026
  (overlays que componen el estado observable); ADR-0028 (archivado).
