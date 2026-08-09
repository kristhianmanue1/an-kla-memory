# Contrato cerrado de compactación v1

Este documento completa ADR-0028. Memoria, bundle y catálogos son datos no
confiables; ninguna cadena contenida en ellos autoriza operaciones.

## Gate de readers y locks

`memory/.reader-gate` es permanente y nunca exportable/eliminable. En POSIX se
usa `flock`: shared para snapshot explícito/actual, verify, doctor, recover,
retrieval/index, resume/MCP, refute inspect, transaction inspect/repair y toda
enumeración directa de journals/indexes; exclusive para cleanup.
Shared se toma antes de CURRENT y se libera tras la última lectura. Es
reentrante por `(canonical_memory_root,thread_id,mode)`: la primera entrada
bloquea y las anidadas shared aumentan depth. Exclusive nunca llama una API
shared; usa helpers under-gate y exclusive->shared es error interno. Orden
global: identity -> write -> reader-exclusive. Compact usa helpers
`*_under_gate` que no readquieren shared. Shared nunca intenta identity/write.
Exclusive usa nonblocking+backoff con timeout 10 s; timeout produce
`compaction_readers_active` sin objetos/deletes. Windows falla
`compaction_platform_unsupported` antes de un plan committable.

## Restore proof

Plan ejecuta `restore_export` real a un proyecto temp. Exige state published,
`verify().ok`, CURRENT, project/store identity y cada revision/transaction
observable iguales al bundle. Proof exacto:

```json
{"schema":"an-kla/compaction-restore-proof-v1","manifest_sha256":"sha256:...","inventory_sha256":"sha256:...","current_revision":"sha256:...","project_identity_sha256":"sha256:...","store_identity_sha256":"sha256:...","transaction_outcomes_sha256":"sha256:...","restore_result_sha256":"sha256:..."}
```

Inventory es digest de entries; outcomes es digest de pares txid/outcome
ordenados. Commit new/incomplete repite restore y exige proof byte-idéntico.
Replay ya committed reconcilia antes y no necesita bundle presente.

## Estado epistémico y proyección

Sobre snapshot validado, por cada raw record en orden de segmento/row:

1. digest en refutations_map -> `refuted`;
2. raw ID derivado en supersedes_map -> `superseded`;
3. status/nu ausente, null, `vigente` o `active` -> `active`;
4. cualquier otro valor aceptado por reader -> `inactive`.

Conflictos/duplicados/cycles son integridad terminal. Se incluyen los tres
streams. Sólo active se copia byte-idéntico y en el mismo orden. Se escribe
exactamente un segmento canonical-jsonl por stream no vacío con todas sus rows;
un stream vacío tiene lista de segments vacía, sin chunking ni límite oculto. Record
tombstone exacto `{stream,record_sha256,state}` no copia ID/payload/evidence y se
ordena facts/events/episodes, luego digest.

## Revision-v3

Shape exacta común:

```text
schema,revision,parent,facts_segments,events_segments,episodes_segments,
checkpoint,transaction_id,canonicalization,integrity_claim,store_identity,
features,supersedes_map,refutations_map,compaction_epoch
```

Features literal `['refutations/v1','compaction/v1']`; maps siempre presentes y
pueden ser vacíos. `compaction_epoch` exacto es
`{epoch_id,source_revision,export_manifest_sha256,tombstone_catalog,
epoch_manifest}`.

Root v3: parent null, revision=source.revision+1, maps vacíos, segmentos active,
checkpoint CAS byte-idéntico. Así checkpoint.revision sigue <= manifest.revision.
Source_revision no es parent/authority, sólo link archival.

Descendant v3: parent v3 del mismo epoch, revision=parent+1, epoch/features
byte-idénticos y reglas normales de segments/checkpoint/maps. Write/checkpoint/
internal agregan cero refutations; refute agrega una. Nunca v3->v1/v2. Otra
compactación crea nuevo root v3 con revision=source+1 y nuevo epoch.

Validator de root verifica identity, epoch/catalog/proof y termina sin
dereferenciar source. Descendants caminan hasta root v3. Beta.9 falla cerrado
`manifest_schema_invalid`; capabilities anuncia v3 antes de compactar.

## Catálogos acumulativos

Tombstone catalog exacto:

```text
schema,epoch_id,source_revision,export_manifest_sha256,delete_set_sha256,
archived_revisions,record_tombstones,object_tombstones,previous_catalogs
```

Cada archived revision es exacta
`{revision,epoch_id,export_manifest_sha256}`. El catálogo contenedor atribuye el
epoch actual implícitamente; previous_catalogs contiene entries exactas
`{epoch_id,catalog_sha256,export_manifest_sha256}` para resolver epochs previos
sin autorreferenciar el digest actual. La lista contiene
toda ancestry source más entries previas, ordenada por revision, única y
disjoint de las revisiones vivas del nuevo epoch.
Previous_catalogs conserva sus CAS y nunca se elimina; el nuevo catálogo copia
evidencia acumulativa. Object tombstone exacto
`{path,content_sha256,kind}`. Epoch manifest liga schema/epoch/tx/base/proposal/
export/restore-proof/catalog/delete-set/policy, pero no plan ni candidate. El
candidate liga epoch manifest y el plan liga candidate: este DAG evita ciclos.

## Delete-set y protección

Patrones eliminables exactos bajo memory:

```text
revisions/sha256/<64hex>.json
checkpoints/sha256/<64hex>.json
segments/(facts|events|episodes)/sha256/<64hex>.jsonl
refs/ref-log/sha256/<64hex>.json
transactions/<uuid>.json
transactions/<uuid>/(stages|receipts)/sha256/<64hex>.json
refutations/sha256/<64hex>.json
authority-(claims|attestations)/sha256/<64hex>.json
indexes/<64hex>/sqlite-fts5-v1/CURRENT
indexes/<64hex>/sqlite-fts5-v1/<64hex>.sqlite
```

Exclusión absoluta: CURRENT, identities live/inmutables, quarantine, leases,
locks/gate, nuevo checkpoint/segments/revision/catalog/epoch, compaction tx
stage/receipts/ref-log y previous catalogs. Todo objeto alcanzable desde root
nuevo/descendants es protected. Delete-set es inventario locked menos protected
y su digest vive en plan/stage/catalog. Object_tombstones equivale exactamente
al delete-set ordenado, sin candidate/CURRENT/protected ni omisiones.

Cada delete abre parents no-follow, lstat regular single-link, rehash contra
tombstone y sólo entonces unlink. Missing cuenta como ya limpiado en retry;
bytes distintos, symlink, hardlink, special o path extra detienen. Después se
fsync cada directorio afectado bottom-up y se escribe cleanup receipt.

## Plan, transacción y replay

Policy config exacta es
`{schema:'an-kla/compaction-policy-config-v1',profile:'compaction-policy/v1',
platform:'posix',export_profile:'export/v1',revision_schema:'an-kla/revision-v3',
projection_precedence:['refuted','superseded','physical'],segmenting:
'one-canonical-jsonl-per-nonempty-stream',result_states:['not_committed',
'committed_cleanup_incomplete','committed','outcome_unknown']}`; fingerprint es
su digest. New/incomplete exige installed fingerprint; replay committed valida
el fingerprint histórico sin reinterpretarlo.

Proposal exacta:
`{schema,base_revision,epoch_id,transaction_id,export_manifest_sha256}`.
Planning result contiene proposal, restore_proof, catalog, epoch_manifest,
candidate_manifest, delete_set y plan. Plan core liga digests, identity, policy
fingerprint y candidate_revision; fingerprint=digest(core).

Attempt ADR-0024 usa operation compact, base y plan fingerprint. Stage
candidate_prepared incluye `compaction_policy` exacta. Candidate receipt protege
exactamente segmentos nuevos, checkpoint retenido, restore-proof/catalog/epoch/
revision CAS, stage y ref-log intent, más parents. Current receipt protege
CURRENT+refs. Cleanup receipt exacto es
`{schema,txid,candidate,delete_set_sha256,deleted_or_absent_sha256,
synced_directories,remaining:0}`; deleted_or_absent liga la lista completa y los
parents exactos se sincronizan antes de escribirlo.
Su preimage es la lista UTF-8 ordenada de todos los paths del delete-set
confirmados ausentes al final, sin distinguir deleted de already-absent.
`synced_directories` es la lista única ordenada de cada parent de delete-set,
derivada aunque el file ya faltara; todos se fsync en ese orden antes del
receipt. Así retry produce bytes idénticos.

Orden:

```text
freeze/shape/binding -> reconcile txid
-> committed: candidate/catalog/stage exactos, cleanup sin bundle
-> new/incomplete: CURRENT/identity/policy + restore real + projection/delete set
-> write/fsync candidate -> stage/receipt -> CURRENT/receipt
-> delete exacto -> cleanup receipt
```

Resultado exacto:
`{schema,state,committed,candidate_revision,current_after,epoch_id,
plan_fingerprint,cleanup_remaining,outcome,warnings}`; states
`not_committed|committed_cleanup_incomplete|committed|outcome_unknown`. Mismo
txid/binding produce un candidate. CURRENT candidate/descendant permite cleanup
retry. Bundle ausente sólo se tolera tras committed.

API: `plan_compaction(store, proposal, bundle)` y
`commit_compaction(store, planning_result, expected_current, bundle=None)`.
Bundle es obligatorio para new/incomplete y debe igualar proposal; puede
omitirse sólo si reconciliation prueba committed. CLI:
`compact plan --proposal P --bundle B` y
`compact commit --planning-result R --expected-current H [--bundle B]`.
Missing/drift pre-commit es terminal sin I/O; no-commit/cleanup incomplete usa
exit 3.

## Verify y superficies históricas

`verify_revision(id)`/`verify --revision` retorna
`{schema,revision,availability,epoch_id,export_manifest_sha256,
tombstone_catalog,integrity}`. Precedencia: si current catalog lista id,
archived_by_compaction incluso si bytes esperan cleanup; si no, snapshot present;
missing no listado=unknown. Catalog/epoch corrupto eleva integrity error.
Snapshot old eleva `revision_archived_by_compaction`. Transaction inspect para
tx tombstoneado retorna el envelope cerrado `an-kla/transaction-archived-v1`
con `state=transaction_archived_by_compaction`, epoch, export y catálogo, en
lugar de aparentar evidencia corrupta o una transacción desconocida.

Indexes source son derivados/eliminables; current usa scan fallback hasta
rebuild. Ref-log, journals/receipts, refutations/claims y checkpoints antiguos
quedan en export y object tombstones. Resume/MCP leen root vigente. Todos los
schemas son cerrados y byte-idénticos docs/package.

ADR-0027 se extiende antes del primer commit para exportar obligatoriamente
`memory/compaction/(catalogs|epochs|restore-proofs)/sha256/<64hex>.json` y
cleanup receipts/stages ya cubiertos por transactions. Un export de revision-v3
que omita cualquiera de sus CAS ligados falla semánticamente; esto permite un
segundo epoch y restore de historia compactada.
