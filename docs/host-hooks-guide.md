# Guía de hooks gobernados para hosts (`host-hooks/v1`, ADR-0047)

Guía para el **host** (Cline, Claude Code, scripts de repo) que gestiona
recuperación y checkpoint en nombre del agente. Contrato completo:
[ADR-0047](architecture/0047-host-hooks-governed-v1.md). Esta guía es
F3-D; el contrato gestionado (`AGENTS.md`/`AN-KLA.md`) no cambia en v1.

## Idea en una frase

El host declara sus hooks en un archivo; AN-KLA los lee (sólo lee); cada
ejecución real deja evidencia firmada por el motor; y `integration status
--schema-version v2` calcula el perfil observado a partir de evidencia,
no de promesas.

## 1. Declarar los hooks

El host escribe `.an-kla/host-hooks.json` en el checkout canónico (un
worktree sin `.an-kla/` propio no proyecta hooks). AN-KLA nunca lo crea,
edita ni borra. Límites congelados: máximo **16** hooks; `id` de 1–128
caracteres de `[A-Za-z0-9._-]`, únicos; `budget_bytes` entero 1..1048576;
`required` sólo con `action: "checkpoint"`.

```json
{
  "schema": "an-kla/host-hooks-v1",
  "adapter": {
    "name": "cline",
    "version": "1.0.0",
    "configuration_fingerprint": "sha256:<64-hex del hash de tu config>"
  },
  "declared_profile": "host-managed/v1",
  "hooks": [
    {"id": "before-task-retrieve", "trigger": "before_task",
     "action": "assemble-context", "budget_bytes": 4096},
    {"id": "material-close-checkpoint",
     "trigger": "material_close_or_handoff", "action": "checkpoint",
     "required": true}
  ]
}
```

Acciones de diccionario cerrado: `assemble-context` | `retrieve` |
`checkpoint` | `status`. Un hook jamás declara shell: el host ejecuta su
mecánica y llama al CLI con estas formas:

| Acción | Invocación CLI |
|---|---|
| `status` | `an_kla --project-root <root> status` |
| `retrieve` | `... retrieve --query <q> --budget <b> [--streams <s>]` |
| `assemble-context` | `... assemble-context --query <q> --new-information <n> --budget <b>` |
| `checkpoint` | `... checkpoint plan --input <ws> --authority <auth>` → `... checkpoint commit --plan <plan> --expected-current <sha256:…> --transaction-id <uuid>` |

## 2. Ejecutar los hooks con evidencia

Añade `--on-behalf-of-hook <hook-id>` a la invocación del hook que estás
ejecutando. El motor acuña entonces una entrada firmada (HMAC con
`attest.key`) en `.an-kla/hook-runs/`:

```bash
an_kla --project-root . retrieve --query "estado" --budget 4096 \
  --on-behalf-of-hook before-task-retrieve
```

- Sólo se acuña en camino **exitoso**; el `hook_id` debe estar declarado
  con esa acción (si no, verás
  `an-kla warning: hook_run_mint_skipped (…)` en stderr y el comando
  conserva su resultado).
- Sin `attest init` no hay acuñación (`attest_not_initialized`).
- **Una invocación plana sin el flag no escribe nada.**
- Cada flujo genera un `run_id` nuevo: dos invocaciones distintas dejan
  dos entradas (evidencia de dos ejecuciones reales). El mismo `run_id`
  es no-op idempotente (reintento del mismo flujo).

## 3. Observar el resultado

```bash
an_kla --project-root . integration status --schema-version v2
```

- `integration.observed_profile`: `unspecified` (sin declaración),
  `declared-not-invoked` (declaración sin evidencia reciente) o
  `host-managed/v1` (declaración + al menos un run **verificado** en las
  últimas **24 horas**). El perfil se calcula, nunca se persiste.
- `host_hooks.pending_continuity`: `required` si un hook
  `material_close_or_handoff` marcado `required: true` no tiene run
  reciente — el fallo visible de continuidad; `indeterminate` si la
  lectura de evidencia está degradada.
- `host_hooks.degraded_codes`: entradas corruptas o sin llave
  (`hook_run_invalid`, `attest_not_initialized`). Una entrada inválida
  jamás contribuye al perfil.
- `--now <ISO-8601>` inyecta el reloj para evaluar recencia de forma
  reproducible.

## 4. Qué NO es este contrato

- La declaración es **dato no confiable**, como todo `.an-kla/`:
  describir hooks no autoriza nada.
- Ningún hook fabrica autoridad: `checkpoint` sigue el flujo gobernado
  con autoridad separada; las acciones read-only no conceden nada.
- El perfil es **diagnóstico, no autoridad**; `agent_binding` sigue
  `unverified` (identidad de agente es G4).
- Un hook que falla no bloquea al host; la política de bloqueo es
  decisión del host. El rastro queda en la salida del comando y en la
  ausencia de evidencia reciente (`pending_continuity`).

## 5. Mantenimiento

- `.an-kla/hook-runs/` crece lineal y **sin limpieza automática** (igual
  que receipts y ref-log); limpieza futura gobernada, nunca automática.
- La compactación jamás alcanza a `hook-runs/` (vive fuera de `memory/`).
- Hooks huérfanos (runs cuyo `hook_id` ya no está declarado) se listan
  en `unknown_hooks` como dato: reordenar la declaración es seguro.
- Requiere `attest init` (ADR-0046) en el proyecto: la misma llave firma
  receipts y hook-runs.
