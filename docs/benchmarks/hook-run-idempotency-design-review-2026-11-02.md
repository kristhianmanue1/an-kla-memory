# Revisión adversarial pre-code del diseño de idempotencia de hook-runs

Fecha: 2026-11-02. Objeto: la nota de diseño
`docs/benchmarks/hook-run-idempotency-design-2026-11-02.md` (gate pre-code de
H2). Plan matriz: `docs/plans/2026-11-02-hook-run-idempotency.md`; acta previa:
`docs/benchmarks/hook-idempotency-plan-review-2026-11-02.md` (proceed sólo
H0–H1). Base verificada: `feat/adr-0062-ci-runner` @
`0e69ae932d1d546bf28534e354ed4a2bc034dc45`.

## Procedencia y alcance

Revisor: subagente de contexto fresco convocado sólo con el encargo de revisión
y el repositorio; no recibió el historial de la sesión que produjo el diseño
(nota autorizada como «agente OpenCode, sesión de ejecución H0–H1», nota §alcance).
**No se verifica independencia de proveedor/modelo** entre productor y revisor
ni separación de infraestructura; la frescura de contexto es la garantía
declarada, no la independencia organizacional.

Alcance: inspección estática y comandos de sólo lectura. No se ejecutó la suite
completa ni `ci_local.py`; no se tocó Git (sin commit/push/checkout/reset), ni
el store canónico `.an-kla`, ni llaves, ni memoria canónica ni memmy; no se
cargó memoria histórica para conservar contexto fresco. La única escritura de
este revisor es esta acta. Los reproductores de la nota (§10, fuera de Git) no
se re-ejecutaron: se auditó su coherencia con el código citado, no su salida.

## Evidencia observada

- `git status` → rama `feat/adr-0062-ci-runner`, sin modificaciones; sin
  seguimiento: el plan, la nota de diseño y el acta previa. `git rev-parse HEAD`
  → `0e69ae932d1d546bf28534e354ed4a2bc034dc45` (coincide con la base declarada
  en la nota, línea 6).
- `.venv/bin/python --version` → Python 3.12.12.
- Lectura íntegra de la nota (304 líneas), plan (119) y acta previa (94);
  lectura de `an_kla/hook_runs.py`, `tests/test_hook_runs.py`,
  `an_kla/attest.py`, `an_kla/store_locks.py`, fragmentos de `store.py`,
  `relocate.py`, `compaction.py`, `write_commit.py`, `checkpoints.py`,
  `__main__.py`, `custody.py`, `identity.py`, `reader_gate.py`,
  `relocation_receipts.py`, `compaction_inventory.py`, `canonical.py`,
  `store_errors.py` y ADR-0047 §4.
- `rg -n "mint_hook_run" --glob '!docs/**' .` → únicos callers de producto:
  `an_kla/__main__.py:167` (vía `_mint_hook_run`, sin `run_id`); restantes son
  tests (`test_hook_runs.py`, `test_custody_root.py:279,306`).
- `rg -in "hook" an_kla/mcp.py` → sin resultados (rc=1): confirma nota §7, la
  ruta no es alcanzable desde MCP.
- `sed` sobre `store_errors.py` → `StoreError(RuntimeError)` (:10),
  `LockBusyError(StoreError)` (:22); `custody.py:32` →
  `CustodyError(StoreError)`: confirma que hoy ninguno de los dos es capturado
  por `__main__.py:175–182` (defecto latente declarado en nota §7: real).
- `grep -n "assertRaisesRegex(CustodyError" tests/test_custody_root.py` →
  :212, :241, :253, **:305** (con `mint_hook_run` en :306), :310, :312.
- `grep -n "hook_run_unwritable" tests/test_hook_runs.py` → :282 (comentario),
  **:296** (`assertIn("hook_run_unwritable", completed.stderr)`), dentro de
  `test_unwritable_runs_dir_does_not_break_successful_command` (:280–297).
- Gates ejecutados antes de redactar esta acta:
  `.venv/bin/python scripts/check_sizes.py` → `OK — 666 archivos`;
  `.venv/bin/python scripts/check_plans.py` → `OK — 5 plan(es)`. Límite
  vigente para esta acta: 800 líneas (`skevi-gate.json`, `default_limit`).
- Baseline de suite (1333 pruebas OK, 738 s) afirmada por el productor en
  nota §10: **no re-verificada** (regla del host: no ejecutar la suite
  completa); se registra como declaración del productor.

## Verificación de afirmaciones archivo:línea de la nota

Cotejadas las citas de §1–§8 contra el árbol: **todas las referencias
archivo:línea citadas existen y dicen lo que la nota afirma**, en particular:
`hook_runs.py:46,53–54,56–60,86–95,104–116,121,142–143,146–163,173–202,179–188,211–227`;
`attest.py:122–149`; `store.py:119,130–132,567–570,572–589`;
`store_locks.py:20–21,29–95,80–88`; `write_commit.py:44–45`;
`checkpoints.py:184`; `compaction.py:538–540`; `relocate.py:478–479`;
`identity.py:148–180,229–263` (`flock(LOCK_EX)` bloqueante sin deadline en
POSIX, línea 263); `custody.py:32,98–116,119–145`; `reader_gate.py:41–58`;
`relocation_receipts.py:63` (`_read_regular`);
`compaction_inventory.py:120–126`; `__main__.py:135–182,175–182,302–305,
494–497,519–522,537–540`; ADR-0047 §4 `docs/architecture/
0047-host-hooks-governed-v1.md:145–149`; plan `:46–47,:118–119`;
`tests/test_hook_runs.py:82–90,:189–192`; ADR `test_integration_status.py:79,
147–152` (no-escritura, intacto). No se falsificó ninguna cita. Las
imprecisiones detectadas se listan como hallazgos (N2, N6) y la especificación
incompleta como B1.

## Hallazgos

| id | severidad | evidencia | análisis |
|---|---|---|---|
| B1 | bloqueante | `tests/test_hook_runs.py:280–297` (aserto en :296) vs nota §4 (:108–131, OSError→`hook_run_scan_incomplete`) y §9.10 (:288–289) | Hoy, con `.an-kla/hook-runs` saboteado como archivo, el fallo emerge del `mkdir` de `_write_exclusive` (NotADirectoryError, OSError) y el CLI emite `hook_run_unwritable`; el test vigente lo exige. Bajo el diseño, el escaneo se ejecuta antes y el mismo sabotaje produce `hook_run_scan_incomplete`: el test vigente **falla**, contradiciendo §9.10 («pruebas vigentes sin edición»). La nota sólo especifica `FileNotFoundError`→universo vacío; ENOTDIR queda sin semántica declarada. Resolver en el diseño: (a) ENOTDIR del root de runs cae al camino de publicación (la escritura es imposible a través de un archivo; sin unicidad falsa publicable) y preserva el warning legacy; (b) escaneo+lock sólo con `run_id` explícito (el uuid fresco del CLI conserva hoy bit a bit y O_EXCL cubre bytes idénticos); o (c) editar ese test y reformular §9.10 con justificación explícita. |
| B2 | bloqueante | `tests/test_custody_root.py:304–308` vs nota §3 paso 3 (:76–81) y §7 (:224–232) | La traducción **interna** de `CustodyError` a `HookRunError("hook_run_custody_divergence")` en `mint_hook_run` rompe el contrato vigente asertado por `test_custody_root.py:305–308` (`assertRaisesRegex(CustodyError, "store_root_divergence")` sobre `mint_hook_run`). §9.10 sólo protege `test_hook_runs.py`, pero el plan (H2 paso 5, `:76`: «contratos previos y autoridad no cambian») cubre este contrato, y la lista de cambios colaterales de §7 (i–iii) lo omite: es un **cambio de comportamiento oculto**. Resolver: traducir en la capa CLI (ampliar el `except` de `__main__.py:175–182` con `CustodyError`/`LockBusyError`, conservando el contrato del API y cerrando el defecto latente del CLI), o declarar el cambio de contrato del API y actualizar el test de custodia como parte de H2. |
| N1 | no bloqueante | plan `:75` («timeout») vs nota §9 | §9 omite la prueba del timeout de lock que el plan exige (contención sostenida >10 s → warning `hook_run_lock_busy` y comando preservado). Incorporar a §9 antes de H2. |
| N2 | no bloqueante | nota §4 (:135–140) y §7; `store_locks.py:20,80–88`; `__main__.py:167` | El CLI nunca transmite `run_id` (`:167`): cada acuñación CLI pagará write_lock + escaneo completo (hasta 2000×64 KiB) para un uuid fresco cuya ausencia es estructural. Coste por invocación no declarado por ruta; considerar la opción (b) de B1 o declarar el coste. Además la redacción «el exceso termina en `hook_run_lock_busy`» confunde: el deadline de 10 s acota la **adquisición**, no la **retención**; la retención sólo queda acotada por el tamaño del universo, sin deadline propio (quienes esperan detrás sí agotan el deadline). Precisar. |
| N3 | no bloqueante | nota §6 (:193–210); `attest.py:122–149` | La matriz de durabilidad es honesta (jamás declara éxito por existencia; re-fsync convierte «existe, quizá no durable» en durable-ahora o `hook_run_publication_uncertain`). Pendiente de prueba: `fsync` sobre fd `O_RDONLY` funciona en Linux/macOS pero es ambiguo en POSIX (EBADF posible en otras plataformas); H2 debe demostrar la re-fsync con inyección de fallo en las plataformas objetivo (§9.8 ya exige la inyección; añadir la prueba de plataforma). Ventana residual honesta pero declarable: entradas completas-no-durables de *otros* run_id no se re-fsyncan salvo reintento de su propio id. |
| N4 | no bloqueante | nota §3 paso 5 (:84–87); `identity.py:148–180` | Si la bóveda es renombrada durante la espera del lock, la re-lectura de binding lanza `IdentityError` (p.ej. `project_identity_missing`), no `CustodyError`; el contrato del paso 5 sólo dice divergencia→`hook_run_custody_divergence`. El CLI queda seguro igualmente (`__main__.py:175` captura `IdentityError`), pero H2 debe fijar la taxonomía del paso 5 (traducir o dejar pasar como hoy). |
| N5 | no bloqueante | `store.py:567–570,572–589`; `write_commit.py:44` | La ventana preflight→lock sigue permitiendo que `_make_layout()` recree el esqueleto de layout en una ruta desposeída (la bóveda puede moverse mientras se espera); la publicación queda cerrada por la revalidación, el residuo de directorios no se discute. Patrón preexistente en todos los escritores (`write_commit.py:44` hace `_make_layout` fuera del lock): declarar o aceptar, no es regresión de este diseño. |
| N6 | no bloqueante | nota §7 (:237–239); `canonical.py:10–17` | §7(i) dice que hoy un `subject` no serializable «acuñaría evidencia degradada»: impreciso. Hoy `digest_json`→`canonical_json` lanza `TypeError`/`ValueError` que escapa a API y CLI (no capturado en `__main__.py:175–182`): el caso actual es **crash**, no acuñación degradada. La validación nueva corrige un crash; corregir la redacción para que el cambio declarado sea exacto. |
| N7 | no bloqueante | nota §4 (:113–118); `tests/test_custody_root.py:262–274`; `custody.py:61–62,152` | Las protecciones del escaneo son por entrada; un root de runs convertido en symlink (`runs/sha256` → fuera de la bóveda) no se rechaza, a diferencia del precedente del repo (receipts/identidad: guards symlink, `test_symlinked_vault_receipts_are_not_followed`). El fallo es fail-closed o escritura fuera de bóveda por un actor local que ya cruza la frontera de confianza (llave en el mismo host, ADR-0046 §1). Añadir verificación de regularidad del directorio de runs o declarar la omisión en §4. |
| N8 | observación | nota §4 (:119–126); plan `:41–45`; `hook_runs.py:147,162–163` | El bloqueo global de acuñación por una sola entrada corrupta es coherente con el plan (fallo cerrado sin reparar) y está declarado con su consecuencia; la remediación pasa a ser deuda de vivacidad. Alineado: una bóveda >2000 runs ya degrada hoy toda lectura (`hook_runs_truncated`), así que `hook_run_scan_limit` no degrada un estado que estaba sano. Los duplicados históricos que el propio defecto creó quedan como veneno `hook_run_duplicate_evidence` permanente para su run_id (§9.7 lo prueba; plan lo prohíbe remediar). Aceptado. |

### ¿Requiere ADR nueva? (ataque 1)

**Posición del revisor: no**; no se activa `Decisión: escalate` por esta vía.
Razones: (i) el resultado observable que ADR-0047 §4 declara — un objeto por
`run_id`, re-acuñación no-op, ninguna acuñación perdida en silencio
(`0047-...:145–149`) — queda cumplido; el mecanismo de la ADR («reproduce
contenido canónico idéntico → O_EXCL no-op») presupone reproducibilidad de
contenido bajo un reloj que avanzó, premisa insatisfacible sin cambiar
semántica de `observed_at` o schema, que la reparación evita; (ii) el
docstring vigente de `mint_hook_run` (`hook_runs.py:79–85`) ya declara
exactamente la semántica reparada: la reparación hace que el código cumpla su
contrato declarado, no que lo cambie; (iii) sin layout nuevo, sin índice
persistente, sin schema, sin contrato de retorno nuevo (`:121` intacto) —
ningún disparador de ADR del plan (`:46–47`) se cumple; (iv) tomar
`store.write_lock()` es reuso de primitiva existente anclada en custodia
(ADR-0048 F0-B; el acta previa, ataque 3, exige coordinar con relocate, lo que
descarta un mutex privado). La tensión interpretativa está declarada en §8 y
se considera aceptable; si el maintainer prefiere la reproducción literal del
contenido, es una decisión suya, no un requisito que esta revisión sostenga.

### Disciplina de locks, durabilidad, escaneo, compatibilidad (ataques 2–5)

- **Locks (ataque 2):** sólo `write_lock`, sin `identity_lock` (POSIX:
  `flock` bloqueante sin deadline, `identity.py:263` — cita correcta); una
  sola pieza de lock no participa en ciclos; relocate (`relocate.py:478–479`)
  y compactación (`compaction.py:538–540`) sostienen el mismo write_lock en su
  sección de mutación, así que el escaneo jamás ve una bóveda a mitad de
  traslado. Reentrancia: `flock` es por open-file-description; la adquisición
  anidada se auto-bloquearía hasta el deadline; verificado que ningún caller
  acuña bajo lock (sitios `__main__.py:302,494,519,537`, todos tras completar
  el comando; `commit_checkpoint` libera al retornar). Alias: `store_root`
  resuelto con `.resolve()` (`store.py:119`) → mismo inode del lock
  (`<store_root>/memory/.write.lock`) para aliases de la misma bóveda; sin
  suponer que el lock de proyecto cubre bóveda externa. Orden preflight→lock
  correcto para el ataque 3 del acta previa (`_make_layout`, `store.py:569`).
  Residuos y taxonomía: N4/N5.
- **Durabilidad (ataque 3):** matriz §6 honesta y separación prefijo vs
  completo por verificación exacta (JSON+bytes+HMAC+nombre), no heurísticas;
  sin publicación adicional tras resultado incierto; inyección separada
  write/fsync-file/fsync-dir exigida en §9.8. Plataforma de re-fsync: N3.
- **Escaneo fail-closed (ataque 4):** universo definido (`*.json` plano en
  `RUNS_RELATIVE`, ausente=vacío), FIFO/symlink/directorio/nlink/tamaño
  cubiertos con el patrón del repo; límite 2000 alineado con la frontera del
  lector (`len(paths) > 2000`); el caso del acta — run buscado tras el umbral
  — queda cubierto por fallo cerrado por límite antes de publicar, con prueba
  positiva exigida (§9.5). ENOTDIR del root: B1; root symlinkeado: N7.
- **Compatibilidad (ataque 5):** lector bit a bit con helper compartido y
  chequeos extra confinados al escaneo de mint; retorno `{run_id, digest}`
  intacto; oro de no-escritura intacto (`test_integration_status.py:79,
  147–152`; CLI sin hook no acuña); recencia no renovada. Excepciones: B1/B2.

### Cobertura de §9 frente al acta previa (ataques del acta, ataque 7)

Acta 1 (alcance/contrato) → §3 paso 9 + §7; Acta 2 (durabilidad) → §6 + §9.8;
Acta 3 (locks/custodia) → §5 + pasos 3/5 (residuos N4/N5); Acta 4 (ausencia/
corrupción/umbral) → §4 + §9.5/§9.6; Acta 5 (autoridad/errores/MCP) → §2
(recencia) + §7 + verificación rg de MCP. Única laguna: timeout del plan no
listado en §9 (N1).

## Decisión y límites

Dos hallazgos bloqueantes (B1, B2), ambos resolubles editando la nota de
diseño antes de tocar producto: B1 exige fijar la semántica de ENOTDIR y
reconciliar §9.10 con el test vigente; B2 exige ubicar/declarar la traducción
de `CustodyError`/`LockBusyError` sin romper el contrato asertado en
`test_custody_root.py`. Se recomienda incorporar en la misma revisión N1, N2,
N3, N6 y N7. No se halló motivo de ADR nueva (§ anterior). H2 no debe
iniciarse hasta que la nota revise estos puntos y la corrección sea verificada.

Estado del trabajo de revisión: OK (revisión completada con evidencia; árbol y
store intactos; única escritura: esta acta). Decisión sobre el diseño:
**fix-and-retry** con alcance limitado a la nota.

Decisión: fix-and-retry

## Re-verificación de la rev. 2

Mismo revisor que firmó el acta precedente (subagente de contexto fresco; sigue
sin verificarse independencia de proveedor/modelo). Ronda de re-verificación
sobre el texto final de la rev. 2 (nota, 391 líneas, encabezado «rev. 2 tras
acta fix-and-retry»), sin cambios de producto observados respecto de la base
`0e69ae9`. Sólo lectura salvo esta sección.

### Evidencia observada (ronda 2)

- `git status --short` → sin modificaciones a tracked; sin seguimiento: plan,
  nota (rev. 2), acta previa y esta acta. `git diff --stat` → vacío. HEAD sin
  cambio (`0e69ae9…`).
- Lectura íntegra de la rev. 2. `rg -n "custody_divergence"` sobre la nota →
  sin resultados (rc=1): el código `hook_run_custody_divergence` de la rev. 1
  fue retirado y no queda referencia residual.
- `rg -n "posix-fsync-dir" an_kla/` → `an_kla/store.py:179`
  (`durability_profile`: `posix-fsync-dir/v1` en POSIX): la afirmación de §6
  [N3] es real.
- Cotejo de citas nuevas de la rev. 2, todas exactas: `hook_runs.py:98` (uuid
  fresco), `__main__.py:167–174` (CLI sin `run_id`) y `:175` (tupla `except`
  vigente sin `CustodyError`), `tests/test_custody_root.py:305–309` (aserto
  `CustodyError` sobre `mint_hook_run`), `:314`
  (`assertFalse((foreign/"hook-runs").exists())`), `:266–272` (guarda symlink
  de receipts, precedente citado por [N7]), plan `:76`, `store.py:119`
  (`.resolve()`), `custody.py:32`, `store_errors.py:10`.
- Gates al cierre de esta ronda: `check_sizes.py`/`check_plans.py` re-verificados
  (resultado al final del acta); suite completa no re-ejecutada (regla del
  host): la baseline de §10 sigue siendo declaración del productor.

### Tabla de resolución por hallazgo

| id acta | veredicto | evidencia | análisis |
|---|---|---|---|
| B1 | sustentada (resuelta) | nota §2 (:51–60), §3 camino A (:97–105), §9.6 (:365), §9.11 (:371–372) | El reparto camino A/B está anclado en el plan (`:113–114`: la idempotencia cubre acuñación con `run_id` explícito). Camino A reproduce el comportamiento vigente sin lock ni escaneo: el test saboteado (`tests/test_hook_runs.py:280–297`) vuelve a fallar en el `mkdir` de `_write_exclusive` → `OSError` → warning `hook_run_unwritable`, verde sin edición. Con las entradas del CLI (exit_code literal 0, subject interno, adapter None, now ausente) las validaciones comunes pasan siempre → CLI bit a bit. Residual: contradicción interna del camino B sobre el root de runs → R-B1. |
| B2 | sustentada (resuelta) | nota §3.B.2 (:110–114), §3.B.4 (:120–125), §7 (:281–296); `test_custody_root.py:305–313`, `:314` | `CustodyError` se propaga sin traducir en ambos caminos: el contrato del API que aserta `:305–309` queda intacto y sin edición; `:314` se cumple porque el preflight precede a todo efecto (no llega a crearse ni el directorio de runs). El defecto latente del CLI (real: `custody.py:32` hereda `StoreError(RuntimeError)`, fuera de la tupla de `__main__.py:175`) se corrige añadiendo `CustodyError` al `except`, cambio declarado expresamente en §7: no oculto. La taxonomía `LockBusyError`→`HookRunError("hook_run_lock_busy")` es superficie nueva sin contrato previo (ningún test atribuye `LockBusyError` a `mint_hook_run` hoy, porque la función no toma locks): traducción justificada y sin efecto colateral. |
| N1 | parcial | nota §9.9 (:361–363) | El test de timeout se añadió, pero su observable («`hook_run_lock_busy` como warning del CLI») es inalcanzable bajo el reparto de caminos → R-B2. |
| N2 | sustentada | nota §4 (:176–183), §7(ii) (:305–308) | Coste confinado al camino B; la distinción adquisición/retención del deadline ahora está correctamente enunciada. El criterio del plan (`:38–39`: límite alcanzado falla cerrado, nunca publicar como si no existiera) se aplica exactamente donde se afirma ausencia (camino B); el camino A no afirma ausencia de nada (uuid fresco, `hook_runs.py:98`). |
| N3 | sustentada | nota §6 (:262–271); `store.py:179` | Ámbito POSIX declarado sobre el perfil real del producto; ventana residual de entradas ajenas no re-fsyncan declarada; prueba de plataforma con inyección exigida en §9.8. |
| N4 | sustentada | nota §3.B.4 (:120–125), §5 (:229–232) | Taxonomía fijada: `IdentityError`/`CustodyError` conservan su tipo en la revalidación (sin traducir); el CLI ya captura `IdentityError` (`__main__.py:175`). Resuelve el hueco señalado. |
| N5 | sustentada | nota §5 (:233–239); `write_commit.py:44` | Residuo de `_make_layout()` declarado y aceptado como clase preexistente en todos los escritores; no es regresión de este diseño. |
| N6 | sustentada | nota §3 (:85–89), §7(i) (:301–304) | Redacción corregida: el caso subject no serializable hoy es un crash real (`canonical.py:10–17` escapa al `except` del CLI), y la validación nueva lo convierte en rechazo saneado; ya no se describe como «acuñaría evidencia degradada». |
| N7 | sustentada | nota §3.B.5 (:126–130), §9.6 (:347–349); `test_custody_root.py:266–272` | Guarda lstat del root añadida con precedente verificado (guardas symlink del repo); §9.6 añade el root symlinkeado → `hook_run_evidence_invalid`. Pendiente la colisión de redacción sobre «no-directorio» → R-B1. |
| N8 | incorporada | nota §4 (:163–169), §7(ii) | El bloqueo por entrada corrupta / límite >2000 queda correctamente acotado al camino B y declarado; el CLI publica como hoy. Coherente con el plan. |

### Nuevos hallazgos de la re-verificación

| id | severidad | evidencia | análisis |
|---|---|---|---|
| R-B1 | bloqueante | nota §3.B.5 (:126–133) vs §9.6 (:350–351); `__main__.py:167–174`; `tests/test_hook_runs.py:82–90` | El mismo escenario estático (root de runs como archivo regular) recibe dos salidas prescritas: la regla lstat dice «symlink o no-directorio → `hook_run_evidence_invalid`» y §9.6 exige «root como archivo (ENOTDIR) → `OSError` con warning `hook_run_unwritable`». Es el mapa de fallos del root sin un único orden determinista. Adicionalmente el observable «warning del CLI» es inalcanzable para cualquier escenario del camino B (el CLI nunca transmite `run_id`): el aserto ENOTDIR de §9.6 debe formularse a nivel API (OSError propagado); el warning `hook_run_unwritable` del CLI ya está cubierto por el camino A y el test vigente (:280–297). La ambigüedad del root ausente («lstat … debe existir» vs «scandir `FileNotFoundError` → universo vacío limpio») es recuperable por la cláusula de scandir, pero es crítica: la primera reposición con `run_id` explícito sobre bóveda fresca — y el test vigente `test_mint_is_idempotent_by_run_id` (:82–90, camino B sobre bóveda sin directorio de runs) — depende de esa lectura; una implementación literal de «debe existir» rompería §9.11 sin edición. Corrección exigida: mapa único en §3.B.5 (ausente→universo vacío; symlink→`hook_run_evidence_invalid`; root archivo u otro `OSError` del root→`OSError` propagado; `OSError` a mitad de escaneo con directorio válido→`hook_run_scan_incomplete`) y aserto ENOTDIR de §9.6 re-expresado a nivel API. |
| R-B2 | bloqueante | nota §9.9 (:361–363) vs §2 (:51–57) y `__main__.py:167–174` | «`hook_run_lock_busy` como warning del CLI» es inalcanzable: el CLI acuña siempre por camino A, que no toma lock, así que ningún comando CLI puede emitir ese warning por contención de acuñación; ningún otro componente produce ese código. N1 debe re-formularse a observable API (camino B): holder que sostenga el write lock más que un `WRITE_LOCK_DEADLINE_SECONDS` acortado → `HookRunError("hook_run_lock_busy")` en el caller de `mint_hook_run` con `run_id` explícito. El determinismo en sí es alcanzable (holder controlado + constante acortada en el test + backoff de 0,05 s acota el ciclo de reintento); el defecto es el canal del observable, no el temporizador. |
| N9 | no bloqueante | nota §3 (:85–89) vs §7(i) (:301–304) | Queda sin declarar un estrechamiento real: hoy un `subject` serializable pero no `Mapping` (p. ej. una lista) acuña sin degradación (`digest_json` lo serializa; el lector sólo ve `subject_digest`); la validación nueva lo rechazará con `hook_run_invalid_input`. §7(i) declara «no serializable (antes: crash)» pero no el caso Mapping. Añadirlo a la lista declarada. |
| N10 | no bloqueante | nota §4 (:157–162) vs `reader_gate.py:43–45` | El patrón de escaneo usa `O_NOFOLLOW\|O_NONBLOCK` sin declarar fallback de plataforma (Windows sin `fcntl`/`O_NOFOLLOW`); §6 declara ámbito POSIX para la re-fsync pero §4 no declara el del escaneo. El precedente del repo (`reader_gate_platform_unsafe`) sugiere un código estable en plataformas sin soporte, o declarar camino B POSIX-only. (La laguna ya existía en rev. 1; se registra ahora explícitamente.) |

### Preguntas específicas del encargo

- **¿El camino A sin escaneo puede publicar duplicados relevantes?** No. Cada
  acuñación camino A genera un uuid nuevo (`hook_runs.py:98`); run_ids
  distintos son evidencias distintas por ADR-0047 §4 (`:145–149`), y la única
  colisión posible (mismo segundo + mismo uuid + mismo payload → bytes
  idénticos → mismo digest) la absorbe O_EXCL, que es el comportamiento
  vigente. El camino A jamás emite un run_id preexistente, así que no puede
  duplicar evidencia del camino B ni violar «un objeto por run_id».
- **¿Quedan huecos entre caminos?** Ninguno funcional más allá de R-B1: el
  camino B escanea y publica bajo el mismo lock (pasos 6 y 8), de modo que la
  carrera multiproceso de §9.4 es determinista (dos scanners no pueden
  intercalarse); el re-fsync del camino B no toca entradas de otros run_id
  (§6, declarado); el `FileExistsError` del paso 8 ocurre bajo lock; y la
  selección de camino por «run_id proporcionado» es inequívoca salvo el caso
  `run_id=""`, que las validaciones comunes rechazan (mal formado, declarado
  en §7(i) genéricamente). Matiz verificado: «paso a paso sin cambios» del
  camino A queda cualificado por las validaciones comunes (§3, cabecera),
  declaradas en §7(i).
- **¿Es determinista la prueba del deadline acortado (§9.9)?** El mecanismo sí
  (holder controlado + constante acortada + backoff acotado); el defecto es el
  observable imposible (R-B2), no el temporizador.
- **Precisión menor:** «sin publicación y sin creación de directorios en los
  casos de rechazo» (§9.6) se cumple para `hook_run_invalid_input` (previo al
  lock) pero no debe leerse para los fallos de escaneo del camino B, donde
  `write_lock()` ya creó el esqueleto de memoria (`store.py:569`; clase
  declarada en N5).

### Cobertura del plan H2 (encargo, punto 7)

Plan `:72–76` frente a §9: deduplicación/conflicto bajo exclusión correcta
(§9.1–9.4), reloj avanzado/reinicio/campos/run_ids (§9.1–9.3), carrera con
barrera/alias/custodia externa (§9.4), HMAC/tipos/binding/nombre
digest/symlinks/duplicados previos/límite >2000/timeout/fsync (§9.5–9.9, con
boundary positivo «exactamente 2000 con el run dentro» añadido en §9.5), CLI y
contratos previos/autoridad (§9.10). Cobertura completa al nivel de
requisitos; los defectos detectados son de redacción del observable
(R-B1/R-B2), no de omisión.

### Decisión de la re-verificación

B1 y B2 quedan resueltos de forma sustentada sin editar tests ni contratos;
N2–N8 quedan incorporados o declarados correctamente (N1 parcial). La rev. 2
introduce dos contradicciones de especificación en el propio gate heredado por
H2 (§3.B.5/§9.6 y §9.9), de corrección textual acotada pero bloqueantes para
iniciar H2 contra este texto. Puntos exactos a corregir: **R-B1** (mapa único
y determinista de fallos del root de runs en §3.B.5, con root ausente→vacío,
y aserto ENOTDIR de §9.6 re-expresado a nivel API) y **R-B2** (§9.9
re-formulado a observable API/camino B). Se recomienda plegar N9 y N10 en la
misma pasada. No hay motivo de ADR nueva (§8 de la nota, posición compartida
con esta revisión).

Decisión: fix-and-retry

## Re-verificación de la rev. 3

Mismo revisor, tercera ronda (sigue sin verificarse independencia de
proveedor/modelo). Objeto: la rev. 3 de la nota (413 líneas, encabezado «rev. 3
tras dos ciclos fix-and-retry»), que declara resolver R-B1/R-B2 y plegar
N9/N10. Sin cambios de producto respecto de `0e69ae9`; sólo lectura salvo esta
sección.

### Evidencia observada (ronda 3)

- `git status --short` → los mismos 4 documentos sin seguimiento, cero
  modificaciones a tracked; HEAD sin cambio (`0e69ae9…`).
- Lectura íntegra de la rev. 3.
- `rg -n "ENOTDIR|NotADirectoryError|custody_divergence"` sobre la nota → sin
  resultados (rc=1): la lectura contradictoria ENOTDIR→OSError de la rev. 2
  desapareció y no queda ningún código retirado.
- `rg -n "hook_run_unwritable"` sobre la nota → :104 (camino A), :134 (§3.B.5:
  «pertenece al camino A»), :367 (§9.6: mismo ámbito): el observable queda
  confinado al camino A en sus tres apariciones.
- Verificaciones de código: `relocation_receipts.py:70` —
  `getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)` + `fstat
  S_ISREG` tras apertura (el patrón getattr-0 real del repo); `reader_gate.py:
  42–45` — `getattr(os, "O_NOFOLLOW", None)` con fallo cerrado
  (`reader_gate_platform_unsafe`); `compaction_inventory.py:121` (getattr-0);
  `hook_runs.py:10–13` (docstring del descriptor subject); `store_locks.py:57,
  80` (deadline leído del global en cada intento → monkeypatch determinista
  viable).
- Gates al cierre de la ronda: `check_sizes.py` y `check_plans.py` OK (abajo);
  suite completa no re-ejecutada (regla del host).

### Resolución por punto (encargo de la ronda 3)

| punto | veredicto | evidencia | análisis |
|---|---|---|---|
| (1) R-B1 | sustentada | §3.B.5 (:126–136), §4 (:157–161, :184–185), §9.6 (:363–373) | Mapa único y coherente en las tres secciones: ausente (`FileNotFoundError`) → universo vacío limpio; presente pero symlink o no-directorio → `hook_run_evidence_invalid` sin seguir el enlace; otro `OSError` de `lstat`/`scandir` → `hook_run_scan_incomplete`; `hook_run_unwritable` queda como observable exclusivo del camino A. La ambigüedad de la primera reposición en bóveda fresca queda eliminada (ausente→vacío→publica con el `mkdir` de `_write_exclusive`) y el test vigente `tests/test_hook_runs.py:82–90` queda cubierto sin edición. Un TOCTOU del root entre `lstat` y `scandir` cae en `scan_incomplete`: fail-closed coherente. |
| (2) R-B2 | sustentada | §9.9 (:381–385), §5 (:229–235) | Observable API exacto: `mint_hook_run` con `run_id` explícito lanza `HookRunError("hook_run_lock_busy")` bajo contención sostenida con deadline acortado; §5 ya no atribuye el código al CLI y delimita el warning del CLI a `OSError` (camino A) y `CustodyError` (ajuste de §7). Determinismo viable: el deadline se lee del global en cada intento (`store_locks.py:57,80`), por lo que acortarlo en el test es determinista. |
| (3) N9 | sustentada | §7(i) (:315–319); `hook_runs.py:10–13` | El estrechamiento a `Mapping` está declarado expresamente («hoy `digest_json` acepta cualquier valor serializable; a partir de ahora se exige `Mapping`, el descriptor del docstring»), con cita exacta. Ningún test vigente pasa un subject no-Mapping (todos usan dicts), así que §9.11 se mantiene sin edición. |
| (4) N10 | sustentada, con imprecisión de cita (no bloqueante) | §4 (:168–172); `relocation_receipts.py:70`; `reader_gate.py:42–45` | La declaración existe (flags con `getattr(..., 0)` y regularidad asegurada por `fstat.S_ISREG` tras la apertura) y es sustantivamente el patrón real de `_read_regular` (:70), ya citado en §4 como fuente del mecanismo. Matiz: la cita «como el resto del repo (`an_kla/reader_gate.py:43`)» es inexacta como precedente del default-0 — `reader_gate` usa `getattr(..., None)` y falla cerrado; el precedente exacto del patrón descrito es `relocation_receipts.py:70` (y `compaction_inventory.py:121`). La «paridad con el lector» es por tanto aproximada: en plataformas sin `O_NOFOLLOW` el lector se niega y el escaneo degrada; con `lstat` previo + `fstat` el residual queda limitado al TOCTOU de esas plataformas. Imprecisión de cita, no de contrato: no bloquea. |
| (5) sin contradicciones nuevas | verificado | rg (arriba) + cotejo §2/§3/§6/§7/§8/§9 | §2 aplicabilidad y §3 camino A sin cambios y coherentes con el nuevo mapa; §6 (N3) íntegro; §7 lista de códigos sin `custody_divergence` y cubriendo todos los códigos usados en §3/§4/§6/§9; §8 sin cambios; §9.6/§9.9 re-escritos en línea con §3.B.5/§5. Todos los escenarios del root tienen salida única en todo el documento; `hook_run_unwritable` sólo con ámbito camino A; camino A bit a bit (:280–297 verde sin edición); contratos del API intactos (`test_custody_root.py:305–313`). |

Hallazgo editorial nuevo (no bloqueante): el encabezado de la nota conserva en
`:12–13` el resumen «Cambios de esta rev. 2 … N1–N7» (sin N8 y sin la rev. 3),
mientras el registro autoritativo del ciclo está al cierre (`:409–413`). Ajuste
de pluma para la entrega (H4); sin efecto en el gate ni en H2.

### Decisión de la re-verificación

R-B1 y R-B2 quedan resueltas de forma sustentada y N9/N10 quedan plegados
(N10 con imprecisión de cita sin efecto de contrato). No quedan hallazgos
bloqueantes, ni cambios de contrato ocultos, ni requisitos inalcanzables:
§9 es implementable tal cual escrito y los tests vigentes quedan cubiertos sin
edición (§9.10/§9.11). Pendientes de guardado editorial para H4: encabezado
`:12–13` y la cita de `reader_gate.py:43` en §4 — ninguno afecta a este gate.

Decisión: proceed
