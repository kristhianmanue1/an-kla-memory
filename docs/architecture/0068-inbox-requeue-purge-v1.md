# ADR-0068: `inbox requeue` e `inbox purge-rejected`, salida explícita de `rejected/` (#234)

- **Estado:** Aceptada por delegación del orquestador (2026-11-19), tras r1 y r2 `fix-and-retry` y r3 `proceed` (Gemini).
- **Implementación:** En la rama `feat/234-inbox-rejected` (PR de #234)
- **Fecha:** 2026-11-19
- **Decide sobre:**
  - reencolar las entradas rechazadas por formato que esta versión ya entiende;
  - purgar los rechazos, con respaldo fuera del store.
- **Depende de:** ADR-0063 (bandeja, `reject_entry`, orden de candados, custodia de `export` y `relocate`), ADR-0065 (`inbox-entry-v2`) y ADR-0066 (`inbox-entry-v3`).

## Contexto

`inbox_entries.reject_entry` rechaza una entrada de `pending/` bajo `write_lock` (el vaciado), de dos formas:

- **Inodo seguro** (archivo regular con `st_nlink == 1`): mueve la entrada a `rejected/<final>` y escribe `rejected/<final>.reason`. Si el nombre ya existe en `rejected/`, `<final>` lleva el sufijo `.<n>`.
- **Inodo inseguro** (enlace, FIFO, socket, dispositivo o hardlink): **no** mueve nada. Escribe sólo `rejected/<final>.reason`, con la evidencia de `lstat`, y borra el nombre de `pending/`.

Ninguna orden saca nada de `rejected/`. Hay dos casos reales:

1. **Rechazo de formato al bajar de versión.** El `inbox drain` de una versión anterior rechaza con `inbox_entry_invalid` las entradas de un formato nuevo: v2 en beta.36, v3 en beta.37. El remedio probado (mover la entrada a `pending/`, borrar el `.reason` y vaciar) es manual y exige tocar el store a mano.
2. **Rechazo de política** (`remember_state_over_fact`, colisiones de idempotencia). Queda contado en `inbox status` para siempre, y el procedimiento de adopción no puede exigir `rejected.count` 0.

## Decisión

### 0. Comunes a las dos órdenes

- **Candados:** el exclusivo de la bandeja, después `identity_lock` compartido y después `write_lock`. Es el orden total de `lock_order` (bandeja → identidad → escritura), y excluye el vaciado, que modifica `rejected/` bajo `write_lock` (R68-01).
  - **Esperas cortas** (R68-14): la bandeja, como mucho `ENQUEUE_LOCK_WAIT_SECONDS`; la identidad, su plazo propio; y `write_lock`, **0,5 s**.
  - Si `write_lock` no llega en ese plazo, se sueltan la identidad y la bandeja enseguida y la respuesta es `write_lock_busy`, reintentable (rc 3). Nunca se retiene el exclusivo de la bandeja esperando el de escritura: un `remember` concurrente sólo espera lo que dura un lote.
  - Con `identity_lock` exclusivo de otro proceso (una reubicación o un cambio de identidad en curso), `identity_lock_busy` reintentable (`retryable: true`, rc 3), como `remember` (#226).
- **Nombres:** se aceptan los nombres de `rejected/` que produce `reject_entry`, esto es, un nombre de entrada válido (`is_entry_name`) con o sin sufijo `.<n>` (R68-07), más su `.reason`. Cualquier otro nombre, una ruta o `..` dan `inbox_entry_name_invalid`.
- **Orden y lote** (R68-08 y R68-13):
  - Se recorre **todo** `rejected/` en orden de bytes del nombre.
  - El lote cuenta sólo lo que **cambia**: 50 reencolados o purgados por invocación. Los rechazos que no se tocan (`not_requeueable_policy`, `still_invalid`, `not_requeueable_unsafe`) no consumen lote, así que el recorrido nunca se queda atascado en ellos.
  - Si quedan cambios por hacer, la salida trae `remaining` con su número, y se repite la orden.
  - Con 50, el exclusivo se retiene poco: 50 `rename` con su `fsync`.
- **Durabilidad:** cada movimiento o borrado va seguido de `fsync` del directorio de origen y del de destino (R68-04).
- **`sha256` en la salida:** es el digest de los bytes del archivo tal como está en disco, o `null` si no existe o no se puede leer (R68-09).
- **Sin rutas locales en la salida.** La del respaldo no se repite.
- **Sin cambios:** `retrieve`, el MCP y el store comprometido.
- **`export` y `relocate`:** siguen negándose con pendientes (`inbox_pending`). Una entrada reencolada es pendiente hasta que se vacía.

### 1. `inbox requeue [<rechazo>…] [--all-format]`

**Candidatas.** Rechazos de inodo seguro (con `.json` y `.reason`) que cumplen dos condiciones:
- su `.reason` tiene `code: inbox_entry_invalid` (R68-10);
- esta versión los valida **ahora** como entrada válida, de cualquier versión de esquema que conozca.

**Resultados de las que no lo son:**
- código de política: `not_requeueable_policy`;
- siguen inválidas: `still_invalid`;
- sólo `.reason` (inodo inseguro): `not_requeueable_unsafe`.

Ninguna de ellas se toca.

**Movimiento, dos pasos, sin nombres nuevos en `rejected/`** (R68-05 y R68-11):
1. `rename` de la entrada a `pending/<destino>`, con `fsync` de los dos directorios;
2. `unlink` de `<final>.reason`, con `fsync`.

**Corte entre los dos pasos.** La entrada ya está en `pending/` y queda un `.reason` sin su entrada, de inodo seguro (sin evidencia `lstat`).
- No se pierde nada: la entrada se vaciará y el motivo sigue en disco.
- No aparece ningún archivo con un nombre que `inbox status`, `export`, `relocate` o `compact` no conozcan, porque es el mismo `.reason` de siempre.
- `inbox status` lo cuenta como rechazo, con su código.
- `requeue` lo informa como `orphan_reason` y no lo borra.
- `purge-rejected` lo respalda y lo purga, como cualquier rechazo de sólo `.reason`.

**`requeue` nunca borra un motivo sin haber movido antes su entrada.**

**Destino** (R68-03):
- `<destino>` es el nombre canónico: `<final>` sin el sufijo `.<n>`.
- Antes del `rename` se comprueba con `lstat` que no existe en `pending/`. La comprobación es segura porque, bajo el exclusivo de la bandeja, nadie más publica en `pending/`.
- Si existe, se genera un nombre de entrada nuevo con el generador de nombres de `enqueue` (mismo prefijo de clave, tiempo y token nuevos), y se repite la comprobación (R68-15).
- Nunca se reemplaza un archivo de `pending/`.

**Qué no hace:** no vacía; quien llama ejecuta `inbox drain` después.

**Selección:** sin nombres ni `--all-format`, `inbox_requeue_target_missing`.

**Idempotente:** la segunda invocación ya no ve la entrada en `rejected/`, y la idempotencia del vaciado protege el store.

### 2. `inbox purge-rejected (<rechazo>… | --all) --backup <dir>`

**Respaldo** (R68-06):
- `--backup` es un directorio absoluto, fuera del store y de `.an-kla/`.
- Puede no existir, estar vacío o contener archivos de purgas anteriores, terminadas o interrumpidas, de este mismo store (R68-12). Así se reanuda una purga cortada, y se purgan más de 50 rechazos en varias invocaciones con el mismo respaldo.
- Se acepta todo archivo cuyo nombre sea el de un rechazo: nombre de entrada, con o sin sufijo `.<n>`, o su `.reason`.
  - Si el mismo nombre sigue en `rejected/`, su sha256 tiene que coincidir. Es una copia ya hecha y no se vuelve a copiar.
  - Si ya no está en `rejected/`, es de una purga anterior y se deja.
- Los `.<nombre>.tmp` que dejó un corte se borran al empezar y la copia se rehace.
- Un archivo con otro nombre, un directorio, un enlace, o un nombre que coincide con distinto sha256 dan `inbox_purge_backup_invalid`, y no se purga nada.

**Directorio:** si `--backup` no existe, se crea con modo 0700, y su padre tiene que existir (R68-16).

**Por rechazo, en orden:**
1. copiar al respaldo cada archivo que exista: la entrada y su `.reason`, o **sólo el `.reason`** en un rechazo de inodo inseguro (R68-02). Cada copia se escribe primero como `.<nombre>.tmp` en el respaldo, con `fsync`, y se renombra atómicamente a `<nombre>`. Así un corte nunca deja una copia truncada con el nombre definitivo (R68-17);
2. `fsync` del directorio del respaldo;
3. comprobar el sha256 de cada copia contra el original;
4. sólo entonces borrar los originales de `rejected/`.

**Si una copia falla o no coincide:** no se borra nada de ese rechazo, y el resultado lo dice (`backup_failed`).

**Sin respaldo no se purga.** No hay `--no-backup`.

**Selección:** sin nombres ni `--all`, `inbox_purge_target_missing`.

### 3. Esquemas

- **`inbox-requeue-result-v1`:** `schema`, `requeued`, `skipped` y `remaining`. Por rechazo: `rejected_name`, `code` (del `.reason` original), `result`, `pending_name` (si se reencoló) y `sha256`. `result` es uno de `requeued`, `not_requeueable_policy`, `still_invalid`, `not_requeueable_unsafe` u `orphan_reason`.
- **`inbox-purge-result-v1`:** `schema`, `purged`, `failed` y `remaining`. Por rechazo: `rejected_name`, `code`, `result` (`purged` o `backup_failed`) y `files`, una lista de `{name, sha256}`.

## Consecuencias

- El remedio de la vuelta atrás pasa a ser `inbox requeue --all-format && inbox drain`, sin tocar ficheros a mano.
- El procedimiento de adopción puede exigir `rejected.count` 0: se lee el `.reason` y después `inbox purge-rejected --all --backup <dir>`.
- Los rechazos de política nunca se reencolan. Para rehacer uno, se escribe un `remember` nuevo con la corrección.
- Las dos órdenes toman `write_lock`. Mientras corren, un `inbox drain` o un `remember` que vacía esperan su turno, como con cualquier lote.

## Pruebas de aceptación

- **Requeue sin pérdida:** una entrada v2 o v3 rechazada con `inbox_entry_invalid` por una versión anterior se reencola, y tras `inbox drain` queda escrita. Después, `rejected` y `pending` quedan a 0 y `verify` da OK.
- **Otras candidatas:**
  - un `remember_state_over_fact` da `not_requeueable_policy` y no se mueve;
  - una entrada corrupta da `still_invalid`;
  - un rechazo de inodo inseguro da `not_requeueable_unsafe`.
- **Sufijos y colisiones:** un rechazo con sufijo `.1` se reencola con su nombre canónico. Si ese nombre ya existe en `pending/`, recibe un nombre nuevo y no se reemplaza nada.
- **Corte inyectado en requeue entre los dos pasos:**
  - la entrada está una sola vez en `pending/` y se vacía;
  - el `.reason` queda en `rejected/`; `inbox status` lo cuenta y `requeue` lo informa como `orphan_reason`;
  - `purge-rejected` lo respalda y lo purga;
  - `export` y `relocate` no ven ningún archivo con nombre desconocido.
- **Purga:**
  - sin `--backup`, se rechaza;
  - con `--backup` dentro del store, `inbox_purge_backup_invalid`;
  - con un respaldo válido, las copias coinciden por sha256 y `rejected` queda a 0;
  - un rechazo de sólo `.reason` se purga con su `.reason` respaldado.
- **Purga interrumpida** (corte inyectado tras copiar): repetir con el mismo `--backup` reanuda y termina.
- **Más de un lote:** 120 rechazos se purgan en tres invocaciones con el mismo `--backup`. La segunda y la tercera aceptan las copias de las anteriores.
- **Respaldo inválido:** con un archivo de nombre extraño, o con un nombre igual y distinto sha256, `inbox_purge_backup_invalid`.
- **Copia fallida o sha256 distinto** (inyectado): no se borra nada de ese rechazo.
- **Concurrencia:**
  - un `inbox drain` que rechaza mientras corre `requeue` o `purge-rejected` espera `write_lock`, y no se pierde ni se duplica ningún rechazo;
  - con `write_lock` tomado por otro proceso, `requeue` responde `write_lock_busy` en menos de un segundo y suelta la bandeja: un `remember` concurrente encola sin `identity_lock_busy` ni `inbox_lock_busy`.
- **Lote:**
  - con 80 rechazos reencolables, se reencolan 50 y `remaining` vale 30;
  - con 300 rechazos de política seguidos de 10 reencolables, `--all-format` reencola los 10 en una invocación.
- **Errores de entrada:**
  - nombres inválidos y rutas (`../x`, absolutas): `inbox_entry_name_invalid`;
  - con una reubicación simulada en curso: `identity_lock_busy` reintentable.
- `retrieve` y los goldens, sin cambios.
