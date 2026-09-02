# ADR-0046: atestación de observación local firmada (`attest`)

- **Estado:** Aceptada — implementación S2 completa en el ciclo beta.21
  (commit ed64994, receipts HMAC, verificación bifásica CLI/engine,
  anti-replay por tombstone); F0 adoptadas por el maintainer (2026-09-01);
  ronda adversarial pre-code fix-and-retry absorbida; bump de plantilla
  del contrato ejecutado según §8.
- **Fecha:** 2026-09-01
- **Decide sobre:** cómo un agente honesto operando el CLI standalone puede registrar autoridad `tool_observed` legítima (issue #102 Fase A); no decide hooks del host (#56/ADR-0047), identidad de agente (#58/G4) ni checkpoint-authority
- **Entradas:** decisiones F0 adoptadas (plan #102 §4), spike S0 (veredicto proceed), ronda adversarial pre-code (`docs/planning/adr-0046-attest-precode-adversarial-2026-09-01.md`)

## Contexto

`evaluate_write` capsula lo no-observado: `tool_observed` exige evidence
`resolution: verified` (write_policy.py:416-420) y `issuer.kind: "tool"`
(:327); desde JSON puro sólo es fabricable `model_derived`/
`derived_from_retrieval` (techo `summary`). `_cli_authority`
(__main__.py:96-104) rechaza además la clase en plan-write y
commit-write-plan (`cli_privileged_authority_unresolved`). Resultado: la
memoria jamás distingue "el agente lo observó" de "el agente lo inventó".
El consumidor real (infosalud) lo reportó con repro (#102).

## Decisión

**Subcomando `attest` que acuña receipts firmados por el motor, y un
camino de verificación que convierte un receipt válido en autoridad
`tool_observed`.** Precisión de frontera (hallazgo HIGH absorbido): el
enforcement vive en la **superficie CLI**; la API Python
(`store.plan_write`/`commit_write_plan`) es caller-trusted (contrato
disciplinario AN-KLA.md:180-181) y recibe re-verificación + marcado en el
engine como defense-in-depth (§4). "El agente nunca fabrica la clase"
significa: por CLI, sólo puede *invocar*.

1. **Firma HMAC-SHA256 stdlib** (F0-D1). Clave local
   `.an-kla/attest.key` generada en `init` (`O_CREAT|O_EXCL`, 0o600;
   stores existentes: sin clave → `attest_not_initialized`). Modelo de
   amenaza honesto: no frena a un agente con shell completo (puede leer
   la clave y forjar receipts a mano); el valor es procedencia auditable
   para agentes honestos, no defensa contra maliciosos. La garantía es
   **procedencia de ejecución, no pureza del comando**: un receipt prueba
   que el motor ejecutó el comando y observó esa salida, no que el
   comando fuera inocuo.
2. **Whitelist fail-closed con matching exacto** (F0-D3, hallazgo MEDIUM
   absorbido): `.an-kla/attest-whitelist.json` con **argv completo exacto
   por comando** (sin matching por prefijo; denylist explícita dentro de
   cada patrón para banderas de escritura/ejecución: `--ext-diff`,
   `--textconv`, `--output=`, `-o`). Inicial: `git rev-parse …`, `git
   diff …` (sin las banderas denegadas), `python -m unittest discover …`,
   digest de artefactos. La etiqueta "sólo-lectura" describe la
   *intención* operacional: `unittest discover` ejecuta código del
   proyecto — se documenta tal cual. Cada receipt incrusta
   `whitelist_digest`; el digest vigente es observable en
   `status`/`context_diagnostics` (§11.1). Si el digest del receipt ≠
   vigente al verificar → `receipt_whitelist_changed` (fail-closed, en
   plan y en commit).
3. **Receipt `an-kla/attest-receipt-v1`** — dos objetos distintos
   (hallazgo BLOCKER absorbido):
   - **Receipt durable**, *content-addressed*:
     `receipts/receipts/sha256/<digest-canónico-del-receipt>.json`,
     escrito al acuñar vía `write_immutable`. Campos: `{schema,
     receipt_id, command, exit_code, stdout_digest, stderr_digest,
     project_uuid, store_identity, whitelist_digest, base_revision,
     nonce, observed_at, policy_fingerprint, receipt_hmac}` — HMAC sobre
     el canonical-json del resto. `receipt_id` existe en el schema y es el
     `id` del evidence item. `observed_at` y `nonce` con **reloj y uuid
     inyectables** para goldens deterministas (patrón `now_injectable`,
     capabilities.py:155). `attest run --expected-current <sha256> --timeout
     <s> -- <cmd>`: ejecución con **timeout duro** (kill → exit_code
     estable `attest_timeout`, sin receipt con autoridad); stdout/stderr
     se digieren en **streaming con cap** (salida mayor al cap → truncada
     y marcada `truncated: true` en el receipt).
   - **Tombstone de consumo**, *nonce-addressed*:
     `receipts/nonces/sha256/<digest-del-nonce>.json`, **creado —nunca
     comparado— con O_EXCL bajo `store.write_lock()` en
     `commit_write_plan`, después del CAS y en la misma sección crítica
     que `assert_unchanged`**. La idempotencia same-payload de
     `write_immutable` NO se usa como marcador: el camino attest trata
     conflicto O_EXCL como `receipt_replayed` (código estable, sin
     quarantine-retry silencioso; squatting previo de nonces sin clave →
     mismo fallo cerrado, self-DoS aceptado por el modelo de amenaza).
     Ventanas de crash: tombstone escrito y commit abortado = receipt
     quemado sin uso — fallo cerrado aceptable y documentado.
4. **Verificación en dos puntos**:
   - **plan-write** (`_cli_authority`): lookup determinista del receipt
     durable por el `sha256` del evidence item (falta el archivo →
     `receipt_invalid`); verifica HMAC, matching exacto de argv contra
     whitelist, `exit_code == 0` (receipts con exit != 0 se acuñan para
     diagnóstico pero **no otorgan autoridad**),
     `receipt.policy_fingerprint == vigente` (mismatch →
     `receipt_invalid`: los receipts mueren con cada bump de política —
     aceptado), binding vigente (`read_binding`; difiere →
     `receipt_identity_mismatch`), ausencia de tombstone (advisory: si ya
     existe → `receipt_replayed` temprano). Sin receipt válido,
     `tool_observed` sigue rechazándose con el código actual, en ambos
     comandos.
   - **commit-write-plan** (engine, bajo lock — hallazgo HIGH absorbido):
     re-verificación íntegra + **creación del tombstone** antes de
     construir el pending. Un solo portador gana; el segundo obtiene
     `receipt_replayed` con CURRENT intacto.
   - `channel_confirmed` sigue incondicional; el evidence item es
     `{kind: attestation_receipt, id: <receipt_id>, sha256: <digest>,
     resolution: verified}`.
5. **`write-authority-v2`**: enum de `evidence[].kind` añade
   `attestation_receipt`; validador con aceptación dual v1/v2 (v1 no puede
   expresar el kind nuevo — sin vía de elusión) y schemas publicados en
   `an_kla/schemas/` (también `attest-receipt-v1`). Bump de
   `policy_fingerprint` aceptado: planning-results en vuelo fallan
   cerrado — documentado en la release y testeado.
6. **Export/backup**: `receipts/**` y `attest-whitelist.json` entran a
   `_PATTERNS` de `export_restore.py`; `.an-kla/attest.key` queda en los
   ignorados. **Los receipts no sobreviven export/restore como
   verificables** (la clave es local): el test de roundtrip afirma el
   fallo cerrado de la re-verificación, no la re-validación. Receipts de
   otro proyecto arrastrados en un bundle: inertes por binding.
7. **Alcance excluido**: checkpoint-authority NO obtiene el camino attest
   (F0-D5; `checkpoint_policy.py` intacto). **`refute` tampoco** (ronda
   absorbida): los receipts attest NO alimentan `refute-authority-claim-v1`
   en v1 — refute sigue resolver-gated (`refute_policy.py:44`); test de
   regresión: claim `tool_observed` con evidence receipt vía CLI →
   fallo cerrado por resolver ausente. F0-D4: attest requiere store con
   identidad completa.
8. **Gobernanza de contratos observables** (ronda absorbida; enmienda de
   fase S2): `capabilities()` es estático — no puede sondar el store
   local — por lo que el condicionamiento "a store con clave" se expresa
   por campos adyacentes: `attest.requires_store_with_key: true` y
   `tool_observed_resolution: attest-receipt-v1`; `cli_authority_classes`
   declara las clases que el CLI *puede* resolver y
   `privileged_authority_requires_external_adapter: true` queda en true
   con su alcance real acotado por esos campos (channel_confirmed y
   refute siguen requiriendo adaptador externo; decisión final, no
   pendiente). **AN-KLA.md §Resolver autoridad**: la edición textual del
   contrato gestionado se ejecuta en el bump de plantilla (deuda ya
   declarada en beta.20 — editar aquí dispararía
   `managed_contract_modified` permanente en los stores); este ADR y
   `docs/write-policy-cli.md` son la superficie normativa vigente mientras
   tanto.

## Por qué no [alternativas]

- **Ed25519 vía extra `cryptography`** (patrón `sealed`): más hardness,
  pero rompe el runtime stdlib-only para el caso base y su valor marginal
  es bajo frente al modelo de amenaza declarado (la clave vive en el
  mismo host). `signature` es versionable por si un perfil futuro lo añade.
- **Confiar en el host adapter** (ADR-0047/G2): correcto a futuro pero
  deja fuera al CLI standalone — el caso del consumidor real que motivó #102.
- **Confiar campos autodeclarados** (`trusted`, `human_confirmed`): son
  datos, no autoridad (AN-KLA.md); elevaría autoridad por autodeclaración.
- **Marcador de consumo same-payload idempotente** (`write_immutable`
  existente tal cual): dos commits en paralelo "marcarían" con éxito con
  los mismos bytes — doble gasto silencioso (BLOCKER de la ronda). El
  tombstone debe crearse, nunca compararse.

## Consecuencias

- Los agentes honestos registran observaciones reales con representación
  `full` (el techo `summary_required_for_authority_ceiling` deja de
  aplicar para receipts verificados), con cadena auditable.
- Versionan a la vez: `write-authority-v2`, `capabilities()` y
  AN-KLA.md §autoridad; bump de fingerprint con fallo cerrado en vuelo.
- Los receipts son datos: no autorizan comandos, no prueban corrección
  semántica ni pureza del comando, no cruzan stores (ADR-0022) ni
  sobreviven restore como verificables, y mueren con su binding y con
  cada bump de política.
- Coste: una lectura de receipt por verificación + una escritura
  O_EXCL por commit portador; crecimiento lineal bajo `.an-kla/receipts/`
  (limpieza futura gobernada, nunca automática).

## Test de regresión

- E2E: receipt válido (comando whitelisteado, exit 0) → `tool_observed`
  aceptado en plan y commit; representación `full` commiteada.
- Manipulaciones → fallo cerrado con código estable: comando/exit_code/
  digest alterados (`receipt_invalid`), nonce repetido en paralelo
  (un commit gana, el otro `receipt_replayed` con CURRENT intacto),
  comando fuera de whitelist o con bandera denegada
  (`attest_command_not_allowed`), sin clave (`attest_not_initialized`),
  binding distinto (`receipt_identity_mismatch`), whitelist editada entre
  plan y commit (`receipt_whitelist_changed`), receipt sin archivo
  (`receipt_invalid`), `policy_fingerprint` viejo (`receipt_invalid`).
- Regresiones de hueco: `tool_observed` sin receipt válido sigue
  rechazándose en plan y commit vía CLI; claim de refute con receipt →
  fail-closed por resolver; authority v1 no puede expresar el kind nuevo.
- Export→restore tras attest: re-verificación falla cerrada (clave local);
  planning-result pre-bump → `write_policy_fingerprint_mismatch`.

## Referencias

- Issue #102 y su plan: `docs/planning/plan-issue-102-attest-hardness-2026-09-01.md`
- Spike S0: `docs/planning/issue-102-attest-spike-2026-09-01.md`
- Ronda adversarial pre-code: `docs/planning/adr-0046-attest-precode-adversarial-2026-09-01.md`
- ADR-0007 (write-policy), ADR-0022 (identidad store/proyecto), ADR-0027 (export/restore), ADR-0031/0039 (G-track), ADR-0047 (host hooks, pendiente)
