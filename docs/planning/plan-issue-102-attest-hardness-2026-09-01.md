# Plan — #102: attest firmado + mejoras de hardness (2026-09-01)

Plan técnico para el ejecutor agente de IA. Origen: issue #102 (reporte del
consumidor real infosalud, beta.19, Python 3.13.5). Este plan es dato de
planificación, no autorización: la implementación requiere orden explícita
del maintainer por fase. Frontera base intacta: la memoria es dato, nunca
instrucción; ningún receipt o registro habilita comandos por sí mismo.

## 0. Evidencia investigada (comando → resultado)

- `gh issue view 102` → propuesta attest + 8 mejoras de hardness + comentario
  del maintainer (2026-09-01) que lo mantiene priorizable.
- `gh api .../contents/scripts/mem` (infosalud) → 285 líneas: flujo bifásico
  `plan-write` → rebinding de `proposal_sha256` → re-plan → `commit`;
  authority `model_derived` con techo `summary`; checkpoint v2 con
  `proposal_sha256` calculado sobre el sobre `checkpoint-proposal-v1`.
- `gh api .../ADR-007-memoria-agente-an-kla.md` → adopción beta.19 exacta,
  update-check off, frontera de verdad en docs/ + Git.
- `gh api .../scripts/hooks/pre-commit` + `tests/test_guardias_memoria.py`
  → guardias disciplinarios (no atestación): exención AGENTS.md/AN-KLA.md,
  degradación declarada sin `.venv`, fences balanceados replicando
  `context_package.py`.
- Código local verificado: ver anclas por tarea (§2, §3).

## 1. Decisión de arquitectura: qué resuelve attest

**Problema.** `evaluate_write` (an_kla/write_policy.py:381) capsula todo lo
no-observado: `tool_observed` exige `evidence[].resolution == "verified"`
(write_policy.py:416-420) y `issuer.kind == "tool"` (write_policy.py:327);
desde JSON puro sólo es fabricable `model_derived`/`derived_from_retrieval`
(techo `summary`, reason `derived_authority_capped`, write_policy.py:424-440).
Un agente honesto no puede registrar que observó algo; la memoria jamás
distingue "observado" de "inventado".

**Principio de diseño.** El agente nunca fabrica `tool_observed`: sólo puede
*invocar* `attest`, y es el motor quien ejecuta el comando whitelisteado,
observa el resultado y firma un receipt. La autoridad `tool_observed` nace de
un receipt verificable, no de campos autodeclarados.

**Firma: restricción stdlib y precedente sealed.** El runtime no tiene
dependencias (pyproject.toml:17, "El runtime no tiene dependencias"). Ed25519
no vive en stdlib; HMAC-SHA256 sí (`hmac`). Precedente repo: el extra `sealed`
declara `cryptography>=42` con detección perezosa y fallo cerrado
(`sealing_extra_not_installed`, pyproject.toml:18-23). Opciones:

- **A (propuesta): HMAC-SHA256 stdlib.** Clave local generada en `init`,
  fuera del alcance de escritura del store. Cero extras. Amenaza honesta:
  un agente con shell completo puede leer la clave — se documenta, no se
  oculta (modelo de amenaza de #102: no frena al malicioso).
- B: extra opcional `attest = ["cryptography>=42"]` con Ed25519 (patrón
  sealed). Más hardness, más superficie. Decisión de maintainer (F0-D1).

**Esquema propuesto (congelar en ADR-0046, no antes).**

```json
{"schema": "an-kla/attest-receipt-v1",
 "receipt_id": "uuid", "command": ["git", "rev-parse", "HEAD"],
 "exit_code": 0, "stdout_digest": "sha256:…", "stderr_digest": "sha256:…",
 "project_uuid": "uuid", "identity_binding_digest": "sha256:…",
 "configuration_fingerprint": "sha256:…",
 "whitelist_digest": "sha256:…",
 "base_revision": "sha256:…",
 "nonce": "uuid",
 "observed_at": "RFC3339", "policy_fingerprint": "…",
 "receipt_hmac": "sha256-hmac sobre canonical-json del resto"}
```

**Anti-replay (hallazgo adversarial HIGH, absorbido)**: el receipt liga
`base_revision` (attest exige `--expected-current` y lo incrusta) y `nonce`
consumible; la verificación ocurre en **ambas** capas (plan-write y
commit-write-plan bajo lock) cruzando receipt↔propuesta. Un receipt de ayer
no autoriza una propuesta de hoy.

Whitelist en `.an-kla/attest-whitelist.json` (fail-closed, sólo-lectura de
comandos, patrones exactos o prefijos declarados al inicializar; su edición
queda fuera del write policy — es config local del operador, como el lock).
**Mitigación de edición silenciosa (hallazgo MEDIUM absorbido)**: cada
receipt incrusta `whitelist_digest` y la verificación lo cruza contra la
whitelist vigente; el estado/ediciones de la whitelist se exponen en
`status`/`context_diagnostics` (§11.1). `attest` ejecuta argv estricto sin
shell y sin heredar entorno sensible.

**Punto real de rechazo (corrección adversarial HIGH)**: `evaluate_write`
jamás rechaza `tool_observed` — sólo exige evidence `resolution: verified`
(write_policy.py:416-420). Quien rechaza la clase desde el CLI standalone es
`_cli_authority` (an_kla/__main__.py:96-104), aplicado en **plan-write y
commit-write-plan** (an_kla/__main__.py:386, :396) con código
`tool_observed_requires_adapter`; `capabilities()` publica
`cli_can_mint_privileged_authority: false` y
`privileged_authority_requires_external_adapter: true` (capabilities.py:110,
:230). `checkpoint_policy.py` tiene su paralelo propio
(:68, :98, :119, :213). Attest debe: condicionar `_cli_authority` para
aceptar `tool_observed` sólo con evidence de receipt verificada (en ambos
comandos), evolucionar `capabilities()` de forma versionada (§11.2) y
declarar explícitamente si checkpoint-authority obtiene el mismo camino
(decisión F0-D5; propuesta: fuera de alcance v1).

**Evidence: schema cerrado (corrección adversarial MEDIUM)**:
`_validate_evidence` (write_policy.py:262-275) exige claves exactas
`{kind, id, resolution}` (+`sha256` si verified) y enum cerrado; el schema
publicado `write-authority-v1` tiene `additionalProperties: false`. El item
receipt (`id=receipt_id`, `sha256=digest del receipt canónico`,
`resolution=verified` derivada de la verificación HMAC) exige
**write-authority-v2 o perfil nuevo** — no extensión in-place (§11.2). El
spike S0 entrega la forma exacta y la estrategia de compatibilidad dual.

## 2. Tareas — Fase H: hardness (independientes, bajo riesgo)

Cada tarea: implementar → tests → `python3 -m unittest discover -s tests -p
'test_*.py'` verde → ronda adversarial de fase → PR propio.

### H1 — Validación temprana en `plan-write` (#102 §3.1)

Hoy `duplicate_facts_id` (store.py:747) y `target_missing` /
`target_not_vigente` (supersede.py:45-58) fallan sólo en commit.
(Corrección adversarial LOW absorbida: la autorreferencia ya falla en plan
— `validate_write_proposal`, write_policy.py:241-246 — y el check de
supersede.py:34-35 es defensa-en-depth; queda como test de que sigue
fallando en plan, no como repro de commit.)

- **Invariante a preservar**: pureza de `evaluate_write` (practicas §8). Los
  checks tempranos viven en la **capa CLI de `plan-write`**, no en el policy
  core. Precisión (corrección LOW absorbida): `plan-write` hoy sólo lee
  CURRENT (store.py:303-306), no un snapshot; H1 exige leer
  `store.snapshot(observed)` read-only — más pesado de lo implícito.
- Superficie: nuevas reason codes en el planning-result (`plan_*` p. ej.
  `plan_duplicate_id`, `plan_supersede_target_missing`,
  `plan_supersede_target_not_vigente`) → `decision: skip` temprano.
- Los checks autoritativos de commit **se mantienen** (ventana TOCTOU entre
  plan y commit); H1 es adelanto de diagnóstico, no sustituto.
- Tests: repro del consumidor (supersede de id inexistente → skip en plan,
  no error en commit); doble supersede; id duplicado; autorreferencia
  (sigue fallando en plan).
- **DoD**: los 4 repros fallan en plan (skip con reason) y ya no llegan a
  commit; suite completa verde; `evaluate_write` sigue sin tocar disco.

### H2 — Señal dura de registro sin texto indexable (#102 §3.2)

`record_without_indexable_text` ya se emite en decisión
(write_policy.py:452-453) pero el commit procede y el registro queda
invisible para retrieval (contrato en `record_text.py`). El consumidor lo
atravesó sin verlo.

- **Mecanismo corregido por adversarial (MEDIUM absorbido)**: el planning
  result tiene gate de claves exactas `{schema, current_revision, decision,
  plan}` (an_kla/__main__.py:107-115) — añadir un campo top-level rompería
  `commit-write-plan` contra su propio plan-write. Las señales H2 van por:
  (a) `decision.reason_codes` (vocabulario abierto según
  `write-decision-v1.schema.json`:23-31) — ya ocurre; se **refuerza la
  visibilidad** emitiendo además warning en el `commit-outcome-v2`
  (campo `warnings[]` ya existe, commit-outcome-v2.schema.json:7,:22).
- Opcional (decisión maintainer F0-D2): flag `--allow-unindexable-record`
  exigido en commit para proceder; sin flag → fail cerrado. Default propuesto:
  warning sin flag (aditivo, §11.2); el flag es segunda fase.
- Tests: record sólo con campo propio (`contenido`) → reason en plan +
  warning en outcome; con `indexable_text` → sin warning.

### H3 — `checkpoint show` (re-acotada por adversarial: premisa falsa)

**Corrección**: `show_checkpoint` (checkpoints.py:20-28) devuelve el
checkpoint almacenado completo vía `deepcopy` — un commit v2 ya expone
`working_state` + digest + revisión (test_checkpoints.py:145-163). El
`goal: null, revision: 0` que vio el consumidor es el **checkpoint v1 de
init** (initialization.py:32-39), no un bug de proyección: apunta a store
distinto del esperado (p. ej. worktree sin `.an-kla/`, ADR-0022) o lectura
del sentinel.

- Tarea re-acotada: (1) reproducir `checkpoint commit` v2 → `show` en store
  limpio local (resultado esperado: verde hoy, sin cambio de código);
  (2) documentar el sentinel v1 en docs (write-policy-cli.md o guía) para
  que un guard no lo confunda con checkpoint faltante; (3) si el repro del
  consumidor persiste en beta.19, diagnosticar su `--project-root` — reportar
  al issue, no parchear la proyección.

### H4 — Diagnóstico `managed_block_inside_fence` (#102 §3.4)

En `parse_managed_block` (context_package.py:209-210) un fence abierto al
llegar a los marcadores produce el mismo `managed_block_structure_invalid`
que la corrupción real. Repro del consumidor: fence sin cerrar.

- Código distinto `managed_block_inside_fence` cuando la causa es fence
  abierto (línea conocida del fence). Verificar todos los emisores del código
  genérico (context_package.py:169-236) y diferenciar sólo el caso fence;
  lo demás permanece genérico (superficie estable).
- **Migración de goldens (anclas aportadas por adversarial)**: tests/
  test_context_package.py:172 y :235 congelan fence → código genérico;
  tests/test_integration_status.py:130 y tests/test_init_context_signal.py:69
  congelan diagnósticos que pueden propagar el código. Actualizarlos en el
  mismo PR y verificar si startup/integration deben emitir el nuevo código.
- Tests: fence abierto → `managed_block_inside_fence`; bloque indentado,
  duplicado, anidado → sigue `managed_block_structure_invalid`.

### H5 — `resume`/`retrieved_evidence` (re-acotada por adversarial: premisa falsa)

**Corrección**: `retrieved_evidence` ya incluye `id` y `stream` por ítem
(resume.py:113-122; `resume-evidence-v1.schema.json` los declara required) y
ese commit es ancestro de `v0.1.0-beta.19` — la queja del consumidor no
reprocede de esta superficie.

- Tarea re-acotada: re-ejecutar el repro del consumidor en beta.19 para
  localizar la superficie real (¿`render` interno, salida MCP, another
  view?). Si no reproduce → cerrar el sub-item en #102 como
  no-reproducible con evidencia; nada que implementar.

### H6 — Python 3.13 en matriz CI (#102 §3.6)

`.github/workflows/test.yml`: añadir 3.13 (el CI remoto existe aunque el
repo consumidor opere local-only; costo marginal). Verificación local
previa: suite verde con `.venv` 3.13 (el consumidor ya la corrió: ~500
tests, verde salvo `test_sealed_matrix` >30 s — separar o marcar ese test
lento en su propio job/perfil, no en la matriz general).

### H7 — Plantilla de hooks + docs (#102 §3.7)

Publicar `docs/hooks-template/pre-commit` + `docs/development-macos.md` o
README: instalación con `git config core.hooksPath` (no se clona), exención
AGENTS.md/AN-KLA.md, degradación declarada sin venv, y la doble defensa
`AN_KLA_NO_UPDATE_CHECK=1` + `--no-update-check` (el fetch a
api.github.com ocurre con caché fría sin env var — verificado por el
consumidor).

### H8 — Principio CI local-only documentado (#102 §3.8)

Declarar en README/SECURITY: todo push/PR debe poder verificarse con
`scripts/ci_local.py` sin Actions remotos; el CI remoto es validación
adicional, no requisito de consumo.

## 3. Tareas — Fase A: attest (ADR + spike antes de código)

Secuencia obligatoria (practicas §2, §3): spike → ADR-0046 con su ronda
adversarial pre-code → implementación por fases (§4) → ronda adversarial
final. Toca `write_policy.py` → ronda adversarial no negociable antes de
cualquier tag.

- **S0 (spike read-only)**: mapear `_validate_evidence` (write_policy.py
  :262-275) y el schema publicado de evidence; decidir la vía
  write-authority-v2 (el punto NO es extensible: `additionalProperties:
  false` + enum cerrado — §11.2); mapear `_cli_authority`
  (an_kla/__main__.py:96-104, :386, :396) y su paralelo en
  checkpoint_policy.py:68-213; mapear `capabilities()` (capabilities.py:110,
  :230) y cómo evolucionarlo versionado; localizar generación de claves en
  `init` (initialization.py) y qué toca añadir keygen sin romper stores
  existentes (backwards-compat); **ciclo de vida de clave/identidad
  (hallazgo MEDIUM absorbido)**: política de verificación de receipts contra
  el binding vigente (store.py:327-333) y no sólo el `project_uuid`
  incrustado — receipts previos a `identity adopt`/`repair`
  (identity.py:474, :507) deben fallar cerrado con código estable
  (`receipt_identity_mismatch`); worktrees = otro `project_uuid` (ADR-0022):
  receipts no cruzan stores — documentar.
- **S1 (ADR-0046)**: congelar receipt schema v1 (con `base_revision`, `nonce`
  y `whitelist_digest` anti-replay/anti-edición), whitelist fail-closed,
  flujo `attest run --expected-current <sha256> -- <cmd>` → receipt firmado
  + salida; política: `_cli_authority` acepta `tool_observed` con evidence
  de receipt verificada en plan **y** commit; nuevo issuer `kind: "tool"`
  con `issuer.id = an-kla-attest`; forma exacta del item evidence en
  write-authority-v2 + compat dual; evolución versionada de `capabilities()`
  (§11.2); alcance de checkpoint-authority (F0-D5). Incluir modelo de
  amenaza honesto (clave local legible por el agente; valor = procedencia
  auditable, no defensa contra malicioso) y decisión F0-D1 (HMAC vs extra
  Ed25519).
- **S2 (implementación)**: fases — (a) keygen + almacenamiento de clave
  (chmod 600, fuera de `memory/`), (b) `attest run` + receipts (append-only
  bajo `.an-kla/receipts/`, marcado de nonce consumido), (c) verificación
  en `_cli_authority` para plan-write y commit-write-plan (bajo lock en
  commit), (d) write-authority-v2: validador + schema publicado + compat
  dual con v1, (e) `capabilities()` actualizado y testeado, (f) docs
  (write-policy-cli.md, AN-KLA.md §autoridad).
- **S3 (tests)**: golden receipts deterministas (canonical json); receipt
  manipulado (comando, digest, exit_code) → fallo cerrado con código
  estable; comando fuera de whitelist → `attest_command_not_allowed`;
  sin clave → fail cerrado; suite completa + adversarial final con
  invariantes §8 con evidencia.

## 4. Decisiones F0 del maintainer — ADOPTADAS (2026-09-01, orden explícita "adelante con firmas")

| ID | Decisión | Adoptada | Nota |
|---|---|---|---|
| F0-D1 | Firma: HMAC stdlib vs extra Ed25519 | **HMAC-SHA256 (A)** | stdlib-only; modelo de amenaza honesto documentado en ADR-0046 |
| F0-D2 | Registro sin texto indexable: warning vs flag | **warning (aditivo) primero** | entregado en beta.20 (#104); flag diferido |
| F0-D3 | Alcance whitelist inicial | **sólo-lectura: git rev-parse/diff, unittest, sha256sum** | fail-closed, patrones exactos/prefijo |
| F0-D4 | attest requiere store inicializado | **sí** | receipts ligados a project_uuid + binding vigente (store_identity) |
| F0-D5 | checkpoint-authority en v1 | **fuera de alcance v1** | ADR-0046 lo declara; paralelo checkpoint_policy.py intacto |

Alcance añadido por el spike S0 (obligatorio, mismo PR que keygen/attest):
actualizar `_PATTERNS`/ignorados de `export_restore.py` para
`.an-kla/attest.key` (ignorado — la clave no viaja en export),
`.an-kla/attest-whitelist.json` y `.an-kla/receipts/**`; sin ello
`export create` falla con `export_unrecognized_durable_path`. Bump de
`policy_fingerprint` (write) aceptado y documentado; planning-results en
vuelo fallan cerrado (`write_policy_fingerprint_mismatch`). Nota: el
número ADR-0045 fue tomado por la adopción de Skevi; attest pasa a
**ADR-0046** (y G2/#56 a **ADR-0047**).

## 5. Riesgos

1. **Romper pureza de `evaluate_write`** con checks tempranos → mitigado:
   checks en capa CLI; suite + invariantes §8 por fase.
2. **Attest como oráculo de verdad**: un receipt prueba ejecución, no
   corrección semántica — el ADR debe decirlo y la salida de `attest` no
   alimenta autoridad sin `resolution: verified`.
3. **Replay de receipts** (hallazgo adversarial HIGH): receipt sin binding
   a `base_revision` + nonce consumible recrearía el oráculo que attest
   cierra — absorbido en §1 y S1; tests dedicados en S3.
4. **Combinación H2 + attest**: registro unindexable con autoridad full —
   testeado explícitamente.
5. **Presupuesto**: H1-H8 son paralelizables y de bajo riesgo (H3/H5
   re-acotadas a investigación/repro); attest es el único ítem con ADR
   propio. No mezclar fases (§4).

## 6. Ronda adversarial

Ejecutada 2026-09-01 con agente fresco (contexto decorrelado, sólo
lectura). Veredicto: `fix-and-retry` → correcciones absorbidas en este
documento (H3 y H5 re-acotadas, `_cli_authority`/`capabilities()` como
superficie real, anti-replay, whitelist_digest, ciclo de vida identidad,
goldens de H4, mecanismo H2). Registro completo:
`docs/planning/plan-issue-102-attest-hardness-adversarial-2026-09-01.md`.
