# Ronda adversarial del lote beta.22 (2026-09-05)

Objeto: commits `7431e80^..32a0f14` (lote menor + entrada G2; el ADR-0047
ya tenía su propia ronda pre-code — revisión ligera cross-cutting).
Método: atacante de contexto fresco (subagente, sólo lectura); verificación
factual de doc nueva, correctitud de `ci_local.py`, integridad de la
partición de tests, doctrina del wrapper de ejemplo, claims de los
comentarios de issues.

## Veredicto: `fix-and-retry` — absorbido en el commit siguiente

2 HIGH, 6 MEDIUM, 6 LOW. Ningún defecto en código de motor; partición de
tests íntegra (multiset de `def test_` idéntico, 211 = 211; clases críticas
en exactamente un archivo); sin recursión infinita en la matriz (guard
`ANKLA_MATRIX_ROW15_ACTIVE` + fallback por `sys.version_info`); doctrina
del wrapper correcta (`model_derived`, sin secretos, tempdirs privados).

## Hallazgos y absorción

| ID | Sev | Hallazgo | Absorción |
|---|---|---|---|
| H1 | HIGH | Path del lock falso en `write-policy-cli.md` (`.an-kla/.write.lock`; el real: `.an-kla/memory/.write.lock`, `store.py:117,622,646`) | Path corregido |
| H2 | HIGH | Comandos `anklawrapper*` inexistentes en README y docstring del ejemplo (primer copy-paste roto) | Referencias corregidas a `ankla_agent.py` |
| M1 | MED | Anchor `#uso-diario-1` imposible en TOC de uso-diario | `#uso-diario` |
| M2 | MED | Anchor interno `#respaldo-sellado-opcional` roto en README (la sección migró) | Enlace a `docs/uso-diario.md#respaldo-sellado-opcional` |
| M3 | MED | `_ROW_MODULES` filas 6/10d/10e huérfanas tras la partición (re-ejecución ya no cubría los tests reales de esas filas) | Remapeadas a los módulos particionados (`behavior`/`errors`/combinado) |
| M4 | MED | Guard regex no descontaba skips (un módulo todo-skips con N>0 pasaba) ni anclaba al resumen final | `^ran N tests` MULTILINE + `skipped=k` descontado; efectivos > 0 |
| M5 | MED | Paso 3/7 moría con traceback en clones/worktrees sin `.an-kla/` | Pre-chequeo con SKIP honesto y razón |
| M6 | MED | Coste de la matriz sin documentar ni opt-out (~45-90s por intérprete extra; host con 3.9+3.12+3.13 ≈ 12-15 min) | Coste documentado en docstring + escape `AN_KLA_CI_LOCAL_MATRIX=0` (SKIP declarado) |
| L1 | LOW | "backoff" sin sleep real en el wrapper | `time.sleep(0.5 * attempt)` en lock ocupado |
| L2 | LOW | Wrapper sin timeout (lock POSIX indefinido cuelga al wrapper) | `timeout=180` + camino (c) `transaction inspect` en `TimeoutExpired` |
| L3 | LOW | `read_back` con query diluida y falso negativo por presupuesto | Query a 12 palabras + chequeo de `excluded_detail.ids.budget` con error específico |
| L4 | LOW | exit 0 con stdout vacío explotaba fuera del camino ambiguo | Guard: outcome vacío → exigir `transaction inspect` |
| L5 | LOW | `shutil.which("python3.12")` casi nunca resuelve en Windows (sin fallback `py -3.12`) | Anotado; SKIP es literalmente cierto y README declara "Windows diferido" — sin cambio |
| L6 | LOW | Helpers replicados entre matrix y rows (patrón copia-muerta que el propio lote critica) | Diferido: refactor a `tests/_matrix_harness.py` como mejora futura, no bloqueante |

## Verificaciones sin hallazgo (confirmadas por la ronda)

- Partición íntegra y fila 1 correcta (`TestNonceCounterF1` con recorrido
  0..99999 en `bundle_units`).
- README 493→251 ✅, índice recíproco ✅, corpus doble de
  `test_release_metadata` no debilita (`assertNotIn "@main"` sobre la
  unión ≡ en ninguno de los dos).
- Claims exactos de la sección de lock salvo el path (deadline 10s,
  mkdir atómico, liberación por kernel, prefijo `an-kla error:`).
- Medición de coste de matriz: suite 3.12 anidada con fila 15 activa =
  45s; los 390-413s observados encajan; sin omisión en los reportes.
- Claims de los comentarios de #106/#111/#112/#56 respaldados por el árbol.
- CHANGELOG sin beta.22: convención del repo (entra en el commit de
  release), no deuda.

## Verificación post-absorción

- `py_compile` ci_local/ankla_agent/matrix ✅; demo del wrapper ✅ (CAS
  perdido → re-plan → read-back OK); `tests.test_release_metadata` OK;
  `tests.test_sealed_matrix` OK (12 tests); suite canónica completa en
  verde (ver commit de absorción).
