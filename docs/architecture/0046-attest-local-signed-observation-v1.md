# ADR-0046: atestación de observación local firmada (`attest`)

- **Estado:** Propuesta (ronda adversarial pre-code pendiente; implementación requiere orden explícita del maintainer)
- **Fecha:** 2026-09-01
- **Decide sobre:** cómo un agente honesto operando el CLI standalone puede registrar autoridad `tool_observed` legítima (issue #102 Fase A); no decide hooks del host (#56/ADR-0047), identidad de agente (#58/G4) ni checkpoint-authority
- **Entradas:** decisiones F0 adoptadas (plan #102 §4), spike S0 (`docs/planning/issue-102-attest-spike-2026-09-01.md`, veredicto proceed)

## Contexto

`evaluate_write` capsula lo no-observado: `tool_observed` exige evidence
`resolution: verified` (write_policy.py:416-420) y `issuer.kind: "tool"`
(:327); desde JSON puro sólo es fabricable `model_derived`/
`derived_from_retrieval` (techo `summary`). `_cli_authority`
(__main__.py:96-104) rechaza además la clase en plan-write y
commit-write-plan (`cli_privileged_authority_unresolved`). Resultado: la
memoria jamás distingue "el agente lo observó" de "el agente lo inventó",
ni siquiera para hechos verificables trivialmente. El consumidor real
(infosalud, ADR-007 local) lo reportó con repro.

## Decisión

**Subcomando `attest` que acuña receipts firmados por el motor, y un
camino de verificación que convierte un receipt válido en autoridad
`tool_observed`.** El agente nunca fabrica la clase: sólo invoca.

1. **Firma HMAC-SHA256 stdlib** (F0-D1). Clave local
   `.an-kla/attest.key` generada en `init` (`O_CREAT|O_EXCL`, 0o600;
   stores existentes: sin clave → `attest_not_initialized`). Modelo de
   amenaza honesto: no frena a un agente con shell completo (puede leer
   la clave); el valor es procedencia auditable para agentes honestos y
   cadena de receipts verificable, no defensa contra maliciosos.
2. **Whitelist fail-closed** (F0-D3): `.an-kla/attest-whitelist.json` con
   patrones de comandos sólo-lectura (inicial: `git rev-parse`, `git
   diff`, `unittest discover`, digest de artefactos). Ejecución argv
   estricto sin shell ni herencia de entorno sensible. Cada receipt
   incrusta `whitelist_digest`; el estado de la whitelist es observable
   en `status`/`context_diagnostics` (§11.1). Su edición queda fuera del
   write-policy (config local del operador, como el lock).
3. **Receipt `an-kla/attest-receipt-v1`**: canonical-json firmado con
   `{command, exit_code, stdout_digest, stderr_digest, project_uuid,
   store_identity, whitelist_digest, base_revision, nonce, observed_at,
   policy_fingerprint}`. Escritura **nonce-addressed** en
   `.an-kla/receipts/nonces/sha256/` vía `write_immutable` (primer
   escritor gana; el receipt es su propio marcador de consumo —
   crash-safety sin estados intermedios). `attest run --expected-current
   <sha256> -- <cmd>` incrusta la revisión observada para diagnóstico; la
   ligadura real ocurre en los puntos de verificación.
4. **Verificación en `_cli_authority`** (plan-write y commit-write-plan):
   `tool_observed` se acepta sólo con evidence
   `{kind: attestation_receipt, id: <receipt_id>, sha256: <digest del
   receipt canónico>, resolution: verified}` cuya verificación incluya
   HMAC válido, comando en whitelist (cruce con `whitelist_digest`
   vigente), digest íntegro, binding vigente (`read_binding` —
   `receipt_identity_mismatch` si difiere) y nonce no consumido
   (`receipt_replayed`). Marcado del nonce bajo `store.write_lock()` en
   commit. Sin receipt válido, el rechazo actual se mantiene íntegro en
   ambos comandos. `channel_confirmed` sigue incondicional.
5. **`write-authority-v2`**: el enum cerrado de `evidence[].kind` añade
   `attestation_receipt`; validador con aceptación dual v1/v2 y schemas
   publicados. Bump de `policy_fingerprint` aceptado: planning-results en
   vuelo fallan cerrado (`write_policy_fingerprint_mismatch`) — se
   documenta en la release y se testea.
6. **Export/backup**: `.an-kla/receipts/**` y
   `.an-kla/attest-whitelist.json` entran a `_PATTERNS` de
   `export_restore.py`; `.an-kla/attest.key` queda en los ignorados (la
   clave no viaja en export) — en el mismo PR que keygen/attest
   (spike, riesgo 1).
7. **Alcance excluido (F0-D5)**: checkpoint-authority NO obtiene el camino
   attest en v1 (`checkpoint_policy.py` intacto; el working-state es
   `caller_asserted` por ADR-0038, no observación de comandos). F0-D4:
   attest requiere store con identidad completa.

## Por qué no [alternativas]

- **Ed25519 vía extra `cryptography`** (patrón `sealed`): más hardness
  contra falsificación de receipts, pero rompe el runtime stdlib-only
  para el caso base y su valor marginal es bajo frente al modelo de
  amenaza declarado (la clave vive en el mismo host). El diseño deja el
  campo `signature` versionable por si un perfil futuro lo añade.
- **Confiar en el host adapter** (`tool_observed` sólo vía hosts como
  Cline): correcto a futuro (ADR-0047/G2) pero deja fuera al CLI
  standalone — exactamente el caso del consumidor real que motivó #102.
- **Confiar campos autodeclarados** (`trusted`, `human_confirmed`): son
  datos, no autoridad (frontera de AN-KLA.md); elevaría autoridad por
  autodeclaración.

## Consecuencias

- Los agentes honestos pueden registrar observaciones reales con
  representación `full` (el techo `summary_required_for_authority_ceiling`
  deja de aplicar para receipts verificados), con cadena auditable.
- Dos superficies versionan a la vez: `write-authority-v2` y
  `capabilities()` (bloque `attest` + `cli_authority_classes`).
- Los receipts son datos: no autorizan comandos, no prueban corrección
  semántica, no cruzan stores (ADR-0022) y mueren con su binding.
- Coste: un snapshot de lectura por verificación; escrituras
  nonce-addressed append-only bajo `.an-kla/` (crecimiento lineal en usos;
  limpieza futura gobernada, nunca automática).

## Test de regresión

- Receipt válido → `tool_observed` aceptado en plan y commit (E2E con
  comando whitelisteado); receipt manipulado (comando, digest, exit_code)
  → `receipt_invalid`; nonce repetido → `receipt_replayed`; comando fuera
  de whitelist → `attest_command_not_allowed`; sin clave →
  `attest_not_initialized`; binding distinto (adopt/repair/worktree) →
  `receipt_identity_mismatch`.
- Sin receipt válido, `tool_observed` sigue rechazándose en ambos comandos
  (regresión del hueco del spike, riesgo 3).
- Export→restore tras attest roundtrip (riesgo 1); commit de un
  planning-result pre-bump → `write_policy_fingerprint_mismatch` (riesgo 2).

## Referencias

- Issue #102 y su plan: `docs/planning/plan-issue-102-attest-hardness-2026-09-01.md`
- Spike S0: `docs/planning/issue-102-attest-spike-2026-09-01.md`
- ADR-0007 (write-policy), ADR-0022 (identidad store/proyecto), ADR-0031/0039 (G-track), ADR-0047 (host hooks, pendiente)
