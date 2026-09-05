# ADR-0047: hooks gobernados del host (`host-hooks/v1`) con perfil observado en `integration-status-v2`

- **Estado:** Propuesta
- **Implementación:** No iniciada
- **Fecha:** 2026-09-05
- **Decide sobre:** el contrato G2 de ADR-0031: cómo declara el host sus
  hooks de recuperación y checkpoint, cómo AN-KLA observa su ejecución con
  evidencia, y cómo evoluciona la superficie observable sin romper
  consumidores. No decide identidad de agente (G4), almacenamiento externo
  (G3) ni adaptadores de proveedores.

## Contexto

ADR-0031 reconoció el perfil host-managed como soportado y encargó a G2 el
"contrato de orquestación". Hoy ese contrato no existe: los hooks son
disciplina de facto del consumidor (`docs/hooks-template/pre-commit` avisa,
no atestúa) y la superficie observable congela la ausencia:
`observed_profile: "unspecified"` está hardcodeado (`an_kla/integration.py:74`),
`host_hooks_evaluated: false` (`integration.py:77`), y el schema publicado
cierra ambos con `const` (`integration-status-v1.schema.json:60,63`) —
extensión in-place imposible (ronda adversarial del plan, HIGH absorbida).

El plan técnico de #56 (`docs/planning/plan-issue-56-g2-host-hooks-2026-09-01.md`)
con su ronda adversarial absorbida dejó F0 pendiente de firma. El
maintainer firmó F0 el 2026-09-05 (sesión, orden explícita "firmado
adelante") sobre los cuatro ejes propuestos: ganchos `before_task` /
`material_close_or_handoff`; autoridad "el host exige, el agente propone
por los flujos gobernados"; evidencia observable de hook ejecutado con
fallo visible si la continuidad queda pendiente; alcance v1 sin
adaptadores de proveedores, sin G3 ni G4. Las decisiones F0-D1–D5 del plan
quedan adoptadas según su propuesta (D5 además pre-restringida por el
`const` del schema vigente).

El spike read-only F1 (`docs/planning/plan-issue-56-g2-spike-s1-2026-09-05.md`,
veredictos S1 proceed / S2 refine / S3 refine) verificó: punto único de
composición (`integration.py:61-79`), goldens que congelan la no-escritura
de las acciones read-only (`tests/test_integration_status.py:79` y
`:147-152`), mecanismo de receipts de ADR-0046 ya aceptada (canonical-json,
O_EXCL+fsync, HMAC, anti-replay por tombstones: `an_kla/attest.py:226-228,
89-122, 485-505`) con formato no reutilizable tal cual, ADR-0030 aún en
Propuesta con su comando `checkpoint obligation` inexistente
(`cli_parser.py:389-398`), y consumidores que grepean salidas
(`docs/hooks-template/pre-commit:45-47`, scripts `check_beta15/16_upgrade.py:83`).

Restricciones vigentes: frontera de confianza de `AN-KLA.md` (todo
`.an-kla/` es dato no confiable); `docs/practicas-ingenieria.md` §11.2
(evolución aditiva o versionada de contratos publicados; dos formatos
paralelos de evidencia exigirían precedencia declarada); ADR-0031 (G2
coordina con el gate de ADR-0030; identidad vedada a G4); contrato
gestionado (no se modifica en esta fase — ver §Consecuencias).

Esta Propuesta absorbió una ronda adversarial pre-code de contexto fresco
(2026-09-05, veredicto `fix-and-retry`: 4 HIGH, 6 MEDIUM, 3 LOW; registro
y absorción en
`docs/planning/plan-issue-56-g2-adr0047-adversarial-2026-09-05.md`). Las
re-verificaciones puntuales de H1–H4 sobre el texto enmendado quedan como
condición para firmar F3-A.

## Decisión

Adoptar el contrato **`host-hooks/v1`**: declaración del host leída por
AN-KLA en modo read-only, evidencia de invocación acuñada y **verificada**
por el motor, y perfil observado calculado en `integration-status-v2` con
v1 congelado y lectura compatible. Fases de implementación F3-A–D según el
plan; esta decisión congela el diseño antes de una línea de código.

### 1. Declaración del host: `.an-kla/host-hooks.json` (F0-D1)

El host escribe el archivo; AN-KLA sólo lo lee (nunca lo crea, edita ni
borra). Schema JSON publicado `an-kla/host-hooks-v1` (paquete + espejo
`docs/schemas/`). Forma (del plan §2): `adapter` (name, version,
configuration_fingerprint), `declared_profile` (`"host-managed/v1"`), y
`hooks[]` con `id`, `trigger` (`before_task |
material_close_or_handoff`), `action` y `required` (sólo con sentido en
`checkpoint`).

Validación por campo con **límites congelados**: máximo **16** hooks por
declaración; `id`: 1–128 caracteres de `[A-Za-z0-9._-]`, únicos; `trigger`
y `action` del diccionario; `budget_bytes`: entero **1..1048576**;
`configuration_fingerprint`: `^sha256:[0-9a-f]{64}$`; `required`: booleano
y sólo permitido cuando `action == "checkpoint"`; sin campos adicionales.

Declaración ausente, ilegible o malformada → eje `declaration: absent |
invalid | well_formed`, degradación **diagnosticable, nunca crash, nunca
filtración de rutas** (precedente ADR-0039:66-70; exit 0 con código
estable).

### 2. Acciones de diccionario cerrado, con mapeo CLI exacto

`assemble-context | retrieve | checkpoint | status`. Un hook jamás
declara shell ni comando arbitrario: el host ejecuta su mecánica y llama
al CLI. Mapeo congelado (placeholders nombrados entre `<…>`; el host los
aporta en runtime):

| Acción | Invocación CLI (la ejecuta el host en runtime) |
|---|---|
| `status` | `an_kla --project-root <root> status` |
| `retrieve` | `an_kla --project-root <root> retrieve --query <q> --budget <b> [--streams <s>]` |
| `assemble-context` | `an_kla --project-root <root> assemble-context --query <q> --new-information <n> --budget <b>` |
| `checkpoint` | `an_kla --project-root <root> checkpoint plan --input <working-state> --authority <authority>` → `... checkpoint commit --plan <plan> --expected-current <sha256:…> --transaction-id <uuid>` |

Presupuesto: el `budget_bytes` de la declaración es el **valor por
defecto** de `--budget`; un flag runtime del host manda si está presente.
La acción `status` del diccionario es el `status` de revisión
(`cli_parser.py:35`), **no** `integration status` (`cli_parser.py:67-77`):
la superficie del perfil observado no es enganchable por declaración
(intencional: el perfil se calcula, no se invoca).

### 3. `hook_declared` ≠ `hook_invoked`

La declaración describe; no evidencia ni autoriza nada. Sólo la
invocación registrada —y verificada— es evidencia. El perfil observado
jamás se deduce de la presencia del archivo.

### 4. Registro de invocaciones: `.an-kla/hook-runs/`, acuñado y verificado por el motor

Formato propio **variante de `attest-receipt-v1`** (precedencia declarada
frente a ADR-0046 según `docs/practicas-ingenieria.md` §11.2: un único
mecanismo de evidencia observada bajo `.an-kla/`, dos perfiles del mismo —
receipt de comando vs registro de hook; `hook-runs` NO consume tombstones
ni quema nonces):

- entrada `{schema: "an-kla/hook-run-v1", run_id, hook_id, trigger,
  action, exit_code, subject_digest, project_uuid, store_identity,
  adapter_fingerprint, observed_at, run_hmac}`; canonical-json,
  HMAC-SHA256 con la clave del motor (`attest.key`), escritura
  O_EXCL+fsync content-addressed bajo `.an-kla/hook-runs/runs/sha256/`
  (reutiliza `_write_exclusive`, `an_kla/attest.py:89-122`).
- **Identidad firmada** (spike/ronda M9): `project_uuid` y
  `store_identity` viajan firmados en la entrada; la lectura rechaza con
  código estable los runs cuyo binding no matchee el vivo (precedente
  `receipt_identity_mismatch`, `attest.py:463-467`) — runs copiados entre
  stores/worktrees no contribuyen al perfil.
- **Quién escribe:** el motor acuña la entrada sólo cuando la acción
  corre con contexto de hook explícito (`--on-behalf-of-hook <hook-id>`,
  flag de la fase F3-C; se aplica al cierre de cada flujo — en
  `checkpoint`, una sola acuñación en `commit` con el `exit_code` global
  del flujo). Una invocación plana del CLI **no escribe nada** — preserva
  la propiedad congelada de no-escritura (`test_integration_status.py:79`
  y `:147-152`) y la pureza de las superficies read-only.
- **`run_id` e idempotencia:** `run_id` lo genera el motor (uuid) en cada
  flujo; el reintento del host con el mismo `run_id` reproduce contenido
  canónico idéntico → O_EXCL encuentra el objeto y la re-acuñación es
  no-op idempotente (`attest.py:372`); invocaciones distintas tienen
  `run_id` distinto → ninguna acuñación se pierde en silencio.
- **Reloj inyectable:** `--now` con precedentes (`cli_parser.py:119-121,
  149-151`); "reciente" se define en §5 con umbral congelado, nunca
  `datetime.now` escondido.
- **Crecimiento y limpieza:** lineal, sin limpieza automática — igual
  que receipts y ref-log (ADR-0046:163-165, `compaction.py:345-353`);
  limpieza futura gobernada, nunca automática. Vive fuera de
  `.an-kla/memory/`: la compactación jamás lo alcanza.
- **Publicación:** `an-kla/hook-run-v1` se publica en el paquete y en el
  espejo `docs/schemas/`, se registra en `SCHEMA_FILES`
  (`an_kla/schemas/__init__.py:12-85`) y entra en la tupla dorada
  (`tests/test_agent_contracts.py:38-113`).
- **Canal nuevo declarado (F0-D3, reconciliación):** F0-D3 prohíbe
  canales de escritura nuevos *sobre la memoria*. `.an-kla/hook-runs/` es
  el único canal nuevo declarado por este ADR: evidencia bajo `.an-kla/`
  pero fuera de `memory/`, sin autoridad, acuñado sólo por el motor, y
  parte de la huella `.an-kla/` que este ADR documenta (la huella previa
  quedaba congelada por ADR-0039/0046).

### 5. Perfil observado: `integration-status-v2` (F0-D5)

Schema + payload nuevos, publicados ambos; **v1 queda byte-idéntico** con
lectura compatible (los goldens legacy y los scripts de upgrade siguen
verificando `integration-status-v1`). `capabilities()` se actualiza
coherentemente y se testea la igualdad payload↔capabilities (goldens).
`integration status` incorpora `--now` inyectable para evaluar recencia
de forma reproducible.

`observed_profile` (calculado, jamás persistido; sólo `integration status`
lo computa):

| Valor | Condición |
|---|---|
| `unspecified` | sin declaración bien formada |
| `declared-not-invoked` | declaración `well_formed`, sin `hook_invoked` reciente |
| `host-managed/v1` | declaración `well_formed` + al menos un `hook_invoked` reciente |

**Reciente (umbral congelado):** `observed_at` dentro de las últimas
**24 horas** (constante `HOOK_RECENCY_HOURS = 24`), evaluada con `--now`
inyectable. Bloque nuevo `host_hooks` en el payload v2: `declaration`,
`hook_declared` (ids), `hook_invoked` (últimos **50** runs, orden por
`observed_at` descendente — el layout content-addressed no es
cronológico; el orden sale del campo), `unknown_hooks` (runs cuyo
`hook_id` ya no está en la declaración — dato, no error; no contribuyen
al perfil salvo que el id siga declarado), `pending_continuity` (§6),
y códigos de lectura degradada.

**Verificación en lectura (congelado):** el cálculo del perfil verifica
por entrada: schema `an-kla/hook-run-v1`, JSON canónico, HMAC válido y
binding de identidad vivo. Una entrada inválida **jamás contribuye** al
perfil; se reporta como dato diagnóstico con código estable sin filtrar
rutas (precedente ADR-0039:66-70). Fabricar `hook_invoked` exige la clave
del motor — el mismo modelo de amenaza de ADR-0046 (procedencia para
agentes honestos; diagnóstico, no autoridad).

**Degradaciones congeladas del lado registro:** entrada corrupta o HMAC
inválido → código `hook_run_invalid` (diagnóstico, no contribuye);
`attest.key` ausente (host sin `attest init`, `attest.py:161-169`) → la
acuñación falla con `attest_not_initialized` y el perfil degrada a
`declared-not-invoked` con el código visible; lectura de
`.an-kla/hook-runs/` imposible → `hook_runs_unreadable` (exit 0, estilo
ADR-0039). El linkage `hook_id` (runs) ↔ `id` (declaración) es exacto por
cadena.

### 6. Fallo y continuidad pendiente (F0-D2)

Un hook que falla o cuelga **no bloquea** la operación del host (política
del host); deja rastro: la declaración queda `declared` y el fallo es
visible en la salida del comando invocado.

**`pending_continuity` (semántica computable congelada):** el campo es
no-vacío si y sólo si existe declaración `well_formed` con algún hook
`required: true` de trigger `material_close_or_handoff` **sin**
`hook_invoked` reciente de ese `hook_id` (misma ventana de 24 h de §5);
valor `required` en ese caso, `indeterminate` cuando la lectura de
evidencia está degradada. El motor no observa los triggers del host:
sólo puede constatar la ausencia de evidencia reciente — eso es lo que el
campo declara, y nada más. Fallo u omisión visible, nunca silenciosa; el
reporte usa el vocabulario `checkpoint-obligation-v1` de ADR-0030
(`required` / `indeterminate`, `PARCIAL (checkpoint_pending)`).

**Precedencia (spike S3):** ADR-0047 **no adopta** ADR-0030 (sigue en
Propuesta en reevaluación); usa su vocabulario de estados como referencia
normativa del reporte. Si ADR-0030 cambia, este mapeo se reevalúa. El
comando `checkpoint obligation` NO se entrega en esta fase (fuera de
alcance v1).

### 7. Autoridad: el hook no eleva nada (F0-D3/D4)

La declaración del host es dato no confiable como todo `.an-kla/`
(F0-D4). Ningún hook fabrica `tool_observed`, `channel_confirmed` ni
autorización de checkpoint: `checkpoint` sigue el flujo gobernado con
autoridad separada (`checkpoint-authority`); las acciones read-only no
conceden nada. Los hooks pueden *referenciar* receipts de ADR-0046,
nunca fabricarlos. El perfil observado es **diagnóstico, no autoridad**;
`agent_binding` permanece `unverified` (G4). Cualquier PR que toque
`agent_binding` se rechaza en esta fase.

### 8. Worktrees

El host escribe `host-hooks.json` en el checkout canónico. `.an-kla/` no
viaja entre worktrees (regla vigente de `AGENTS.md`/ADR-0022/0031): un
worktree sin memoria propia tampoco proyecta hooks.

## Por qué no [alternativa]

### Extender `integration-status-v1` in-place

El schema congela `observed_profile` con `const` y la raíz con
`additionalProperties: false` (`integration-status-v1.schema.json:6,60`):
toda extensión rompe validadores legacy y §11.2 de prácticas. Pre-restringido
por F0-D5. Descartada.

### Reutilizar `attest-receipt-v1` como registro de hooks

El receipt es command-centric, single-use (su tombstone lo quema al
consumirse) y atado a whitelist + `policy_fingerprint`
(`an_kla/attest.py:345-362, 485-505`): forzarlo convertiría cada lectura
de perfil en consumo destructivo de evidencia y sólo cubriría comandos
shell, no acciones del diccionario. Se reutiliza el **mecanismo**
(canonical-json, O_EXCL, HMAC, reloj inyectable), no el formato.
Descartada; precedencia declarada en §4.

### Acuñar el registro como efecto colateral de las acciones read-only

Rompería la propiedad congelada "no crea nada" de `status`/`retrieve`/
`assemble-context` (`test_integration_status.py:79, 147-152`) y la
expectativa de pureza de las superficies de lectura. Sólo el contexto
explícito de hook (`--on-behalf-of-hook`) escribe. Descartada.

### Eje de hooks en `startup-diagnostic-v1`

Schema cerrado (`startup-diagnostic-v1.schema.json:6`) con tests que
rechazan campos desconocidos (`test_startup_diagnostic.py:205-223`);
añadir un eje in-place exigiría `startup-diagnostic-v2`. El diagnóstico
de arranque no es la superficie del perfil (eso es ADR-0039/G1). Diferido;
los ejes de hooks viven en `integration-status-v2`. Descartada aquí.

### Adoptar ADR-0030 como bloque o entregar `checkpoint obligation`

ADR-0030 está en Propuesta en reevaluación tras los casos
`expertoGobernanza`/`adrc-python`; adoptar su gate completo excedería el
alcance v1 y mezclaría frecuencia de checkpoint con assurance. Se toma
sólo su vocabulario de reporte con precedencia declarada (§6).
Descartada.

### Permitir shell o comandos arbitrarios en el hook

Frontera base: ningún contrato de AN-KLA ejecuta comandos hallados en
declaraciones. El diccionario cerrado con mapeo CLI exacto mantiene el
motor fuera de la mecánica del host. Descartada.

## Consecuencias

- **Positivas:**
  - `observed_profile` deja de ser `unspecified` cuando el host declara y
    ejecuta hooks: la ganancia titular del plan (plan §1).
  - Los hooks dejan de ser disciplina del consumidor y pasan a contrato
    con evidencia acuñada **y verificada** por el motor (no
    autodeclarada; fabricarla exige la clave).
  - La continuidad material pendiente en el cierre se vuelve visible con
    un vocabulario único (ADR-0030), sin segundo vocabulario paralelo.
  - v1 permanece byte-idéntico: cero ruptura de consumidores grepeantes.

- **Negativas:**
  - `.an-kla/hook-runs/` crece lineal y sin limpieza automática (igual
    que receipts); el operador asume huella en disco.
  - Dos schemas de integration-status vigentes (v1 congelado + v2) hasta
    una futura deprecación gobernada de v1.
  - La veracidad del perfil sigue acotada al modelo de ADR-0046: quien
    controle el host y la clave del motor puede acuñar evidencia válida;
    contra eso no hay defensa local — es diagnóstico, no autoridad.

- **Neutras:**
  - El contrato gestionado (`AGENTS.md`/`AN-KLA.md`) **no cambia en v1**:
    F3-D queda re-alcanceado a guía de hosts + plantilla de declaración,
    sin editar `AN-KLA.md` (si en el futuro el contrato del agente
    necesitara reflejar los hooks, sería un bump versionado con su propio
    flujo, no parte de esta fase).
  - MCP permanece read-only y sin superficie de hooks en v1.
  - El registro canónico gana la fila 0047 (47 ADRs: 43 aceptadas,
    4 propuestas); el conteo y su comentario de
    `tests/test_adr_registry.py` se actualizan en el mismo commit.

## Test de regresión

- `scripts/check_adr_registry.py` pasa: fila 0047 presente, estado
  `Propuesta` coherente con este documento.
- `tests/test_adr_registry.py`: conteo `Propuesta` 3→4, `Aceptada` 43;
  el comentario del bloque de propuestas se reescribe (0047 corresponde a
  #56/G2, F2 2026-09-05 — no a #102).
- `scripts/check_sizes.py` pasa: este archivo ≤ 400 líneas.
- Suite canónica en verde (ningún cambio de código en esta fase).

Tests funcionales diferidos a F3/F4 (criterios del plan §3): hooks
omitidos, duplicados, desconocidos, fallidos y reintentados; idempotencia
de `run_id` definida y probada; declaración malformada y registro corrupto
con códigos estables sin filtrar rutas; no-escritura intacta para acciones
planas (`leftovers == []`, propiedad fuerte del CLI en
`test_integration_status.py:147-152`, y ausencia de `.an-kla/memory` en
`:79`); goldens v1 + v2 e igualdad payload↔capabilities; ronda adversarial
final con evidencia (comando → resultado) antes de cerrar la fase.

## Referencias

- **Issue #56** (G2) y su plan técnico con ronda adversarial absorbida:
  `docs/planning/plan-issue-56-g2-host-hooks-2026-09-01.md` +
  `...-adversarial-2026-09-01.md`.
- **Spike F1 (2026-09-05):**
  `docs/planning/plan-issue-56-g2-spike-s1-2026-09-05.md`.
- **Ronda adversarial pre-code de este ADR (2026-09-05, fix-and-retry
  absorbido):**
  `docs/planning/plan-issue-56-g2-adr0047-adversarial-2026-09-05.md`.
- **ADR-0031** — perfil host-managed y mandato G2; seis ejes.
- **ADR-0039** — `integration-status-v1`; precedente de degradación
  diagnosticable y de evolución de contratos publicados.
- **ADR-0046** — attest: mecanismo de receipts, modelo de amenaza y
  precedencia de evidencia observada bajo `.an-kla/`.
- **ADR-0023 / ADR-0030** — checkpoint gobernado y vocabulario de
  obligación de continuidad (referencia, no adopción).
- **ADR-0036** — precedente de ejes observables y evolución aditiva.
- `docs/practicas-ingenieria.md` §11.2 — evolución de contratos
  publicados.
- F0 firmada por el maintainer el 2026-09-05 (sesión).
