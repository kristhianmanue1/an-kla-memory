# ADR-0063: Escribir en una llamada con bandeja, escritor declarado y disputa

- **Estado:** Aceptada parcialmente (2026-11-14, decisión del orquestador
  en el mandato 4, bajo la delegación del esfuerzo de memoria agéntica):
  aceptadas D2, D3 y «Commit con el candado tomado»; **D1 (bandeja y
  vaciado) sigue en Propuesta**; su texto ya incorpora la evidencia del
  spike de recuperación y espera ronda y decisión. Ver
  «Partición del estado».
- **Implementación:** No iniciada
- **Fecha:** 2026-11-14
- **Decide sobre:** la orden aditiva de CLI `remember`, que guarda un
  recuerdo en una invocación sin perder ni pisar escrituras concurrentes,
  con escritor y hora de encolado declarados y sin que un agente desactive
  el hecho de otro.

## Contexto

Guardar un hecho hoy cuesta cuatro invocaciones y ~5 KB de JSON
(`AN-KLA.md:79-109`: `status` → proposal → `plan-write
--emit-authority-template` → `plan-write --authority` → `commit-write-plan
--expected-current`). Tres fuerzas, medidas en `main@29c5ec0`:

1. **Concurrencia.** Con 4 escritores y 8 lectores durante 60 s, 629 de 874
   intentos fallaron por CAS (72 %) y **0** por candado
   (`benchmarks/scale/results/20261028-110445/concurrency-v2.json`:
   `cas_conflicts_total: 629`, `lock_busy_total: 0`). El candado
   (`an_kla/store_locks.py:20-21, 76-89`: `flock LOCK_NB`, reintento cada
   50 ms hasta 10 s) no es la causa: cada escritor planifica **fuera** del
   candado contra una `base_revision` que caduca antes del CAS
   (`an_kla/write_commit.py:42-51, 104-110`;
   `benchmarks/scale/scenarios_ops.py:43-69`).
2. **Procedencia.** `lineage` e `issuer` se validan
   (`an_kla/write_policy.py:335-344` para `lineage`, `:414-434` para
   `issuer`) pero `lineage.refs`, `issuer` y la
   atribución por registro no se persisten: el evento
   `write_policy_decision` sólo lleva clase, hashes, decisión y razones
   (`write_policy.py:655-676`; el booleano `derived_from_retrieval`
   sobrevive sólo como razón agregada, `:522-523`), y el manifest de
   revisión no tiene tiempo (`an_kla/revision_builder.py:22-41`). No se sabe
   quién escribió qué.
3. **Silenciar a otro.** Un `model_derived` puede sustituir un hecho ajeno
   (`write_policy.py:117-120`: `derived_authority.allowed_operations:
   ["add","supersede"]`; `an_kla/supersede.py:18-58` sólo exige que el
   target exista y sea vigente) y el original pasa a `sustituida`.

Restricciones:

- **Compatibilidad.** Las órdenes de datos existentes (`status`, `verify`,
  `inventory`, `retrieve`, `resume`, `assemble-context`, `export`,
  `plan-write`, `commit-write-plan`, `refute`) y el MCP devuelven lo mismo
  para el mismo store y entradas si el store no tiene `memory/inbox/` (la única excepción, `export` y `relocate commit` con bandeja, se declara en D1). El `policy_fingerprint` de
  `write-policy/v1` (`digest_json(_POLICY_CONFIGURATION)`,
  `write_policy.py:154-155`) no cambia. `capabilities`, `schema list` y
  `--help` sólo cambian de forma aditiva.
- **MCP de sólo lectura.** ADR-0003 pospone deliberadamente el MCP
  escribible y ADR-0047 lo mantiene read-only en v1 (`an_kla/mcp.py:3,
  344, 596`: `ReadOnlyMcp`, `an-kla-read`). Esta decisión no lo cambia.
- **Lecturas puras.** Una lectura no muta el store (ADR-0047 §4).
- **`refute` no sirve.** ADR-0026 proyecta `status="refutada"` sobre el
  target (`an_kla/store.py:345-358`), que deja de ser vigente
  (`an_kla/vigency.py`), y exige autoridad privilegiada con resolver
  (`an_kla/refute_policy.py:25, 96-104`) que un agente no tiene.
- **Records abiertos.** `validate_record_fields` sólo valida `id`,
  `verified_at`, `status`/`nu` y `subject_ref` (`write_policy.py:268-286`);
  `_SELF_ASSERTED_AUTHORITY_KEYS` (`:36-47`) no incluye claves de
  identidad. Un record admite claves adicionales sin cambiar el formato de
  segmento (JSONL canónico direccionado por contenido, `store.py:616-633`),
  cuyo versionado vive en el manifest.
- **Lote.** `write-proposal-v2` es homogéneo en stream y operación, sin
  supersede intra-lote (`an_kla/write_batch.py:1-7, 44-95`; prohibición intra-lote en `:88-91`); su tope
  declarado es 1000 (`write_policy.py:123`), pero `_MAX_JSON_NODES =
  10_000` (`write_policy.py:49, 185-212`) se aplica a propuesta y plan: con
  un sobre de 21 nodos por record el máximo medido es ≈ 380 (spike E1.a).
- **Custodia.** `export`, el sellado y `relocate plan` recorren la custodia y
  fallan con `export_unrecognized_durable_path` ante cualquier archivo no
  listado (`an_kla/export_restore.py:82-98`; `relocate.py:124-137, 188`),
  medido en el spike de E1.a.
- **Candado no reentrante.** `write_lock` abre un descriptor nuevo por
  llamada (`store.py:567-570`): `commit_write_plan` dentro de otro
  `write_lock` espera 10 s y falla con `write_lock_busy` (spike).
- **Identidad.** C0 `memoria/identidad/v1`, **congelada** en `main` de
  `aria/coordination` (commit `8fccbcc`, 76 vectores y 8 comprobaciones de
  derivación). #58 (G4) exige threat model y trata la identidad sólo como
  routing, nunca como permiso.

## Decisión

Añadir a la CLI `remember`, `inbox drain`, `inbox status` y
`disputes list`. El MCP no cambia; de las órdenes existentes sólo cambian
`export` y `relocate commit` cuando hay bandeja (D1, «La bandeja no es
estado durable»). Tres decisiones; el trato de la bandeja en la custodia es
parte de D1, no un cuarto cambio. La extracción del commit con el candado
tomado tiene sección propia porque se acepta aparte.

### Partición del estado

Las rondas r1 a r4 convergieron en todo salvo en la recuperación tras un
corte durante el vaciado (pasos 0 y 7 de D1), que ya no se puede cerrar en
el papel. Por eso el estado se parte:

| Parte | Estado | Qué autoriza | Criterios |
|---|---|---|---|
| «Commit con el candado tomado» | Aceptada | Extracción neutra en `write_commit.py`, sin llamante nuevo | 10 |
| D2: formato del sobre, validador C0, derivación de `repo.id`, construcción desde el entorno | Aceptada | Módulo y schema `record-envelope-v1` sin llamante: ninguna orden escribe sobres | 5 y las pruebas de C0 |
| D3: regla propia/ajena, record de disputa, selector `raw_records` | Aceptada | Nada en `main` todavía: su único camino es `remember` | 4 (al implementarse) |
| D1: `remember`, bandeja, vaciado, órdenes `inbox`, `disputes list`, cambios de custodia en `export`/`relocate` | **Propuesta**, corregida con la evidencia del spike; pendiente de ronda y decisión | Nada | 1–3, 6–9 |

**Regla de cierre.** Mientras D1 no esté aceptada, no entra en `main`
código de la bandeja, `remember`, `inbox drain`, `inbox status`,
`disputes list`, los cambios de custodia de D1 ni el camino de D3 (la fase
B y la C). D1 se acepta sólo con un PR `docs/` que reescriba sus pasos 0 y 7
con la evidencia del spike (`kill -9` en los puntos del criterio 3,
8 clientes concurrentes) y resuelva la deuda de r4 («Deuda de r4 y spike de
recuperación»), con ronda adversarial `proceed` y decisión de quien acepta.
Ese PR cambia esta tabla.

**Independencia.** Lo aceptado no depende de la forma de D1:

- la extracción es un refactor neutro de `commit_write_plan` y se demuestra
  con sus propias pruebas (criterio 10). Que el vaciado sea un futuro
  llamante no es requisito;
- el sobre y el validador de D2 son datos y funciones puras. Sólo el
  momento en que se escribe el sobre en un record depende de `remember`;
- la regla de D3 se aplica bajo `write_lock` al planificar el commit del
  record, sea cual sea el mecanismo que lo lleve allí. Los destinos
  «al vaciar», `rejected/` y `"resolution": "pending"` son los de D1 y
  siguen su estado.

Si el spike obliga a cambiar algo de lo aceptado, esa parte vuelve a
Propuesta en el mismo PR.

### Commit con el candado tomado (aceptado)

`write_commit.py` se parte, sin cambio de comportamiento, en la envoltura
pública de hoy (toma el candado; mismos bytes y errores) y
`_commit_write_plan_locked(store, lock_result, …)`, que recibe el testigo
del candado, hace la misma revalidación completa (`verify_write_plan`, CAS
contra `CURRENT`, replay por `transaction_id` de ADR-0024, supersede,
`subject_ref`) y devuelve `(revision, outcome)`. La envoltura y cualquier
llamante futuro que ya tenga el candado comparten el post-proceso tras
soltarlo (`_post_lock_outcome`, `_maybe_reindex`, `_context_diagnostics`,
aviso `record_without_indexable_text`), en el orden de hoy. Es la técnica de
la extracción de `supersede.py` (#59 Fase 0). El candado no es reentrante
(`store.py:567-570`): sin esta extracción, nadie que ya tenga `write_lock`
puede comprometer. La compactación toma `write_lock` (`compaction.py:540`),
así que planificar bajo él cubre el TOCTOU que ADR-0060 cierra para
`plan_write` con el gate de lectores. En este camino la defensa contra
duplicados es `_assign_records` (`duplicate_<stream>_id`), bajo el candado;
`plan_duplicate_id` (`plan_guard.py`) sólo actúa en `plan_write`.

Orden de trabajo, no dependencia: la extracción se programó después del
spike de recuperación, por si el cierre del journal (deuda H5) pedía más
del cuerpo bloqueado. El spike concluyó que sigue siendo neutra: el paso 0
y el cierre no llaman al cuerpo, y el marcador se escribe antes de
invocarlo. El cuerpo recibe además el `preflight` ya calculado (`binding`
y `context`).

### D1 — Bandeja de entrada y vaciado en lote bajo candado, sin demonio

> **Estado de D1: Propuesta**, corregida con la evidencia del spike. Ver
> «Partición del estado». Nada de esta sección se implementa todavía.

**Orden.** `remember (--text <t> | --text-file <ruta|->) [--kind
fact|decision|state] [--supersedes <id>] [--idempotency-key <k>]`. Único
dato obligatorio: el texto. `--text-file -` (stdin) es la forma recomendada:
`--text` pone el contenido en `argv`, visible para `ps` y el historial del
shell. Máximo 64 KiB de texto en UTF-8. `kind` por defecto `fact`; `fact` y
`decision` van al stream `facts` y `state` a `episodes` (el checkpoint
`working-state-v2` no se toca). Con `--supersedes`, el stream lo decide el
target (ver D3).

**Record.** `remember` escribe exactamente `{"id": <id>, "text": <texto>,
"an_kla_envelope": {…}}` (más `"disputes": {…}` en D3), que `record_text`
indexa (`record_text.py:15-32`), con `requested_representation: "summary"`
(techo de `model_derived`) y `lineage: {"derived_from_retrieval": false,
"refs": []}`. Schemas nuevos: `inbox-entry-v1`, `record-envelope-v1`,
`remember-result-v1`, `inbox-drain-result-v1`, `inbox-status-v1`,
`disputes-list-v1`.

**Directorios.** `memory/inbox/` contiene `.lock`, `tmp/` (temporales del
encolado), `pending/` (entradas completas), `inflight/` (marcadores de
lotes en vuelo, paso 0), `rejected/` (evidencia). Sólo
cuenta como entrada un archivo de `pending/` cuyo nombre case
`^[0-9]+-[0-9]+-[0-9a-f]{16}-[0-9a-f]{8}\.json$`; el vaciado ignora sin
tocar todo lo demás de `pending/`. Sólo cuenta como marcador un archivo de
`inflight/` cuyo nombre sea `<transaction_id>.json`. En todo este ADR,
«`pending/` vacío» significa «sin nombres que casen el patrón de entrada»
e «`inflight/` vacío», «sin nombres de marcador»: un directorio u otro
nombre ignorado no bloquea la custodia ni impide que `inbox drain`
termine, e `inbox status` lo informa aparte (`ignored`).

**Orden total de candados:** bandeja (`memory/inbox/.lock`) → identidad
(`identity_lock`) → `write_lock` → gate de lectores. Nadie pide un candado
anterior teniendo uno posterior; las órdenes que usan el de bandeja lo toman
al principio, antes de crear nada, y lo sueltan al final. En plataformas sin
`flock` compartido el candado de bandeja se toma siempre en exclusivo (más
lento, igual de correcto); hay prueba por plataforma.

**Encolar.**

1. Ejecuta el preflight de la escritura gobernada
   (`_mutation_preflight_with_context`, que incluye `_custody_guard`,
   `identity.py:60, 670`) **antes de crear nada** en `memory/inbox/`.
2. Toma el candado de bandeja en compartido con plazo corto; si está
   ocupado (un `export` o `relocate commit` en curso), falla con
   `inbox_busy` y pista de reintento, sin escribir.
3. Con él, repite el preflight; si la custodia cambió, falla con su código
   (`store_root_divergence` o `store_identity_changed`) y no deja entrada.
4. Escribe la entrada `an-kla/inbox-entry-v1` en `memory/inbox/tmp/`
   (`O_EXCL`, fsync del archivo). Antes de publicar hace `lstat` del
   destino en `pending/`: si el nombre existe, regenera `<aleatorio8>` y
   reintenta; nunca publica sobre un nombre existente (`os.replace`
   sobrescribe en silencio, medido). Publica con `os.replace` (mismo
   sistema de archivos, el inodo nunca tiene dos nombres, `st_nlink` sigue
   en 1) y hace fsync de `pending/`. Si `os.replace` falla (EXDEV, ENOSPC,
   E/S), el encolado falla con ese error, sin entrada en `pending/`, y el
   temporal queda en `tmp/` para el recolector. No se usa `os.link` +
   `unlink`: entre ambos el inodo tiene `st_nlink == 2` y el paso 2 del
   vaciado rechazaría una entrada legítima (medido: 12 de 166 796
   lecturas). Nombre: `<tiempo_ns>-<pid>-<clave16>-<aleatorio8>.json`. La entrada guarda texto,
   `kind`, sobre (D2), clave, `payload_sha256` (de texto, `kind` y target) y,
   si lo hay, sólo el `target_id` pedido: la resolución propia/ajena ocurre
   al vaciar.
5. Suelta el candado de bandeja y pasa a vaciar.

**Vaciar.** Intenta `write_lock` con un plazo corto (parámetro opcional
nuevo de `write_lock`; la constante de 10 s no cambia). Si está ocupado →
`{"state": "queued"}`.

**Recolección de `tmp/`.** Antes de pedir `write_lock`, el vaciado intenta
el candado de bandeja en **exclusivo y sin esperar**. Si lo obtiene, no hay
encolador vivo: cada uno tiene el compartido durante todo el encolado y el
sistema operativo lo suelta al morir el proceso, también con `SIGKILL`. Por
tanto todo lo que haya en `tmp/` es huérfano y se borra. Si el candado está
ocupado, no recolecta. No hay umbral de antigüedad: uno de 60 s pierde el
temporal de un encolado demorado. Un temporal nunca es una entrada
confirmada.

Con `write_lock` tomado:

0. **Reconcilia** los lotes en vuelo. Antes de comprometer un lote, el
   vaciado escribe con fsync `memory/inbox/inflight/<transaction_id>.json`
   con `{txid, base_revision, entries}`; así la bandeja sabe qué journals
   son suyos sin depender del espacio UUIDv5. Por cada marcador, en orden,
   `store.inspect_transaction(txid)` (sólo lectura,
   `transactions.py:312-313`) y tres ramas:
   - `committed is True` → **cierra el journal** («Cierre del journal»).
     Si el resultado es `durability_incomplete`, llama a
     `repair_durability(txid)`. Después vuelve a inspeccionar y exige
     `committed is True` y `durability_state == "complete"`; si la
     reparación lanza o el predicado no se cumple, aborta sin borrar
     marcador ni entradas e informa `drain_error: transaction_<state>`
     (`state` de `commit-outcome-v2`). Una auditoría incompleta
     (`audit_state != "complete"`) no aborta: las entradas ya están en
     `CURRENT` con durabilidad completa, así que se borran y se informa
     el aviso `inbox_audit_incomplete`. Con el cierre de abajo no se
     observó nunca (spike, configuración F). Después borra de
     `pending/` las entradas del marcador (fsync de `pending/`) y, al
     final, el marcador (fsync de `inflight/`). El orden journal → entradas
     → marcador es obligatorio;
   - `committed is False` → borra sólo el marcador. Las entradas siguen
     pendientes; si el lote siguiente reconstruye el mismo `txid`,
     `commit_locked` reintenta el commit sobre el journal existente;
   - `committed is None` no significa «no llegó». Se borra el marcador
     sólo si la transacción **no dejó rastro**: no existe
     `transactions/<txid>.json`, ningún manifiesto lleva ese
     `transaction_id` y no existe `transactions/<txid>/`. El journal
     `prepared` es lo primero que escribe `commit_locked`
     (`transactions.py:532`), así que su ausencia prueba que no se escribió
     nada. En cualquier otro caso (journal ilegible, candidato ambiguo,
     `CURRENT` ilegible) el vaciado **conserva marcador y entradas, aborta**
     e informa `transaction_<código>`; nunca a `rejected/`.

   Los journals de otras órdenes no se tocan.

   **Cierre del journal.** Reescribe `transactions/<txid>.json` con
   `stage: "committed"` y los campos de `transactions.py:712-725`:
   - conserva `parent`, `candidate`, `attempt`, `stage_object` y
     `write_policy` del journal existente; si falta o está corrupto, los
     reconstruye del objeto inmutable de `stages/`;
   - si `observed_log` no es una cadena, escribe los ref-logs `intent` y
     `observed_commit` y **enlaza `observed_log`** al segundo; así
     `audit_state` pasa a `complete` (`audit_validation.py`). Los objetos
     están direccionados por contenido, así que es idempotente;
   - enlaza **sólo los recibos que existen y validan** y nunca fabrica uno
     (patrón de `compaction.py:437-440`).

   Un segundo cierre es un no-op. No sirven la ruta de replay de
   `_commit_locked` (`transactions.py:505-508`, retorna sin escribir:
   medido, el journal queda byte a byte igual) ni
   `_reconcile_committed_journal` (privada de compaction, exige un
   `planning`).

   Un corte entre `_replace_current` (`:687`) y el recibo `current-durable`
   deja el journal `committed`, con `inspect_transaction` en
   `durability_incomplete`, que no es un `stage` sino un resultado derivado
   de los recibos. `repair_durability` escribe el recibo `repair`
   (`transaction_repair.py:90-99`): resuelve la durabilidad, no la
   auditoría, que ya completó el cierre. El estado final es `committed`.
1. lee `CURRENT` y el snapshot;
2. para cada nombre de `pending/` que casa el patrón de entrada, `lstat`:
   un directorio se ignora sin tocarlo (como todo nombre que no casa); si
   no es archivo regular con `st_nlink == 1` (FIFO, socket, enlace,
   hardlink) → `rejected/` con `inbox_entry_unsafe`, sin abrirla (un FIFO
   no bloquea el vaciado); si no se puede leer o no valida
   `inbox-entry-v1` → `rejected/` con su motivo;
3. resuelve cada `--supersedes` (D3), con lo que cada entrada tiene stream e
   id definitivos;
4. **deduplica**: dentro de `pending/`, por id, si clave **y**
   `payload_sha256` coinciden conserva la más antigua y borra las demás; si
   el id coincide con otro `payload_sha256` → `rejected/` con
   `remember_id_collision`. Contra el snapshot, igual comparando con la
   clave y el texto del record existente. Además, si dos entradas
   sustituyen al mismo target, conserva la más antigua y la otra va a
   `rejected/` con `supersedes:duplicate_target`: es el único error de lote
   que ninguna entrada produce sola (prefiltro O(n), 0,018 ms con 250);
5. **evalúa cada entrada sola** con las funciones puras de política
   (`evaluate_write` y construcción del plan de un record, sin escribir
   nada), con el candado tomado: `skip` → `rejected/` con
   `remember_policy_skip` y sus `reason_codes`; error terminal de política
   → `rejected/` con su código. Después arma lotes homogéneos sólo con las
   entradas que pasaron, con presupuesto de nodos (propuesta + plan
   ≤ 9.000) y como máximo 250 entradas;
6. construye propuesta, autoridad `model_derived` (la plantilla de
   `emit_write_authority_template`) y plan con las funciones puras de
   política, y compromete por `_commit_write_plan_locked` con
   `transaction_id = uuid5(NS_AN_KLA_INBOX, base_revision + sorted(digests
   de las entradas del lote))`;
7. el marcador del paso 0 se escribe antes del commit. Según el resultado:
   - `committed: true` → borra las entradas del lote de `pending/` (fsync)
     y **después** el marcador (fsync). `commit_locked` ya escribió el
     journal `committed` (`transactions.py:725`): un corte en cualquier
     punto de este paso lo resuelve el paso 0 por la rama `True`;
   - `decision: skip` o error terminal de política antes de que
     `commit_locked` escriba nada (`invalid_*`, `plan_*`,
     `invalid_supersede_target`, `duplicate_<stream>_id`) → borra el
     marcador y **aísla sin soltar `write_lock`**, en dos tiempos:
     1. **bisección por prefijos en memoria**: contra la misma base, con
        las funciones puras (`evaluate_write`, construcción del plan) y la
        validación de lote de `write_batch`, acumula las entradas aceptadas
        y busca el prefijo más corto que falla. Su última entrada es la
        culpable y va a `rejected/` con su código; se repite con el resto
        (⌈log₂ 250⌉ = 8 evaluaciones por entrada mala; nada se escribe).
        La bisección por mitades no sirve: no atribuye los fallos de par
        (medido con `duplicate_target`: las dos mitades pasan solas);
     2. los supervivientes se comprometen en **un** lote nuevo: se relee
        `CURRENT` bajo el candado, se replanifica con esa `base_revision` y
        se recalcula su `transaction_id`, y se escribe su marcador en
        `inflight/` antes del commit. Como nadie más puede mover
        `CURRENT` mientras el candado esté tomado, `write_plan_base_changed`
        no puede ocurrir aquí; si ocurre, es un defecto y aborta.
     Sólo si ese lote vuelve a fallar con un error que la bisección pura no
     predijo (`duplicate_<stream>_id`, que nace en `_assign_records`), se
     compromete entrada por entrada, releyendo `CURRENT` y replanificando
     cada commit. Cada uno sigue la misma regla que cualquier lote: su
     `transaction_id` (uuid5 de su base y del digest de su única entrada)
     y su marcador en `inflight/`, con fsync, antes del commit; con
     `committed: true`, borra la entrada de `pending/` y después el
     marcador. Así un corte en cualquiera de esos commits lo resuelve el
     paso 0 como cualquier otro. Este último recurso cuesta un commit y dos
     fsync de marcador por entrada, y se reporta;
   - `committed: false` sin decisión `skip`, o un error de infraestructura
     o concurrencia con resultado conocido (E/S como `storage_io_failed`,
     `write_lock_busy`, `store_root_divergence`, `store_identity_changed`,
     `write_plan_base_changed`, `transaction_*`) → borra el marcador, deja
     `pending/` intacto, aborta e informa `drain_error`;
   - `committed: null` / `outcome_unknown` (p. ej. `current_reread_failed`)
     → **conserva marcador y `pending/`**, aborta e informa
     `outcome: "unknown"`; lo resuelve el paso 0 del vaciado siguiente
     (medido: cierra `committed` y deja un solo record).
   Ninguno de estos códigos va a `rejected/`.

`remember` vacía como máximo un lote, y ese lote incluye su propia entrada
(se arma primero el lote de su stream y operación con ella dentro).
`remember-result-v1` cubre todos los desenlaces, con el nombre de la
entrada:

| Desenlace de su entrada | Respuesta |
|---|---|
| comprometida | `committed` y revisión |
| rechazada | `rejected`, código (`inbox_entry_unsafe`, `remember_policy_skip` con `reason_codes`, `remember_id_collision`, `supersedes:duplicate_target`, `invalid_supersede_target`, …) |
| `write_lock` ocupado | `queued` |
| vaciado abortado con resultado conocido | `queued` + `drain_error: <código>` |
| resultado desconocido | `queued` + `outcome: "unknown"` |

Reintentar es idempotente: mismo texto, `kind` y target dan la misma clave
y el mismo id, y el paso 4 deduplica, así que reintentar tras `queued`,
`drain_error` u `outcome: "unknown"` nunca duplica. `inbox drain` vacía lotes sucesivos
hasta dejar `pending/` vacío o agotar un presupuesto de tiempo, soltando el
candado entre lotes. Las lecturas no vacían ni informan de la bandeja.
`inbox status` (sólo lectura) informa `pending`, `inflight`, `rejected`
(con motivo por entrada), `tmp` e `ignored` (nombres de `pending/` e
`inflight/` que no son entrada ni marcador); las respuestas de `remember` e `inbox drain` incluyen los
rechazos que produjeron. `rejected/` no se borra sola: es evidencia, y se
declara. La bandeja no tiene cuota total: un `pending/` que crece sin vaciar
es un límite declarado (cada entrada ≤ 64 KiB de texto).

**Commit desde el vaciado.** El vaciado compromete con
`_commit_write_plan_locked` (sección «Commit con el candado tomado») y
comparte su post-proceso. En este camino, a la defensa de `_assign_records`
se suma la deduplicación del paso 4, también bajo el candado.

**La bandeja no es estado durable del store.**

1. `memory/inbox/` se añade a los prefijos excluidos de `_files`
   (`export_restore.py:82-98`) **después** de los chequeos de enlace y de
   archivo especial: su contenido no se exporta, sella ni reubica, pero un
   enlace o hardlink plantado ahí sigue haciendo fallar la orden.
2. `export create`, `--seal sealed-export/v1` y `relocate commit` (ida y
   `--back`) toman el candado de bandeja en **exclusivo** al principio de la
   orden (antes del `mkdir` del bundle, `export_restore.py:121`, y antes de
   `identity_lock`) y exigen `pending/` e `inflight/` vacíos (sin entradas
   ni marcadores, en el sentido de «Directorios»); si no, fallan
   con `inbox_pending` o `inbox_inflight` (pista: `inbox drain`) sin crear
   nada. Con el orden journal → entradas → marcador no es alcanzable un
   marcador con `pending/` vacío y journal abierto; exigir `inflight/`
   vacío es defensa en profundidad. `relocate plan`
   no lo exige: el plan ya excluye la bandeja y `commit` revalida. El
   exclusivo cierra la carrera con un encolado concurrente.
3. `memory/inbox/` se añade a `_KEPT_PREFIXES` de
   `project_anchor_residue` (`relocate.py:52, 276-286`): tras `relocate commit`
   el `.lock` y `rejected/` que queden en el ancla de origen no cuentan como
   residuo de custodia en `doctor`.
4. `compact` no borra `memory/inbox/` porque sus `_RULES`
   (`compaction_inventory.py:17-30`) no casan esa ruta, no por la
   precondición de export.
5. Un store sin `memory/inbox/` recorre exactamente el camino de hoy. Para
   un store que ya tuviera algo en esa ruta antes de esta decisión, `export`
   y `relocate` pasan de `export_unrecognized_durable_path` a la regla
   nueva: es la única variación observable de órdenes existentes, forma
   parte de D1 y se declara.

### D2 — Escritor C0 y hora de encolado en un sobre dentro del record

Cada record que escribe `remember` lleva una clave reservada:

```json
"an_kla_envelope": {
  "schema": "an-kla/record-envelope-v1",
  "writer": {"schema": "memoria/identidad/v1", "repo": {…}, "agent": {…}, "session": {…}},
  "enqueued_at": "2026-11-14T18:30:00.123456Z",
  "time_source": "host-clock/v1",
  "idempotency_key": "sha256:…",
  "kind": "fact"
}
```

- **Sin segmento v2 ni `revision-v4`.** El sobre es una clave más del
  record; los stores existentes no se migran y se leen igual.
- **Hora.** `enqueued_at` es el reloj del host en UTC en el momento en que
  `remember` acepta la petición, antes de cualquier cola o commit (con D1,
  al encolar), declarado `host-clock/v1`: una observación, no un sello. Una entrada puede
  comprometerse después; **la hora de commit (por record o por revisión)
  sigue sin registrarse** y queda para otra decisión. El orden del vaciado
  (nombre de archivo) no es orden causal entre relojes distintos.
- **Quién lo rellena.** Sólo `remember`, desde el entorno, conforme a C0
  `8fccbcc`:
  - `repo.id` por la derivación exacta de C0 (casos 1, 2 —incluidos
    `file://` y remotos que son rutas locales— y 3); `repo.branch` del
    checkout, ausente si `HEAD` está desacoplado. Exige un repo Git; sin él,
    `remember` falla con `identity_repo_unavailable` y la pista de usar la
    receta `plan-write` (que sigue funcionando sin Git). La versión mínima
    de Git la fija la implementación y la comprueba al arrancar;
  - `agent.name`, `agent.cli`, `agent.model`, `agent.role` y `session.id`
    de variables que fija el lanzador (`AN_KLA_AGENT_NAME`,
    `AN_KLA_AGENT_CLI`, `AN_KLA_AGENT_MODEL`, `AN_KLA_AGENT_ROLE`,
    `AN_KLA_SESSION_ID`), con los centinelas de C0: `sin-nombre`,
    `desconocido` (modelo y rol) y `<cli>:sin-sesion`;
  - `AN_KLA_SESSION_ID` trae sólo el identificador del CLI; la herramienta
    compone `session.id = <agent.cli>:<identificador>`;
  - `agent.cli` es obligatorio: sin él, `identity_env_missing` y no se
    encola nada. Un valor presente que viola C0 (nombre fuera del patrón,
    rol fuera del enum, rama inválida) falla con `identity_env_invalid` y
    el campo culpable; nunca se corrige ni se sustituye por un centinela.
- **Validación.** an-kla implementa su propio validador C0. Los vectores de
  C0 `8fccbcc` se copian al repo con su digest
  (`a169a7f93728f327f2f47282b339ff8a2b4fc1f0e9cd383a6afe7f6441a92643`).
- **Alcance aceptado.** El formato del sobre, el validador, la derivación
  y la construcción desde el entorno se implementan sin llamante. Escribir
  el sobre en un record llega con `remember`, que sigue el estado de D1.
- **Protección del sobre.** `plan-write` no cambia: un caller puede escribir
  a mano un `an_kla_envelope`. El sobre es aserción, como C0. Endurecer
  `plan-write` cambia el `policy_fingerprint` y queda como decisión aparte
  del maintainer.

### D3 — Sustitución ajena convertida en disputa

`remember --supersedes <id>` se resuelve bajo `write_lock`, al planificar el
commit del record (con D1, en el paso 3 del vaciado). Lo que esta sección
acepta es la regla. Los destinos que nombra (`rejected/`, «queda en cola»)
son los de D1 y siguen su estado. El código de D3 no entra en `main` antes
que D1 («Partición del estado»).

- **Target.** Se busca el id en los tres streams del snapshot. Ausente o no
  vigente → la entrada va a `rejected/` con `invalid_supersede_target`.
  Presente en más de un stream → `rejected/` con
  `remember_target_ambiguous`. El record nuevo va al stream del target. Si
  `--kind` se omitió, se toma el del target (o el que corresponde a su
  stream si es legado); si se dio explícito y su stream no es el del target
  → `rejected/` con `remember_kind_mismatch`.
- **Propia** → `supersede` normal (ADR-0019): el anterior queda
  `sustituida`. Es propia si el target tiene `an_kla_envelope` y su
  `writer.repo.id` y `writer.agent.name` coinciden con los del escritor
  actual, y ese nombre no es `sin-nombre`. La unidad de identidad es el
  **nombre de agente**, no la sesión: un agente que reanuda en otra sesión
  sigue siendo dueño de sus hechos. **Requisito del lanzador:** dos agentes
  activos a la vez sobre el mismo repo no comparten `agent.name`. Si se
  incumple, se tratan como el mismo escritor y uno puede sustituir lo del
  otro sin disputa; queda auditable por `session.id` en el sobre (límite
  declarado, verificado por el criterio 4).
- **Ajena, legada sin sobre o con `sin-nombre`** → `add` de un record nuevo
  con `"disputes": {"stream", "target_id", "target_record_sha256"}`, donde
  `target_record_sha256 = digest_json(snapshot.raw_records[stream][i])`
  (el record canónico **antes** de overlays: el mismo selector de
  ADR-0026; nunca sobre `snapshot.records`, que lleva `status`
  proyectado). El original sigue vigente. Una disputa es un `add`: no
  escribe `supersedes_map` ni `refutations_map` y no puede disparar
  `manifest_lifecycle_overlay_conflict`.
- **Visibilidad.** Si el vaciado ocurre en la misma invocación, la respuesta
  de `remember` declara `"disputed": {…}` o `"superseded": …`; si queda en
  cola, `"resolution": "pending"`. `disputes list [--target <id>]` (sólo
  lectura) enumera las disputas vigentes. Su anotación en la recuperación
  pertenece a la orden nueva de recuperación de hechos (E1.b, C4a);
  `retrieve` no cambia.
- El camino `plan-write … supersede` no cambia: un `model_derived` sigue
  pudiendo sustituir un hecho ajeno por esa vía. D3 cierra el agujero sólo en
  `remember`.

### Idempotencia

`idempotency_key` = la dada o `sha256(canonical_json({"repo": repo.id,
"agent": agent.name, "session": session.id, "kind": kind, "text": text,
"supersedes": target_id o null}))`. `record.id = <prefijo> + "-r-" + 24 hex
de la clave`, con prefijo `facts→f`, `events→e`, `episodes→ep`
(`store.py:67`). Mismo texto con otro target es otra intención y otro id.

## Modelo de amenaza

Agentes **honestos pero falibles** en una máquina de un solo usuario del
sistema; todos los procesos pueden leer y escribir el store.

| Amenaza | Dentro o fuera | Tratamiento |
|---|---|---|
| Un agente declara la identidad de otro (suplantación) | **Fuera, declarado** | Sobre y C0 son aserciones guardadas tal cual; no prueban autoría. La memoria sigue siendo no autoritativa |
| Un sobre falso escrito a mano vía `plan-write` | Fuera, declarado | Igual; endurecer `plan-write` es decisión aparte |
| Dos escritores honestos se pisan | **Dentro** | D1: planificación y CAS bajo el mismo candado |
| Corte brusco o de energía al encolar o vaciar | **Dentro** | fsync en `tmp/` antes de publicar; nada sale de `pending/` sin `committed: true`; reconciliación de journals (paso 0); deduplicación por clave y `payload_sha256` |
| Una entrada mala bloquea toda la escritura (corrupta, no regular, FIFO, `skip`, error terminal) | **Dentro** | D1 pasos 2, 4, 5 y 7: `rejected/` con motivo, prevalidación por entrada y aislamiento sin soltar el candado; el resto se compromete |
| El vaciado toma el temporal de un encolado en curso | **Dentro** | Temporales en `tmp/`; sólo cuentan los nombres completos de `pending/` |
| Una entrada se pierde en `export`/`relocate` o en un ancla abandonada | **Dentro** | Preflight de custodia antes y después del candado de bandeja; exclusivo y `inbox_pending` en `export` y `relocate commit` |
| `pending/` crece sin vaciar hasta llenar el disco | Dentro, límite declarado | Sin cuota total; ≤ 64 KiB por entrada; `inbox status` lo hace visible |
| Un agente honesto desactiva por error el hecho de otro | **Dentro** | D3: disputa |
| Dos agentes sin nombre o con el mismo nombre | Dentro, límite declarado | `sin-nombre` nunca es dueño; nombres repetidos = mismo escritor |
| Contenido del recuerdo visible en `argv` | Dentro, declarado | `--text-file -` recomendado; `--text` lo expone a `ps` y al historial |
| Bandeja leída por otro proceso del usuario | Fuera | Igual que el store: JSON en claro bajo el mismo usuario |
| Texto recuperado tomado como instrucción | Dentro (sin cambio) | Las salidas nuevas llevan el marcador de dato no confiable vigente |

**Relación con #58 (G4).** Cierra sólo la parte «identidad declarada
guardada»: el escritor queda registrado, auditable y filtrable. No cierra
namespaces, aislamiento multi-scope, divulgación entre agentes ni identidad
verificada, y no usa la identidad como permiso: la distinción propia/ajena
sólo elige entre sustituir y disputar, nunca concede escritura. #58 sigue
abierto. Respecto de #197 no cierra G1 (firma), G5 (CAS por objeto) ni G6
(tiempo de commit).

## Criterios de aceptación

1. **Una llamada.** Guardar es una invocación de CLI cuyo único dato
   obligatorio es el texto; el record lleva sobre con `writer` válido según
   C0 `8fccbcc` y `enqueued_at`; y `retrieve --query <palabra del texto>`
   devuelve ese texto.
2. **Concurrencia.** 8 procesos, 200 `remember` en total con textos únicos,
   mientras otro proceso ejecuta `inbox drain` en bucle, y un `inbox drain`
   final: 200 records distintos, 0 perdidos, 0 duplicados, `pending/`,
   `rejected/` y `tmp/` vacíos, `verify` ok, **0 conflictos CAS**
   (`write_plan_base_changed`) en el camino nuevo, 0 `write_lock_busy` en
   `inbox drain` con un solo vaciador (con dos, la respuesta `queued` del
   que encuentra el candado ocupado es correcta), 0 errores de encolado; se
   reportan el p95 de `remember` y el número de respuestas `queued`.
3. **Corte brusco.** `kill -9` real, al menos 20 repeticiones por punto, en
   ocho puntos:
   1. tras el fsync en `tmp/` y antes de publicar en `pending/`;
   2. tras escribir el marcador y antes del journal `prepared`;
   3. tras escribir objetos y antes de `_replace_current`;
   4. tras `_replace_current` (`transactions.py:687`) y antes del recibo
      `current-durable`;
   5. con los recibos escritos y antes del journal `committed` (`:725`);
   6. tras el journal y antes de borrar `pending/`;
   7. a medio borrar `pending/`;
   8. con las entradas borradas y el marcador vivo.

   Tras la **siguiente invocación de escritura** (`remember` o `inbox
   drain`) se exige:
   - 0 perdidos sobre entradas confirmadas (`queued`) y 0 duplicados;
   - `verify` ok;
   - 0 journals de la bandeja con `stage != committed` cuyo candidato sea
     `CURRENT` o ancestro suyo;
   - 0 `durability_incomplete` residuales (el paso 0 repara);
   - 0 marcadores, `pending/` y `tmp/` vacíos;
   - y una tercera invocación que no se atasca.
4. **Disputa.** Con variables de lanzador distintas, A disputa un hecho de B:
   el de B sigue vigente (`is_active`); el record de disputa lleva el
   `target_record_sha256` de `raw_records` y aparece en la respuesta de
   `remember` y en `disputes list --target`. Controles: A sustituye uno suyo
   y el anterior queda `sustituida`; target legado sin sobre → disputa; con
   `AN_KLA_AGENT_CLI` pero sin `AN_KLA_AGENT_NAME` (`sin-nombre`) → disputa
   incluso sobre lo propio; dos sesiones distintas con el mismo
   `agent.name` → se sustituyen sin disputa y el sobre registra las dos
   `session.id` (límite declarado, verificado); mismo texto con dos targets
   → dos records.
5. **Compatibilidad.** Un store **sin `memory/inbox/`** creado con
   `v0.1.0-beta.35` (fixture versionado, abierto desde una ruta absoluta
   fija) da, antes y después, el
   mismo `sha256` de salida en `status`, `verify`, `inventory`, `retrieve`,
   `resume`, `assemble-context` y las herramientas MCP; para `export`, el
   mismo `manifest_sha256` y digests de entradas del bundle;
   `policy_fingerprint` sin cambio; `capabilities`, `schema list` y `--help`
   sólo añaden entradas; `tools/list` del MCP no cambia.
6. **Lecturas puras.** Con entradas en `pending/`, tras cada lectura,
   `CURRENT` y el listado recursivo `(ruta, tamaño, mtime_ns, sha256)` de
   `memory/inbox/` son idénticos a los de antes.
7. **Bandeja y custodia.** Con `pending/` no vacío, `export create`,
   `--seal sealed-export/v1` y `relocate commit` (ida y `--back`) fallan con
   `inbox_pending` y el destino del bundle no existe; `relocate plan` pasa;
   tras `inbox drain` todo pasa y el bundle no contiene `memory/inbox/`; un
   enlace simbólico bajo `memory/inbox/` sigue dando `export_unsafe_link`;
   un `remember` concurrente con `relocate commit` acaba en `pending/` del
   store resultante o falla con `inbox_busy`, `store_root_divergence` o
   `store_identity_changed`, y nunca deja una entrada en un ancla
   abandonada; tras `relocate commit`, `doctor` informa
   `project_local_residue: 0`.
8. **Lote y entradas malas.** `inbox drain` con 1000 pendientes y sobre C0
   completo termina con `pending/` vacío en varios commits, sin
   `invalid_write_proposal` ni `invalid_write_plan`. Con, a la vez, una
   entrada corrupta, un FIFO, un enlace simbólico y un directorio en
   `pending/`, dos entradas con la misma clave y el mismo payload, dos con
   la misma clave y payload distinto, una con target inexistente y una que
   la política rechaza con `skip`: el vaciado no se bloquea; corrupta, FIFO
   y enlace van a `rejected/` (`inbox_entry_unsafe` o su motivo), el
   directorio se ignora, la duplicada se compromete una vez, la colisión va
   a `rejected/` con `remember_id_collision`, la del target con
   `invalid_supersede_target`, la del `skip` con `remember_policy_skip`, y
   las demás se comprometen; se reporta el tiempo máximo con `write_lock`
   tomado en un intento. Además, dos entradas `--supersedes` sobre el mismo
   target: la más antigua se compromete y la otra va a `rejected/` con
   `supersedes:duplicate_target`. Y un lote de 250 con un fallo de par que
   el prefiltro no ve: la bisección por prefijos usa ≤ 8 evaluaciones y los
   demás se comprometen en un solo lote.
9. **Orden de candados.** Prueba negativa: ningún camino pide el candado de
   bandeja teniendo `identity_lock` o `write_lock` (instrumentación del
   orden en test).
10. **Extracción neutra.** Antes de tocar `write_commit.py`, en un commit
    propio, goldens diferenciales generados con el código de `main` (add,
    lote, supersede válido y a target ausente, `skip`, CAS sin
    `transaction_id`, replay comprometido y no comprometido, `tool_observed`
    sin recibo, record sin texto indexable, `release_error` al soltar el
    candado), con resultado y árbol del store. Después de la extracción
    coinciden byte a byte. Las pruebas existentes de `write_commit` no se
    modifican. `_commit_write_plan_locked` llamado con el candado tomado no
    da `write_lock_busy` y produce el mismo resultado que la envoltura.

Los criterios 1–4 y 6–9 se exigen al implementar D1 y D3, y pueden
cambiar con el PR que acepte D1. En la fase A sólo se exigen el 5
(goldens, sin bandeja), el 10 y las pruebas del validador C0.

## Deuda de r4 y spike de recuperación

La deuda que dejó la ronda r4 se resolvió con el spike de recuperación
(rama `spike/e1a-recuperacion`, que no se fusiona; acta en
`docs/planning/adr-0063-d1-spike-recuperacion-2026-11-14.md`). El texto de
D1 y los criterios 2, 3 y 8 ya la incorporan.

| ID r4 | Resolución en D1 | Evidencia del spike |
|---|---|---|
| H3 | Prefiltro de target repetido en el paso 4 y bisección por prefijos en el paso 7 | Por mitades: `unattributable_pairwise` en 3 evaluaciones; por prefijos: 8 evaluaciones, 21,7 ms con 250, y 249 comprometidas en un lote |
| H4 | Paso 0 con tres ramas; `None` sin rastro borra el marcador y cualquier otro `None` aborta | `None` aparece en el corte más simple, marcador sin journal. La regla de r4 atasca el vaciado 20 veces de 20; la del texto, 0 |
| H5 | «Cierre del journal» propio y `repair_durability` | La ruta de replay deja el journal intacto, byte a byte. Con ella quedan journals abiertos con candidato `CURRENT` en 40 de 40 cortes; con el cierre, 0 de 160 |
| H6 | Tabla de `remember-result-v1` | Siete desenlaces provocados; el reintento tras `outcome_unknown` deja un solo record |
| H7 | `lstat` previo, sufijo regenerado, sin `os.link` | `os.replace` sobrescribe en silencio; `lstat` cuesta lo mismo (0,244 ms frente a 0,236 de p50); `link` muestra `st_nlink == 2` |
| H8 | `inflight/` vacío exigido (`inbox_inflight`) e informado | El escenario de r4 no es alcanzable con el orden journal → entradas → marcador |
| `tmp/` | Recolector por candado exclusivo, sin reloj | 20 huérfanos de 20 recogidos; con un encolador vivo, 0 borrados |

Cifras globales, con la configuración del texto:

- **Cortes:** 160 `kill -9` reales (8 puntos × 20), con 0 perdidos, 0 duplicados y `verify` ok.
- **Concurrencia:** 8 clientes con 200 encolados, 0 conflictos CAS, 0 `write_lock_busy` con un vaciador y p95 de encolado de 10,7 ms.
- **Con `kill -9` aleatorio:** 2000 encolados, 0 perdidos y 0 duplicados.
- **Candado:** entre 0,041 y 0,064 s con `write_lock` tomado por lote
  **limpio** de 250. La bisección por prefijos añade 21,7 ms sobre 250 sin
  soltar el candado (≈ 0,086 s en un lote que bisecciona). El máximo
  observado en toda la campaña fue 0,203 s, en el escenario de `kill -9`
  aleatorio, donde cada vaciado tras una muerte ejecuta además el paso 0
  (cierre, reparación y borrado). El último recurso uno a uno no se
  midió.

**Sin ejercitar en el spike.** La implementación debe probarlo:

- el último recurso uno a uno, con su marcador por commit y un corte en
  cada uno;
- el aviso `inbox_audit_incomplete` y `ignored` de `inbox status`;
- el movimiento real a `rejected/` y `remember_id_collision`;
- D3 de extremo a extremo;
- el orden de candados, con prueba negativa;
- plataformas sin `flock`;
- `export`/`relocate` reales con la regla de `inflight/`;
- `lock_result.release_error`;
- EXDEV y ENOSPC reales, que sólo se inyectaron;
- un corte de energía (`kill -9` no descarta la caché de páginas);
- el coste del paso 0 con miles de revisiones.

## Por qué no

- **Reintento sobre el CAS actual.** Mantiene la planificación fuera del
  candado: la causa medida del 72 %.
- **Demonio escritor.** Exige instalar y mantener un servicio y rompe «an-kla
  funciona sola».
- **MCP escribible en E1.a.** Reemplaza parcialmente ADR-0003 y cambia una
  propiedad de seguridad del servidor (`an-kla-read`); la CLI basta para
  «una llamada». Se decide en E1.c con su propio ADR.
- **Que las lecturas vacíen la bandeja.** Convierte lecturas en mutadores y
  rompe la compatibilidad y ADR-0047 §4.
- **`refute` para la sustitución ajena.** Desactiva el original y requiere
  autoridad privilegiada (ADR-0026).
- **Resolver propia/ajena al encolar.** El estado del target puede cambiar
  antes del vaciado; resolver bajo el candado es la regla de ADR-0019.
- **Segmento v2 o `revision-v4`.** Toca validación de revisiones,
  recorridos, compactación, export y sellado, y abre una migración
  innecesaria: el record ya admite la clave.
- **Endurecer `plan-write` ya.** Cambia el `policy_fingerprint` y no protege
  contra suplantación, que está fuera de alcance.
- **Bandeja fuera de la custodia.** Ensucia `git status` del consumidor
  (ADR-0031 §7) y no viaja con la bóveda.
- **Exportar o trasladar la bandeja en `relocate`.** Mezclaría en el bundle
  estado no revisado por la política; trasladar archivos entre volúmenes
  añade otra ventana de pérdida. Vaciar antes es más simple y verificable.
- **Identidad por sesión en D3.** Un agente que reanuda perdería la
  propiedad de sus hechos y todo se volvería disputa.

## Consecuencias

- Positivas: guardar cuesta una invocación; 0 conflictos CAS en el camino
  nuevo; escritor y hora de encolado auditables; un agente ya no silencia a
  otro por `remember`; los stores existentes no se migran.
- Negativas: dos caminos de escritura conviven (`plan-write` sigue
  permitiendo la sustitución ajena); el sobre es aserción; la hora de commit
  no se registra; `remember` exige Git; `rejected/` crece sin GC; `export`
  y `relocate` ganan la precondición `inbox_pending` cuando hay bandeja; el
  código toca `export_restore.py`, `relocate.py`, `relocate_back.py`,
  sellado y `write_commit.py` (extracción sin cambio de comportamiento)
  además de los módulos nuevos; el vaciado retiene el candado de los demás
  durante su lote (≤ 0,2 s medidos con 250 entradas sobre 20.000 records
  sin prevalidación; el spike midió entre 0,041 y 0,064 s por lote limpio
  de 250 y, aparte, 21,7 ms de bisección por prefijos sobre 250, y un
  máximo de 0,203 s con el paso 0 bajo `kill -9` aleatorio; el último
  recurso uno a uno queda fuera de esas cifras).
- Neutras: la receta del bloque gestionado no cambia en E1.a (llega en
  E1.c, con el MCP escribible); la anotación de disputas en la recuperación
  llega en E1.b.

## Test de regresión

- `tests/test_identity_c0.py`: vectores de C0 `8fccbcc` y comprobaciones
  de derivación; dos worktrees del mismo repo dan el mismo `repo.id`;
  control negativo.
- `tests/test_write_commit_locked_extraction.py`: criterio 10.
- `tests/test_inbox.py`: atomicidad, orden, `queued`, deduplicación,
  `remember_id_collision`, `rejected/`, `inbox status`.
- `tests/test_remember_concurrency.py`: criterio 2.
- `tests/test_inbox_crash.py`: criterio 3.
- `tests/test_remember_dispute.py`: criterio 4.
- `tests/test_legacy_store_byte_identity.py`: criterios 5 y 6.
- `tests/test_inbox_custody.py`: criterio 7.
- `tests/test_inbox_batch_limits.py`: criterio 8.
- `tests/test_inbox_lock_order.py`: criterio 9, más la prueba de plataforma
  del candado de bandeja.
- Pruebas existentes de `write_commit`, export, sellado y `relocate` sin
  cambios y en verde.
- Escenario de escala nuevo en `benchmarks/scale/` (8 escritores).

## Referencias

- Issues: #58 (G4, sólo identidad declarada guardada), #197 (contexto; no
  cierra G1, G5 ni G6), #169 (disparador de caché, a medir).
- ADR-0003 (MCP de sólo lectura), ADR-0019 (supersede), ADR-0024 (outcome
  y replay por `transaction_id`), ADR-0026 (refute), ADR-0031 (G4
  diferido; huella Git), ADR-0047 (lecturas planas sin escritura; MCP
  read-only), ADR-0048 (custodia), ADR-0054 (lote v2), ADR-0060
  (planificación coherente).
- C0 `memoria/identidad/v1`: `aria/coordination`, `main@8fccbcc`.
- Spike de E1.a (sólo lectura, 2026-11-14) y ronda adversarial:
  `docs/planning/adr-0063-e1a-adversarial-2026-11-14.md`.
- Delegación: `docs/gobernanza/2026-11-14-delegacion-memoria-agentica.md`.
