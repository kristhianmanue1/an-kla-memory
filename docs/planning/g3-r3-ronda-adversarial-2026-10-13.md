# G3 · R3 — ronda adversarial final

- **Artefacto revisado:** `git diff 6cb1faf..8f71390` (G3 R0–R3, ~5.100 líneas,
  45 archivos) más las correcciones de esta acta.
- **Fecha:** 2026-10-13.
- **Revisor:** subagente de contexto fresco lanzado por el agente ejecutor.
  Era de la misma familia de modelo, trabajó en sólo lectura, sin el
  historial de la implementación y con instrucción de refutar. **No es
  revisión independiente**: comparte modelo y orquestador con el productor.
  Las correcciones son autorrevisión del productor.
- **Veredicto del revisor:** `fix-and-retry`. **Tras correcciones:**
  `proceed` para cerrar G3 técnicamente, con la decisión pendiente §M3 y los
  riesgos residuales de abajo. `proceed` no autoriza un release.

## Hallazgos y resolución

| Id | Severidad | Hallazgo (reproducido salvo indicación) | Resolución | Evidencia |
| --- | --- | --- | --- | --- |
| M1 | MAJOR | Tras borrar el puntero en relocate-back, la bóveda externa aceptaba escrituras por flag/env: dos bóvedas vivas | `check_custody` falla con `store_root_divergence` si la custodia es externa, no hay puntero y existe bóveda project-local (Enmienda 4 §2) | `test_after_commit_point_the_external_copy_is_inert_and_local_may_advance`; `test_destination_before_pointer_is_inert_and_abort_checks_every_file`; script del revisor → `external write blocked` |
| M2 | MAJOR | Una escritura local tras el commit de relocate-back impedía reconciliar para siempre | Tras `pointer_removed` ya no se exige igualdad de revisión; el cleanup sólo borra archivos que coinciden byte a byte con el plan | mismo test (commit local antes de `reconcile`) |
| M3 | MAJOR | `--store-root <bóveda ajena> init` ligaba un segundo proyecto | `init` sin puntero exige `canonical_project_root_at_init` igual a la raíz del proyecto → `store_root_project_mismatch` | `test_init_never_binds_another_projects_vault`. Ligar una bóveda movida de raíz queda como **REQUIRES_DECISION** (Enmienda 4 §3) |
| m1 | MINOR | Crash entre el bootstrap externo y el puntero: un `init` desnudo posterior crea una gemela | **No corregido.** Recuperación: repetir `--store-root <bóveda> init` *antes* de cualquier `init` desnudo | riesgo residual |
| m2 | MINOR | Un traslado interrumpido no aparecía en diagnósticos | `doctor.custody_divergence.relocations_unfinished` | test M1/M2 (valor 1 antes de reconciliar) |
| m3 | MINOR (razonado) | `reconcile --abort` de ida borraba el árbol sin mirar archivos fuera del allow-list; un fallo de `fsync` tras el rename marcaba `aborted` | El abort exige que todo archivo sea copia planificada, receipt propio o lock inerte; el `fsync` se movió fuera del bloque pre-publicación | test m3 (archivo ajeno en `indexes/` → `relocate_destination_unrecognized`) |
| m4 | MINOR (razonado) | Un proceso longevo calcula `custody_pointer_present` una sola vez | **No corregido**: las mutaciones sí releen el puntero; las lecturas de un MCP abierto antes de un relocate pueden servir el origen si el cleanup quedó pendiente | riesgo residual |

## Comprobado sin contraejemplo (según el revisor)

- Layout por defecto byte-compatible (walk de identidad y de export iguales a beta.29).
- Descriptores de diagnóstico sin rutas. Planes, journals y receipts sí llevan
  rutas por diseño; los relocation receipts viajan en los bundles de export.
- Export y restore conservan los controles de rutas inseguras.
- Orden de locks: identidad y después escritura; sin inversiones.

## Riesgos residuales tras la ronda

- m1 y m4, arriba.
- La variable de entorno sin puntero hacia otra raíz sólo avisa (Enmienda 4 §4).
- El puntero no es control de acceso; la simulación de crash no es `kill -9`.

## Evidencia de verificación

- Tests focalizados tras las correcciones: 77 OK (relocate, relocate_back,
  custody_*, export_restore, adr_registry).
- Scripts del revisor re-ejecutados: M1 bloqueado, M2 reconcilia, M3 bloqueado;
  la gemela de m1 se sigue reproduciendo (no corregida).
- Suite completa y gates: ver la PR de R3.
