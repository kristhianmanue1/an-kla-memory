# G3 · R2a — traslado gobernado (`relocate`)

- **Tarea:** R2a del plan `docs/plans/2026-10-10-g3-discovery-agent-roadmap.md` (#57).
- **Estado:** `verified` para el alcance descrito: project-local → externo.
  **No** acredita relocate-back ni recuperación tras recrear el checkout
  (R2b), export desde custodia externa (R3) ni externo → externo.
- **Fecha:** 2026-10-13. **Base:** `main` en `1a6f346` (R0–R1c, PRs #141 y #142).
- **Ejecutor:** agente Claude Code (modelo efectivo `unknown`). **Revisión:**
  autorrevisión adversarial; sin revisor independiente.

## Flujo

1. `relocate plan --to <abs>`: bajo `identity_lock` + `write_lock`, verifica la
   bóveda, fija `base_revision`, `custody_fingerprint`, `store_identity` y el
   set exacto (allow-list de export + `attest.key`) con tamaño y sha256. El
   destino debe ser absoluto, ausente y válido como `store_root`.
2. `relocate commit --plan <file> --expected-current <rev>`: bajo los mismos
   locks revalida identidad, CURRENT, destino ausente y set; escribe el
   journal `staging`; copia a `<padre>/.staging-<txid>` con hash por archivo;
   escribe el receipt `store_root`; `verify()` del staging; `rename_noreplace`;
   journal `published`; puntero; journal `pointer_written`; cleanup bajo gate
   exclusivo de lectores; journal `cleaned`.
3. `relocate inspect|reconcile --transaction-id`: estado observado y
   recuperación (`--abort` sólo antes del puntero).

Decisiones de mecanismo: ADR-0048 Enmienda 2.

## Matriz de fallo (tests en `tests/test_relocate.py`)

| Punto | Estado que deja | Recuperación probada |
| --- | --- | --- |
| Expected-current o digest del plan alterados | nada escrito | — |
| Destino ocupado, CURRENT movido, contenido alterado | origen intacto; journal `aborted` si ya había empezado | plan nuevo |
| Crash tras journal / antes de publicar | `staging`, sin destino | `reconcile` → `aborted`, staging borrado |
| Crash tras `rename` sin journal | `staging`, destino presente | `reconcile` reconoce la copia exacta + receipt propio → continúa |
| Crash tras `published` | destino, sin puntero | `reconcile` → `cleaned`; o `--abort` → borra sólo la copia exacta |
| Origen avanzó tras el crash | copia obsoleta | `relocate_source_advanced`; `--abort` |
| Crash tras el puntero | origen aún presente | `reconcile` → `cleaned`; `--abort` → `relocate_abort_too_late` |
| Destino ajeno apareció tras el crash | bóveda de otro proyecto | `reconcile` aborta sin tocarla ni escribir puntero |
| Lector con gate compartido durante el cleanup | `pointer_written`, origen completo | `relocate_cleanup_readers_active`; `reconcile` al soltarse |
| Dos commits concurrentes del mismo plan | uno ejecuta | el otro devuelve `replayed: true` (sin duplicar) |
| Escritor abierto antes del puntero | árbol muerto | falla cerrado; la bóveda no cambia |
| Commit repetido tras éxito (timeout) | — | `replayed: true`, mismo receipt |

## Evidencia

- `python3 -m unittest tests.test_relocate` → 9 tests OK (el de crash recorre
  5 puntos como subtests).
- Prueba manual en temp: tras relocate, `retrieve` y `doctor` funcionan por
  el puntero sin `rebuild-index` manual; el anchor del proyecto conserva sólo
  `store-root.txt`, `relocations/` y archivos de lock.
- Suite completa sobre `3c03476` (Python 3.13.16, Linux): `Ran 1109 tests in 542.806s` · `OK (skipped=12)`. Gates `check_sizes`, `check_plans`, `check_adr_registry` OK.

## Límites y riesgos residuales

- La simulación de crash es un `BaseException` en límites de etapa, no un
  `kill -9` ni pérdida de energía; la durabilidad depende de los fsync de
  `normalize_and_sync_tree`, `atomic_write` y directorios padre.
- El journal vive en el checkout: borrar el checkout a mitad de un relocate
  pierde el journal (la bóveda publicada y su receipt siguen; R2b cubre
  recrear el checkout).
- Un escritor obsoleto puede recrear directorios vacíos en el árbol muerto
  (`_make_layout`) antes de fallar.
- Las rutas absolutas viajan en el plan, el journal y el receipt (igual que
  los receipts de R1a); los diagnósticos siguen sin rutas.
