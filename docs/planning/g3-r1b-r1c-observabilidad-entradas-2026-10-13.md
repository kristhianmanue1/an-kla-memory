# G3 · R1b y R1c — observabilidad de custodia y entradas

- **Tareas:** R1b y R1c del plan `docs/plans/2026-10-10-g3-discovery-agent-roadmap.md` (#57).
- **Estado:** `verified` para el alcance descrito. Tras R1c el store externo
  nuevo es utilizable por CLI, MCP (lectura), upgrade, attest y hook-runs.
  **No** acredita `relocate` (R2) ni export claro o sellado desde custodia
  externa (R3), que siguen fallando cerrados.
- **Fecha:** 2026-10-13. **Base:** `main` en `51ba336` (R0 + R1a, PR #141).
- **Ejecutor:** agente Claude Code (modelo efectivo `unknown`). **Revisión:**
  autorrevisión adversarial; sin revisor independiente.

## Decisiones tomadas bajo delegación del maintainer

El maintainer delegó las decisiones del plan al agente (2026-10-13). Cada
una se registra con su alternativa descartada:

1. **Emisión de `startup-diagnostic-v3`.** Dispersa (convención ADR-0049):
   v3 aparece cuando la custodia no es la project-local por defecto (store
   externo o puntero presente), o con `startup-diagnostic --schema-version
   v3`. El layout por defecto conserva v1/v2 byte-idénticos. *Descartado:*
   v3 siempre (rompe a todo lector de v1/v2 sin aportar información) y v3
   sólo opt-in (un lector v1/v2 recibiría `external_memory_evaluated:
   false` sobre una bóveda externa, que es falso).
2. **`integration-status-v3` opt-in** (`--schema-version v3`), igual que v2.
   v1 y v2 fijan `external_memory_evaluated: false` aunque la custodia sea
   externa: sus schemas son congelados y significan «no evaluado».
3. **`doctor.custody_divergence`** se añade a `doctor-v1`, que no tiene
   schema JSON publicado; es aditivo.
4. **Resolución compartida.** `an_kla/store_resolution.py` resuelve para CLI,
   MCP y upgrade. Un puntero inválido no aborta el proceso: abre el store
   project-local, cuyas lecturas y mutaciones fallan cerradas, y deja
   operar a las superficies project-local (contexto gestionado,
   capabilities, schemas).
5. **Hook Git.** La plantilla `docs/hooks-template/pre-commit` hace `unset
   AN_KLA_STORE_ROOT` (H8): resuelve por el puntero del proyecto, nunca por
   una variable heredada del shell.
6. **Aviso de env no ligado.** Con `AN_KLA_STORE_ROOT` y sin puntero, si la
   identidad de la bóveda se inicializó en otra raíz, la CLI avisa
   `store_root_env_unbound_project`. No bloquea: el binding es por bytes y
   un worktree legítimo produce el mismo caso.

## Qué cambia

| Pieza | Cambio |
| --- | --- |
| `an_kla/custody_status.py` (nuevo) | Descriptor de custodia total y sin rutas (`store_external`, `custody_fingerprint`, `pointer`, `divergence`) y eje de doctor |
| Schemas | `startup-diagnostic-v3` e `integration-status-v3` en `an_kla/schemas/` y `docs/schemas/`; v1/v2 intactos |
| `startup.py`, `integration.py`, `store_recovery.py` | v3 disperso, v3 opt-in, eje `custody_divergence` |
| `attest.py`, `hook_runs.py` | Llave, whitelist, receipts, nonces y hook-runs bajo la raíz de custodia (F0-B); verificación del puntero antes de acuñar; `receipt_path` conserva el prefijo lógico `.an-kla/` |
| `store.py` | `init` externo crea el material de attest en la bóveda |
| CLI | `--store-root` global; `attest init/run` y `upgrade apply/verify` usan la custodia resuelta; avisos estables en stderr |
| MCP | `--store-root` y la misma resolución; sigue siendo superficie de lectura |
| `capabilities` | Bloque `storage.custody` y `integration.schema_v3` |

## Matriz entrada × estado de custodia (tests)

| Entrada | Externo por flag/env/puntero | Puntero divergente o inválido | Sin resolución |
| --- | --- | --- | --- |
| CLI `init`/`status` | misma revisión e identidad (`test_cli_resolves_flag_env_and_pointer_to_the_same_vault`) | aviso + `store_root_divergence` / `store_root_pointer_invalid`, sin bóveda gemela | project-local (beta.29) |
| CLI `attest run` / `hook-runs` | receipts y runs en la bóveda | `store_root_divergence`, nada acuñado (`test_custody_entries_refuse_a_disowned_vault`) | project-local |
| `startup-diagnostic` / `integration status v3` | v3, `divergence: none`, sin rutas | código de divergencia estable | v1/v2 |
| MCP | sigue el puntero (`test_mcp_and_upgrade_follow_the_pointer`) | lecturas fallan cerradas | project-local |
| `upgrade verify` | verifica la bóveda resuelta | igual que CLI | project-local |
| Worktree enlazado | con env: misma identidad, `root_relocated: true` observacional | — | store ausente + `linked_worktree`, sin `init` (`test_worktree_without_and_with_resolution`) |
| Hook Git (checkout y worktree) | ignora `AN_KLA_STORE_ROOT` heredado, con control positivo del wrapper | — | degradación existente |
| `export create` claro/sellado | `store_root_external_unsupported` (R3) | — | project-local |

## Evidencia

- `python3 -m unittest tests.test_custody_root tests.test_custody_diagnostics tests.test_custody_entries`
  → 43 tests OK.
- Suite completa (Python 3.13.16, Linux): `Ran 1099 tests in 521.283s` ·
  `OK (skipped=12)`.
- Corrección posterior detectada en autorrevisión: un relocation receipt de
  R1a hacía fallar `export create` con `export_unrecognized_durable_path`.
  Ahora `relocation-receipts/` viaja en el export (evidencia de la bóveda) y
  `store-root.txt` queda excluido (es del proyecto); regresión en
  `test_relocation_receipt_travels_in_export`. La suite se repitió sobre
  este diff final (resultado en la PR).
- Gates: `check_sizes` OK (478 archivos), `check_plans` OK,
  `check_adr_registry` OK.

## Límites y riesgos residuales

- Export claro y sellado desde custodia externa: pendiente de R3.
- `relocate` (mover una bóveda existente) no existe todavía: R2.
- El puntero sigue sin ser control de acceso (ver registro R1a).
- La variable de entorno es global al shell: dos proyectos pueden apuntar a
  la misma bóveda. Sólo se avisa; ADR-0048 decide que la env resuelve
  *dónde leer* y no liga proyecto.
