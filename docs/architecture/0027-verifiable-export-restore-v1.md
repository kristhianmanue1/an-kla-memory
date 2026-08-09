# ADR-0027: export verificable y restore fail-closed v1

- Estado: Aceptado e implementado localmente; gate de implementación `PROCEED`
- Fecha: 2026-08-08
- Gate: ronda adversarial pre-code obligatoria

## Contexto

Refute conserva historia, pero compactar sin una copia externa verificable haría
irreversible un error de retención. Un backup debe preservar la revisión
autoritativa, identidad, objetos CAS y evidencia transaccional necesaria para
volver a ejecutar `snapshot()` y `verify()`.

## Decisión

Se introduce un bundle-directory `an-kla/export-v1`. Export no cambia estado
durable y captura bajo el orden global de locks de ADR-0022 (identity antes de
write). Dentro del lock enumera y lee la superficie exacta; ningún journal,
receipt o bootstrap puede variar durante la captura.

La allowlist exacta bajo `anchor/` incluye `project-identity.json`,
`identity-intent.json` sólo si representa una operación completa verificable,
`identity-intents/sha256/**`, `identity-receipts/sha256/**`; y bajo
`anchor/memory/`: `identity.json`, `identities/sha256/**`, `refs/CURRENT`,
`refs/ref-log/sha256/**`, revisions, checkpoints, los tres namespaces de
segments, refutations, authority claims/attestations y transactions (journal
UUID y `stages|receipts/sha256/**`). Excluye locks, leases, indexes, quarantine
y contexto. La gramática cerrada es:

```text
anchor/project-identity.json
anchor/identity-intent.json                         (0..1)
anchor/(identity-intents|identity-receipts)/sha256/<64hex>.json
anchor/memory/identity.json
anchor/memory/identities/sha256/<64hex>.json
anchor/memory/refs/CURRENT
anchor/memory/refs/ref-log/sha256/<64hex>.json
anchor/memory/(revisions|checkpoints|refutations|authority-claims|authority-attestations)/sha256/<64hex>.json
anchor/memory/segments/(facts|events|episodes)/sha256/<64hex>.jsonl
anchor/memory/transactions/<canonical-rfc4122-uuid>.json
anchor/memory/transactions/<canonical-rfc4122-uuid>/(stages|receipts)/sha256/<64hex>.json
anchor/memory/compaction/(catalogs|epochs|restore-proofs)/sha256/<64hex>.json
```

Project identity, store identity, CURRENT, al menos una revision y checkpoint
son obligatorios; los demás patrones admiten cero o más. Cualquier otra
profundidad, basename, extensión o archivo regular es extra inválido.

El bundle exacto es `manifest.json` más `entries/anchor/**`, sin otro archivo.
Manifest tiene exactamente `{schema,profile,core,manifest_sha256}`; core tiene
`current_revision,project_identity_sha256,store_identity_sha256,entry_count,
total_bytes,entries`; cada entry exacta es `{path,size,content_sha256}`. Entries
están ordenadas/son únicas por bytes UTF-8 y
`manifest_sha256=digest_json(core)`. Path empieza `anchor/`, NFC, `/`, ASCII de
namespace, sin absolutos, vacíos, `.`/`..`, backslash, colisiones NFC o
case-fold. CURRENT debe contener literalmente `current_revision`; identity
digests deben corresponder a sus entries y al manifest/revision ligados.

`verify-export` primero autentica manifest/bytes sin materializar. Usa `lstat`
en todos los ancestors, rechaza symlink/especial/hardlink (`st_nlink!=1`), abre
relativo con no-follow y compara `fstat` antes/después. Si la plataforma no
ofrece apertura descriptor-relative/no-follow o un fallback que revalide
identidad de todos los ancestors inmediatamente antes y después del read, falla
`export_platform_unsafe`; nunca degrada. Rechaza
extras, faltantes y supera límites explícitos (default 100000 files/10 GiB).
Luego copia los bytes autenticados desde los mismos descriptors, o reabre y
rehash; en ambos casos rehash de cada archivo staged contra manifest es
obligatorio antes de `MemoryStore.verify()`. No repara/completa. Soporta sólo
profile v1 y Python 3.9+.

Restore/import v1 es no-merge: project root puede contener archivos ordinarios,
pero `.an-kla` debe no existir; cualquier identidad/estado parcial falla antes
de staging. Verifica el bundle, crea staging hermano con modo 0700, archivos
0600, verifica sin reparar, fsync bottom-up, renombra el `anchor` completo a
`.an-kla` y fsync del project root. Outcomes cerrados: `not_published`,
`published`, `published_durability_incomplete`, `outcome_unknown`; tras rename
no se borra ni se hace rollback y se exige `verify` si no hay éxito completo.
La identidad se conserva y root relocalizada se reporta.

`backup create|verify|restore` reutiliza exactamente este contrato. No hay
overwrite, merge, redacción, red remota ni cifrado en v1.
El bundle se crea exclusivamente (sin overwrite) con 0700/0600, emite warning
estable `plaintext_export_contains_untrusted_memory_data` y no registra
payloads. Hashes dan integridad accidental, no autenticidad ni confidencialidad.

## Invariantes y pruebas

- Export no muta estado durable y captura con locks en orden global.
- Missing/extra/tampered/symlink/traversal fallan cerrado.
- `.an-kla` existente falla antes de copiar; archivos ordinarios externos se
  conservan. Fault injection pre-publicación deja cero `.an-kla` destino.
- Roundtrip preserva CURRENT, identidad, snapshots, refutations y outcomes.
- Wheel incluye schemas; docs/package son byte-idénticos.

## Fuera de alcance

Merge, export parcial, adapters de proveedor, object storage, claves,
compactación y borrado. ADR-0028 no avanza a código hasta demostrar roundtrip
y cerrar la ronda adversarial de este contrato.
