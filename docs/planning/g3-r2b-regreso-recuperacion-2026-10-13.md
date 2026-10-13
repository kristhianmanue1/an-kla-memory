# G3 · R2b — regreso y recuperación de custodia

- **Tarea:** R2b del plan `docs/plans/2026-10-10-g3-discovery-agent-roadmap.md` (#57).
- **Estado:** `verified` para el alcance descrito. Con R2a, R2 queda
  demostrado en stores de prueba. **No** acredita export desde custodia
  externa ni la ronda adversarial final (R3).
- **Fecha:** 2026-10-13. **Base:** `main` en `d6a1f44` (R2a, PR #143).
- **Ejecutor:** agente Claude Code (modelo efectivo `unknown`). **Revisión:**
  autorrevisión adversarial; sin revisor independiente.

Decisiones de mecanismo: ADR-0048 Enmienda 3.

## Matriz (tests en `tests/test_relocate_back.py` y `tests/test_relocate.py`)

| Caso | Verificación |
| --- | --- |
| Roundtrip project-local → externo → project-local → externo | bytes de cada entrada del plan, CURRENT, fingerprint de custodia, cadena de receipts `store_root` (predecesor enlazado), `context/` intacto, export claro de nuevo operativo, replay idempotente |
| Subárbol ocupado en el destino (al planear y al ejecutar) | `relocate_destination_occupied`; la bóveda externa sigue resolviendo |
| Crash entre subárboles (`published:memory/refs`) | lectura sigue en la bóveda; `reconcile` → `cleaned`, o `--abort` → `aborted` retirando sólo copias exactas |
| Crash tras borrar el puntero | `--abort` → `relocate_abort_too_late`; `reconcile` → `cleaned` |
| Checkout borrado y recreado | diagnóstico `absent` sin `init` implícito; `--store-root` + `init` devuelve la revisión original y reescribe el puntero |
| Puntero/bóveda ajenos | escritura → `store_root_divergence` |
| `init --store-root` con bóveda project-local existente | `store_root_divergence`, sin gemela ni puntero |
| CLI `relocate plan --back` / `commit` | `status` por resolución project-local con la misma revisión |

## Evidencia

- `python3 -m unittest tests.test_relocate_back tests.test_relocate` → 15 tests OK.
- Suite completa sobre `57d50a2` (Python 3.13.16, Linux): `Ran 1115 tests in 552.420s` · `OK (skipped=12)`. Gates OK.

## Límites y riesgos residuales

- No hay un único `rename` en el regreso: entre subárboles el anchor del
  proyecto está parcial, protegido por el puntero (lecturas project-local
  fallan cerradas) y por el journal.
- Evidencia tardía sin lock (`receipts/`, `hook-runs/`) que quedó en el
  proyecto tras R2a bloquea el regreso como subárbol ocupado: hay que
  revisarla a mano; no se mezcla automáticamente.
- Con `AN_KLA_STORE_ROOT` aún apuntando a la raíz externa vaciada, una
  invocación resolvería un store ausente; `init` allí queda bloqueado por la
  guarda de la Enmienda 3 §6 mientras exista la bóveda project-local.
