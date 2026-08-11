# ADR-0028: compactación gobernada por epoch v1

- **Estado:** Aceptada e implementada localmente; pre-code r4 e implementación
  adversarial final `PROCEED`
- **Fecha:** 2026-08-08
- **Gate:** ronda adversarial pre-code obligatoria

## Problema

La cadena append-only conserva auditoría pero crece sin límite. Borrar objetos
referidos convierte historia archivada en aparente corrupción y puede romper un
reader que capturó CURRENT antes del GC. ADR-0027 ya permite probar un restore
externo; compactación debe ligarse exactamente a esa evidencia.

## Decisión

Las shapes, transiciones, locks, delete-set y replay normativos se definen en
[`../compaction-contract-v1.md`](../compaction-contract-v1.md).

Compactación es `plan -> commit` explícito y sólo POSIX en v1. Plan recibe
bundle export-v1, `epoch_id` y `transaction_id` UUID canónicos preasignados;
ejecuta `verify_export`, exige bundle.current==CURRENT e identidad exacta, y
proyecta sin escribir:

- records raw cuyo estado epistémico actual es `active`;
- checkpoint actual completo;
- catálogo de record tombstones con digest/stream y estado
  `superseded|refuted|inactive`, sin copiar payload ni ID raw;
- catálogo de object tombstones con path/digest/tipo para cada objeto antiguo;
- root `revision-v3` de epoch, segmentos activos nuevos y plan fingerprint.

Commit congela el plan y, en orden `identity lock -> write lock -> reader gate
exclusive`, revalida identidad, CURRENT, bundle/manifest/bytes/store semántico,
policy y proyección. Readers toman el mismo gate en shared desde antes de leer
CURRENT hasta terminar `snapshot`; por tanto ningún reader observa objetos
borrados durante una lectura. Windows mantiene reads pero compact devuelve
`compaction_platform_unsupported`.

Antes de mover CURRENT se sincronizan: segmentos compactos, checkpoint,
tombstone catalog, epoch manifest, revision-v3, stage inmutable y receipt. El
nuevo root tiene revision=source.revision+1,parent=null, store_identity, source_revision,
epoch_id, export_manifest_sha256 y tombstone_catalog; no afirma continuidad por
parent. CURRENT se reemplaza/sincroniza y desde ese punto el epoch es autoridad.
Revision-v3 se hereda en toda escritura futura; una compactación posterior crea
otro root v3 y acumula evidencia/tombstones de todos los epochs anteriores.

Sólo después se eliminan paths exactamente enumerados. Fallo de cleanup no
revierte CURRENT: resultado `committed_cleanup_incomplete`; retry con mismo
txid/binding continúa la misma lista, nunca crea otro root. Un error anterior a
CURRENT es `not_committed`; error alrededor de CURRENT se reconcilia como
ADR-0024. Ningún path no listado ni objeto del nuevo epoch se elimina.

## Disponibilidad e integridad

`verify --revision <digest>` devuelve shape cerrada con:

- `present`: revisión verificable del epoch actual;
- `archived_by_compaction`: tombstone ligado a epoch, source revision y export
  manifest, aunque bytes antiguos aún esperen cleanup;
- `unknown`: nunca `corrupt` por el solo hecho de estar archivada.

Se mantienen ejes separados: estado epistémico del record
`active|superseded|refuted|inactive`; integridad física
`present|quarantined`; disponibilidad histórica
`present|archived_by_compaction|unknown`. `verify()` de CURRENT sigue fail-closed
ante corrupción real del epoch vigente.

## Invariantes y pruebas

- Sin export semánticamente verificado y restorable no existe plan committable.
- Bundle drift, CURRENT drift, identidad drift o reader activo no borran nada.
- Fault injection en cada objeto, CURRENT y cada delete converge a un epoch.
- El conjunto activo visible antes/después es byte-idéntico por record raw;
  checkpoint, working_state y store/project UUID se preservan.
- Refuted/superseded no reaparecen en scan, index, resume ni MCP.
- `verify(old)` es archived y liga manifest/epoch; `verify(current)` es present.
- Backup restore recrea el source pre-compaction completo.
- Catálogos/schemas docs-package y wheel limpio pasan gates.

## No incluido

Purga del bundle externo, compactación remota, merge de stores, firma,
autenticidad criptográfica, adaptadores de proveedor o ejecución automática.
