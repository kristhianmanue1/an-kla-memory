# G3 · R1a — resolución de raíces e identidad sin migración

- **Tarea:** R1a del plan `docs/plans/2026-10-10-g3-discovery-agent-roadmap.md` (#57).
- **Estado:** `verified` para el alcance de R1a descrito aquí; **no** acredita
  que la custodia externa funcione de extremo a extremo (eso exige R1b y R1c).
- **Fecha:** 2026-10-13. **Base:** R0 (`docs/planning/g3-r0-contrato-baseline-2026-10-13.md`).
- **Ejecutor:** agente Claude Code (modelo efectivo `unknown`). **Revisión:**
  autorrevisión adversarial; sin revisor independiente.

## Qué cambia

| Pieza | Cambio |
| --- | --- |
| `an_kla/custody.py` (nuevo) | Resolución flag > env > puntero > project-local (`resolve_store_root`), lectura y escritura del puntero `.an-kla/store-root.txt`, `custody_fingerprint` sin rutas y guardas `check_custody`/`require_project_local` con códigos estables |
| `MemoryStore(project_root, *, store_root=None)` | `store_root` por defecto `project_root/.an-kla`; `custody_walk_root = store_root.parent`; rechaza raíces dentro de `.an-kla`, iguales o ancestras del proyecto (`store_root_invalid`). El constructor no lee entorno ni puntero |
| `identity.py` | Anchor y todos los walks de symlink re-anclados a la custodia (regla general H4); guarda de puntero en `init`, `adopt`, `repair` y en toda mutación (`mutation_preflight`) |
| `identity_evidence.py` | Receipts bajo `store_root`; el prefijo `.an-kla/` de sus rutas se interpreta como raíz de custodia (H9, Enmienda 1 §4); el schema no cambia |
| `an_kla/relocation_receipts.py` (nuevo) | Receipts `an-kla/relocation-receipt-v1` encadenados por `predecessor_receipt`, bajo `store_root/relocation-receipts/sha256/` |
| `adopt` | La igualdad de ruta se sustituye por un relocation receipt: plan observado en otra raíz + receipt válido adopta; receipt ausente, inválido, de otro plan o con symlink falla cerrado. CLI: `identity record-relocation` y `identity adopt --relocation-receipt` |
| `init` externo | Escribe el puntero tras completar la identidad; `attest` queda degradado de forma visible (`attest_external_custody_pending`) hasta R1c |
| Entradas no adaptadas | `attest run/init`, verificación y consumo de receipts de attest, `hook-runs` (acuñar y leer), `export create` claro y sellado: fallo cerrado `store_root_external_unsupported` con custodia externa o con puntero presente |
| Lecturas project-local con puntero | `read_current` falla con `store_root_divergence` si existe puntero y el store abierto es el project-local (evita servir una bóveda gemela) |

## Evidencia (comando → resultado)

- `python3 -m unittest tests.test_custody_root` → `Ran 25 tests` · `OK`.
- Control positivo de H9: con `_custody_target` mutado para resolver contra
  `project_root`, `test_legacy_receipts_resolve_against_moved_custody_root`
  falla (`FAILED (failures=1)`); restaurado, pasa.
- Suite completa sobre el diff final de R1a (Python 3.13.16, Linux):
  `Ran 1081 tests in 500.699s` · `OK (skipped=12)`; incluye
  `test_sealed_matrix_rows` que ejecuta `scripts/ci_local.py` anidado.
- Una primera corrida falló sólo por `check_sizes` (`identity.py` 829 y
  `sealed/bundle.py` 802 líneas > 800); se extrajo
  `an_kla/identity_relocation.py` y `_export_anchor`, y la segunda corrida
  quedó verde.
- Gates: `check_sizes` OK (470 archivos), `check_plans` OK (3 planes),
  `check_adr_registry` OK (49 ADRs).

Casos cubiertos por `tests/test_custody_root.py`: V1 layout por defecto
idéntico; V2 init externo fresco (identidad en la bóveda, sólo el puntero en
el proyecto, `verify` verde); V3 resolución por puntero con la misma
identidad y revisión tras un commit; V4 puntero frente a init project-local,
bóveda fresca en otra ruta, bóveda ajena y gemela copiada; V5 precedencia y
aviso flag/env; puntero inválido o symlink; V8 symlink hostil en la bóveda y
en `identity-receipts`; V9 adopción con receipt (válido, ausente,
manipulado, de otro plan, directorio con symlink, CURRENT distinto, mismo
root sin receipt); V10 entradas no adaptadas; bóveda movida con bytes
iguales sigue operando.

## Límites y riesgos residuales

- **No utilizable de extremo a extremo:** CLI, MCP y upgrade todavía no
  reciben `--store-root` ni resuelven el puntero (R1c). Con puntero presente,
  las lecturas de esas entradas fallan cerradas en vez de abrir la bóveda.
- **Diagnóstico pendiente:** `startup-diagnostic`, `integration status` y
  `doctor` no describen custodia (R1b, bloqueado por la confirmación del
  nombre `startup-diagnostic-v3`).
- **Puntero no es control de acceso:** quien puede escribir
  `project_root/.an-kla/` puede reescribir puntero y fingerprint. El puntero
  evita divergencias accidentales y bóvedas gemelas, no un atacante local.
- **TOCTOU:** la guarda de puntero se evalúa antes del lock de escritura; un
  puntero creado durante una mutación en curso no la detiene.
- **Proceso largo:** `custody_pointer_present` se calcula al construir el
  store; un MCP ya iniciado no ve un puntero creado después (sus mutaciones
  sí, por `mutation_preflight`).
- **Otras mutaciones:** `transaction repair-durability` y operaciones que no
  pasan por `mutation_preflight` se inventarían en R1c.
