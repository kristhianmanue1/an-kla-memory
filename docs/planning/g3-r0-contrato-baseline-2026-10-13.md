# G3 · R0 — contrato reconciliado, baseline y matriz de compatibilidad

- **Tarea:** R0 del plan `docs/plans/2026-10-10-g3-discovery-agent-roadmap.md` (#57).
- **Fecha de observación:** 2026-10-13 (UTC).
- **Base:** `main` = `origin/main` = `6cb1faf0a268ae4df305a36f1dd4588eb267c4b7`
  (beta.29). Rama de trabajo `claude/g3-roadmap-m25oie`, árbol limpio al iniciar.
  El plan se escribió sobre `0f874e9`; la diferencia es el release beta.29
  (PRs #138, #139), sin cambios en store, identidad ni export.
- **Ejecutor:** agente Claude Code en contenedor Linux (modelo efectivo:
  `unknown` para este documento). **Revisor:** ninguno independiente; las
  comprobaciones de este documento son autorrevisión.
- **Autoridad:** el maintainer autorizó commits y push para avanzar el plan
  (2026-10-13). No autorizó merge, tag, release ni escritura en un store
  AN-KLA vivo; R0 no escribe ninguno.

## 1. Baseline (antes de cualquier cambio G3)

Intérprete `Python 3.13.16`, Linux x86_64, SHA `6cb1faf`, sin `.an-kla/` local.

| Comando | Resultado real |
| --- | --- |
| `python3 -m unittest discover -s tests -p 'test_*.py'` | `Ran 1056 tests in 516.558s` · `OK (skipped=12)` |
| `python3 scripts/check_sizes.py` | `OK — 466 archivos de texto dentro de límites` |
| `python3 scripts/check_plans.py` | `OK — 3 plan(es) verificados (estructura E1-E5)` |
| `python3 scripts/check_adr_registry.py` | `OK — 49 ADRs (aceptada=46, propuesta=3)` |

Una ejecución independiente previa (hilo de análisis, mismo SHA y mismo
intérprete) reportó el mismo conteo. **Límites:** no cubre macOS ni
Python 3.9/3.12; el repositorio no tiene `.github/workflows/`, así que no hay
CI remoto que contraste. Los 12 skips no se auditaron en R0.

## 2. Nombres de schemas (paso 1)

- **Hecho:** ADR-0048 §4 y §Consecuencias reservan `startup-diagnostic-v2`
  para custodia.
- **Hecho:** `startup-diagnostic-v2` está publicado desde beta.28 con otro
  significado: bloque `vocabulary` (ADR-0049, #133). Consumidores:
  `an_kla/startup.py:24,192`, `an_kla/schemas/__init__.py:74`,
  `an_kla/schemas/startup-diagnostic-v2.schema.json`,
  `tests/test_startup_diagnostic.py`, `tests/test_agent_contracts.py`.
- **Hecho:** `integration-status-v3` no existe; sólo v1 y v2.
- **Resolución:** ADR-0048 Enmienda 1 renombra el diagnóstico de custodia a
  `startup-diagnostic-v3`, superconjunto que conserva `vocabulary` tal como lo
  emite la ruta beta.28. `integration-status-v3` no cambia. Estado de la
  decisión normativa: ver la Enmienda 1 del ADR.

## 3. Referencias históricas del fallo #119 (paso 2)

- **Hecho:** #119 está cerrado (`completed`, 2026-09-06T04:05Z).
- **Hecho:** `an_kla/export_restore.py:43` incluye
  `anchor/hook-runs/runs/sha256/<hex>.json` en `_PATTERNS` y
  `an_kla/export_restore.py:67` excluye `anchor/host-hooks.json`, como fijó
  ADR-0048 §3 (H3).
- **Hecho:** `tests/test_export_restore.py:44`
  (`test_export_with_host_managed_artifacts_issue119`) pasa en la baseline.
- **Resolución:** la frase de ADR-0048 §3 «Hoy un proyecto con perfil
  host-managed no puede exportar» describe el estado del 2026-09-05. La
  Enmienda 1 la marca como histórica y resuelta, sin borrar su procedencia
  ni el registro de la ronda pre-code.

## 4. `restore` frente a `relocate` (paso 3)

Delimitación según ADR-0048 §Por qué no y `export_restore.py:254-270`. Esta
tabla no amplía `restore`; la fila marcada «decisión separada» queda fuera del
plan hasta que el maintainer la decida.

| Operación | Origen | Destino | Contrato vigente tras G3 |
| --- | --- | --- | --- |
| `export create`/`verify` | project-local | bundle | sin cambio |
| `export create`/`verify` | store externo | bundle | R3: anchors desde la custodia resuelta; mismas exclusiones (`attest.key`, `host-hooks.json`) |
| `export restore` | bundle | project-local sin `.an-kla` | sin cambio: publica project-local, identidad nueva de raíz (`root_relocated: true`) |
| `export restore` | bundle | store externo | **decisión separada**; no se implementa en G3 |
| `relocate plan/commit` | project-local | store externo | R2a: custodia continua, mismo binding, staging hermano + `rename_noreplace` |
| `relocate` back | store externo | project-local | R2b: publicación por subárbol bajo `write_lock` + journal |

## 5. Convenciones de implementación que R1 fija dentro de ADR-0048

Estas convenciones concretan lo que el ADR deja como mecanismo; no cambian su
decisión. Si el maintainer las objeta, se revisan antes de R1c.

1. **Raíz de custodia y walk de symlinks.** `store_root` se resuelve a ruta
   absoluta (`Path.resolve()`); por defecto es `project_root/.an-kla`. Todo
   recorrido de symlinks de identidad se ancla en `store_root.parent`. En el
   caso por defecto eso es `project_root`: comportamiento byte-idéntico al
   actual, incluido el rechazo de `.an-kla` como symlink.
2. **Rutas relativas de receipts (H9).** El prefijo `.an-kla/` de las rutas en
   `identity-durability-receipt-v1` denota la raíz de custodia, no un
   directorio literal bajo el proyecto. Es la única lectura en la que «los
   receipts anteriores a un relocate siguen resolviendo igual» (ADR §2) cuando
   la bóveda externa no se llama `.an-kla`. El schema no cambia.
3. **Fingerprint de custodia.** `custody_fingerprint =
   digest_json({"schema": "an-kla/custody-binding-v1", "project_uuid": …,
   "store_identity": …})`, calculado sobre los bytes de identidad ya ligados.
   No contiene rutas.
4. **Puntero.** `project_root/.an-kla/store-root.txt` contiene JSON canónico
   `{"schema": "an-kla/store-root-pointer-v1", "store_root": <ruta absoluta>,
   "custody_fingerprint": <digest>}`. La ruta es localizador, nunca
   autoridad: la custodia abierta debe reproducir el fingerprint o la
   operación falla con `store_root_divergence`.
5. **`init` con store externo deja el puntero.** ADR §1 asigna el puntero a
   `relocate commit`; un `init --store-root` fresco sin puntero reproduciría
   H1 (la siguiente invocación sin flag resolvería project-local y un `init`
   fabricaría una bóveda gemela). Por eso `init` externo también lo escribe,
   tras completar la identidad.
6. **Relocation receipt (§2).** Se guarda bajo
   `store_root/relocation-receipts/sha256/`, encadenado por
   `predecessor_receipt`, ligado a `store_identity`, `current_observed` y a
   las raíces observadas antes y después. Registra un hecho; no autoriza nada
   por sí mismo fuera de `adopt`.

## 6. Matriz de variantes (paso 5)

| Variante | Resultado esperado | Falsación |
| --- | --- | --- |
| V1 project-local legado, sin flag/env/puntero | idéntico a beta.29: `store_root = project_root/.an-kla` | cualquier test de la baseline cambia de resultado, o un byte de layout difiere |
| V2 store externo fresco (`--store-root`/env) | `init` crea identidad bajo `store_root`, escribe puntero; `verify` verde | `store_identity_invalid` en init fresco, o el puntero falta tras init |
| V3 externo resuelto por puntero, sin flag ni env | abre la misma identidad y revisión | se abre o crea un store project-local |
| V4 puntero presente y custodia resuelta distinta | `store_root_divergence` en mutaciones, `init` y `adopt`; sin escritura | se crea una bóveda gemela o se escribe en la raíz equivocada |
| V5 flag y env divergentes | gana el flag; aviso en stderr | gana el env o no hay diagnóstico |
| V6 worktree sin resolución | comportamiento de hoy: store ausente + `linked_worktree` | un worktree inicializa memoria propia por defecto |
| V7 worktree con resolución (env/flag; puntero en R3) | misma identidad/revisión que el checkout | identidad distinta o store gemelo |
| V8 symlink hostil en la custodia externa | `store_identity_invalid`, sin escritura | se sigue el symlink |
| V9 `adopt` con plan observado en otra raíz | sin receipt: `identity_adoption_base_changed`; con receipt válido: adopción | receipt ausente, inválido o de otro binding permite adoptar |
| V10 entradas aún no adaptadas (attest, hook-runs, CLI, MCP, upgrade) con custodia externa | R1a: fallo cerrado estable; R1c: misma custodia | acuñan evidencia en `project_root/.an-kla` o abren otra bóveda |
| Plataformas | macOS/Linux en v1; Windows diferido (F0) | — |

## 7. Estado de R0

- Pasos 1–3 y 5: documentados aquí y en ADR-0048 Enmienda 1.
- Paso 4 (baseline): ejecutado, §1.
- Pendiente fuera del agente: confirmación normativa del maintainer del
  nombre `startup-diagnostic-v3` (bloquea R1b, no R1a).
