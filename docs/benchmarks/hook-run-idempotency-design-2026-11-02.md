# Diseño H1: deduplicación de hook-runs por `run_id`

Fecha: 2026-11-02 (rev. 5: declara el endurecimiento `fullmatch` de
`hook_id` [H3-N1] y la base de las citas [H3-N2]). Estado: diseño
implementado (H2) con revisión fresca final **proceed** (H3,
`docs/benchmarks/hook-run-idempotency-implementation-review-2026-11-02.md`),
pendiente de CI legacy. Nota de citas [H3-N2]: las referencias
`hook_runs.py:línea` de este documento señalan la base
`0e69ae932d1d546bf28534e354ed4a2bc034dc45` (árbol previo al cambio); las
líneas del árbol modificado difieren por el propio diff (verificado
semánticamente por el revisor H3 contra `git show 0e69ae9`).
Plan matriz: `docs/plans/2026-11-02-hook-run-idempotency.md` (tareas H1–H4;
actas `docs/benchmarks/hook-idempotency-plan-review-2026-11-02.md`,
`docs/benchmarks/hook-run-idempotency-design-review-2026-11-02.md`,
`docs/benchmarks/hook-idempotency-lock-delta-review-2026-11-02.md` y
`docs/benchmarks/hook-run-idempotency-implementation-review-2026-11-02.md`).
Base: `feat/adr-0062-ci-runner` @ `0e69ae932d1d546bf28534e354ed4a2bc034dc45`.
Alcance: `an_kla/hook_runs.py`, un ajuste acotado del `except` de acuñación en
`an_kla/__main__.py` y su prueba focal; sin layout nuevo, sin índice
persistente, sin cambio de schema ni del contrato de retorno. Autor: agente
OpenCode (sesión de ejecución H0–H1). Cambios por revisión: rev. 2 resuelve
B1/B2 del primer acta e incorpora N1–N8; rev. 3 resuelve R-B1/R-B2 de la
re-verificación y plega N9/N10 (proceed del diseño); rev. 4 incorpora el
delta de locks y las correcciones del relevo; rev. 5 declara H3-N1/H3-N2
(ver «Ciclo de revisión», §10).

## 1. Defecto y reproducción de hoy

`mint_hook_run` incluye `observed_at` en el contenido firmado y publica por el
digest de ese contenido (`an_kla/hook_runs.py:107–116`). Con el mismo
`run_id` y el mismo payload funcional, un reloj que avanza un segundo produce
otro digest, otro nombre y otro objeto: O_EXCL sólo evita repetir bytes
idénticos. ADR-0047 §4 declara el reintento con el mismo `run_id` como
«no-op idempotente» (`docs/architecture/0047-host-hooks-governed-v1.md:145–149`);
el docstring vigente de la función ya declara esa semántica
(`an_kla/hook_runs.py:79–85`): la reparación hace que el código cumpla el
contrato que ya declara.

Reproducción de esta sesión (stores efímeros, reloj interno sustituido en
memoria con `patch.object(hook_runs, "_utc_now", ...)`; reloj del host y store
canónico intactos; bitácora y JSON fuera de Git en
`/private/var/folders/q1/k3y040sd0rv9cbxcdskwr_zw0000gp/T/opencode/hook-idem-h0-h1/`):

| Escenario | Reloj interno | Objetos | Digest devueltos |
|---|---|---|---|
| Control mismo segundo | fijo | 1 | idéntico (2ª llamada igual a 1ª) |
| Contraejemplo reloj +1 s | avanza | 2 | distintos |
| Reinicio de proceso | +5 s entre procesos | 2 | distintos |

El duplicado sobrevive al reinicio: es estado en disco, no memoria de proceso.
La prueba vigente `test_mint_is_idempotent_by_run_id`
(`tests/test_hook_runs.py:82–90`) usa el reloj real dentro del mismo segundo:
pasa hoy y no refuta el defecto (temporalmente frágil, ya documentado en
`docs/benchmarks/hook-run-idempotency-blocker-2026-10-30.md`).

## 2. Contrato propuesto

- **Identidad de deduplicación:** `run_id` dentro de una misma custodia
  (bóveda). Dos aliases resueltos a la misma bóveda comparten universo: los
  campos de identidad viajan firmados (`project_uuid`, `store_identity`,
  `an_kla/hook_runs.py:104–105`) y una entrada verificada del mismo `run_id`
  con binding idéntico es la misma evidencia.
- **Aplicabilidad [B1/N2]:** la deduplicación por búsqueda actúa cuando el
  caller entrega un `run_id` explícito (semántica de reintento del host,
  ADR-0047 §4). El CLI nunca transmite `run_id` (`an_kla/__main__.py:167–174`):
  sus acuñaciones usan un uuid fresco (`an_kla/hook_runs.py:98`), que es una
  identidad nueva por construcción — no hay afirmación de ausencia que
  demostrar, O_EXCL cubre la única colisión posible (bytes idénticos) y la
  ruta conserva el comportamiento vigente paso a paso (§3, camino A). Esto
  elimina el coste de lock+escaneo por invocación CLI y conserva sin edición
  los tests vigentes del CLI, incluido el de directorio saboteado
  (`tests/test_hook_runs.py:280–297`).
- **Payload funcional** (lo que debe coincidir para aceptar el reintento): los
  ocho campos que no son hora ni firma — `hook_id`, `trigger`, `action`,
  `exit_code`, `subject_digest`, `project_uuid`, `store_identity`,
  `adapter_fingerprint` (`an_kla/hook_runs.py:56–60`). `observed_at` y
  `run_hmac` no son funcionales; `now` sólo fija la hora de primera
  publicación.
- **`run_id` nunca viaja a rutas.** El layout sigue siendo content-addressed
  por el digest de la entrada completa (`an_kla/hook_runs.py:113–116`); la
  búsqueda por `run_id` se hace por escaneo verificado, no por nombre.
- **Ausencia no se prueba con el lector público.** `read_verified_runs` trunca
  a 2000 y degrada (`an_kla/hook_runs.py:54,146–163`); no sirve como índice
  autoritativo. La acuñación con `run_id` explícito usa su propio escaneo
  fail-closed (§4).
- **Recencia no se renueva.** El reintento devuelve la evidencia original con
  su `observed_at` original; `is_recent` sigue leyendo ese campo
  (`an_kla/hook_runs.py:211–227`), así que un replay no rejuvenece evidencia.

## 3. Algoritmo reparado de `mint_hook_run` (orden exacto)

**Validaciones comunes, antes de efectos** (ambos caminos;
`hook_run_invalid_input` si fallan): `hook_id` contra `ID_PATTERN` —
endurecimiento declarado [H3-N1]: la implementación usa `fullmatch` donde el
texto previo usaba `match`; el patrón es anclado (`^...$`,
`an_kla/host_hooks.py:28`) pero `match` con `$` acepta un salto de línea
final sin consumirlo, así que `fullmatch` cierra esa puerta (dirección
fail-closed, sin hosts afectados en las pruebas vigentes) — y
`trigger`/`action` contra catálogos (ya existen, `an_kla/hook_runs.py:86–89`);
`exit_code` `int` no-bool en 0..255 (hoy sólo int-ness: alinear con lo que el
lector exige, `an_kla/hook_runs.py:179–183`, para no acuñar evidencia que el
lector degradaría siempre); `subject` debe ser un `Mapping` serializable —
hoy un subject no serializable lanza `TypeError`/`ValueError` de
`canonical_json` que escapa al `except` del CLI (`an_kla/__main__.py:175–182`)
y **rompe un comando ya exitoso**: la validación nueva convierte ese crash en
rechazo saneado [N6]; `adapter_fingerprint` `str | None` (hoy sin validar);
`run_id` si viene: `str` de 1..256 sin caracteres de control (suficiente
porque no viaja a rutas; gramática más estricta rompería hosts sin beneficio);
`now` si viene: formato `%Y-%m-%dT%H:%M:%SZ` (el lector exige ese formato,
`an_kla/hook_runs.py:184–188`). Además, si el payload canónico supera
`_MAX_ENTRY_BYTES` (64 KiB): rechazar antes de escribir (evita acuñar
entradas que el lector degradaría por tamaño, `an_kla/hook_runs.py:53`).

### Camino A — `run_id` no proporcionado (todo el CLI)

Comportamiento vigente **paso a paso sin cambios**: cargar llave y binding
(`an_kla/hook_runs.py:92–93`), `check_custody` (`:95`, sigue lanzando
`CustodyError` sin traducir), construir entrada con uuid fresco, firmar y
publicar con `_write_exclusive` (`an_kla/attest.py:130–149`), `FileExistsError`
absorbido (`:117–120`). Sin lock ni escaneo. Un fallo de publicación sigue
emergiendo como `OSError` y el CLI emite `hook_run_unwritable` exactamente
como hoy (`tests/test_hook_runs.py:280–297` queda verde sin edición) [B1].

### Camino B — `run_id` explícito (semántica de reintento)

1. Cargar llave y binding (como hoy).
2. **Preflight de custodia:** `check_custody(store, binding)`; error
   `CustodyError` **se propaga sin traducir** — es el contrato vigente
   asertado por `tests/test_custody_root.py:305–309`, y el preflight va antes
   de cualquier efecto para que una bóveda desposeída no llegue a crear ni el
   directorio de runs (`test_custody_root.py:314`) [B2].
3. `write_lock(store.root)` **directo** sobre el lock de la bóveda
   (`an_kla/store_locks.py:29–95`), NO el wrapper `store.write_lock()`
   (delta de locks, proceed:
   `docs/benchmarks/hook-idempotency-lock-delta-review-2026-11-02.md`):
   el wrapper ejecuta `_make_layout()` antes de devolver el mismo helper
   (`an_kla/store.py:567–589`) y podría recrear el esqueleto de layout en
   una bóveda desposeída durante la espera; el helper directo sólo abre
   o crea el archivo de lock dentro del `memory/` existente, sin
   `parents=True` (`an_kla/store_locks.py:75–76`). Si `memory/` falta,
   falla con `OSError` sin recrear nada — la garantía precisa del delta
   es «no recrear layout/ancestros», no cero efectos previos. El fallback
   sin fcntl/msvcrt falla por contención al instante, sin deadline de
   10 s: sin paridad universal. `LockBusyError` — superficie **nueva**
   introducida por este diseño, sin contrato previo — se traduce a
   `HookRunError("hook_run_lock_busy")`; los errores de custodia e
   identidad conservan sus tipos (`CustodyError`, `IdentityError`) en
   todo el camino [B2/N4].
4. **Revalidación bajo lock:** re-leer binding, repetir `check_custody` y
   recargar la llave (`_load_key`), todo dentro del lock (precisión del
   delta). `IdentityError` se propaga tal cual (el CLI ya lo captura,
   `an_kla/__main__.py:175–182`); `CustodyError` se propaga. Un lock
   adquirido no prueba que la referencia de custodia siga vigente. El
   flujo normal de relocate **copia** el origen a staging, publica el
   destino, publica el puntero y limpia el origen bajo write lock
   (`an_kla/relocate.py:428,478–531`); no renombra el origen
   preservando su inode y los locks de origen quedan como residuos
   inertes (`:581`): la seguridad del acuñador depende del lock de
   origen y de esta revalidación, no de que un descriptor abierto
   «viaje» con la bóveda. Si la custodia cambió mientras se esperaba,
   la revalidación falla cerrado y no se publica nada [N4].
5. **Comprobaciones del directorio de runs** (`<custodia>/hook-runs/runs/
   sha256/`), con semántica única y sin ambigüedad [R-B1]: recorrido de
   ancestros dentro de la bóveda rechazando symlinks en `hook-runs/`,
   `runs/` o el leaf (precedente `_reject_symlink_path`,
   `an_kla/identity.py:71–84`: la resolución de rutas sigue enlaces en
   componentes intermedios) [N7]; `lstat` del root — ausente
   (`FileNotFoundError`) → universo vacío limpio (primera reposición
   sobre bóveda fresca; p. ej. `tests/test_hook_runs.py:82–90`);
   presente pero symlink o no-directorio (archivo) →
   `hook_run_evidence_invalid` fail closed; otro `OSError` del `lstat`
   o de `scandir` → `hook_run_scan_incomplete`. El observable
   `hook_run_unwritable` vía `OSError` de publicación pertenece al
   camino A: el CLI no transmite `run_id` y nunca ejecuta este paso.
6. **Escaneo verificado del universo** (§4) buscando entradas con el
   `run_id` pedido.
7. Exactamente una entrada verificada con ese `run_id`: comparar payload
   funcional. Coincide → **re-establecer durabilidad** (§6) y devolver
   `{"run_id", "digest"}` originales. Difiere →
   `HookRunError("hook_run_conflict")`, cero escrituras. Dos o más →
   `HookRunError("hook_run_duplicate_evidence")` (no se elige
   arbitrariamente, no se borra; remediación fuera de alcance).
8. Ninguna: construir la entrada con `now or _utc_now()`, firmar, calcular
   digest y publicar con `_write_exclusive` **bajo el lock**. Un
   `FileExistsError` aquí sólo es posible por un escritor que no coopera con
   el lock: re-verificar bytes completos + HMAC + nombre; si coinciden con
   nuestro payload, tratar como publicado (§6) y devolver ese digest; si no,
   `hook_run_evidence_invalid`.
9. Liberar el lock. **Retorno sin cambios:** `{"run_id", "digest"}`
   (`an_kla/hook_runs.py:121`); conservar bytes/hora en disco no exige
   ampliar el contrato de retorno (acta previa, ataque 1).

## 4. Universo de escaneo, lectura segura y límites (camino B)

- Universo: las entradas `*.json` de `<custodia>/hook-runs/runs/sha256/`
  (`RUNS_RELATIVE`, `an_kla/hook_runs.py:46`); root validado por §3.5 [N7]:
  ausente = universo vacío limpio; symlink o no-directorio =
  `hook_run_evidence_invalid`. Nombres que no terminan en `.json` se
  ignoran: fuera del layout vigente.
- **Lectura FIFO-segura** reutilizando el patrón ya presente en el repo
  (`an_kla/relocation_receipts.py:63–90` `_read_regular`):
  `lstat` previo, apertura
  con `O_NOFOLLOW | O_NONBLOCK`, verificación `fstat.S_ISREG` y
  `st_nlink == 1`, tamaño ≤ 64 KiB, comparación `(dev, ino)` antes y
  después de abrir. Un FIFO, symlink o directorio en el directorio de
  runs no cuelga el proceso (lección R3-04/R4-02/R6-01/R8-01).
  **Delta de locks (supersede N10):** los dos flags son OBLIGATORIOS, sin
  fallback cero — `fstat` posterior no evita que una apertura bloquee en
  un FIFO o siga un enlace. La disponibilidad se verifica una vez al
  entrar al camino B, antes de abrir candidatos o publicar; en plataformas
  sin los flags el camino B no está disponible y falla saneado con
  `hook_run_platform_unsupported` (pérdida de disponibilidad declarada;
  el helper global de receipts no cambia en este delta).
- **Todo candidato ilegible, no regular, sobre-medido, con JSON inválido,
  HMAC inválido, binding ajeno o cuyo nombre no coincida con el digest de
  sus bytes falla cerrado con `hook_run_evidence_invalid`.** No se puede
  descartar que una entrada indecifrable porte el `run_id` buscado, así que
  la unicidad queda indemostrable y no se publica. Consecuencia declarada:
  una entrada corrupta bloquea la acuñación con `run_id` explícito de todo
  `run_id` hasta que una remediación (fuera de este encargo) la retire [N8].
- **Límite:** si el número de candidatos `*.json` supera
  `_MAX_ENTRIES_SCANNED` (2000, `an_kla/hook_runs.py:54`) →
  `HookRunError("hook_run_scan_limit")`, nunca publicar como si no
  existiera; el caso «el `run_id` buscado queda después del umbral» queda
  cubierto por ese fallo cerrado antes de publicar. Un `OSError` a mitad del
  escaneo (directorio válido) → `hook_run_scan_incomplete`.
- **Coste, acotado y localizado [N2]:** lock + escaneo se pagan sólo en el
  camino B. Peor caso: ≤ 2000 candidatos × ≤ 64 KiB ≈ 128 MiB de lectura
  local más 2000 HMAC; sin `run_id` encontrado, el escaneo no puede abortar
  temprano (la ausencia exige recorrer todo el universo). El deadline de
  10 s acota la **adquisición** del lock (`hook_run_lock_busy`); la
  **retención** no tiene deadline propio — queda acotada por el tamaño del
  universo, y quienes esperan detrás agotan su propio deadline de
  adquisición. El CLI (camino A) no paga ninguno de los dos costes.
- El lector público `read_verified_runs` conserva sus códigos de
  degradación, truncado y tamaños; la verificación por entrada vive en un
  único predicado compartido `_entry_is_valid` (claves exactas, schema,
  exit_code, formato de hora, HMAC, binding) usado por lector y escaneo,
  para que los criterios no deriven [riesgo del relevo:
  «criterios duplicados lector/scan»]. El escaneo del camino B añade, por
  encima del predicado, igualdad byte a byte con el canónico,
  nombre==digest y revalidación de gramática; el lector NO añade esos
  chequeos. Cambio declarado frente al texto previo del lector: un
  `run_hmac` no-str crafted ahora degrada como `hook_run_invalid` en lugar
  de romper la lectura con `TypeError` de `compare_digest` (crash latente
  sin cobertura de pruebas). Las pruebas vigentes de lectura quedan sin
  edición y en verde.

## 5. Locks: disciplina, reentrancia, timeout y relación con relocate

Orden vigente en los escritores reales del store:

| Flujo | Locks | Evidencia |
|---|---|---|
| `commit_write_plan` | `write_lock` sólo | `an_kla/write_commit.py:45` |
| `commit_checkpoint` | `write_lock` sólo | `an_kla/checkpoints.py:184` |
| Compactación | `identity_lock` → `write_lock` | `an_kla/compaction.py:538–540` |
| Relocate (mutación) | `identity_lock` → `write_lock` | `an_kla/relocate.py:478–479` |

- El acuñador del camino B toma **sólo `store.write_lock()`**. Con eso queda
  excluido de la fase de mutación de relocate y de compactación (ambas
  sostienen el mismo write lock dentro de su sección crítica) y de otros
  acuñadores del camino B; con una sola pieza de lock no puede haber ciclo
  ni inversión de orden. No toma `identity_lock`: en POSIX ese lock es
  `flock` **bloqueante sin deadline** (`an_kla/identity.py:263`), y un
  acuñador que lo esperara colgaría el CLI de un comando ya exitoso.
- **Reentrancia:** `flock` es por descriptor; un caller que ya sostenga el
  write lock se auto-bloquearía hasta el deadline. Verificado que ningún
  caller actual acuña bajo lock: `_mint_hook_run` corre tras completar el
  comando (`an_kla/__main__.py:300–305` status, `:493–500` checkpoint commit,
  `:518–524` retrieve, `:536–542` assemble-context) y `commit_checkpoint`
  libera el lock al retornar (`an_kla/checkpoints.py:184`). Restricción
  documentada para callers futuros.
- **Timeout:** el mismo deadline del repo, `WRITE_LOCK_DEADLINE_SECONDS = 10`
  con backoff (`an_kla/store_locks.py:20–21,80–88`) →
  `HookRunError("hook_run_lock_busy")` (traducción interna; §3.B.3;
  observable API del camino B — el CLI no toma lock y no puede ver este
  código; son los hosts/API quienes deben tratarlo). El warning del CLI con
  comando preservado aplica a las degradaciones que sí alcanza: `OSError`
  del camino A y `CustodyError` tras el ajuste del §7.
- **Alias y bóveda externa:** el lock vive en la bóveda
  (`<store_root>/memory/.write.lock`, `an_kla/store.py:130–132,570`) y
  `store_root` se resuelve con `.resolve()` (`an_kla/store.py:119`) — dos
  aliases de la misma bóveda compiten por el mismo inode. No se asume que
  «el lock de proyecto cubre una bóveda externa»: el anclaje es la custodia
  resuelta, no `project_root`.
- **Relocate mientras se espera (descripción corregida por el delta):** el
  flujo normal de relocate copia el origen a staging
  (`an_kla/relocate.py:428`), publica el destino, publica el puntero y
  limpia el origen bajo write lock (`an_kla/relocate.py:478–531`); NO
  renombra el origen preservando su inode y sus locks quedan como residuos
  inertes (`an_kla/relocate.py:581`). La seguridad del acuñador depende del
  lock de origen y de la revalidación bajo lock (paso 4), no de que un
  descriptor abierto «viaje» con la bóveda: si la custodia cambió mientras
  se esperaba, la revalidación falla cerrado y no se publica nada.
- **Sin recreación de layout [N5, resuelto por el delta]:** el lock directo
  `write_lock(store.root)` no ejecuta `_make_layout()`; si `memory/` falta,
  falla con `OSError` sin recrear nada (§3.B.3). La garantía es «no
  recrear layout/ancestros», no cero efectos: el archivo `.write.lock`
  puede crearse dentro de un `memory/` ya existente, y la apertura
  ordinaria del helper no endurece el propio lock file contra
  symlink/FIFO (`an_kla/store_locks.py:76`) — el delta no atribuye
  protección integral frente a sustituciones hostiles de esa ruta.

## 6. Durabilidad y recuperación tras resultado incierto

`_write_exclusive` (`an_kla/attest.py:130–149`): `mkdir` → `open O_EXCL` →
bucle de escritura → `fsync(file)` → `close` → `fsync(dir)`. Matriz de
fallos y comportamiento del reintento (el retry jamás declara éxito por
existencia; existencia e integridad no prueban durabilidad):

| Fallo | Estado en disco | Comportamiento del reintento |
|---|---|---|
| Escritura parcial (`os.write`/open) | prefijo inválido | el escaneo verifica y falla: `hook_run_evidence_invalid`; no reparar, no sobrescribir |
| `fsync(file)` falló con bytes completos | objeto completo, durabilidad incierta | verificar bytes+HMAC+nombre; **re-fsync** (`open O_RDONLY` FIFO-seguro + `fsync(fd)` + `fsync(dir)`); éxito → devolver digest original; fallo → `hook_run_publication_uncertain` |
| `fsync(dir)` falló | ídem | ídem (la re-fsync de directorio re-establece la durabilidad de la entrada en el layout) |

La re-fsync es idempotente, no cambia contenido ni `observed_at` (no
renueva recencia) y convierte «existe, quizá no durable» en «durable ahora»
antes de afirmarlo. Si la re-fsync falla, el resultado es incierto y se
falla cerrado: ninguna publicación adicional tras un resultado incierto.
El archivo completo cuyo fsync falló y el prefijo se distinguen por
verificación exacta (JSON parsea, bytes == `canonical_json(entry) + b"\n"`,
HMAC válido, nombre == digest de los bytes), no por heurísticas de tamaño.

**Corrección TOCTOU del relevo:** la verificación y el fsync ocurren sobre
UNA sola apertura (`_open_verified` → `fsync` del mismo descriptor):
el contenido verificado jamás se re-abre después, así que los bytes cuya
durabilidad se afirma son exactamente los bytes verificados; la igualdad
con un payload esperado queda probada por nombre==digest de esos bytes
(otro contenido tendría otro digest y, por tanto, otro nombre). Un fallo
de `fsync` del archivo o del directorio produce
`hook_run_publication_uncertain`. Residual honesto: el directorio padre se
re-resuelve por ruta para su fsync; la sustitución hostil de ancestros ya
está cubierta por el recorrido de symlinks del §3.B.5 y el actor que
pudiera intercambiar rutas bajo la bóveda ya cruzó la frontera de confianza
(llave en el mismo host, ADR-0046 §1).

- **Ámbito de plataforma [N3]:** el mecanismo se declara POSIX (el perfil de
  durabilidad del producto ya es `posix-fsync-dir/v1`,
  `an_kla status`); `fsync` sobre fd `O_RDONLY` funciona en Linux/macOS y es
  ambiguo en el POSIX estricto, así que H2 lo demuestra con inyección de
  fallo en la plataforma objetivo (macOS, `.venv/bin/python` 3.12) y el
  código trata un fallo de re-fsync como resultado incierto fail-closed,
  nunca como éxito.
- **Ventana residual declarada [N3]:** las entradas completas-pero-inciertas
  de *otros* `run_id` no se re-fsyncan salvo que se reintente su propio id;
  es el alcance natural del reintento y no se oculta.

## 7. Códigos nuevos y propagación

Códigos `HookRunError` nuevos (patrón vigente `str(exc) == código`,
`an_kla/hook_runs.py:63–64,87`): `hook_run_conflict`,
`hook_run_duplicate_evidence`, `hook_run_evidence_invalid`,
`hook_run_scan_limit`, `hook_run_scan_incomplete`, `hook_run_lock_busy`,
`hook_run_publication_uncertain`, `hook_run_platform_unsupported`
(delta de locks: disponibilidad obligatoria de `O_NOFOLLOW`/`O_NONBLOCK`
verificada antes de efectos en el camino B).

- **Contratos del API sin cambios:** `CustodyError` y `IdentityError` se
  propagan con sus tipos actuales en ambos caminos (asertos vigentes en
  `tests/test_custody_root.py:305–313`, sin edición) [B2]. `LockBusyError`
  no tiene superficie previa desde `mint_hook_run` (hoy la función no toma
  locks): su única ruta nueva se traduce a `HookRunError("hook_run_lock_busy")`.
- **Ajuste acotado del CLI (defecto latente declarado):** `CustodyError`
  hereda de `StoreError(RuntimeError)` (`an_kla/custody.py:32`;
  `an_kla/store_errors.py:10`) y hoy **no** está en el `except` de
  `_mint_hook_run` (`an_kla/__main__.py:175–182`): un fallo de custodia
  durante la acuñación rompería con traceback un comando ya exitoso. Se
  añade `CustodyError` a ese `except` para que emita el warning estable
  `hook_run_mint_skipped (...)` como el resto de degradaciones. Es una
  corrección de un defecto real declarada aquí, no un cambio silencioso;
  el contrato del API (que el test de custodia aserta) no se toca. [N6:
  mismo patrón que el `TypeError` de subject, que la validación nueva
  convierte en rechazo saneado]
- **MCP:** `an_kla/mcp.py` no tiene referencias a hooks ni a
  `mint_hook_run` (`rg -in hook an_kla/mcp.py` sin resultados): la ruta no
  es alcanzable desde MCP; no se inventa integración (acta previa, ataque 5).
- **Retorno sin cambios:** `{"run_id", "digest"}` (`an_kla/hook_runs.py:121`).
- **Cambios de comportamiento declarados (dirección fail-closed):**
  (i) `exit_code` fuera de 0..255, `subject` no serializable (antes: crash)
  o no-`Mapping` (estrechamiento declarado [N9]: hoy `digest_json` acepta
  cualquier valor serializable; a partir de ahora se exige `Mapping`, el
  descriptor del docstring, `an_kla/hook_runs.py:10–13`), `hook_id` con
  salto de línea final (endurecimiento `match`→`fullmatch`, [H3-N1]),
  `adapter_fingerprint` no str/None, `run_id` mal formado, `now` con formato
  inválido o payload > 64 KiB pasan de acuñar evidencia degradada (o romper)
  a rechazar antes de efectos; (ii) bóvedas con > 2000 runs o con alguna
  entrada corrupta pasan de acuñar a fallar cerrado **en el camino B** (con
  `run_id` explícito); el camino A (CLI) publica como hoy porque un uuid
  fresco no afirma ausencia de nada [N2/N8]; (iii) fallos de custodia en el
  CLI pasan de romper el comando a warning. Una invocación CLI sin contexto
  de hook no acuña nada y queda byte-idéntica (oro de no-escritura intacto,
  `tests/test_hook_runs.py:189–192`).

## 8. ¿Requiere ADR nueva? — posición: no (compartida con la revisión)

ADR-0047 §4 ya decide lo esencial: el formato de la entrada, el layout
content-addressed bajo `.an-kla/hook-runs/runs/sha256/`, y la semántica
«el reintento del host con el mismo `run_id` → re-acuñación no-op
idempotente» (`docs/architecture/0047-host-hooks-governed-v1.md:145–149`).
Este diseño implementa lo declarado con primitivas existentes
(`_write_exclusive`, `store.write_lock` — reuso anclado en custodia,
ADR-0048 F0-B, exigido por el ataque 3 del acta previa) sin layout nuevo,
sin índice, sin schema y sin contrato público nuevo. El resultado observable
que la ADR declara — un objeto por `run_id`, ninguna acuñación perdida en
silencio — se cumple, y el docstring vigente ya declara la semántica
reparada (`an_kla/hook_runs.py:79–85`). La tensión interpretativa
(«reproduce contenido idéntico» presupone un reloj estable) queda declarada:
si el maintainer prefiere la reproducción literal del contenido, es una
decisión suya, no un requisito de esta reparación. Ningún disparador de ADR
del plan (`:46–47`) se cumple.

## 9. Requisitos que H2 debe implementar y probar (gate heredado)

1. Reintento con reloj avanzado y `now` distinto (camino B): bytes, digest y
   hora originales; retorno igual al original; recencia no renovada.
2. Reinicio de proceso entre acuñaciones con el mismo `run_id` (estado en
   disco; dos procesos, misma custodia).
3. Cambio de cada campo funcional → `hook_run_conflict`; `run_id` distintos
   → eventos distintos.
4. Carrera multiproceso con barrera (camino B): mismo payload → un objeto
   válido; payload distinto → exactamente un objeto y el resto
   `hook_run_conflict`; alias de la misma custodia; custodia externa; sin
   sleeps como sincronización ni procesos huérfanos.
5. Límite (camino B): >2000 candidatos → `hook_run_scan_limit` con el run
   buscado después del umbral (prueba positiva del escaneo, no sólo el
   conteo); exactamente 2000 con el run dentro → escaneo procede y devuelve
   el original.
6. Entradas hostiles (camino B): FIFO, symlink de entrada, JSON inválido,
   HMAC inválido, binding ajeno, nombre≠digest, tamaño excedido →
   `hook_run_evidence_invalid`; root de runs symlinkeado o como archivo
   (no-directorio) → `hook_run_evidence_invalid` (observable API del camino
   B [R-B1]; el warning `hook_run_unwritable` del CLI es y sigue siendo
   observable del camino A — `tests/test_hook_runs.py:280–297` sin edición,
   vía `OSError` de publicación); root ausente → universo vacío limpio
   (primera reposición sobre bóveda fresca); tipos inválidos, `exit_code`
   fuera de rango, `now` malformado, payload >64 KiB →
   `hook_run_invalid_input`; sin publicación y sin creación de directorios
   en los casos de rechazo.
7. Duplicados históricos previos (fabricados firmando dos entradas válidas
   con la llave de la bóveda de prueba y horas distintas) →
   `hook_run_duplicate_evidence` para ese `run_id`.
8. Inyección separada de fallos: escritura parcial, `fsync(file)`,
   `fsync(dir)`; segunda invocación según la matriz de §6; prueba de
   re-fsync en la plataforma objetivo con `O_RDONLY` [N3]; sin falsas
   garantías de durabilidad ni escrituras tras resultado incierto.
9. Timeout de lock [N1/R-B2]: contención sostenida con
   `WRITE_LOCK_DEADLINE_SECONDS` acortado en el test → `mint_hook_run` con
   `run_id` explícito lanza `HookRunError("hook_run_lock_busy")`
   (observable API del camino B; determinista; el CLI no toma lock y no
   puede ver este código).
10. CLI y contratos previos: sin hook (no escribe), hook exitoso (camino A),
    directorio saboteado (`tests/test_hook_runs.py:280–297` verde sin
    edición), recencia vencida (reintento no rejuvenece); contratos de
    custodia del API (`tests/test_custody_root.py` sin edición, incluido el
    aserto `CustodyError` del camino B) [B2]; lector y retorno intactos
    (pruebas vigentes de lectura sin edición); contratos previos y autoridad
    sin cambios (plan H2 paso 5, `:76`).
11. Pruebas vigentes de `tests/test_hook_runs.py` sin edición (lectura
    legacy y caminos CLI bit a bit) más suites focales y gates del plan (H3).

## 10. Evidencia de la sesión (resumen; bitácora completa fuera de Git)

| Comando | Resultado |
|---|---|
| `git rev-parse HEAD` | `0e69ae932d1d546bf28534e354ed4a2bc034dc45`, árbol limpio salvo docs nuevos sin seguimiento |
| `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'` | 1333 pruebas, OK (74 omitidas, extra sellado no instalado), rc=0, 738 s |
| `context status` / `status` / `verify` (con `--no-update-check`) | ok, revisión `sha256:0fde0250…`, rev 89, sin diagnósticos |
| `gh issue list --state open` / `gh pr list --state open` | #169 #168 #166 #140 #58; sin PRs; rc=0 |
| Reproductor control/contraejemplo (in-process) | 1 objeto / 2 objetos con digests distintos |
| Reproductor dos procesos sobre la misma custodia | 2 objetos, digests distintos |

Trazado de código citado: §3–§7. Los reproductores y sus salidas viven en
`/private/var/folders/q1/k3y040sd0rv9cbxcdskwr_zw0000gp/T/opencode/hook-idem-h0-h1/`
(fuera de Git, sin llaves ni payloads privados). Ciclo de revisión de este
documento: acta fix-and-retry (B1/B2 bloqueantes) → rev. 2 (resuelve B1/B2,
incorpora N1–N8) → rev. 3 (resuelve R-B1/R-B2, plega N9/N10; **proceed**
del revisor fresco) → rev. 4 (incorpora el delta de locks con proceed
documental de `review_lock_delta` y las correcciones del relevo:
TOCTOU de apertura única, symlinks en ancestros, flags obligatorios
verificados antes de efectos, criterios lector/escaneo consolidados,
descripción real de relocate).

Estado de implementación (H2, rev. 4/5): `an_kla/hook_runs.py` (caminos
A/B, escaneo fail-closed, `_entry_is_valid` compartido, `_open_verified`
con verificación+fsync en una sola apertura, lock directo sin layout),
`an_kla/__main__.py` (CustodyError añadido al `except` de acuñación) y
`tests/test_hook_run_retry.py` (matriz determinista: reloj avanzado,
reinicio spawn, conflictos por campo, carrera con barrera, hostiles,
duplicados firmados, límite real 2001, inyección fsync, timeout de lock,
flags ausentes, memoria eliminada antes del lock, custodia cambiada en
espera, alias de custodia externa, pin de apertura única). Suites
focales en verde sobre el árbol modificado; verificación completa en el
reporte final de H4.
