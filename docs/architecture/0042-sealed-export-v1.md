# ADR-0042: export sellado (`sealed-export/v1`, extra opcional `[sealed]`)

- **Estado:** Aceptada como **diseño pre-code** por decisión del dueño
  (🔒 2026-08-21), quien ratificó el proceso completo del acta (once
  rondas de revisión: R1–R10 más la verificación del acto registral)
  (`adr-0042-precode-adversarial-2026-08-20.md`). La aceptación
  **autoriza únicamente el registro documental**: no la implementación,
  ni instalar `cryptography`/`[sealed]`, ni rama/PR/release/push, ni
  cerrar #46 como implementado.
- **Implementación:** Implementada (beta.18; PRs #93–#101, issue #46).
- **Fecha:** 2026-08-20 (partida en ADR corto + apéndice técnico en
  2026-08-28, #95)
- **Decide sobre:** confidencialidad y autenticidad en reposo del bundle de
  export; no decide atestación de autoría (F8-E), transporte seguro, ni
  sellado del manifiesto (diferido a un hipotético v3)
- **Detalle técnico:** el desglose normativo fila a fila de las secciones
  §1–§9 vive en
  [`refs/sealed-export-v1-appendix.md`](refs/sealed-export-v1-appendix.md).
  Este ADR declara la decisión y sus límites; las anclas `§N` se citan
  igual antes y después de la partición.

## Contexto

`export/v1` produce un bundle en claro y lo declara con honestidad
(`plaintext_export_contains_untrusted_memory_data`; ADR-0027: *"hashes dan
integridad accidental, no autenticidad ni confidencialidad"*). El bundle
sale del store por definición y los permisos POSIX del origen no viajan:
para consumidores cuyo payload es dato personal (kairos), el respaldo es
la parte menos protegida del sistema. La decisión documental
`issue-46-decision-2026-08-20.md` analizó las opciones y el maintainer
eligió **B**: extra opcional `[sealed]` con criptografía auditada en
core, fail-closed en todos los bordes, core por defecto sin dependencias.

Verificado en la decisión y re-verificado ahora: `cryptography` (46.x)
expone `AESGCM` (nonce 12 B) y `HKDF`; **no** expone XChaCha20 (sólo
PyNaCl/libsodium vía bindings de bajo nivel, sin clase AEAD). El repo es
stdlib-only en runtime (`[project]` sin `dependencies`; `jsonschema` es
extra de test).

## Decisión

**Perfil aditivo `sealed-export/v1` junto a `export/v1` intacto. El core
cifra con AES-256-GCM (`cryptography`, extra opcional `[sealed]
cryptography>=42`); el adaptador externo custodia la capacidad de
wrap/unwrap; el core genera una CEK efímera y no serializa ni escribe
**intencionalmente** CEK ni subclaves en bundle, staging, logs,
warnings ni resultados (la materialización posible por el SO/runtime
—swap, hibernación, dumps, copias— queda fuera de garantía, §Límites);
toda falla es cerrada; jamás hay degradación a claro.**

Las reglas congeladas por sección — cada una con su desglose normativo
completo en el
[apéndice técnico](refs/sealed-export-v1-appendix.md) — son:

- **§1 Algoritmo y librería**: AES-256-GCM + HKDF-SHA256 de
  `cryptography>=42` (extra `[sealed]`); subclaves por propósito vía
  `HKDFExpand` con `info` separado (`aead_key`, `bundle_id_raw`,
  `mac_key`) — la CEK raíz jamás es clave AES directa; CEK de 32 bytes
  del CSPRNG del SO, una por bundle, viva sólo en memoria del proceso
  durante la operación (F1, F7); custodia de wrap/unwrap exclusiva del
  adaptador.
- **§2 Schemas y gramática CLI**: manifiesto `export-manifest-v2` con
  `seal` y `core`/`manifest_sha256` con shape v1; resultados v2 propios
  (`export-result-v2`, `export-restore-result-v2`,
  `export-verify-result-v2`) y contrato `sealing-adapter-contract-v1`;
  `wrapped_cek` base64 ≤ 4096 chars; CLI `export create --seal
  sealed-export/v1 --key-adapter …` con argv estructurado sin shell
  (flags repetibles, jamás split de un string con espacios).
- **§3 Compatibilidad**: `export/v1` intacto (create/verify/restore sin
  cambios); un bundle sellado jamás es restaurable por el camino v1 —
  la ausencia de downgrade es estructural; `content_sha256` siempre
  sobre el plano; la compactación sigue exigiendo bundle v1 en claro
  (sellado es respaldo, no insumo de compactación).
- **§4 Adaptador externo de claves**: proceso externo con contrato JSON
  por stdio (`wrap`/`unwrap`); `wrapped_cek` opaco; runner acotado —
  argv sin shell, JSON cerrado, límites de I/O leídos incrementalmente
  (stdin 8 KiB / stdout 64 KiB / stderr 8 KiB, descartado), timeout de
  30 s, terminación del árbol de procesos, entorno mínimo con allowlist
  explícita (`--key-adapter-env`); cero destino publicado parcial
  (staging hermano + renombrado atómico, F6); stderr del adaptador
  jamás se propaga.
- **§5 Fail-closed y sin downgrade**: enum cerrado —
  `sealing_extra_not_installed`, `sealing_adapter_required`,
  `sealing_adapter_error`, `sealed_payload_auth_failed` (código único
  para todo fallo autenticado, sin oráculo), `sealed_entry_too_large`,
  `sealing_adapter_id_invalid`, `unsupported_export_profile`. No existe
  rama que "intente claro como fallback"; sin restauración parcial.
- **§6 Nonce, AAD y MAC del manifiesto**: nonce = contador puro
  0-based congelado a 12 bytes (`i.to_bytes(12, "big")`), jamás en
  disco; AAD por entrada = `UTF8(perfil) || bundle_id (16 B crudos) ||
  canonical_json(entry)`; `manifest_mac` = HMAC-SHA256 sobre el
  transcript canónico completo (incluye `seal`), comparación constante
  en tiempo; layout físico idéntico a v1 (`entries/<path>`, tamaño
  `size + 16`); `max_entry_bytes = 512 MiB` por entrada, sin chunking.
- **§7 Fugas residuales**: el manifiesto v2 va en claro y expone
  metadatos de composición y actividad del store (conteos, tamaños,
  categorías, estructura relativa) — precio de la verificación
  estructural sin clave; el bundle no es byte-reproducible (CEK
  aleatoria), lo preservado y probado es el store restaurado
  byte-idéntico; warnings sin cruce por perfil.
- **§8 Verify dual**: sin clave es estructural y honesto — jamás
  `verified: true`, `diagnostics` enum cerrado con mapeo congelado
  (`manifest_invalid`, `entry_size_mismatch`, `entry_missing`,
  `entry_unexpected`, `unsafe_path`, `count_mismatch`); con adaptador,
  autenticado completo (AEAD + MAC + `content_sha256` del plano).
- **§9 Matriz de pruebas y gate de publicación**: 16 filas congeladas
  (detalle fila a fila en el apéndice) consolidadas en
  `tests/test_sealed_matrix.py`; gate REL sobre ambos perfiles de
  instalación (clean wheel sin extra: camino v1 y suite verde; con
  extra: matriz sellada completa) + gate de upgrade beta.17→18
  (`scripts/check_beta17_upgrade.py`) ejercitando `--seal` contra
  `scripts/gate_sealed_adapter.py` (adaptador determinístico, sólo
  gates, nunca en el paquete).

## Por qué no [alternativa]

- **A (dependencia dura)**: rompe la promesa stdlib-only para todo
  usuario; supply-chain ampliada sin necesidad.
- **C (crypto casera en stdlib)**: reimplementar AEAD/HKDF a mano.
- **D (delegación total al adaptador)**: cero dependencias, pero el core
  no puede testear las invariantes (nonce/AAD/MAC) y la corrección
  criptográfica queda fuera de las pruebas del repo (análisis completo
  en `issue-46-decision-2026-08-20.md`).
- **Sellado del manifiesto (v2 del perfil)**: pierde verify sin clave;
  diferido hasta demanda real.
- **XChaCha20-Poly1305**: no expuesto por `cryptography` (sólo PyNaCl
  via bindings); AES-256-GCM cumple con **nonce contador inyectivo
  dentro de cada bundle y `aead_key` independiente por CEK**.

## Consecuencias

- Positivas: el respaldo — la parte menos protegida del sistema para
  consumidores con dato personal — queda cifrado en reposo con
  criptografía auditada, sin romper `export/v1` ni la promesa
  stdlib-only por defecto.
- Negativas: fugas de metadatos por el manifiesto en claro (§7); el
  sellado no es atestación de origen (§Límites); la compactación sellada
  no existe (§3).
- Neutras: `cryptography>=42` sólo para quien instale el extra; el
  core por defecto sigue siendo stdlib-only.

## Límites

- Confidencialidad **en reposo del bundle**; no protege el store vivo
  (permisos del filesystem), ni el transporte, ni autentica al operador.
- El sellado no convierte la memoria restaurada en confiable
  (`untrusted_memory_data` sigue true).
- La CEK existe en memoria del proceso durante create/restore/unwrap:
  un atacante con acceso al proceso vivo la observa; el modelo es
  "lector del destino del respaldo", no "adversario en el host".
- **Swap, hibernación, crash dumps y copias del runtime** (fork,
  snapshots de VM, backups de memoria) pueden materializar la CEK en
  disco **sin escritura intencional del core**: fuera de toda garantía
  de esta decisión; un consumidor con requisito estricto configura
  swap cifrado o deshabilita dumps a nivel de SO.
- El adaptador es confianza externa: AN-KLA no audita su correctitud; un
  adaptador roto produce `sealing_adapter_error`, uno débil produce
  `wrapped_cek` débil (la confianza criptográfica de reposo sigue en la
  CEK/AES-GCM del core, pero la disponibilidad de la clave es del
  adaptador).
- **El sello da integridad bajo una clave, no atestación de origen**
  (corregido tras ronda pre-code; la atestación es F8-E, diferida): con
  un adaptador de clave pública (age/KMS), un atacante puede **re-sellar
  el bundle completo** con su propia CEK y el `restore` del operador
  tendría éxito con contenido del atacante. La defensa disponible es la
  comparación fuera de línea: `export-result-v2` **debe** devolver
  `bundle_id` y `manifest_sha256` al crear, para que el operador los
  registre y compare antes de restaurar un respaldo (ancla manual, no
  automática). Con adaptador simétrico (passphrase/Keychain/YubiKey) la
  sustitución cae en unwrap-fail. `seal` en sí no lleva MAC propio: una
  `wrapped_cek` sustituida falla al desencriptar o en `manifest_mac`
  (denegación posible; la falsificación bajo la clave correcta, no).

## Test de regresión

- `tests/test_sealed_matrix.py` — matriz §9 consolidada (16 filas
  identificables, incluida la taxonomía de warnings y la reescritura
  completa del bundle).
- `tests/test_sealed_bundle.py`, `tests/test_sealed_kdf.py`,
  `tests/test_sealed_cek.py`, `tests/test_sealed_key_adapter.py`,
  `tests/test_sealed_schemas_v2.py`,
  `tests/test_export_sealed_cli.py` — criptografía del bundle, KDF/CEK,
  runner del adaptador y schemas v2 contra las reglas congeladas.
- `scripts/check_beta17_upgrade.py` + `scripts/gate_sealed_adapter.py`
  — gate de upgrade con `--seal` end-to-end.

## Referencias

- Issue #46 (diseño del consumidor, §§1-10) y su ronda
  (`issue-46-decision-adversarial-2026-08-20.md`); decisión del
  maintainer 2026-08-20 (opción B).
- ADR-0027 (export/restore verificable, honestidad del plaintext);
  ADR-0028 (compactación y restore-proof); ADR-0031 (frontera general
  de custodia y propiedad de la memoria — **sin** atribuirle decisión
  criptográfica alguna sobre generación de claves, que no contiene).
- [Apéndice técnico](refs/sealed-export-v1-appendix.md) — desglose
  normativo de §1–§9 (partición de #95).
- `docs/practicas-ingenieria.md` (ronda pre-code, ADR-antes-que-código).
