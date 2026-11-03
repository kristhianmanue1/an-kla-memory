# Acta H3 — Revisión adversarial final: idempotencia de hook-runs

Fecha: 2026-11-02. Base: `feat/adr-0062-ci-runner` @ `0e69ae932d1d546bf28534e354ed4a2bc034dc45`,
con los cambios de la reparación sin commitear (2 archivos modificados + 6 sin
seguimiento). Objeto: revisar la implementación (H2) del diseño
`docs/benchmarks/hook-run-idempotency-design-2026-11-02.md` (rev. 4) contra el
plan `docs/plans/2026-11-02-hook-run-idempotency.md` (tarea H3, `:78–85`).

## 1. Procedencia

- Revisor: subagente fresco, sesión nueva sin historial del implementador.
  Agente observado: OpenCode sobre GLM (proveedor Z.ai). **No se dispone de
  verificación de independencia de proveedor/modelo** respecto del
  implementador (también OpenCode); el contexto fresco es la única
  independencia afirmada aquí, conforme a plan `:103–104`.
- Contexto entregado: el repositorio y su diff, el diseño rev. 4, el plan
  (H3 `:82–85`), las actas previas
  (`hook-run-idempotency-design-review-2026-11-02.md`,
  `hook-idempotency-lock-delta-review-2026-11-02.md`,
  `hook-idempotency-plan-review-2026-11-02.md`) y los tests vigentes.
- Restricciones respetadas: única escritura esta acta; no se ejecutó la
  suite completa ni `scripts/ci_local.py` (verificado que el run del
  implementador estaba activo en background durante esta revisión: `ps`
  muestra `ci_local --simulate-ci` + `unittest discover`, PIDs 54198/56171 y
  54203/56175); no se tocó producto, Git, store canónico ni memoria.

## 2. Evidencia observada (comandos ejecutados → resultado real)

| Comando | Resultado |
|---|---|
| `git status && git log --oneline -1 && git rev-parse HEAD` | rama `feat/adr-0062-ci-runner`, HEAD `0e69ae932d1d…`; 2 modificados (`an_kla/__main__.py`, `an_kla/hook_runs.py`) + 6 sin seguimiento (4 docs, plan, test nuevo) |
| `git diff --stat` | `an_kla/__main__.py` (±3), `an_kla/hook_runs.py` (+282/−60); total 2 ficheros |
| `git diff an_kla/hook_runs.py`, `git diff an_kla/__main__.py` | leídos completos; coincide con lo descrito en el encargo |
| Lectura `an_kla/hook_runs.py` completo (461 líneas) y `tests/test_hook_run_retry.py` (378 líneas, 24 métodos de test) | análisis sección 4 |
| Lecturas de primitivas citadas | `store_locks.py` (1–98), `attest.py` (`custody_anchor` :82–94, `_fsync_dir` :126–132, `_write_exclusive` :134–149), `store.py` (:100–140, :560–600), `custody.py` (:1–140), `identity.py` (:60–95), `relocation_receipts.py` (:63–90), `canonical.py` (:40–48), `host_hooks.py` (:28,116), `store_errors.py` (:10,22), `__main__.py` (:136–185) |
| Sonda regex (`.venv/bin/python`, sólo cómputo) | `ID_PATTERN.match('abc\n')` → `True`; `fullmatch('abc\n')` → `False` (fundamento del hallazgo N1) |
| `git diff --check` | rc=0, sin errores de whitespace |
| `.venv/bin/python scripts/check_sizes.py` | `OK — 669 archivos de texto dentro de límites`, rc=0 |
| `.venv/bin/python scripts/check_plans.py` | `OK — 5 plan(es) verificados (estructura E1-E5)`, rc=0 |
| `.venv/bin/python scripts/check_adr_registry.py` | `OK — 62 ADRs (aceptada=57, propuesta=5)`, rc=0 |
| `.venv/bin/python -m unittest tests.test_hook_runs tests.test_hook_run_retry tests.test_custody_root tests.test_integration_status tests.test_integration_status_v2 tests.test_host_hooks_declaration` | **Ran 98 tests … OK**, 23,717 s |
| `git status --porcelain` (post-revisión) | mismos 2 modificados + 6 sin seguimiento; sin residuos de esta revisión salvo esta acta |

No se ejecutó la suite completa ni `ci_local.py` (prohibido por encargo;
en ejecución por el implementador). Evidencia de esa vía corresponde al
reporte H4 del implementador.

## 3. Coherencia diseño rev. 4 ↔ código ↔ pruebas

Mapeo verificado de cada paso del §3 del diseño sobre el árbol modificado:

| Afirmación del diseño | Código real | Cuadra |
|---|---|---|
| §3 validaciones comunes antes de efectos (`hook_run_invalid_input`) | `hook_runs.py:113–114,153–172` (incluye rango `exit_code` 0..255, `subject` Mapping serializable, `run_id` ≤256 sin control, `now` con formato, tamaño ≤64 KiB en `_new_entry:185–186`) | sí |
| §3.B.2 preflight custodia antes de efectos, `CustodyError` sin traducir | `:119–121` (key/binding/custodia) y propagación sin `except` que la capture (`:149` sólo captura `LockBusyError`); refutado escrito en `tests/test_custody_root.py:304–316` sin edición + nuevo `test_path_b_disowned_vault_raises_custody_and_writes_nothing` | sí |
| §3.B.3 lock directo sin `_make_layout`; `LockBusyError` → `hook_run_lock_busy` | `:126–129,149–150`; `store_locks.py:75–76` abre `a+b` sin `parents`; wrapper con layout en `store.py:567–570` correctamente evitado | sí |
| §3.B.4 revalidación binding/custodia/llave bajo lock | `:130–132`; custodia cambiada en espera cubierta por `test_custody_changed_while_waiting_publishes_nothing` | sí |
| §3.B.5 recorrido de symlinks + `lstat` del root (ausente→vacío; no-dir/symlink→`hook_run_evidence_invalid`) | `_reject_symlink_ancestors:215–227` (anclado a `custody_anchor`), `_find_runs:340–348`; tests root archivo/symlink/ancestro symlink | sí |
| §3.B.6 escaneo fail-closed, límite >2000 → `hook_run_scan_limit`, OSError → `hook_run_scan_incomplete` | `:349–358`; `HookRunError` del límite no es atrapado por `except OSError` (`:357`) | sí |
| §3.B.7 comparación de payload funcional (8 campos; hora y firma fuera) | `_FUNCTIONAL_FIELDS:71–74`, comparación `:140` | sí |
| §3.B.8 publicación bajo lock; `FileExistsError` → verificación completa + re-fsync | `:144–148` y `_publish:196–201`; no-cooperante con bytes distintos → `hook_run_evidence_invalid` vía `_open_verified` | sí |
| §3.B.9 retorno `{"run_id","digest"}` sin cambios | `:143,202` (ambas rutas; camino A `:202`) | sí |
| §4 apertura FIFO-segura con flags obligatorios sin fallback, `(dev,ino)` antes/después | `_require_run_platform_flags:205–212` (preflight camino B `:115–118`, antes de key/binding/lock), `_safe_open:230–244`; precedentes verificados: `relocation_receipts.py:63–90` conserva el fallback `getattr` (delta declarado), `identity.py:71–84` es el patrón del recorrido | sí |
| §4 predicado compartido lector/escaneo; lector añade sólo degradación; `run_hmac` no-str crafted ahora degrada | `_entry_is_valid:247–278` usado por escaneo (`:307`) y lector (`:421–423`); el escaneo añade canonical-byte-equality, name==digest y re-gramática (`:303–313`); delta del lector declarado en §4/§7 y real | sí |
| §5 disciplina de locks (una sola pieza; sin `identity_lock`; deadline 10 s; sin recreación de layout; alias por store_root resuelto; relocate copia+publica bajo lock, locks origen inertes) | `store_locks.py:20–21,80–88`; `store.py:131` (`root=store_root/"memory"`) + `:119` (`Path(store_root).resolve()`) → wrapper y lock directo apuntan al mismo `memory/.write.lock`; `relocate.py:428` (copia a staging), `:478–479` (`identity_lock`→`write_lock`), `:581` (`_INERT` incluye `memory/.write.lock`); orden tabla §5 verificado en `write_commit.py:45`, `checkpoints.py:184`, `compaction.py:538–540` | sí |
| §6 una sola apertura verificación+fsync; fallos → `hook_run_publication_uncertain`; matriz parcial/completo | `_open_verified:281–318` + `_restore_durability:321–335` (fsync del mismo fd, luego dir); `_write_exclusive` no des-enlaza en fallo → el prefijo/completo queda en disco y el siguiente escaneo decide; inyecciones fsync(file)/fsync(dir) en `test_retry_after_fsync_failure` | sí (ver N3 para escritura parcial) |
| §7 códigos nuevos y propagación; `CustodyError` añadido al `except` del CLI | códigos presentes en el código; `__main__.py:62,176`; `CustodyError(StoreError(RuntimeError))` y `LockBusyError(StoreError)` disjuntos de `OSError` y de `AttestError(WritePolicyError(ValueError))`; CLI no transmite `run_id` (`__main__.py:168–174`) | sí |
| §9.1–9.11 gates de prueba | 24 métodos en `test_hook_run_retry.py` cubren reloj+spawn, conflictos por campo, carrera con barrera (mismo/distinto payload), hostiles (FIFO/symlink/dir/large/json), binding ajeno, renombrada (name≠digest), sobre-medida firmada, duplicados firmados, límite real 2001 + control positivo 2000, timeout de lock con deadline parcheado, flags ausentes ×2, memoria eliminada antes del lock, custodia cambiada en espera, bóveda desposeída, alias de custodia externa, pin de 2 aperturas | sí, con huecos menores (N3, N5) |

**Divergencias detectadas**: las citas archivo:línea del diseño a
`an_kla/hook_runs.py` refieren a la base `0e69ae9` y varias ya no apuntan al
mismo contenido en el árbol modificado (N2). Todas las citas a archivos NO
modificados fueron verificadas una a una y cuadran (tabla §5 y comandos §2),
incluidas `0047-host-hooks-governed-v1.md:145–149`,
`test_hook_runs.py:82–90,189–192,280–297` y `test_custody_root.py:305–314`.

## 4. Ataques por eje (veredictos)

- **Concurrencia.** El lock directo `write_lock(store.root)` y el wrapper
  `MemoryStore.write_lock` resuelven al mismo fichero
  (`store_root` resuelto en `store.py:119`; `root=store_root/"memory"` en
  `:131`; wrapper `:570` pasa `self.root`): la exclusión B–B es real y los
  aliases de la misma bóveda compiten por el mismo inode. Camino A sin lock
  es correcto: un uuid fresco no afirma ausencia y O_EXCL cubre su única
  colisión. Reordenamientos: el acuñador toma una sola pieza (no hay ciclo
  posible); relocate/compactación serializan contra él por el mismo write
  lock y su revalidación bajo lock refuta el caso «custodia cambió mientras
  esperaba». Reentrancia: ningún caller actual acuña bajo lock
  (`__main__.py:303,495,520,538` — todos post-comando; `checkpoints.py:184`
  libera al retornar) — restricción documentada en diseño §5. Deadline y
  backoff verificados; traducción a `hook_run_lock_busy` correcta y no
  observable por el CLI (que no toma lock). **Sin hallazgos bloqueantes.**
- **Autoridad.** El reintento aceptado no re-escribe bytes: devuelve
  digest original tras re-fsync (metadatos, no contenido); `observed_at`
  queda intacto en disco y `is_recent` (`:432–448`) no fue tocado → nada
  rejuvenece recencia. La comparación funcional contra una entrada recién
  construida es segura porque `_entry_is_valid` ya garantizó binding vivo
  (y `project_uuid`/`store_identity` están además en
  `_FUNCTIONAL_FIELDS`). No hay superficie nueva de autoridad; el único
  cambio de CLI (`CustodyError` al `except`) convierte un crash latente en
  warning estable, declarado en §7. **Sin hallazgos bloqueantes.**
- **Corrupción.** FIFO/symlink/dispositivo/directorio/over-size fallan en
  `lstat` previo (sin colgar: la apertura O_NONBLOCK es cinturón además de
  tirantes); hardlink (nlink≠1) rechazado; sustitución de ruta cerrada por
  comparación `(dev,ino)`; sobre-lectura acotada (64 KiB+1); JSON roto,
  HMAC inválido, binding ajeno, name≠digest y gramática inválida →
  `hook_run_evidence_invalid` fail closed (un solo candidato corrupto
  bloquea todo el camino B: consecuencia declarada N8 y probada con
  binding ajeno/renombrada/duplicados). Root ausente → universo vacío
  limpio; root archivo o symlinkeado y ancestros symlinkeados → fail
  closed con refutaciones escritas que además verifican cero escrituras
  fuera de la bóveda. Flags obligatorios verificados antes de cualquier
  efecto (dos tests con `delattr` y aserto de no-creación de directorio).
  **Sin hallazgos bloqueantes.**
- **Falsa ausencia.** El escaneo no trunca silenciosamente: >2000
  candidatos → `hook_run_scan_limit` ANTES de publicar (prueba con 2001
  ficheros reales firmados y el run buscado dentro; control positivo:
  2000 exactos → procede y devuelve el original). `scandir` OSError →
  `hook_run_scan_incomplete`. El lector público no se usa como índice en
  ningún punto del código nuevo. Camino A nunca afirma ausencia.
  **Sin hallazgos bloqueantes.**
- **TOCTOU residual.** En el reintento hay dos aperturas del `.json`
  (escaneo y durabilidad; pin de regresión exige exactamente 2). La
  comparación funcional se basa en la primera lectura y el fsync se afirma
  sobre la segunda; el puente es name==digest verificado en AMBAS
  aperturas: el contenido de un nombre queda únicamente determinado salvo
  colisión sha256 → la ventana no es explotable sin romper sha256 o la
  llave (frontera declarada ADR-0046 §1, coherente con el residual §6 del
  diseño). En la rama `FileExistsError` de `_publish`, la igualdad con el
  payload propio queda probada por el mismo argumento. El fsync del
  directorio re-resuelve la ruta (residual declarado en §6). La custodia
  se revalida bajo lock antes de mkdir/publicar; relocate necesita ese
  mismo lock para mutar → serialización correcta. **Sin hallazgos
  bloqueantes.**

## 5. Hallazgos

| id | Severidad | Evidencia (archivo:línea) | Análisis |
|---|---|---|---|
| N1 | No-bloqueante | `hook_runs.py:156` (`ID_PATTERN.fullmatch`) vs base (`match`); `host_hooks.py:28,116`; sonda: `match('abc\n')=True`, `fullmatch('abc\n')=False` | El endurecimiento `match`→`fullmatch` del `hook_id` no está declarado en diseño §3 (que presenta la comprobación como «ya existen»). Diferencia real sólo para identifiers con `\n` final (`$` de la regex acepta newline final en `match`). Dirección fail-closed y sin impacto en los tests vigentes (98 OK), pero deja asimetría: el cargador de declaraciones (`host_hooks.py:116`) aún acepta con `match` un id que la acuñación rechazaría, y una entrada legacy hipotética con `\n` final bloquearía el camino B completo (N8). Recomendación: declarar el endurecimiento en rev. 5 (o unificar el cargador) — no requiere re-trabajo de código |
| N2 | No-bloqueante | Diseño rev. 4 §1–§7 (citas a `an_kla/hook_runs.py:46,53–54,56–60,79–85,92–93,98,104–107,113–116,121,146–163,184–188,211–227`) vs árbol modificado (p. ej. `_FUNCTIONAL_FIELDS` hoy `:71–74`; publicación hoy `:190–202`; `is_recent` hoy `:432–448`) | Las citas a `hook_runs.py` refieren a la base `0e69ae9` (verificado contra `git show 0e69ae9:an_kla/hook_runs.py`: contenido semántico correcto en cada caso), pero con rev. 4 declarando «Estado: diseño implementado (H2)» varias ya no apuntan al código real. Recomendación: nota de que las citas a `hook_runs.py` son relativas a la base, o renumeración en rev. 5 |
| N3 | No-bloqueante | Gate §9.8 (inyección «escritura parcial») y §9.10 («recencia vencida… no rejuvenece») vs `tests/test_hook_run_retry.py` | No hay inyección de escritura parcial explícita: su observable («prefijo en disco → siguiente reintento `hook_run_evidence_invalid`») queda cubierto por el candidato corrupto de 1 byte (`test_corrupt_and_nonregular_candidates`) y la traducción OSError→`hook_run_publication_uncertain` por las inyecciones fsync(file)/fsync(dir) (mismo `except OSError` en `:147–148`). Tampoco hay aserto explícito post-reintento de no-recencia: cubierto estructuralmente por preservación byte a byte de `observed_at` (`test_clock_and_restart_preserve_bytes`) y `is_recent` intocado. Huecos de cobertura de bajo riesgo; no invalidan el gate |
| N4 | No-bloqueante | `tests/test_hook_run_retry.py:168–193` | `test_missing_flags_fail_closed` y `test_flags_absent_empty_dir_publishes_nothing` son redundantes (mismo escenario y mismos asertos). Ruido de matriz, no defecto |
| N5 | No-bloqueante | `tests/test_hook_run_retry.py:97–115,323–338`; `store.py:119` | La carrera se prueba con la misma cadena de ruta y el «alias» reinstanciando `MemoryStore` con el mismo `store_root`; la exclusión por aliases de ruta distintos descansa (verificado por lectura) en `Path(store_root).resolve()` del constructor. Una carrera con dos cadenas alias distintas sería el pin completo; la garantía actual es estructural y suficiente |
| N6 | No-bloqueante | `hook_runs.py:129` (descarta el `LockResult`); `store_locks.py:24–26,89–95` | El CM de lock puede reportar `release_error` y el acuñador lo ignora. Benigno: el `close` del handle al salir del `with` libera el `flock` de todos modos; patrón idéntico al wrapper. Cosmético |

## 6. Verificación de compatibilidad e historia declarada

- `tests/test_hook_runs.py` y `tests/test_custody_root.py` **sin edición**
  (`git status`: sólo 2 productos modificados); ambos suites en verde en la
  corrida focal (98 tests OK), incluyendo el idempotismo legacy
  (`test_mint_is_idempotent_by_run_id`, ahora camino B), el oro de
  no-escritura de invocación plana (`:189–192`) y el aserto `CustodyError`
  de bóveda desposeída (`:304–316`).
- Contrato de retorno `{"run_id", "digest"}` intacto en todas las rutas de
  retorno (`hook_runs.py:143,202`); `__all__` sin cambios; `is_recent` y el
  resto del lector (códigos de degradación, truncado, orden) sin cambios
  funcionales; único delta de lector declarado: `run_hmac` no-str crafted
  degrada (`hook_run_invalid`) en vez de romper con `TypeError`.
- `CustodyError`/`IdentityError` preservan tipo en ambos caminos; el CLI
  añade `CustodyError` al `except` (defecto latente declarado en §7,
  corrección con warning estable `hook_run_mint_skipped`).
- Camino A paso a paso igual al base (verificado por lectura del diff:
  key→binding→custodia→entry→`_publish` con absorción de
  `FileExistsError`); las validaciones nuevas comunes sólo estrechan
  fail-closed lo ya declarado en §7(i).

## 7. Decisión

Revisión adversarial completada sobre el diff real, el diseño rev. 4 y las
suites focales; seis hallazgos, todos no bloqueantes (dos de documentación,
dos de cobertura menor, dos cosméticos); ningún contrato roto, ninguna
autoridad fabricada, ninguna ausencia falsa, ningún TOCTOU explotable
identificado. Los puntos N1–N2 pueden resolverse documentalmente en rev. 5
sin re-trabajo de código.

Decisión: proceed

---

*Acta generada por el revisor adversarial H3 (subagente fresco). Única
escritura de esta sesión; el árbol queda con los mismos 2 archivos
modificados y los 6 sin seguimiento originales, más esta acta.*
