# Reporte de reparación: idempotencia de hook-runs por `run_id`

Fecha: 2026-11-02 (cierre 2026-11-03 UTC). Encargo del Operador: ejecutar
`docs/plans/2026-11-02-hook-run-idempotency.md` (H0–H4) con revisión fresca
H1, corrección de hallazgos y paso a H2–H4 sólo con proceed. Base:
`feat/adr-0062-ci-runner` @ `0e69ae932d1d546bf28534e354ed4a2bc034dc45`
(preservada intacta, sin reset ni checkout destructivo). Estado de esta
entrega: **OK** — todas las tareas H0–H4 completas; el gate legacy quedó
verde en la corrida de confirmación (apartado 6); los cambios siguen sin
commitear a la espera de orden explícita del Operador.

## 1. Trazabilidad de autoridad

- Encargo del Operador (2026-11-02): plan autorizado; alcance H0–H4 con
  gates; sin commit/push/merge/tag/build/release; sin activar CI; sin
  escritura de memoria canónica; ADR-0062 local conservada; evidencia y
  reporte en `docs/benchmarks/`; un solo escritor de código.
- Relevo intermedio: implementación parcial de un agente Codex (detenido,
  sin pruebas activas verificadas por `pgrep`); sus cambios fueron
  verificados, corregidos y completados por esta sesión como escritor
  único desde ese punto.

## 2. H0 — preflight (completo)

| Verificación | Resultado |
|---|---|
| Rama/HEAD/árbol | `feat/adr-0062-ci-runner` @ `0e69ae9…`; limpio salvo documentos nuevos sin seguimiento |
| Intérprete | `.venv/bin/python` 3.12.12 (regla del repo) |
| `context status` / `status` / `verify` | ok, sin diagnósticos; revisión `sha256:0fde0250…`, rev 89 |
| `gh issue list` / `gh pr list` | #169 #168 #166 #140 #58; sin PRs; rc=0 |
| Suite baseline completa | **1333 pruebas, OK (74 omitidas), rc=0, 738 s** |

## 3. H1 — spike y diseño (completo)

- Reproducción propia en stores efímeros (reloj interno sustituido; host y
  store canónico intactos): control mismo segundo = 1 objeto; contraejemplo
  reloj +1 s = 2 objetos con digests distintos; dos procesos sobre la misma
  custodia = 2 objetos (el duplicado sobrevive al reinicio).
- Diseño `hook-run-idempotency-design-2026-11-02.md`: dos ciclos
  fix-and-retry del revisor fresco (B1/B2 bloqueantes; R-B1/R-B2
  textuales; N1–N10) y **proceed** en rev. 3. Sin ADR nueva: ADR-0047 §4
  ya declara la semántica; el docstring vigente ya la proclamaba.

## 4. H2 — implementación (completa)

Heredado del relevo y verificado; correcciones del escritor único:

1. **TOCTOU en durabilidad**: verificación y `fsync` sobre UNA sola
   apertura (`_open_verified` → `_restore_durability` usa el mismo
   descriptor); la igualdad con el payload esperado queda probada por
   nombre==digest. Pin de regresión: 2 aperturas por reintento (escaneo +
   durabilidad), no 3.
2. **Symlinks en ancestros** del directorio de runs
   (`_reject_symlink_ancestors`, precedente `identity.py`): `hook-runs/`
   o `runs/` symlinkeados no sacan el escaneo fuera de la custodia.
3. **Flags obligatorios antes de efectos** (delta de locks): disponibilidad
   `O_NOFOLLOW`/`O_NONBLOCK` verificada al entrar al camino B;
   `hook_run_platform_unsupported` si faltan; sin fallback cero; el camino
   B no publica nada sin ellos (ni con directorio vacío).
4. **Criterios lector/escaneo consolidados** en `_entry_is_valid` (una
   sola definición); el lector conserva códigos/truncado; cambio declarado:
   `run_hmac` no-str crafted ahora degrada en lugar de romper la lectura
   con `TypeError` (crash latente sin cobertura).

Pruebas: `tests/test_hook_run_retry.py` (nuevo, 24 tests): reloj avanzado,
reinicio spawn, conflicto por cada campo funcional, carrera con barrera
(mismo/distinto payload), hostiles (FIFO/symlink/root archivo/root
symlink/ancestro symlink/binding ajeno/renombrado/sobre-medido firmado),
duplicados firmados a mano, límite real 2001 archivos + control positivo
en 2000, inyección separada write/fsync-file/fsync-dir, timeout de lock,
flags ausentes, `memory/` eliminada antes del lock (sin recreación),
custodia cambiada en espera (cero publicación), custodia desposeída
camino B (contrato `CustodyError`, cero directorios), alias de custodia
externa, `scan_incomplete` inyectado, validaciones antes de efectos.

## 5. Verificación (completa, salvo gate)

| Verificación | Resultado |
|---|---|
| Focales (hook_runs + retry + custody + integration_status + v2 + host_hooks + recipe del contrato) | **110 + 23 pruebas OK** |
| `check_sizes.py` | OK — 670 archivos |
| `check_plans.py` | OK — 5 planes |
| `check_adr_registry.py` | OK — 62 ADRs (57 aceptadas) |
| `git diff --check` | limpio |
| Revisión delta de locks (Codex `review_lock_delta`) | **proceed** con precisiones incorporadas |
| Revisión fresca final H3 (`implementation-review-2026-11-02.md`) | **proceed**; 6 hallazgos no bloqueantes (H3-N1 `fullmatch` y H3-N2 base de citas, documentados en rev. 5 del diseño) |

## 6. Gate legacy `ci_local.py --simulate-ci`

**Corrida 1 (rc=1, FAIL — paso unittest):** falló
`tests/test_ci_audit.py::ProcessAuditTests::test_term_resistant_child_has_positive_control_then_kill`
(`heartbeat` no encontrado: stdout del hijo vacío) en AMBAS piernas
(1354 y 1357 pruebas) y, en cascada, el anidado
`test_ci_local_both_modes`. **Ningún fallo de hooks**: el defecto que
bloqueaba el gate (idempotencia) aparece reparado dentro de las piernas.

Hipótesis del fallo: sensibilidad al tiempo de arranque bajo carga externa.
La coincidencia con carga alta y el pase posterior apoyan esta explicación,
pero no demuestran causalidad ni excluyen una carrera del propio test:

- El test da al hijo **0,9 s** para arrancar un intérprete y escribir;
  bajo saturación el arranque no llega a tiempo.
- Durante la corrida, el CI de **otro proyecto**
  (`/Users/krisnova/www/adrc-mini-wt-ocupacion`, PIDs verificados con
  `lsof` por cwd) llevaba 1 h 32 min de `pytest` pesado; load medio 16,59;
  la pierna larga duró 1082 s (+46 % vs baseline 738 s en máquina tranquila).
- El mismo test **pasa aislado** (0,68 s) y el módulo completo
  (`tests.test_ci_audit`, 29 pruebas) pasa **verde**, incluso bajo carga
  residual; pasó en el baseline H0 de esta mañana con máquina tranquila.
- `tests/test_ci_audit.py` no importa ni ejercita `hook_runs`.

**Corrida 2 (confirmación en máquina tranquila): verde.** Lanzada tras el
fin del CI externo (load 4,66 cayendo, sin procesos `pytest`/`ci_local`
ajenos verificados por `pgrep`): **1357 pruebas, OK (74 omitidas), 911 s**,
pierna −16 % frente a la corrida bajo carga; resumen `ci_local: OK` con los
siete pasos en verde (importabilidad, unittest, redteam_selftest,
matriz_interpretes, check_sizes, check_plans, check_adr_registry), **rc=0**
(log completo: `h3_ci_legacy_rerun.log` en la bitácora efímera). El test
que falló en la corrida 1 pasó dentro de la pierna sin edición. Sin
procesos de prueba residuales al cierre.

## 7. Archivos (estado final sin commitear)

Modificados:
- `an_kla/hook_runs.py` (+339/−60; caminos A/B, escaneo fail-closed,
  durabilidad de apertura única, criterios compartidos)
- `an_kla/__main__.py` (+2/−1; `CustodyError` en el `except` de acuñación)

Nuevos sin seguimiento:
- `tests/test_hook_run_retry.py`
- `docs/plans/2026-11-02-hook-run-idempotency.md`
- `docs/benchmarks/hook-idempotency-plan-review-2026-11-02.md`
- `docs/benchmarks/hook-run-idempotency-design-2026-11-02.md` (rev. 5)
- `docs/benchmarks/hook-run-idempotency-design-review-2026-11-02.md`
- `docs/benchmarks/hook-idempotency-lock-delta-review-2026-11-02.md`
- `docs/benchmarks/hook-run-idempotency-implementation-review-2026-11-02.md`
- `docs/benchmarks/hook-run-idempotency-repair-report-2026-11-02.md` (este)
- actualización: `docs/benchmarks/hook-run-idempotency-blocker-2026-10-30.md`

Bitácoras crudas y reproductores (fuera de Git, sin llaves):
`/private/var/folders/q1/k3y040sd0rv9cbxcdskwr_zw0000gp/T/opencode/hook-idem-h0-h1/`.

## 8. Restricciones honradas

Sin commit/push/merge/tag/build/release; sin activación de CI ni del runner
optativo; sin escritura de memoria canónica AN-KLA; ADR-0062 local
conservada en `0e69ae9`; sin instalación de dependencias ni escalación de
permisos; stores de prueba efímeros; un solo escritor tras el relevo;
árboles y stores ajenos no tocados (el CI externo de otro proyecto sólo se
esperó, no se interfirió).

## 9. Riesgos y residuales declarados

- Plataformas sin `O_NOFOLLOW`/`O_NONBLOCK`: camino B no disponible
  (`hook_run_platform_unsupported`); camino A intacto.
- El archivo `.write.lock` no está endurecido contra sustitución hostil
  (límite del delta; actor que lo haga ya cruzó la frontera de confianza
  de la llave local, ADR-0046 §1).
- Re-fsync POSIX (`posix-fsync-dir/v1`); probado en macOS; fallo →
  `hook_run_publication_uncertain` fail closed.
- Coste del camino B acotado (≤2000×64 KiB) bajo lock con deadline de 10 s
  (adquisición); retención acotada por el universo.
- Bóvedas >2000 runs o con entradas corruptas: camino B falla cerrado
  (deuda de vivacidad: remediación fuera de alcance).
- Duplicados históricos de un `run_id`: envenenan ese id hasta remediación
  explícita (no se eligen ni borran aquí).
- Lectura legacy: micro-endurecimiento declarado (`run_hmac` no-str degrada
  en vez de romper).
- El test del gate afectado es sensible a carga (0,9 s de presupuesto de
  arranque del hijo): puede reproducirse bajo saturación ajena; su
  presupuesto no se modificó en este encargo.

## 10. Impacto en la transición ADR-0062

El bloqueo de producto que invalidaba las baselines legacy
(`mint_hook_run` no idempotente) quedó reparado y probado deterministamente;
el gate legacy ya no falla por hooks. La activación del gate nuevo sigue
requiriendo su proceso propio (baseline legacy válida, comparación de
cobertura por obligaciones y aceptación explícita del Operador): nada se
activó aquí.

## 11. Decisión solicitada al Operador

1. Aceptar la reparación y autorizar, en orden separado, commit/PR del
   conjunto (2 modificados + pruebas + documentos).
2. Gate legacy confirmado verde (apartado 6, corrida 2): H3 cerrado; no se
   requiere ninguna repetición adicional del gate.
3. Si se pretende release: la ronda adversarial pre-release y la higiene de
   publicación siguen siendo fases separadas conforme al repo.
