# Spike #68 — inventario físico por revisión (2026-08-20, read-only)

Punto 9 del plan `plan-backlog-prioridades-2026-08-20.md`. Cumple la
condición de salida del issue: mapa código:línea, threat model, schema
candidato, casos legacy/compactación/concurrencia y veredicto.
**Sin implementación ni cambio de formato** (el issue no la autoriza).

## Mapa código:línea (verificado contra `main` de esta rama)

| Mecanismo | Ubicación | Qué aporta al inventario |
|---|---|---|
| Snapshot bajo reader gate | `store.py:169-171` (`shared_reader_gate`) | Concurrency: lease de lectura compartida durante toda la enumeración |
| Resolución de revisión + detección de archivada | `store.py:173-186` + `compaction.py:721` (`archived_revision_link_under_gate`) | Caso compactación: revisión archivada → error explícito `revision_archived_by_compaction`, sin caminar tombstones |
| Verificación hash/manifest | `store.py:187-191` | La revisión pedida se valida igual que en `verify --revision` |
| Filas físicas por stream desde segmentos | `store.py:195-208` (`ID_FIELDS`, dedup) | La población física exacta: todo record en segmentos, incluidos legacy |
| Validación de ciclo de vida | `store.py:209` (`_validate_lifecycle`) | Fall-closed antes de enumerar |
| Overlay supersede | `store.py:210-230` (`supersedes_map` → `status="sustituida"` en memoria) | Estado observable sin mutar segmentos inmutables (`O_EXCL`) |
| Overlay refute | `store.py:231-244` (`refutations_map` → `status="refutada"` por digest del record crudo) | Segundo overlay; el estado observable es composición de ambos |
| Snapshot dual | `store.py:245` (`records` superpuestas vs `raw_records` físicas, expuesto en `store.py:71-77`) | El inventario reporta ambos planos sin releer segmentos |
| Cursor opaco ligado a revisión+identidad | `context_view.py:156-181` | Patrón de paginación análogo (no idéntico: la clave aquí es record-id, no subject) |
| Chequeo archived ANTES de servir | patrón `verify_revision` (`compaction.py:691-702`) | El inventario debe copiarlo (ver caso compactación) |
| Estado `eliminada` | sin **operación** gobernada (AN-KLA.md) | Existe como estado físico autodeclarado en segmentos (`test_store.py:201` fixturea `status: "eliminada"`); enumerable como `physical_status` untrusted, nunca compuesto a "vigente" |

## Threat model

El inventario expone **metadata de datos no confiables** (ids, digests,
tamaños, estados). Riesgos y mitigaciones del diseño:

- **Export encubierto**: prohibido `render`/payload/text por defecto; el
  item lleva sólo `id/record_sha256/status/bytes`. Sin flag de contenido
  en v1.
- **Oracle de digests**: precedente existente — G-VIEW ya emite
  `record_sha256` por record (`context_view.py:242`); el inventario no
  crea el oráculo, lo extiende a una población **nueva**: los records
  sin `subject_ref` que G-VIEW hoy saltea por completo
  (`context_view.py:278-281`, sólo cuenta `missing`). Bajo riesgo en
  CLI local; Medio si se abriera MCP — por eso MCP queda diferido como
  condición.
- **Inyección vía ids**: los ids son datos; la salida es JSON canónico
  con `untrusted_memory_data: true`; el consumidor no debe interpretarlos.
- **Fingerprinting de corpus**: `bytes` es oráculo de tamaño débil;
  aceptable para un operador local que audita "¿qué hay?".
- **CURRENT implícito**: el issue lo prohíbe; `--revision` es
  obligatorio y falla cerrado si falta.

## Schema candidato `an-kla/inventory-v1`

```json
{
  "schema": "an-kla/inventory-v1",
  "revision": "sha256:…",
  "streams": ["facts"],
  "untrusted_memory_data": true,
  "counts": {"facts": {"total": 23, "vigente": 20, "sustituida": 2, "refutada": 1}},
  "pagination": {"complete": true, "next_cursor": null, "served_records": 23, "total_records": 23},
  "records": [
    {"stream": "facts", "id": "f-…", "record_sha256": "sha256:…",
     "physical_status": "vigente",
     "status": "vigente", "status_source": "physical",
     "has_subject_ref": true, "bytes": 431}
  ]
}
```

`physical_status` es el estado crudo autodeclarado del segmento
(untrusted: puede decir `eliminada` sin operación gobernada que lo
respalde). `status` es el observable compuesto por overlays
(`physical` cuando ningún overlay lo toca, `supersede_overlay` /
`refute_overlay` en caso contrario) con `status_source` — misma
separación de planos que G-VIEW (`state`/`state_source`/
`physical_status_untrusted`, `context_view.py:242-245`). Los `counts`
se computan sobre el observable; el invariante es
`counts.total = Σ estados` y `served + resto = total` por paginación.
`bytes = len(canonical_json(row))` (huella exacta en disco,
`store.py:672`; si incluye el `\n` final lo decide el ADR).

Superficie CLI propuesta: `inventory --revision <sha256:…> [--streams
facts,episodes] [--cursor …] [--limit N]`. MCP: **diferido** (más
superficie, mismo valor para operador local; sin consumidor que lo
pida). Invariante: `served + excluidos_por_página = total` y
`counts.total = Σ estados` por stream.

## Casos

- **Legacy sin `subject_ref`**: enumerado igual (`has_subject_ref:
  false`); el id viene de `ID_FIELDS`, no del subject.
- **Compactación (corregido tras ronda)**: el chequeo de archivada debe
  resolverse **antes** de servir, copiando el patrón de `verify_revision`
  (`compaction.py:691-702`), porque la ventana
  `committed_cleanup_incomplete` (`compaction.py:626-672`) es alcanzable
  y persistente hasta el replay: ahí una revisión archivada puede tener
  aún su manifest presente y `snapshot()` la serviría como válida
  (el chequeo de `store.py:177-186` sólo se dispara si la lectura
  falla), o un borrado parcial produciría `segment_missing:{stream}` —
  engañoso. Post-commit, `_protected_paths` + `inventory_deletable`
  garantizan que ninguna revisión **viva** referencia segmentos
  borrados.
- **Concurrencia**: la compactación corre bajo `exclusive_reader_gate` +
  write lock (`compaction.py:527-528,663`) y `snapshot()` sostiene el
  `flock` compartido durante toda la página (`reader_gate.py:86`), inter-proceso.
  El gate se libera **entre páginas**: una compactación a mitad puede
  archivar la revisión → la página siguiente falla cerrado (correcto),
  o en la ventana anterior sirve datos que ya no están vivos: el
  comportamiento entre páginas debe declararse en el ADR. El cursor no
  toca índice y sobrevive `rebuild-index` (derivable, la compactación
  puede borrarlo).

## Veredicto

**ADR-needed**. La superficie es barata (todo el estado observable ya
vive en `Snapshot`; cero cambios de formato), la necesidad es real
(auditar "¿qué hay?" sin query ni score) y los riesgos tienen
mitigación diseño-arriba. El ADR debe decidir: MCP sí/no (propongo no en
v1), si `bytes` se mide del raw canonical (`digest_json(raw)`) y el
límite de página por defecto. Implementación sólo tras ADR congelado y
ronda; este spike no la autoriza.
