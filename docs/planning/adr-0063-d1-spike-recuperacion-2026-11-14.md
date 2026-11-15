# Spike de recuperación del vaciado (D1 del ADR-0063), 2026-11-14

Acta del spike que pidió el orquestador (mandato 4, B2) para cerrar la
recuperación tras corte de D1 con evidencia, no en papel. Prototipo en la
rama `spike/e1a-recuperacion` (no se fusiona; `an_kla/` sin cambios). Cifras
crudas fuera del repo: `/var/tmp/orquestador-memoria/capitanes/ankla/faseA/datos-B2/`.
El texto corregido de D1 está en el ADR. Abajo, el informe íntegro del
ejecutor (Claude Sonnet).

---


Ejecutor: Claude Sonnet (B2). Rama `spike/e1a-recuperacion` (prototipo, **no se fusiona**), worktree
`/Users/krisnova/.herdr/worktrees/an-kla-memory/spike-recuperacion`. `an_kla/` no se tocó (`git diff main -- an_kla` vacío);
todo el código está en `spikes/e1a_recovery/`. Cifras crudas: `/var/tmp/orquestador-memoria/capitanes/ankla/faseA/datos-B2/`.
Los stores del spike (`/var/tmp/ankla-spike-b2/`) se borraron al terminar; no queda ningún proceso vivo.

Estado: **OK** (spike completo; límites en §6). Entregable hermano: `D1-redaccion-corregida.md`.

## 0. Respuestas en una página

| Pregunta | Respuesta medida |
|---|---|
| ¿Se pierde o duplica algo con `kill -9` en los cuatro puntos del criterio 3? | **No**, con el paso 0 corregido: 20/20 muertes reales por punto, 0 perdidos, 0 duplicados, `verify` ok 20/20. |
| ¿Basta el paso 0 **tal como lo escribe el ADR**? | **No.** Deja el journal abierto con candidato `CURRENT` en 40/40 corridas de los dos cortes entre `_replace_current` y el journal `committed` (viola el criterio 3), y la variante de r4 (`None` ⇒ abortar) **bloquea el vaciado para siempre** con un corte tras escribir el marcador (20/20 atascadas, 100 entradas confirmadas sin comprometer). |
| ¿8 clientes concurrentes? | 200/200 comprometidos, 0 perdidos, 0 duplicados, **0 conflictos CAS**, 0 `write_lock_busy` con un vaciador; con `kill -9` aleatorio (10 corridas, 44 muertes, 2000 encolados) 0 perdidos/0 duplicados. |
| H3 | La bisección **por mitades no aísla** `supersedes:duplicate_target` (par). Sirve la bisección **por prefijos** (8 evaluaciones, 22 ms con 250) o, mejor, un prefiltro O(n) en el paso 4. |
| H4 | `committed: None` **no es exótico**: sale en el corte más común (marcador escrito, journal `prepared` aún no). Regla: `None` ⇒ «nunca empezó» (borrar marcador) sólo si no hay journal, ni candidato, ni `transactions/<txid>/`; si no, conservar y abortar. |
| H5 | Ninguna ruta actual cierra el journal. `_commit_locked` retorna sin escribir (medido: el journal no cambia). `_reconcile_committed_journal` sirve con un `planning` sintético pero es privada de compaction y no enlaza recibos. Cierre implementado y probado; el estado honesto tras el corte entre `_replace_current` y el recibo es `committed` en el journal + **`durability_incomplete` en `inspect_transaction`**, que `repair_durability` convierte en `committed`. |
| H6 | Tabla de 7 desenlaces en §3.4. |
| H7 | **Sí**, `os.replace` sobrescribe un nombre plantado en silencio. `lstat` previo lo evita al mismo coste (0,24 ms). `os.link`+`unlink` **no sirve**: duplica el coste y deja `st_nlink == 2` visible al vaciado (12 de 166 796 lecturas con 1500 encolados; con `replace`, 0 de 139 870). |
| H8 | El escenario del revisor es **inalcanzable** con el orden journal → entradas → marcador (todo corte con `pending/` vacío y marcador vivo tiene el journal `committed`). Aun así: exigir `inflight/` vacío es barato y quedó probado. |
| `tmp/` huérfano | Recolector **por candado** (`flock` exclusivo no bloqueante, sin reloj): sin carrera. El de antigüedad tiene carrera que falla visible (`ENOENT` en `os.replace`), no pierde en silencio. |
| ¿La extracción puede seguir siendo neutra? | **Sí**, con tres precisiones (§4). |

## 1. Cuatro puntos de corte con `kill -9` real

Método: hijo `python -m spikes.e1a_recovery.worker` que se mata a sí mismo con `SIGKILL` (`os.kill(getpid(), SIGKILL)`) en el
punto (`SPIKE_CUT=<punto>`); `returncode == -9` en 20/20 de cada punto. Cada repetición: store nuevo, 5 entradas confirmadas
(`queued`), un vaciado muerto en el punto, luego **dos** invocaciones de vaciado limpias (la 2.ª es «la siguiente invocación
de escritura»; la 3.ª comprueba que no queda atascado). Se mide en un proceso aparte: perdidos (confirmadas y ausentes del
snapshot), duplicados (texto con >1 record), `verify`, journals (por `stage`, y los abiertos cuyo candidato es `CURRENT`),
marcadores, `pending/`, `tmp/`.

Puntos: (i) `enq_tmp`; (ii) `pre_replace_current`; (iii-a) `post_replace_current` (entre `_replace_current` y el recibo
`current-durable`); (iii-b) `pre_committed_journal` (recibos escritos, journal `committed` no); (iv) `post_journal`. Extras que
el mandato no pedía y que resultaron decisivos: `post_marker` (marcador escrito, journal `prepared` no), `mid_delete`
(a medio borrar `pending/`), `post_entries_deleted` (entradas borradas, marcador vivo).

**Configuración D (paso 0 del spike), 20 repeticiones por punto — 160 muertes reales:**

| Punto | muertos | perdidos | dupl. | `verify` ≠ ok | journal abierto con candidato CURRENT | `committed` con `durability_incomplete` | marcadores | pending | tmp (antes → después) |
|---|---|---|---|---|---|---|---|---|---|
| (i) `enq_tmp` | 20/20 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | **20 → 0** |
| (ii) `pre_replace_current` | 20/20 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 → 0 |
| (iii-a) `post_replace_current` | 20/20 | 0 | 0 | 0 | 0 | **20** | 0 | 0 | 0 → 0 |
| (iii-b) `pre_committed_journal` | 20/20 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 → 0 |
| (iv) `post_journal` | 20/20 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 → 0 |
| `post_marker` | 20/20 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 → 0 |
| `mid_delete` | 20/20 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 → 0 |
| `post_entries_deleted` | 20/20 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 → 0 |

- «Perdidos» cuenta sólo entradas **confirmadas** (`queued`). En (i) la entrada del encolador muerto nunca se confirmó y nunca
  llegó a `pending/`: queda un huérfano en `tmp/` (20 de 20), que recoge el recolector por candado. El criterio 3 sólo puede
  sostener «0 perdidos» sobre lo confirmado, como dice la deuda heredada.
- (iii-a) deja `committed` con `durability_incomplete`: el corte ocurrió antes del recibo `current-durable`, y el cierre no lo
  fabrica (patrón `compaction.py:437-440`). La configuración **E** (D + `repair_durability` en el paso 0) lo deja en `committed`
  completo: 0 en las 160 corridas (`cuts-E_spike_repair.json`).

**Las tres variantes del paso 0 que sólo difieren en el cierre y en la rama `None` (mismas 20 repeticiones por punto):**

| Config. | cierre (`True`) | rama `None` | Resultado |
|---|---|---|---|
| A — ADR literal | ruta de replay (no escribe) | borra marcador | **journal abierto con candidato CURRENT: 20/20 en (iii-a) y 20/20 en (iii-b)** ⇒ criterio 3 incumplido. El resto, igual que D. |
| B — prescripción r4 sin cierre | ruta de replay | conserva y aborta | lo de A **y** `post_marker`: **20/20 atascadas**, 100 entradas confirmadas sin comprometer, la 3.ª invocación sigue abortando (`transaction_transaction_evidence_missing_or_invalid`). |
| C — r4 con cierre | escribe journal `committed` | conserva y aborta | cierra bien (iii-a/iii-b), pero **mismo atasco** en `post_marker` (20/20; `pending` = 100). |
| D — spike | escribe journal `committed` | `never_started` ⇒ borra; si no, aborta | 0 fallos en las 160. |
| E — D + `repair_durability` | ídem + repara | ídem | 0 fallos y 0 `durability_incomplete`. |

Datos: `datos-B2/cuts-*.json`, resumen `datos-B2/matriz-cortes-resumen.txt`.

## 2. Ocho clientes concurrentes

200 `remember` = 8 procesos × 25 textos únicos; un proceso vaciando en bucle; vaciado final. (Cifras de la bandeja con
`_mutation_preflight_with_context` activo en cada encolado, antes y con el candado de bandeja tomado.)

| Escenario | acked | comprometidos | perdidos | dupl. | CAS (`write_plan_base_changed`) | `write_lock_busy` | p50 / p95 encolado | máx. con `write_lock` | residuo pending/tmp/inflight |
|---|---|---|---|---|---|---|---|---|---|
| 1 vaciador | 200 | 200 | 0 | 0 | **0** | 0 | 4,71 / 10,69 ms | 0,033 s | 0/0/0 |
| 2 vaciadores a la vez | 200 | 200 | 0 | 0 | 0 | **5** respuestas `queued` (el otro tenía el candado) | 3,63 / 8,37 ms | 0,055 s | 0/0/0 |
| 1 vaciador con `kill -9` aleatorio (10 corridas) | 2000 | 2000 | 0 | 0 | 0 | 0 | p50 3,55–12,72 ms; p95 máx. 20,42 ms | 0,203 s | 0/0/0 |

- `verify` ok en las 12 corridas. En las 10 con `kill`: 44 `SIGKILL` a un vaciador en bucle (2–8 por corrida).
- Los 5 `write_lock_busy` del segundo escenario son la respuesta `queued` de un vaciador al encontrar al otro con el candado
  (plazo 0): no se pierde nada. El criterio 2 (0 `write_lock_busy` en `inbox drain`) sólo vale con un vaciador.
- Lote de 250: tiempo con `write_lock` tomado **0,041–0,064 s** (1000 pendientes → 4 lotes de 250, 4 revisiones, `verify` ok;
  `datos-B2/probe-lockhold.json`).
- Límite honesto: el vaciador en bucle sólo registra su línea al volver de cada pasada, así que en varias corridas con `kill`
  `drain_calls = 0` y **no se puede afirmar cuántas muertes cayeron dentro de un commit**; la evidencia de recuperación por punto
  es la matriz de §1, no ésta. La carga completa dura ~0,5 s (no es carga sostenida).

## 3. Deudas, una por una

### 3.1 H3 — aislamiento y `supersedes:duplicate_target` (`datos-B2/probe-h3.json`)
Lote de 250 entradas `supersede` donde la 1.ª y la 250.ª sustituyen al mismo target (store con 250 hechos vigentes).
- El lote entero falla puro (0,33 ms): `invalid_write_proposal:supersedes:duplicate_target`.
- **Bisección por mitades (como el paso 7 del ADR): no aísla.** Tres evaluaciones, profundidad 1: el lote falla, ambas mitades
  pasan por separado ⇒ `unattributable_pairwise`. El fallo es entre dos entradas, ninguna lo causa sola. (Si el par queda en la
  misma mitad, ocurre igual un nivel después.) «≤ 8 niveles por entrada mala» no se cumple aquí: ni 1.
- **Bisección por prefijos** (acumular aceptadas; el prefijo más corto que falla señala la culpable): 8 evaluaciones puras,
  21,7 ms para 250; rechaza `s-dup`; los 249 supervivientes se comprometen en **un** lote (`committed`, 249 targets
  `sustituida`). Coincide con ⌈log₂ 250⌉ = 8 por entrada mala.
- **Prefiltro O(n) en el paso 4** (segundo target repetido ⇒ `rejected/` con `supersedes:duplicate_target`): 0,018 ms, y el
  lote restante pasa la evaluación. Es la solución barata; la bisección por prefijos queda para fallos de par no previstos.
- Aislamiento uno a uno bajo candado (último recurso del ADR): **no ejercitado** en el spike.

### 3.2 H4 — cuándo `committed` es `None` y qué hace el paso 0 (`probe-h4.json`)
`inspect_transaction` en estados provocados (cortes reales y datos plantados):

| Estado | `committed` | `state` | `operation_error_code` |
|---|---|---|---|
| (ii) antes de `CURRENT` | `False` | `not_committed` (candidato `orphan`) | `audit_incomplete` |
| (iii-a) tras `CURRENT`, antes del recibo | `True` | `durability_incomplete` | `audit_incomplete` |
| (iv) tras el journal | `True` | `committed` | — |
| (v) **marcador escrito, journal `prepared` no** | **`None`** | `outcome_unknown` | `transaction_evidence_missing_or_invalid` |
| journal corrupto, sin candidato | `None` | `outcome_unknown` | `transaction_evidence_missing_or_invalid` |
| dos manifiestos con el mismo `txid` | `None` | `outcome_unknown` | `transaction_candidate_ambiguous` |
| `read_current` falla al inspeccionar | `None` | `outcome_unknown` | `audit_incomplete` |

La fila (v) es la clave: es el corte **más simple de alcanzar** (cualquier muerte entre el `fsync` del marcador y la primera escritura de
`commit_locked`; no medí su frecuencia relativa) y da `None`. Por eso: ADR literal (`None` ⇒ borrar marcador) funciona ahí pero borraría también los otros tres
`None`; r4 (`None` ⇒ conservar y abortar) bloquea el vaciado para siempre en (v) (§1, config B/C). Regla del spike (`never_started`):
`None` y **sin journal, sin manifiesto candidato y sin `transactions/<txid>/`** ⇒ la transacción no dejó rastro (el journal
`prepared` es lo primero que escribe `commit_locked`, `transactions.py:532`) ⇒ borrar sólo el marcador; cualquier otro `None` ⇒
conservar el marcador y abortar con `transaction_*`. Efecto medido en `post_marker`: A «ok», B/C `DrainAbort` permanente,
D «ok» con `pending = 0` tras el siguiente vaciado.

### 3.3 H5 — cierre del journal (`probe-h5.json`)
Estado tras cada corte: journal `candidate_prepared`, `current_receipt: null`, `observed_log: null`.
- Corte (iii-a): recibos en disco = sólo `candidate-data-durable`. Corte (iii-b): ambos recibos, pero el journal no los enlaza.
- **Ruta de replay `_commit_locked`** (`transactions.py:505-508`): devuelve el resultado sin escribir; medido: el journal queda
  **byte a byte igual**. No cierra nada.
- **`compaction._reconcile_committed_journal`**: funciona si se le pasa un `planning` sintético (`proposal.transaction_id`,
  `proposal.base_revision`, `plan.core.candidate_revision`) y el `attempt` exacto; deja `stage: committed`. No enlaza los recibos
  existentes (`current_receipt` sigue `null`; `inspect` los encuentra de todos modos escaneando el directorio). Es privada de
  compaction (`CompactionError`, `planning`): reutilizarla acopla la bandeja a compaction.
- **Cierre del spike** (`close_committed_journal`): mismo patrón, sin `planning`; completa `intent`/`observed_commit` si faltan
  (idempotente: los objetos son content-addressed), **enlaza sólo recibos existentes y válidos** y nunca fabrica. Resultado
  (iii-b): `committed`, durabilidad `complete`, con ambos recibos enlazados. Resultado (iii-a): journal `committed`, pero
  `inspect_transaction` informa `durability_incomplete`; **`repair_durability`** (re-`fsync` de dependencias y de `CURRENT`, recibo
  `repair`) lo lleva a `committed`/`complete`. Segunda ejecución del cierre: `already_committed` (idempotente); `verify` ok.
- ¿Es honesto `durability_incomplete`? Sí como **estado de `inspect_transaction`**, derivado de los recibos. Pero el journal no
  tiene un `stage` con ese nombre (sólo `prepared`/`candidate_prepared`/`committed`); la redacción de r4 («el estado honesto del
  journal es `durability_incomplete`») debe decir: journal `committed`, resultado `durability_incomplete` hasta reparar.
  Recomendación: que el paso 0 llame a `repair_durability` (se tiene el candado; E: 0 `durability_incomplete` residuales).

### 3.4 H6 — desenlaces observados de `remember` y respuesta correspondiente (`probe-h6.json`)

| # | Desenlace provocado | Observado en el vaciado | `remember-result-v1` que corresponde |
|---|---|---|---|
| 1 | entrada comprometida | `committed`, `pending` vacío | `committed` |
| 2 | reintento del mismo texto | 1 solo record con ese texto (dedupe por clave) | `committed` o `queued`, idempotente |
| 3 | `write_lock` ocupado por otro proceso | `queued`, `lock_busy`, entrada intacta | `queued` |
| 4 | entrada con hardlink | `rejected: inbox_entry_unsafe`; las demás se comprometen | `rejected` + código + nombre de entrada |
| 5 | E/S falla antes de `CURRENT` (`_write_segment`) | `committed: false`, `storage_io_failed`; entrada intacta, 0 marcadores; el siguiente vaciado compromete | `queued` + `drain_error: storage_io_failed` |
| 6 | `CURRENT` escrito y no releíble | `committed: null`, `outcome_unknown`, `current_reread_failed`; marcador y entrada vivos; el siguiente paso 0 cierra (`committed`, `complete`) y queda 1 record | `queued` + `outcome: "unknown"`; reintento idempotente (1 record) |
| 7 | decisión `skip` de política | `skip`, `reason_codes: [derived_authority_capped, summary_required_for_authority_ceiling]` | `rejected` + `remember_policy_skip` + `reason_codes` |

`write_plan_base_changed` no aparece en ningún desenlace con el candado tomado (0 en 12 corridas concurrentes).

### 3.5 H7 — `os.replace` y nombre plantado (`probe-h7.json`)
Nombre plantado con contenido `VICTIMA-LEGITIMA` en `pending/`:
- `os.replace`: **sobrescribe en silencio** (la víctima desaparece, sin error ni `rejected/`).
- `lstat` previo: `FileExistsError` (errno 17); víctima intacta; el temporal queda en `tmp/`.
- `os.link` + `unlink`: `FileExistsError`; víctima intacta; temporal en `tmp/`.
- Coste (500 encolados por modo, `fsync` reales, sin preflight): `replace` p50 0,236 / p95 0,295 ms; `lstat` 0,244 / 0,358 ms;
  `link` 0,518 / 0,665 ms.
- **Carrera de `link`**: con un hilo que hace `lstat` continuo a `pending/` mientras se encolan 1500 entradas, `st_nlink != 1`
  aparece 12 veces en 166 796 lecturas; con `replace`, 0 en 139 870. En modo `link` el vaciado rechazaría entradas legítimas
  por `inbox_entry_unsafe` (el problema G1 de r3). **Se descarta `link`.**
- EXDEV y ENOSPC (simulados con `OSError` inyectado en `os.replace`/`os.link`; **no** con un sistema de archivos real distinto):
  el encolado falla con el errno, `pending/` vacío, el temporal queda en `tmp/`.
- Conclusión: `lstat` previo + `os.replace`; si existe, regenerar `<aleatorio8>` (el nombre incluye pid y nanosegundo, así que el
  TOCTOU restante sólo lo explota quien ya puede escribir en `pending/`).

### 3.6 H8 — `inflight/` ante `export`/`relocate` (`probe-h8.json`)
- `export create` de `main` hoy con `memory/inbox/pending/` no vacío: `export_unrecognized_durable_path` (rc 1). La exclusión del
  ADR cambia esto.
- Estados alcanzables por `kill -9` con el orden journal → entradas → marcador: `(post_journal: pending 1, inflight 1,
  committed)`, `(mid_delete: 0, 1, committed)`, `(post_entries_deleted: 0, 1, committed)`. **No existe** `pending` vacío +
  marcador + journal abierto: el journal `committed` se escribe dentro de `commit_locked`, antes de borrar entradas. El escenario de r4
  (descartar el único puntero a un journal `prepared`) no es alcanzable con ese orden.
- Regla propuesta, probada: `export create`/sellado/`relocate commit` toman el candado de bandeja exclusivo y exigen `pending/` e
  `inflight/` vacíos (`inbox_pending` / `inbox_inflight`). Con marcador vivo y `pending/` vacío da `inbox_inflight`; tras un
  vaciado (paso 0 borra el marcador) devuelve OK. Es defensa en profundidad, no corrección de un hueco real. `inbox status`
  debe informar `inflight` (no implementado en el spike).

### 3.7 Temporales huérfanos en `tmp/` (`probe-tmp.json`)
`kill -9` en (i) deja 1 temporal en `tmp/`, 0 en `pending/`.
- **Recolector por candado**: `flock` exclusivo no bloqueante sobre `inbox/.lock`; sólo se obtiene si no hay encolador vivo (los
  encoladores tienen el compartido; el SO lo suelta al morir, también con `SIGKILL`). Con un encolador vivo: 0 borrados y el
  temporal vivo sobrevive; sin encoladores: borra todo. No necesita reloj ni umbral. Respeta el orden de candados si se ejecuta
  **antes** de pedir `write_lock`. En la matriz: 20 huérfanos → 0.
- **Recolector por antigüedad** (umbral 60 s): un encolado demorado 120 s (un `fsync` bloqueado) pierde su temporal; su
  `os.replace` falla con `FileNotFoundError`: falla **visible**, sin entrada ni pérdida silenciosa. Elegible, pero estrictamente
  peor.
- Contra: con encolado ininterrumpido el recolector por candado casi nunca obtiene el exclusivo (sólo retrasa la limpieza); los
  huérfanos son basura, no pérdida, y `inbox status` informa `tmp`.

## 4. Para la extracción (fase A2): ¿`_commit_write_plan_locked` debe devolver o hacer algo distinto?

**Respuesta: sí puede seguir siendo neutra.** El cierre del journal y el paso 0 no llaman al cuerpo bloqueado: usan
`inspect_transaction`, el journal y los recibos (más `repair_durability`), todo independiente de `commit_write_plan`. Lo que el
vaciado sí pide del cuerpo, y lo que tuve que sacar de `write_commit.py` al prototiparlo (`spikes/e1a_recovery/inbox.py`,
`commit_batch_locked`, líneas de `write_commit.py:84-189` sin la rama CAS/replay y sin el post-proceso):

1. **Firma**: el cuerpo recibe `observed` leído bajo el candado por el llamante y el **`preflight`** (`binding` + `context`), no sólo
   el testigo del candado: `assert_unchanged(store, preflight.binding, observed)`, `check_subject_ref_binding` y
   `_commit_locked(..., _context=preflight.context)` los necesitan. El ADR dice `(store, lock_result, …)`; hay que añadir ese
   parámetro. La rama CAS/replay por `transaction_id` (`write_commit.py:46-83`) **permanece en la envoltura**: bajo el candado no
   aplica.
2. **`skip`**: hoy retorna un dict sin `outcome` (`write_commit.py:120-129`). El cuerpo debe decidir qué devuelve; en el spike
   devolví `(observed, {"committed": False, "state": "skip", "reason_codes": …})`. Para el vaciado no importa (el paso 5
   prevalida y nunca llega un `skip`), pero la extracción debe fijarlo.
3. **Orden del marcador**: se escribe **antes** de llamar al cuerpo (basta `fsync` del marcador y el `txid` que calcula el
   vaciado); no hace falta ningún gancho dentro del cuerpo ni que devuelva el `txid`.
Lo demás (`(revision, outcome)`, `outcome["committed"]` ∈ {True, False, None}, `operation_error_code`) ya lo da
`_commit_locked`. `WritePolicyError` se propaga como excepción y el vaciado la clasifica. **No comprobado**: el tratamiento de
`lock_result.release_error` en el vaciado (`_post_lock_outcome`), que el spike ignora.

## 5. Reproducir (desde el worktree; intérprete `3.12` del checkout canónico)

```bash
cd /Users/krisnova/.herdr/worktrees/an-kla-memory/spike-recuperacion
export AN_KLA_NO_UPDATE_CHECK=1 PYTHONDONTWRITEBYTECODE=1 TMPDIR=/var/tmp/ankla-spike-b2
PY=/Users/krisnova/www/an-kla-memory/.venv/bin/python
mkdir -p /var/tmp/ankla-spike-b2/out
# §1: 20 repeticiones por punto y configuración (A,B,C,D,E); ~3 min cada una
$PY -m spikes.e1a_recovery.cuts 20 /var/tmp/ankla-spike-b2/out/cuts-D_spike.json D_spike
$PY -m spikes.e1a_recovery.cuts 20 /var/tmp/ankla-spike-b2/out/cuts-E_spike_repair.json E_spike_repair
$PY -m spikes.e1a_recovery.summarize /var/tmp/ankla-spike-b2/out
# §2
$PY -m spikes.e1a_recovery.conc clean    /var/tmp/ankla-spike-b2/out/conc-clean.json
$PY -m spikes.e1a_recovery.conc twodrain /var/tmp/ankla-spike-b2/out/conc-twodrain.json
for i in 1 2 3 4 5 6 7 8 9 10; do $PY -m spikes.e1a_recovery.conc kill /var/tmp/ankla-spike-b2/out/conc-kill-$i.json _$i; done
# §3
for p in h3 h4 h5 h6 h7 h8 tmp lockhold; do $PY -m spikes.e1a_recovery.probes $p /var/tmp/ankla-spike-b2/out/probe-$p.json; done
rm -rf /var/tmp/ankla-spike-b2   # los stores son desechables
```
Los puntos de corte son la variable `SPIKE_CUT` (sólo la lee `spikes/e1a_recovery/inbox.py`); nada de `an_kla/` cambia.

## 6. Lo que no pude comprobar

- **Pérdida de energía / caché del SO.** `kill -9` no descarta el caché de páginas, así que no se prueba que los `fsync` omitidos
  se pierdan; (iii-a) se evalúa por recibos (lógico), no por corte de corriente.
- **EXDEV/ENOSPC reales**: sólo inyectados.
- **Dónde cayeron las 44 muertes de §2**: no hay instrumentación por muerte; la evidencia de recuperación es la matriz de §1.
- **Carga sostenida y almacenes grandes**: la carga dura ~0,5 s; no medí el coste de `inspect_transaction`/`_manifest_candidates`
  (recorren todas las revisiones) con miles de revisiones, que el paso 0 y `never_started` pagan.
- **No implementado en el spike**: movimiento real a `rejected/`, `remember_id_collision` (misma clave, payload distinto),
  resolución propia/ajena de D3, `--supersedes` de extremo a extremo por el vaciado (sólo a nivel de lote en H3), aislamiento uno
  a uno, órdenes `inbox`, `export`/`relocate` reales con la regla de H8 (sólo la función de comprobación), orden de candados
  bandeja → identidad → `write_lock` con prueba negativa, plataformas sin `flock`, `lock_result.release_error`.
- **Custodia**: `relocate commit` concurrente con `remember` no se probó (el preflight se ejecutó en cada encolado, pero no se
  movió la custodia).
- Temporales `.nombre.<hex>.tmp` de `atomic_write` que un `kill -9` deja en `transactions/` (existe hoy, ajeno a D1): no se
  provocó el corte exacto.

## 7. Notas de ejecución

- El worktree no tiene `.venv`: usé el intérprete 3.12 del checkout canónico; verifiqué que `import an_kla` resuelve al código del
  worktree (`/Users/krisnova/.herdr/worktrees/.../an_kla/__init__.py`), no al del canónico.
- Un hook (`adrc-guardarrail`) bloqueó **una** orden compuesta que mezclaba `git add/commit` con la variable `$PY` («segmento no
  clasificado»). No se esquivó el guardarraíl: no se ejecutó nada de esa orden; repetí los pasos separados (copiar datos; `git add`;
  `git commit`) como órdenes simples. Sin otros bloqueos.
- Commit local único en la rama (mensaje en español, con `Co-Authored-By`). Sin push, PR, merge ni instalaciones; sin agentes ni Herdr.
- `scripts/check_sizes.py` sobre el worktree: OK.

## Ronda adversarial del texto de D1 — `fix-and-retry`

Revisor: Gemini vía `agy --mode plan`, contexto fresco, sólo lectura, sobre
`5c5750a..3c310ad` contra la evidencia del spike. Deuda r4: H3–H8 y `tmp/`
**cerrados**. La regla «sin rastro» del paso 0 se juzgó segura. Hallazgos:
2 MEDIUM y 3 LOW, todos de redacción. Dictamen íntegro fuera del repo:
`/var/tmp/orquestador-memoria/capitanes/ankla/ronda-adr0063/dictamen-D1-spike-gemini.md`.

| ID | Sev | Hallazgo | Disposición |
|---|---|---|---|
| H-01 | MED | La cifra de 0,041–0,064 s no incluía la bisección | Corregido: lote limpio y bisección (21,7 ms) por separado |
| H-02 | MED | El paso 2 movería un directorio a `rejected/`, contra el criterio 8 | Corregido: sólo nombres de entrada; los directorios se ignoran |
| H-03 | LOW | Fallo de `repair_durability` sin camino | Corregido: aborta sin borrar marcador ni entradas |
| H-04 | LOW | «reanuda desde el journal» es inexacto | Corregido: «reintenta el commit sobre el journal existente» |
| H-05 | LOW | Marcador del lote replanificado no explícito | Corregido en el paso 7.2 |

**Estado:** correcciones absorbidas, **sin ronda que las verifique**: el
mandato 4 autoriza una sola ronda sobre D1. D1 sigue en Propuesta y este PR
no se fusiona; va al orquestador con el dictamen.


## Ronda de cierre (orquestador) — `fix-and-retry` y corrección

Revisor: DeepSeek por OpenCode, sesión nueva, sólo lectura, sobre
`3c310ad..2be22e2` contra el código; la corrió el orquestador. H-02 a H-05
cerrados, H-01 parcial; cuatro hallazgos nuevos. Dictamen íntegro fuera del
repo: `/var/tmp/orquestador-memoria/ronda-cierre/dictamen-ankla-d1-deepseek.md`.

**N-02 se decidió con evidencia.** El prototipo (`spike/e1a-recuperacion`,
`3e0502d`) ya cerraba el journal enlazando `observed_log` (escribe los
ref-logs `intent` y `observed_commit`), pero tras `repair_durability` no
comprobaba nada: borraba entradas y marcador sin predicado. El texto
(«`committed` completa») no correspondía a ningún estado de
`commit-outcome-v2`. En `8561b80` se añadió al prototipo el predicado que
ahora dice el ADR (`committed is True` y `durability_state == "complete"`,
auditoría incompleta tolerada con aviso) y un control G cuyo cierre no
enlaza `observed_log`. 20 `kill -9` por punto, en los 8 puntos:

| Config. | Punto | Tras el cierre | Tras reparar | Final del paso 0 | Abortos | Perdidos / dupl. | `verify` |
|---|---|---|---|---|---|---|---|
| F | (iii-a) `post_replace_current` | `durability_incomplete` | `committed` | `committed`, durab. y audit. `complete` (20) | 0 | 0 / 0 | ok |
| F | (iii-b) `pre_committed_journal` | `committed` | — | ídem (20) | 0 | 0 / 0 | ok |
| F | `post_journal`, `mid_delete`, `post_entries_deleted` | ya `committed` | — | ídem (60) | 0 | 0 / 0 | ok |
| F | demás puntos | sin rama `True` | — | — | 0 | 0 / 0 | ok |
| G | (iii-a) y (iii-b) | — | — | `committed_audit_incomplete` (40), aviso `inbox_audit_incomplete` | 0 | 0 / 0 | ok |

Lectura: el escenario del revisor es real si el cierre no enlaza
`observed_log` (G: 40 de 40 cortes en `committed_audit_incomplete`, que el
predicado anterior habría abortado en cada `drain`, bloqueando la custodia).
Con el cierre del texto (F) no aparece, y con el predicado nuevo tampoco
bloquearía si apareciera. En F y G: 0 marcadores y `pending/` vacío tras la
tercera invocación, que queda `idle`. Salida cruda y sha256 fuera del repo:
`/var/tmp/orquestador-memoria/capitanes/ankla/faseA/datos-B2/n02/` y
`…/datos-B2/n02.sha256`. Stores en `/var/tmp/ankla-spike-b2`, borrados.

| ID | Sev | Hallazgo | Disposición |
|---|---|---|---|
| N-01 | MED | «Cifras globales» daba 0,064 s sin bisección ni el 0,203 s | Corregido: lote limpio, bisección (≈ 0,086 s), máximo 0,203 s con paso 0 bajo `kill -9`; también en Consecuencias |
| N-02 | MED | Predicado «`committed` completa» inexistente | Corregido con la evidencia de arriba: predicado de `commit-outcome-v2`, `observed_log` enlazado explícito, código `transaction_<state>` |
| N-03 | LOW | Último recurso sin marcador | Elegido marcador por commit: `transaction_id` propio y marcador antes de cada commit; orden entrada → marcador |
| N-04 | LOW | «`pending/` vacío» sin definir frente a ignorados | Definido en «Directorios» (sin nombres de entrada / de marcador); custodia e `inbox status` (`ignored`) lo citan |
