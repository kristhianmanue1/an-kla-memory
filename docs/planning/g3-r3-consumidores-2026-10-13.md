# G3 · R3 — consumidores: export, worktrees e instrucciones

- **Tarea:** R3 (pasos 1–3) del plan `docs/plans/2026-10-10-g3-discovery-agent-roadmap.md` (#57).
  El paso 4, la ronda adversarial final, tiene su propia acta:
  `docs/planning/g3-r3-ronda-adversarial-2026-10-13.md`.
- **Fecha:** 2026-10-13. **Base:** `main` en `05fd7c9` (R2b, PR #144).
- **Ejecutor:** agente Claude Code (modelo efectivo `unknown`). **Revisión:**
  autorrevisión adversarial en este corte.

## Cambios

| Pieza | Cambio |
| --- | --- |
| `export_restore._export_anchor` | Devuelve la raíz de custodia resuelta. Antes falla cerrado si el puntero diverge (`check_custody`) o si se abre la raíz project-local habiendo puntero. Sustituye a `require_project_local`, que se elimina |
| `export_restore._read_anchor` | Lee desde el padre del anchor con `safe_read`. Para la custodia project-local es exactamente el recorrido de beta.29; un anchor enlazado por symlink se sigue rechazando |
| `sealed/bundle.py` | Usa el mismo anchor y el mismo lector |
| `restore` (claro y sellado) | Sin cambios: publica sólo project-local (Enmienda 1 §3) |
| `AGENTS.md`, sección manual «Worktrees y memoria» | Regla posterior a #57: un worktree comparte la bóveda por el checkout canónico o por `AN_KLA_STORE_ROOT`/`--store-root`, nunca con `init` propio. El bloque gestionado no cambia |

## Matriz (tests)

| Caso | Test |
| --- | --- |
| Export claro desde bóveda externa → verify → restore project-local con la misma revisión y fingerprint, sin puntero ni `attest.key` | `tests/test_custody_export.py::test_plain_export_from_external_custody_restores_project_local` |
| Export sellado desde bóveda externa → restore project-local | `test_sealed_export_from_external_custody` (requiere `cryptography`; corrió aquí) |
| Bundle dentro de la bóveda, destino ocupado, puntero divergente, restore sobre un checkout con anchor | `test_export_negative_controls` |
| Entrada con `..` y digest del manifiesto re-sellado | `test_tampered_bundle_cannot_escape_the_destination` (`export_entries_invalid`; el digest no es lo que la rechaza) |
| Worktree sin resolución (`absent`, sin `init`) y con `AN_KLA_STORE_ROOT` (misma identidad y revisión) | `tests/test_custody_entries.py::test_worktree_without_and_with_resolution` (R1c) |
| Export project-local tras relocate-back | `tests/test_relocate_back.py` roundtrip |

## Verificación de instrucciones

- Lectura final de `AGENTS.md` (sección manual) y del bloque gestionado:
  `context status` → `ok: true`, `diagnostics: []`, sin crear `.an-kla/`.
- Los dos ejemplos de la sección corresponden a comportamientos probados: el
  checkout canónico (`--project-root`) y `AN_KLA_STORE_ROOT` desde un worktree
  (test de worktree citado arriba).

## Evidencia

- Tests focalizados: `tests.test_custody_export tests.test_custody_root tests.test_export_restore tests.test_sealed_bundle tests.test_relocate tests.test_relocate_back` → 80 tests OK.
- Suite completa sobre `302b7b1`: `Ran 1122 tests in 555.030s` · `OK (skipped=12)`; gates OK.

## Límites

- Restore a un destino externo sigue fuera de G3 (Enmienda 1 §3).
- No se publicaron bundles ni claves; todo ocurrió en directorios temporales.
