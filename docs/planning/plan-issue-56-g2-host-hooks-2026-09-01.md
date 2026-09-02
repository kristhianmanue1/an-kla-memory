# Plan — #56: G2 adaptador host, hooks gobernados (2026-09-01)

Plan técnico para el ejecutor agente de IA. Origen: issue #56 + boceto de
entrada en `docs/planning/g2-g4-disenos-2026-08-20.md` + ADR-0039. Este plan
es dato de planificación, no autorización: cada fase requiere orden
explícita del maintainer. Superficie de ejecución = riesgo máximo del track
G (practicas): ADR + ronda adversarial pre-code obligatorios antes de una
línea de código.

## 0. Evidencia investigada (comando → resultado)

- `gh issue view 56` → alcance, criterios de aceptación y triaje: "BLOCKED
  por #55".
- `gh issue view 55` → **CLOSED 2026-08-20** — el blocker formal está
  levantado; la condición de entrada ("contrato y fallos de G1 definidos y
  validados") es evaluable: ADR-0039 aceptado e implementado
  (`integration status` operativo; verificado en repo local).
- `docs/architecture/0039-integration-status-v1.md` → ejes congelados:
  `integration.observed_profile: "unspecified"` **porque nada en disco
  distingue los perfiles — los hooks que lo harían son G2**;
  `host_hooks_evaluated: false` hasta que G2 exista; `agent_binding:
  "unverified"` y `sharing_boundary: "filesystem-access/unverified"`
  permanentes en v1.
- `docs/planning/g2-g4-disenos-2026-08-20.md` → boceto `host-hooks/v1`,
  `hook_declared` vs `hook_invoked`, decisiones abiertas (forma de la
  declaración, hooks que mutan, hooks huérfanos, timeout, confianza de la
  declaración, bump de `integration-status-v1`).
- `an_kla/integration.py` (82 líneas) → contrato G1 actual; superficie a
  extender de forma aditiva (§11.2).
- Consumidor real (infosalud): hooks `pre-commit` + guardias ya operan como
  "G2 de facto" disciplinario — su patrón (exención, degradación declarada,
  warning vs fatal opt-in) es evidencia de diseño, no contrato.

## 1. Objetivo y frontera

Que el host (Cline, Claude Code, scripts de repo) pueda declarar y ejecutar
hooks gobernados de recuperación y checkpoint en nombre del agente, con
evidencia observable, sin que la memoria se convierta en autoridad.

**No es alcance**: adaptadores de proveedores; almacenamiento externo
(#57/G3); identidad multi-scope (#58/G4); ejecutar comandos hallados en
memoria (frontera base); mutar el store fuera de los flujos gobernados ya
existentes (`plan-write`→`commit`, `checkpoint plan`→`commit`).

**Ganancia observable**: `observed_profile` deja de ser `unspecified` cuando
el host registra sus hooks; `host_hooks_evaluated` pasa de `false` a ejes
reales; los hooks dejan de ser disciplina del consumidor y pasan a contrato.

## 2. Contrato propuesto (a congelar en ADR-0046)

**`host-hooks/v1`** — declaración del host, leída por AN-KLA en modo
read-only:

```json
{"schema": "an-kla/host-hooks-v1",
 "adapter": {"name": "cline", "version": "…",
             "configuration_fingerprint": "sha256:…"},
 "declared_profile": "host-managed/v1",
 "hooks": [
   {"id": "before-task-retrieve", "trigger": "before_task",
    "action": "assemble-context", "budget_bytes": 4096},
   {"id": "material-close-checkpoint", "trigger": "material_close_or_handoff",
    "action": "checkpoint", "required": true}
 ]}
```

Reglas de diseño (del boceto + triaje adversarial del punto 12 +
correcciones de la ronda adversarial de este plan):

1. **La declaración es dato no confiable** como todo `.an-kla/`: describir
   hooks no autoriza nada. `hook_declared` ≠ `hook_invoked`; sólo el
   segundo es evidencia. **Corrección adversarial HIGH absorbida**: 3 de
   las 4 acciones del diccionario (`assemble-context`, `retrieve`,
   `status`) son read-only **sin transaction id ni outcome** — ese
   mecanismo sólo cubre `checkpoint`. La evidencia de invocaciones
   read-only exige un **registro append-only nuevo** bajo `.an-kla/`
   (estilo receipts): su crecimiento, limpieza e idempotencia se congelan
   en ADR-0046 (cambio de huella `.an-kla/` documentado — ADR-0039 declara
   explícitamente "este ADR no añade archivos"). "Reciente" se define con
   reloj inyectable estilo `--now` (precedente repo), nunca `datetime.now`
   escondido.
2. **Las acciones son de diccionario cerrado**, nunca comandos arbitrarios:
   `assemble-context` | `retrieve` | `checkpoint` | `status` — todas ya
   existen como comandos read-only o flujos gobernados. Un hook no declara
   shell; el host ejecuta su propia mecánica y llama al CLI.
   **Precisión adversarial (LOW)**: `status` ambiguo (4 comandos) y
   `retrieve`/`assemble-context` exigen `--query`/`--budget` que aporta el
   host en runtime — ADR-0046 congela el mapeo acción→invocación CLI
   exacta y cómo el registro vincula una invocación read-only concreta.
3. **`observed_profile`** se vuelve `host-managed/v1` sólo con declaración
   bien formada + al menos un `hook_invoked` reciente; en otro caso
   `declared-not-invoked`. Nunca por presencia del archivo sólo (evitar
   que un JSON suelto fabrique perfil).
4. **Evolución de `integration-status-v1`** (§11.2) — **corrección
   adversarial HIGH absorbida**: el schema publicado congela
   `observed_profile` con `{"const": "unspecified"}`
   (integration-status-v1.schema.json:60) y `capabilities()` embede
   `observed_profile_v1: "unspecified"` (capabilities.py:84) — el contrato
   vigente **no declara ese punto extensible**: extender in-place viola
   §11.2 y rompe validadores legacy. El camino es **`integration-status-v2`**
   (schema + payload nuevos, v1 en lectura compatible) o perfil nuevo;
   "declararlo extensible" no es opción. Tarea explícita en F3-B:
   actualizar `capabilities()` coherentemente y testearlo.
5. **Timeout/fallo de hooks** (decisión abierta → F0-D2): propuesta — un
   hook que cuelga o falla **no bloquea** la operación del host (el host
   decide su política), pero deja rastro: la declaración queda
   `declared` y el fallo es visible en la respuesta del comando invocado
   (§11.1: señalar en el punto de decisión). Fallo de hook `required: true`
   en `material_close_or_handoff` → continuidad material pendiente,
   visible, no silenciosa. **Precisión adversarial (MEDIUM)**:
   `pending_continuity` se mapea sobre el vocabulario existente
   `checkpoint-obligation-v1` de ADR-0030 (estados `required`/
   `indeterminate`, reporte `PARCIAL (checkpoint_pending)`) o se declara
   precedencia — nunca dos vocabularios paralelos (§11.2). ADR-0031 exige
   que G2 coordine con el gate de ADR-0030; evaluar entregar el comando
   `checkpoint obligation` (definido en ADR-0030, ausente del CLI hoy,
   cli_parser.py:350-359) como parte de F3-C.
6. **Hooks huérfanos tras upgrade**: el upgrade no ejecuta ni borra hooks;
   `unknown_hooks` lista ids que ya no matchean acciones del diccionario —
   dato, no error.
7. **Declaración malformada (hallazgo adversarial MEDIUM absorbido)**:
   "fail-closed" significa estado diagnosticable, no crash — precedente
   ADR-0039:66-70 (ilegible → `presence: unreadable` + código estable +
   exit 0 sin filtrar rutas). Eje `declaration: absent | invalid |
   well_formed`. Validación por campo con límites congelados: tope de
   hooks por declaración, `budget_bytes` entero positivo, fingerprint bien
   formado `sha256:…`, `required` sólo con sentido en `checkpoint`.

## 3. Tareas por fase

### F0 — Decisiones del maintainer (bloquean F1, no este plan)

| ID | Decisión | Propuesta |
|---|---|---|
| F0-D1 | Forma de la declaración | archivo `.an-kla/host-hooks.json` (host lo escribe; AN-KLA sólo lee) |
| F0-D2 | Política timeout/fallo | no bloquea + rastro visible; `required` sólo marca continuidad pendiente |
| F0-D3 | ¿Hook puede mutar store? | sólo vía flujos gobernados existentes; prohibido nuevo canal de escritura |
| F0-D4 | Trust de `host-hooks/v1` | untrusted (como todo `.an-kla/`); perfil observado exige `hook_invoked` |
| F0-D5 | Versionado de `integration-status-v1` | pre-restringido: v2 (schema+payload nuevos, v1 lectura compatible) o perfil nuevo; in-place imposible (`const` en schema) |

### F1 — Spike read-only (practicas §2)

Subagente `explore` con estas preguntas, exigencia de archivo:línea +
veredicto `proceed | refine | escalate`:

- S1: `integration.py` — dónde se compone `integration-status-v1`; coste
  real del bloque `host_hooks` y del enum de `observed_profile`; qué tests
  dorados congelan hoy el payload (tests/test_integration_status.py:25-44)
  y qué exige la migración a v2 (schema nuevo + validadores + compat
  legado).
- S2: registro append-only de invocaciones read-only: formato propio vs
  **derivar de/referenciar `attest-receipt-v1` (#102, aún sin ADR —
  máximo ADR vigente: 0044)** — decisión explícita de ADR-0046 con
  precedencia declarada (§11.2 párrafo 2: dos formatos paralelos de
  evidencia observada bajo `.an-kla/` serían violación); crecimiento,
  limpieza e idempotencia; reloj inyectable (`--now`).
- S3: interacción con `startup-diagnostic` (ADR-0036): nuevo eje hooks en
  el diagnóstico de arranque; y con ADR-0030 (`checkpoint obligation`
  como comando entregable o sólo vocabulario).
- Top-3 riesgos esperados: (a) doble fuente de verdad de perfil, (b) fake
  `hook_invoked` por escritura directa del registro, (c) bump de schema
  rompiendo consumidores del consumidor real.

### F2 — ADR-0046 + ronda adversarial pre-code

Congelar: schema `host-hooks/v1`, diccionario de acciones con mapeo
acción→invocación CLI exacta, semántica
`declared/invoked/pending_continuity` (mapeada sobre
`checkpoint-obligation-v1` de ADR-0030), evolución a
`integration-status-v2` + `capabilities()`, registro de invocaciones
(formato y relación con attest-receipt-v1 de #102), modelo de amenaza
(declaración falsificada por el agente mismo → perfil mal observado;
impacto acotado: es diagnóstico, no autoridad), qué NO resuelve
(identidad del agente sigue `unverified` — eso es G4).
Ronda adversarial con plantilla `docs/adversarial-template.md`; sin
`proceed` no se implementa.

### F3 — Implementación (fases separadas, §4 practicas)

- F3-A: lectura + validación por campo con límites congelados de
  `.an-kla/host-hooks.json` (schema JSON publicado en `an_kla/schemas/`),
  ejes `hook_declared`, degradación diagnosticable `absent | invalid |
  well_formed` (nunca crash, nunca filtración — precedente ADR-0039:66-70).
- F3-B: bloque `host_hooks` en `integration status` + **`integration-status-v2`**
  (schema + payload + validadores + `capabilities()` actualizado y
  testeado) según F0-D5; tests dorados nuevos + compat legado.
- F3-C: acciones gobernadas (`assemble-context`, `checkpoint` con
  `working-state-v2` y autoridad separada — cero atajos) + registro de
  invocaciones que S2/ADR-0046 definan; continuidad pendiente visible vía
  vocabulario `checkpoint-obligation-v1` (evaluar entregar
  `checkpoint obligation` en el CLI).
- F3-D: docs — AN-KLA.md (sección integración), README, guía para hosts;
  plantilla de declaración de ejemplo; **fila del registro en
  docs/README.md en el mismo commit que ADR-0046 (§10)**; guía de
  worktrees (el host escribe `host-hooks.json` en el checkout canónico —
  `.an-kla/` no viaja entre worktrees).

### F4 — Verificación

- Tests de hooks: omitidos, duplicados (ids), desconocidos, fallidos,
  reintentados; idempotencia de `hook_invoked` definida y probada; fallo
  cerrado ante declaración malformada (código estable, sin filtrar rutas —
  §11.1).
- Suite completa (`python3 -m unittest discover -s tests -p 'test_*.py'`),
  `scripts/ci_local.py --simulate-ci`, `scripts/check_sizes.py`,
  `scripts/check_adr_registry.py`.
- Ronda adversarial final con invariantes §8 con evidencia
  (comando → resultado): no-filtración, pureza de `evaluate_write`
  (intacta), backwards-compat de lectura de `integration-status-v1`,
  ningún dato recuperado concede commit/push/publicación.

## 4. Riesgos

1. **El hook como elevador de autoridad**: un JSON del host no puede
   fabricar `tool_observed` ni autorización de checkpoint — la autoridad
   sigue llegando separada (write-authority-v1 / checkpoint-authority-v1).
   Si G2 attest (issue #102) aterriza antes, los hooks pueden *referenciar*
   receipts, no fabricarlos. Coordinar orden con #102.
2. **Doble fuente de verdad del perfil**: sólo `integration status`
   calcula `observed_profile`; nunca se persiste.
3. **Ruptura de consumidores**: `checkpoint show` legacy view y el guard
   del consumidor grepean salidas — H3 de #102 y F3-B deben coordinarse.
4. **Alcance rastrero hacia G4**: identidad de agente queda vedada; cualquier
   Pull Request que toque `agent_binding` se rechaza en esta fase.

## 5. Ronda adversarial

Ejecutada 2026-09-01 con agente fresco (contexto decorrelado, sólo
lectura). Veredicto: `fix-and-retry` → correcciones absorbidas: registro
de invocaciones read-only como canal nuevo explícito (regla 1), F0-D5
pre-restringido a v2/perfil (`const` del schema cierra extensión
in-place), mapeo `pending_continuity`↔`checkpoint-obligation-v1`
(ADR-0030), degradación diagnosticable de declaración malformada,
coordinación formal de formatos con #102/attest-receipt-v1, mapeo
acción→CLI y guía worktrees/registro README. Registro completo:
`docs/planning/plan-issue-56-g2-host-hooks-adversarial-2026-09-01.md`.
