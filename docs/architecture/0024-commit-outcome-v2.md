# ADR-0024: resultado de commit y durabilidad v2

## Estado

Aceptada e implementada localmente el 2026-08-08 por autorización del roadmap
del maintainer. Diseño e implementación cerraron sus rondas adversariales en
`proceed`; fault injection forma parte del gate ejecutable.

## Contexto

`CURRENT` es la autoridad lógica. Hoy puede avanzar y después propagarse un
`OSError` al caller; `observed_commit` descarta errores y `_fsync_directory()`
silencia fallos de apertura pese a anunciar `posix-fsync-dir/v1`. Un booleano de
éxito no separa autoridad, auditoría y durabilidad.

## Txid conocido antes de I/O

La política pura no genera UUID ni lee entropía. `plan_write()` y
`write-planning-result-v1` permanecen byte-idénticos y deterministas; planes v1
pendientes siguen siendo válidos. El intento se separa en
`an-kla/transaction-attempt-v1`. Sus variantes one-of de claves exactas son:

- `write|checkpoint`: schema, operation, base_revision, plan_fingerprint,
  transaction_id y execution_fingerprint;
- `initialize`: schema, operation, `expected_current=null`,
  initialization_fingerprint, transaction_id y execution_fingerprint;
- `internal_commit`: schema, operation, base_revision, mutation_fingerprint,
  transaction_id y execution_fingerprint.

`initialization_fingerprint` cubre identidad candidata y checkpoint raíz;
`mutation_fingerprint` cubre records/checkpoint completos de la API interna.
El execution fingerprint es SHA-256 de todas las claves anteriores salvo él
mismo. Identity bootstrap/adoption no finge ser commit: usa las mismas
primitives estrictas, pero su `identity-durability-receipt-v1` y
`identity-operation-result-v1` propios de ADR-0022.
Sólo init raíz usa la variante initialize.

La API `begin_transaction(binding, transaction_id=None)` no hace I/O: valida la
variante y devuelve el attempt con UUID canónico generado o provisto por caller.
CLI acepta `commit-write-plan --transaction-id <uuid>` y el caller conserva el
UUID antes de arrancar el proceso; no cambia `plan-write`. Checkpoint define su
plan determinista en ADR-0023 y usa el mismo attempt. Un attempt/txid queda
ligado de forma idempotente a un único binding.

Validación/CAS previos a iniciar una transacción aún pueden lanzar códigos
terminales. Desde que se acepta el txid, toda falla operacional retorna un
`commit-outcome-v2`; no propaga `OSError` desnudo.

Si falla el primer journal, el algoritmo se detiene sin más I/O y devuelve
`recorded=false`. Ese resultado sólo vive en la respuesta de esa invocación.
Una inspección posterior sin journal ni candidato responde `outcome_unknown`:
la ausencia no permite distinguir «nunca se grabó» de pérdida/corrupción.

## Resultado

```json
{
  "schema": "an-kla/commit-outcome-v2",
  "transaction_id": "uuid",
  "parent_revision": "sha256:...",
  "candidate_revision": "sha256:...",
  "current_observed": "sha256:...",
  "candidate_relation": "ancestor",
  "state": "committed_audit_incomplete",
  "committed": true,
  "recorded": true,
  "authority_state": "candidate_authoritative",
  "audit_state": "incomplete",
  "durability_state": "complete",
  "operation_error_code": "journal_commit_failed",
  "warnings": []
}
```

Revisiones y error pueden ser `null`. `committed` es `true|false|null`: `null`
cuando authority es desconocida. `recorded` también es triestado: false sólo en
la respuesta runtime del primer write fallido, true con journal verificable y
null cuando inspect carece de evidencia. Claves exactas.

Ejes:

- authority: `parent_lineage_authoritative`, `candidate_authoritative`,
  `unknown`;
- audit: `not_started`, `prepared`, `complete`, `incomplete`;
- durability: `complete`, `incomplete`, `unknown`;
- candidate relation: `current`, `ancestor`, `orphan`, `unknown`.

Precedencia de `state`:

1. authority unknown → `outcome_unknown`;
2. durability incomplete → `durability_incomplete`;
3. candidate autoritativo + audit incompleto →
   `committed_audit_incomplete`;
4. candidate autoritativo + audit/durability completos → `committed`;
5. parent lineage autoritativo y candidate `orphan|unknown|null` →
   `not_committed`.

Así, un fsync de segmento fallido produce `durability_incomplete`,
`committed=false`, parent-lineage authoritative y audit incomplete/prepared. Los ejes
no se pierden por el estado principal.

## Máquina bajo lock

1. recibir txid preasignado y escribir journal `prepared`;
2. escribir segmentos y, si aplica, checkpoint;
3. escribir manifest e intent ref-log;
4. objeto inmutable de stage `candidate_prepared` con candidato y journal-head
   mutable que lo enlaza, sin autocertificar durabilidad;
5. fsync estricto de esos artefactos y crear receipt
   `candidate-data-durable` sólo después de que todos terminaron con éxito;
6. revalidar identidad y CURRENT padre;
7. reemplazar CURRENT y fsync del directorio;
8. crear receipt `current-durable` sólo después del fsync-dir exitoso;
9. releer CURRENT;
10. journal `committed` y observed ref-log;
11. salir/liberar lock y devolver outcome.

Fallos pre-replace detienen el algoritmo. Fallos desde replace se reconcilian
mediante CURRENT y la cadena de parents. Nunca hay rollback automático.

La capa exterior conserva txid/outcome hasta después de `__exit__`: errores al
desbloquear flock/Windows/rmdir se capturan como audit incomplete con warning
`lock_release_incomplete`; no reemplazan un error primario. Cleanup de temporal
también se registra y jamás enmascara la causa original.

## Relación histórica

Inspect no exige `CURRENT == candidate`. Recorre de forma acotada y con detección
de ciclos la cadena verificable desde CURRENT:

- candidate == CURRENT → `current`;
- candidate es ancestro → `ancestor`, históricamente committed;
- candidate verificable fuera de esa cadena → `orphan`;
- cadena ilegible/ambigua → `unknown`.

Por tanto, después de A→B→C, inspeccionar el tx de B sigue devolviendo
`committed=true`, relation `ancestor`; `current_observed` es C.

## Journal corrupto y reconstrucción

Inspect no confía en `stage`. Si journal falta/corrompe, escanea manifests
content-addressed por `transaction_id`; exactamente un candidato en la cadena
permite reconstruir authority y marca audit incomplete. Journal ausente + cero
candidatos, igual que journal corrupto + cero candidatos, devuelve
`outcome_unknown`. Múltiples candidatos son integridad ambigua y cierran en
unknown. `transaction_not_recorded` es sólo un warning del outcome en memoria
que devolvió la invocación cuyo primer write falló; `operation_error_code`
conserva el punto real (`temporary_fsync_failed`, etc.). Nunca es una conclusión
de `inspect`.

Journals legacy se reconcilian best-effort; `transaction_id="root"` sigue válido
históricamente.

## Durabilidad y reparación

En POSIX ningún fallo de fsync-dir se ignora. Cada primitive distingue
mkdir/open/write/fsync/close/replace/read/cleanup y si replace ya ocurrió.
Windows conserva `windows-no-dir-fsync/v1`.

Un journal no se autocertifica: sus flags no prueban el fsync de los propios
bytes. La evidencia positiva son receipts content-addressed distintos. Cada
receipt enumera hashes y paths relativos protegidos y sólo se crea *después* de
que todos sus writes/fsync/fsync-dir previos hayan retornado éxito. Ver un
receipt prueba la ruta de control previa; si escribirlo falla puede faltar y la
clasificación degrada conservadoramente, pero nunca certifica una operación
posterior ni su propia durabilidad.

Cada receipt vive en
`transactions/<txid>/receipts/sha256/<digest>.json` y tiene claves exactas:

```json
{
  "schema":"an-kla/durability-receipt-v1",
  "kind":"current-durable",
  "transaction_id":"uuid",
  "execution_fingerprint":"sha256:...",
  "candidate_revision":"sha256:...",
  "predecessor_receipt":"sha256:...",
  "repair_for_kind":null,
  "protected":[
    {"path":"refs","operation":"directory_fsync","content_sha256":null}
  ]
}
```

Kind es `candidate-data-durable|current-durable|repair`. Candidate usa
`predecessor_receipt=null`; current liga obligatoriamente el digest del receipt
candidate. Repair liga el último receipt disponible (candidate o current), o
null cuando no existe ninguno, y `repair_for_kind` nombra
`candidate-data-durable|current-durable`; no pretende referir un objeto ausente.
Protected está ordenado por bytes de
path+operation, sin duplicados; path es relativo al store, NFC, sin vacío,
`.`/`..`, absoluto, backslash ni symlink. Operation es
`file_fsync|directory_fsync`; content_sha256 es obligatorio para file y null
para directory. UUID, fingerprint, candidate y cada hash se revalidan contra
journal/manifest/attempt antes de confiar.

`candidate-data-durable` cubre segmentos/checkpoint/manifest/intent y los bytes
exactos del objeto inmutable de stage `candidate_prepared` del paso 4; el
journal-head puede avanzar sin invalidar ese hash y queda explícitamente fuera
de `candidate-data-durable`: su pérdida degrada audit, no la durabilidad de los
bytes candidatos. El objeto de stage sustituye normativamente cualquier claim
sobre los bytes mutables del head;
`current-durable` cubre además replace+fsync-dir de CURRENT. Para
`durability_state=complete` se exige el receipt aplicable con hashes exactos;
journal legible sin receipt es `incomplete|unknown`. Un estado incomplete nunca
mejora por mera legibilidad o inspect. Sólo:

```text
an-kla transaction repair-durability <txid>
```

bajo lock revalida identidad/CURRENT, fsync de nuevo cada archivo/directorio
(también objetos ya existentes) y crea un receipt nuevo después de que todo
pasa. El receipt de reparación liga el último receipt existente o null y queda
en el journal como evidencia audit, no como autocertificación. Retry de commit no
repara ni crea otro hijo cuando candidate ya es current/ancestor.

## Inicialización

Init nuevo usa la misma máquina, txid UUID y outcome; su manifest raíz deja de
usar `root`. Si CURRENT raíz avanzó antes de un fallo, init reconcilia y el retry
retorna esa raíz. Raíces legacy `transaction_id="root"` siguen verificables.
El bootstrap de identidad llama estas primitives endurecidas; por eso outcome y
fsync se implementan antes de habilitar ADR-0022.

## API y CLI

- `commit_with_outcome()` siempre retorna outcome tras aceptar txid;
- `commit_write_plan()` conserva campos v1 y añade `outcome`;
- `MemoryStore.commit()` interno devuelve hash y nunca propaga un error de audit
  post-CURRENT; callers que necesitan certeza usan outcome;
- `transaction inspect` es read-only;
- `transaction repair-durability` es mutativo, identity-checked y auditable;
- durante init raíz incompleto, transaction repair sólo acepta
  `--bootstrap-intent <digest>`: adquiere `.identity.lock` y luego el lock del
  store, exige bytes byte-idénticos al intent durable y no concede autoridad
  fuera de ese intent. Receipts de archivos identity se reparan mediante
  `identity repair` de ADR-0022, no mediante transaction inspect.

El transaction-attempt, no el plan puro, contiene txid y
`execution_fingerprint`. Commit revalida ambos: mismo txid+binding inspecciona y
continúa/reproduce el mismo candidato determinista; mismo txid con otro binding
falla `transaction_binding_conflict`. Si el primer journal falló, reusar el
mismo attempt puede reiniciar porque produce los mismos bytes/candidato; si
existe cualquier evidencia durable, primero reconcilia y nunca crea un segundo
hijo. Si el CLI recibe un plan
v1 sin `--transaction-id`, genera el UUID antes de cualquier acceso al store y
lo incluye siempre en el outcome; esta forma conserva compatibilidad, pero sólo
un UUID proporcionado permite al caller inspeccionar tras pérdida total de la
respuesta.

CLI imprime outcome canónico incluso en falla operacional: exit 0 para estados
committed (completo o degradado), exit 3 para not_committed/outcome_unknown. Los
errores de validación previos conservan stderr seguro sin outcome.

## Fault injection obligatorio

Se inyecta en begin, lock acquire/release, journal mkdir/open/write/fsync/close,
segment/checkpoint/manifest/intent, candidate journal, ambos receipts, CURRENT
replace antes y después, fsync-dir, relectura, committed journal, observed log
y cleanup. Se
simulan `EIO`, `ENOSPC`, temporales, journal truncado y unlock/rmdir.

Cada caso afirma CURRENT, outcome/ejes, bytes permitidos, inspect, retry sin
segundo hijo y error primario no enmascarado. Incluye init, A→B→C inspeccionando
B, manifest por txid con journal corrupto, y repair-durability exitoso/fallido.

## Alternativas descartadas

- Capturar todo como éxito: oculta durabilidad.
- Propagar todo error: mantiene ambigüedad.
- Tratar ref-log como autoridad: contradice ADR-0001.
- Elevar durabilidad por lectura posterior: no demuestra persistencia.
- Borrar journals: elimina evidencia de convergencia.

## Consecuencias

Se extraen primitives/outcome fuera de `store.py` antes de identidad. El
resultado es más ancho, pero hace explícitos autoridad, audit, durabilidad y
coordinación sin reinterpretar corrupción como un fallo de fsync.
