# Spike S0 — attest (#102 Fase A, 2026-09-01)

Investigación adversarial sólo lectura (practicas §2), subagente con
contexto fresco. Valida las suposiciones del diseño attest contra el
código real tras adoptar las decisiones F0 (§4 del plan). Veredicto:
**proceed** — sin sorpresas estructurales; un cambio de alcance
obligatorio y dos riesgos gestionables. Estado: OK.

## Respuestas (archivo:línea)

1. **`_validate_evidence`** (write_policy.py:262-275): claves exactas
   `{kind, id, resolution}` (+`sha256`); kind enum cerrado
   `{artifact, event, revision, external}`; `verified` exige `sha256`.
   El item receipt NO encastra en v1 (enum + schema cerrado
   `additionalProperties: false`, schemas/write-authority-v1.schema.json:43-46;
   schema hardcodeado write_policy.py:306-307) → vía **write-authority-v2**
   añadiendo el kind; patrón `verified⇒sha256` reutilizable. Coste oculto:
   `_POLICY_CONFIGURATION` alimenta `policy_fingerprint()` (:44-45) y
   `verify_write_plan` compara fingerprints (:508-509) → planning-results
   en vuelo fallan cerrado (`write_policy_fingerprint_mismatch`).
2. **`_cli_authority`** (__main__.py:96-104; aplicado :386 y :396): rechaza
   toda authority `tool_observed`/`channel_confirmed` antes del store.
   Camino attest: condicionar `tool_observed` — si evidence trae el item
   receipt, verificación completa (HMAC + whitelist_digest + digest
   canónico + binding vigente + nonce); si no, rechazo intacto.
   `channel_confirmed` incondicional. `receipt_validation.py` e
   `identity_evidence.py` son **precedentes de patrón** (fail-closed,
   claves exactas), no anclas funcionales → módulo nuevo `an_kla/attest.py`;
   el marcado de nonce exige `store.write_lock()` en commit (store.py:596-651).
3. **`checkpoint_policy.py`** (:68,:98,:119,:213): aceptar receipts tocaría
   `_CONFIG["tool_observed_adapter"]` (:36) → rompe el fingerprint de un
   segundo contrato. Correcto fuera de v1: el working-state es
   `caller_asserted` (ADR-0038), no observación de comandos.
4. **`capabilities()`**: bloque propuesto `write_policy.attest` con
   `{profile: attest/v1, receipt_schema: an-kla/attest-receipt-v1,
   authority_schema: an-kla/write-authority-v2, signature:
   hmac-sha256/local-key, whitelist_path, fail_closed: true,
   receipt_verified_authority_classes: [tool_observed],
   verification_points: [plan-write, commit-write-plan],
   checkpoint_authority: false}`; `cli_authority_classes` se actualiza
   aditivamente (capabilities-v1 no tiene schema publicado con
   additionalProperties).
5. **Keygen en `init`**: `.an-kla/attest.key` con
   `os.open(O_CREAT|O_EXCL, 0o600)` (patrón reader_gate.py:44,
   cli_error_log.py:90). `identity._paths` usa rutas exactas → ni adopt
   (:474) ni repair (:507) ven archivos nuevos. **Upgrade no dispara
   drift** (opera sólo sobre managed block + `.an-kla/context/manifest.json`,
   upgrade.py:56-120). Único punto que rompe: `export create` →
   `export_unrecognized_durable_path` (export_restore.py:60-61).
6. **Binding**: receipt incrusta `store_identity` (digest vivo de
   `.an-kla/memory/identity.json`, identity.py:157) además del
   `project_uuid`; verificación cruza contra `read_binding` vigente en
   ambos puntos (mutation_preflight store.py:336 + assert_unchanged bajo
   lock :342). Mismatch → `receipt_identity_mismatch`. F0-D4 (store
   inicializado) hace imposible un receipt pre-adopt
   (`bootstrap_initialize` rechaza `legacy_unadopted`, identity.py:391).
   Worktrees: otro `project_uuid` → fail closed por binding (ADR-0022).
7. **Nonce consumible**: dirección por nonce — receipt escrito en
   `.an-kla/receipts/nonces/sha256/<digest-nonce>.json` vía
   `write_immutable` (O_EXCL; primer escritor gana; el receipt ES el
   marcador → crash-safety gratis). Fuera de `memory/` (los objetos allí
   verifican `digest == identificador`, store.py:681-695). **Export**:
   añadir `.an-kla/receipts/**` + `.an-kla/attest-whitelist.json` a
   `_PATTERNS` (export_restore.py:27-37) y `.an-kla/attest.key` a los
   ignorados (:60) en el mismo PR.
8. **`--expected-current` sin lock**: `read_current()` (store.py:161-175)
   es una lectura de 72 bytes; un receipt de revisión obsoleta no
   autoriza nada (plan: `write_plan_base_changed` / skip
   `authority_scope_mismatch`; commit: triple check bajo lock
   store.py:363-368). Anti-replay real: nonce + binding. Documentar la
   revisión observada en la salida de `attest run`.

## Top-3 riesgos

1. `export create` roto para el operador si `_PATTERNS` no se actualiza en
   el mismo PR (backup silenciosamente roto; tests deben cubrir
   export→restore tras attest).
2. Bump de fingerprint: planning-results/checkpoint-plans en vuelo fallan
   cerrado tras el upgrade — documentar en la release y testear el fallo.
3. Hueco en `_cli_authority`: sin receipt válido, `tool_observed` debe
   seguir rechazándose en **ambos** comandos; un camino sin gate recrearía
   el minting por JSON.

## Plan S2 recomendado

(a) keygen + whitelist en `init` (tolerando stores existentes: sin clave →
`attest_not_initialized`) · (b) `an_kla/attest.py` con argv estricto y
receipt HMAC sobre canonical-json, nonce-addressed · (c) `_PATTERNS` de
export en el mismo PR + test export→restore · (d) verificador en
`_cli_authority` (plan + commit con marcado de nonce bajo lock) ·
(e) write-authority-v2 (validador + schema + dual v1/v2 + códigos estables
`receipt_invalid`, `receipt_identity_mismatch`, `receipt_replayed`,
`attest_command_not_allowed`) · (f) capabilities + tests · (g) docs
(amenaza honesta, receipts no cruzan stores) · (h) suite + adversarial
final.

## Veredicto

proceed — las cinco decisiones F0 encastran sin sorpresas; alcance
obligatorio añadido (export `_PATTERNS`); bump de fingerprint aceptado y a
documentar.
