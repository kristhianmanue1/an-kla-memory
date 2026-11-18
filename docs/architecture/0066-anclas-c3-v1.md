# ADR-0066: Anclas de C3 en `remember`, frescura al recuperar y disputa nativa (E1.d2)

- **Estado:** Aceptada por delegación del orquestador (respuesta al informe 15, 2026-11-18), tras tres
  rondas adversariales de otra familia (Gemini): r1 `fix-and-retry` (4 HIGH, 3 MEDIUM, 1 LOW),
  r2 `proceed` (2 MEDIUM, 2 LOW, incorporados), r3 `proceed` sobre lo añadido después, incluida la
  errata 3 de C3 (1 LOW, incorporado). Las nueve ambigüedades las decidió el orquestador (§9).
- **Implementación:** En la rama `feat/e1d2-anclas` (PR de E1.d2, sin integrar): 240 de 257 vectores pasan y 17 no aplican (`document` con custodio); 0 discrepancias con el verificador de agora
- **Fecha:** 2026-11-18
- **Decide sobre:**
  - `remember --anchor`, con las tres comprobaciones de C3 al escribir y sus rechazos;
  - la cobertura determinista de elementos (`fact-checks-rules/v1`);
  - la frescura al recuperar, con tope de anclas comprobadas (32 por defecto);
  - `anchors verify <id>`, el momento de auditoría;
  - `dispute`, la operación nativa para dictámenes externos (agora);
  - el esquema y la vista de las resoluciones de anclas de conversación (sin quien las escriba todavía).
- **Depende de:**
  - ADR-0063 (bandeja, sobre C0, disputa);
  - ADR-0065 (`state` y casilla);
  - ADR-0064 (`recall`) sólo para la frescura en `recall`.
- **Contrato:** C3 `memoria/ancla/v1`, congelado con sus vectores (coordinación, commit `798e247`), más sus erratas 0 y 1 (`e0dd7e8`), 2 (`ac478f2`) y 3 (`172c3b4`), en `ERRATAS.md`. Donde las erratas contradigan el README, prevalecen.
  - La errata 2 trae `anchor_too_many`, `anchor_schema_invalid` y el orden de los rechazos.
  - La errata 3 fija nueve lecturas, entre ellas `anchor_quote_not_normalized`.
  - Implementación de referencia para contrastar: el verificador de agora (PR #17, integrado), que pasa los 241 vectores congelados y los 16 de las erratas. Es un contrato externo, que este ADR implementa y no redefine.

## Contexto

Un recuerdo sin fuente no se puede comprobar: el agente que lo lee tiene que fiarse de quien lo escribió. C3 fija cómo cita un recuerdo su fuente (`repo-file`, `conversation`, `document`) y qué significa comprobar esa cita: tres comprobaciones, nunca un booleano, y una frescura derivada sin ningún modelo.

El plan (E1.d2) pide tres cosas:
1. `remember --anchor` con las tres comprobaciones;
2. cobertura determinista de elementos;
3. operación nativa de disputa para dictámenes externos.

Criterios de aceptación:
- an-kla pasa los vectores congelados de C3 con implementación propia;
- el hecho «puerto 8080» con una cita que dice 8081 queda con cobertura `none` y el número señalado;
- una cita inexistente se rechaza, y el hecho no se guarda a medias.

Agora ya implementó C3 y elevó 9 puntos, que el orquestador resolvió como errata 1 (E1–E9). Este ADR sigue el README de `798e247` corregido por `ERRATAS.md` (`e0dd7e8`). Las nueve ambigüedades que vi como implementador las decidió el orquestador, dueño del contrato (respuesta al informe 13, 2026-11-18). Están incorporadas en las secciones y resumidas en §9.

## Decisión

### 1. Dónde viven las anclas en el registro

- **`anchors`:** campo de primer nivel del registro, una lista de 0 a 16 objetos `memoria/ancla/v1` tal como los define C3. Si hay más de 16, se rechaza el registro entero con `anchor_too_many` (A1; errata 2 de C3). Sin anclas, el campo no existe: no se guarda `[]`.
- **`coverage`, `missing` y `missing_total`:** campos de primer nivel, hermanos, como en el ejemplo de C3 y en `vectores.json` (`cobertura`). Presentes sólo si hay anclas (C3, «Reglas al escribir», 3).
- **Lo que el store durable guarda de un ancla:** sólo el objeto `memoria/ancla/v1`, más la cobertura del registro. El resultado de las tres comprobaciones al escribir y su `at` **no** se guardan en el registro: viajan en la entrada de la bandeja y en la respuesta de `remember` (A2). La lectura vuelve a comprobar siempre (§4).
- **Sin cambio en `record-envelope-v1`.** El sobre sigue siendo de C0, como hizo ADR-0065 con `slot`.
- **Bandeja: `inbox-entry-v3`** = v2 más tres campos opcionales. v1 y v2 se siguen leyendo.
  - `anchors`: la lista de anclas, y por cada una `write_check`, que lleva el resultado de las tres comprobaciones y su `at` (§2). El vaciado no vuelve a leer Git (A2), y `write_check` no pasa al registro.
  - `verdict`: sólo en una entrada de `dispute` (§6), con `target_id` (el campo que ya existe en v1).
  - `operation`: `remember` (por defecto), `dispute` o `anchor_resolution`. Esta última lleva el objeto `anchor_resolution` de §6bis y no tiene orden pública en E1.d2: la escribirá el resolutor de C2.
- **El texto del ancla es dato no confiable, como el del recuerdo.** `quote` nunca se interpreta como instrucción, y la salida lleva `untrusted_memory_data: true`.

### 2. Escribir: `remember --anchor`

- **Entrada:** `--anchor-file <ruta|->` con una lista JSON de anclas.
  - Atajo para el caso común: `--anchor-path <p> --anchor-quote <q> [--anchor-commit <c>]`, repetible en grupo. Sin `--anchor-commit`, un `fact` o una `decision` toman el `HEAD` actual, y un `state` deja `commit: null`.
  - `repo` y `session` los rellena la herramienta desde C0. Quien llama no los escribe.
- **Normalización:** antes de medir, guardar o calcular el hash, la cita pasa a NFC y se le recortan los extremos según `White_Space`.
  - Límites: 8 bytes de mínimo contando sólo lo que no es espacio, 40 para `document`, y 300 bytes de máximo.
  - Rechazos: `anchor_quote_too_short` y `anchor_quote_too_long`. Se comprueba primero el mínimo, así que una cita que incumple los dos da `too_short` (errata E1).
  - `quote_sha256` se calcula sobre los bytes guardados.
- **Ruta:** relativa, sin `..` y sin enlaces simbólicos en ningún componente. Si no, se rechaza con `anchor_path_invalid`.
  - Para un `fact` o una `decision`, el archivo tiene que estar versionado en el commit. Si en el commit declarado la ruta es un enlace simbólico, no se sigue: `integrity` da `not_found` con `commit_blob_lacks_quote` (errata E8).
  - Para un `state`, «versionado» significa que existe en el árbol de trabajo y que Git no lo ignora, o que ya está rastreado aunque case con un patrón de ignorados. No hace falta que esté en el índice (erratas E2 y 3.1).
  - **«Ignorado»** se decide sólo con las reglas del repositorio: los `.gitignore` del árbol y el archivo de exclusiones local del clon. Nunca con el ignore global de quien ejecuta ni con `core.excludesFile`: la herramienta lo anula al preguntar a Git, para que el resultado no dependa de la máquina (errata 3.2).
- **Fallo de lectura** distinto de «no existe»: `source` es `unverifiable` con `repo_unavailable`, y `quote` e `integrity`, `source_not_verified`. Nunca `not_found`, así que nunca rechaza (errata E4). En un `state` también: si la lectura falla, `integrity` es `source_not_verified`, y si va bien, `working_tree` (errata 3.3).
- **Comprobación al escribir**, con la regla «Dónde se mira» de C3:
  - un `state` se comprueba en el árbol de trabajo, con `integrity` siempre `unverifiable` por `working_tree`;
  - un `fact` o una `decision` se comprueban en el `commit` declarado.
  - **Momento (A2; errata 2):** se comprueba **sólo al encolar**, en `remember`, fuera de todo candado. Es cuando el agente tiene la fuente delante. El vaciado puede ocurrir más tarde y en otro checkout, así que no vuelve a comprobar: escribe el registro con las anclas tal como llegaron. El `write_check` de la entrada sólo sirve para la respuesta.
  - Consecuencia declarada: si entre encolar y vaciar desaparece el commit, o un `state` cambia el árbol, lo guardado es la observación del escritor. La lectura (§4) vuelve a comprobar con el estado de ese momento.
- **Orden de los rechazos al escribir** (erratas 2 y 3). Primero se mira el número de anclas del registro y después, ancla por ancla, en su orden guardado, el primer rechazo que aplique:
  1. `anchor_too_many`, antes de comprobar ninguna. El registro rechazado no lleva `coverage` (errata 3.4);
  2. `anchor_schema_invalid`;
  3. `anchor_quote_not_normalized` (errata 3.9);
  4. `anchor_quote_too_short` / `anchor_quote_too_long`;
  5. `anchor_path_invalid`;
  6. `anchor_source_not_found`, `anchor_quote_not_found`, `anchor_integrity_not_found`.
- **Cita no normalizada** (errata 3.9). `remember` normaliza y recorta la cita que recibe, así que con lo que escribe la herramienta este rechazo no aparece.
  - Sí se rechaza una cita que llega **ya guardada** y no está en NFC o tiene espacio en los extremos. Pasa en una entrada de bandeja escrita a mano, en un `--anchor-file` que trae `quote_sha256` o en una importación.
  - Va antes de medir el tamaño.
- **Forma** (errata 2): `anchor_schema_invalid` si el `schema` es desconocido, el `kind` está fuera del conjunto cerrado, falta un campo obligatorio, `modality` está fuera de su conjunto, o falta `commit` en un `repo-file` de `fact` o `decision` (el atajo `--anchor-path` lo rellena con `HEAD`; en `--anchor-file`, quien escribe lo da). La forma se valida siempre, también para `document`.
  - **Hexadecimal en minúsculas** (errata 3.8): `quote_sha256`, `document_sha256` y `commit` van en minúsculas; en otra forma, `anchor_schema_invalid`. `manifest_sha256` y `derivation_id` son del custodio y no se validan.
- **Rechazo por comprobación** (regla 1 de C3): si una comprobación da `not_found`, `remember` falla sin encolar nada, en el orden del punto 6.
  - El registro no se guarda a medias: decide quien escribe si lo vuelve a mandar sin ancla.
  - Un `unverifiable` se acepta, y el ancla queda `unverified` o `pending`.
- **Tipos de fuente:**
  - `conversation`: nace `resolution: pending`, con `turn_id` y `seal` en `null`, y así se guarda siempre (A5, §6bis). Hasta que exista el resolutor de C2, toda ancla de conversación queda `pending`, que es un ancla válida. Al leer, una resolución `resolved` con `turn_id` nulo cuenta como turno ausente: `turn_purged` (errata 3.7).
  - `document` (A9): E1.d2 no comprueba su significado, pero sí valida su forma al escribir: los campos obligatorios (`document_sha256` y `derivation`) y `modality` dentro de `native_text`/`ocr_text`/`visual`. `locator` y `copy` no son obligatorios, y un `locator` ausente equivale a `"unknown"` (errata 3.6). Si está mal formado se rechaza con `anchor_schema_invalid` (errata 2). Su cita mínima es de 40 bytes; por debajo, `anchor_quote_too_short`, como cualquier cita. Bien formado, se guarda intacto, y al comprobarlo responde `unverified` con `kind_not_supported`.
- **Idempotencia:**
  - La clave derivada de ADR-0063 incluye el `quote_sha256` y la `source` canónica de cada ancla, en orden.
  - El `payload_sha256` de la entrada incluye el digest canónico de la lista de anclas.
  - En una entrada de `dispute`, `verdict` y el objetivo también forman parte de la clave derivada y del `payload_sha256`. Así dos dictámenes con el mismo texto y distinto veredicto no se confunden.
  - Al vaciar, «mismo registro» exige la misma clave, el mismo texto **y las mismas anclas**. Con una `--idempotency-key` explícita reutilizada con anclas distintas, el resultado es un rechazo `remember_id_collision` (`idempotency_key_other_anchors`), no un reintento, igual que #218 hizo con el `kind`.

### 3. Cobertura determinista

- Se implementan en an-kla las reglas `fact-checks-rules/v1` de agora. La norma son sus 63 vectores (`fact-checks-v1-vectors.json`, copiados en C3); la implementación de agora es sólo la referencia.
- Se calcula al escribir, sobre el texto del registro frente a la `quote` guardada de sus anclas, **nunca frente a `matched_text`** (A3). Así no depende del estado de la fuente y coincide con los 63 vectores de agora. Se guarda tal cual:
  - `coverage {total, present, level}`;
  - `missing`, ordenado por tipo y por aparición, con un máximo de 8 entradas;
  - `missing_total`.
- El registro **siempre se guarda**. Sólo el nivel `none` se sirve como aviso. Ningún nivel afirma respaldo.

### 4. Leer: frescura con tope

- **Dónde se muestra:**
  - `recall` (cuando ADR-0064 esté implementado);
  - `state show` e `history`;
  - `anchors verify <id>` (§5).
- **`retrieve` no cambia**, byte a byte. Los goldens de beta.35 tienen que seguir pasando sin regenerar.
- **Qué lleva cada ancla servida:** las tres comprobaciones con su `reason`, `at`, `match` y `matched_text`, y la `freshness` con su `reason`, con los campos que exige `vectores.json`.
- **Agregado por registro (A7):** `anchors_freshness`, la peor frescura de sus anclas, en este orden: `broken`, `stale`, `unverified`, `pending`, `fresh`. Sin anclas, el campo no existe. Es presentación de an-kla (C4a), no de C3: la frescura por ancla se sigue mostrando siempre.
- **Tope (A8):**
  - se comprueban sólo las anclas de lo que se sirve: los registros en su orden de servicio y, dentro de cada uno, las anclas en su orden guardado, hasta completar `--anchor-limit` (32 por defecto);
  - el resto sale `unverified` con `anchor_limit`, y cuenta como `unverified` en el agregado;
  - la salida declara `anchor_limit`, `anchors_checked` y `anchors_unchecked`;
  - nunca hay tope de tiempo (C3, pregunta 2).
- **Lectura por lotes:** una sola lectura de Git (`git cat-file --batch`) para todos los blobs de una respuesta, más `merge-base --is-ancestor` por commit distinto.
  - Sobre los bytes leídos se aplican, en este orden, las reglas de lectura de C3, antes de buscar la cita: más de 4 MiB da `too_large` (se mira el tamaño que declara `cat-file`, sin leer el blob); un NUL en los primeros 8000 bytes da `binary`; si no decodifica como UTF-8, `not_utf8`.
- **Rama por defecto (A4; errata E5):** es configuración de an-kla, no del contrato. Nunca se adivina por el nombre.
  - La clave `default_branch` en la configuración del proyecto del store.
  - La variable de entorno `AN_KLA_DEFAULT_BRANCH`, opcional, la sustituye. **Definida pero vacía** significa «no hay rama por defecto».
  - Clave y variable ausentes: se usa `origin/HEAD`.
  - Sin rama por defecto, o sin `origin/HEAD`: `source` es `unverifiable` con `no_default_branch`.
- **Rama del sobre:** se usa `repo.branch` de C0, como manda C3.
- **Leer nunca arranca un custodio ni un resolutor.**

### 5. Auditar: `anchors verify <id> [--all]`

- Es de sólo lectura. Comprueba de nuevo las anclas de un registro, o de todos los vigentes con `--all`. Devuelve la misma salida por ancla que §4.
- El único límite es `--anchor-limit`, el mismo tope por número de §4. No hay presupuesto de tiempo.
- Con `--all`, los registros van en orden determinista: por stream (`facts`, `events`, `episodes`), después por `enqueued_at`, con los legados al final, y después por id. Dentro de cada registro, las anclas van en su orden guardado (A8).
- Es el momento «auditoría» de C3: el único que podría consultar un custodio o un resolutor, si los hubiera. E1.d2 no instala ninguno.

### 6. Disputa nativa para dictámenes externos: `dispute`

- **Orden:** `dispute <target-id> --verdict <v> --text-file - [--anchor …]`, con `<v>` **sólo** `contradicted` o `insufficient` (A6). Un `supported` o un `not_reviewed` no entran en el store: se quedan en el libro de agora. Cualquier otro valor se rechaza con `dispute_verdict_invalid`.
- **Qué escribe:** un registro de disputa con la forma exacta de ADR-0063 D3, la que valida `disputes._valid_disputes`.
  - Es un `add` de `kind: fact` en el stream `facts`, con `disputes: {stream, target_id, target_record_sha256}`. `stream` es el del objetivo, que puede ser `facts` o `episodes`.
  - Lleva además `verdict` como campo de primer nivel del registro.
  - `kind` es siempre `fact`, también cuando el objetivo es un `state`. Por eso una entrada de `dispute` nunca entra en la lógica de casilla de ADR-0065: no jubila ninguna cabeza, y el `state` disputado sigue vigente en su casilla.
  - El objetivo sigue vigente. Nunca es una sustitución ni un campo propio de agora en la recuperación.
  - Pasa por la bandeja como cualquier `remember`, con sobre C0: el juez se identifica con `AN_KLA_AGENT_CLI`/`NAME` (p. ej. `agora`).
- **Qué no hace:** no exige juez medido. La medición es de agora; an-kla guarda el dictamen como dato no confiable.
- **Dónde se ve:**
  - `disputes list` muestra el `verdict`;
  - `recall`, `state show` e `history` marcan el objetivo como disputado, con el veredicto más reciente de cada escritor.

### 6bis. Resolución de anclas de conversación (A5): sólo esquema y vista

- Un store que sólo añade no muta un ancla guardada. La resolución es un **registro nuevo de anotación**, de la misma familia que la disputa.
- **Esquema `anchor-resolution-v1`.** Es un registro del stream `events`, para que nunca salga como hecho en `recall`:

  ```json
  {"id": "e-r-<24 hex>", "kind": "anchor_resolution",
   "anchor_resolution": {"schema": "an-kla/anchor-resolution-v1",
     "target": {"stream": "facts", "record_id": "f-r-…", "anchor_index": 0,
                "quote_sha256": "…"},
     "resolution": "resolved", "turn_id": "…", "seal": "…"},
   "an_kla_envelope": {…}}
  ```

- **Invariantes**, validadas al vaciar. Si una falla, la entrada se rechaza con `anchor_resolution_invalid`:
  - el registro objetivo existe;
  - `anchor_index` es menor que su número de anclas;
  - el ancla de ese índice es `conversation` y su `quote_sha256` coincide;
  - `resolution` es `resolved` (con `turn_id` y `seal` no nulos) o `not_found` (con los dos nulos).
- La vista de lectura aplica la **última resolución** de cada ancla, por el orden total de ADR-0065: `enqueued_at`, y después id.
- E1.d2 define sólo el esquema (`anchor-resolution-v1`) y la vista. No hay orden pública que escriba resoluciones: las escribirá el resolutor de C2 (E2/E4). Hasta entonces, toda ancla de conversación queda `pending`.

### 7. Rechazos y códigos nuevos

**Al escribir:**
- los seis de C3;
- `anchor_quote_not_normalized` (errata 3.9);
- `anchor_too_many` (más de 16) y `anchor_schema_invalid` (forma inválida, p. ej. un `document` mal formado), los dos de la errata 2 de C3;
- `anchor_input_invalid` (JSON mal formado);
- `dispute_verdict_invalid`;
- `dispute_target_missing`;
- `anchor_resolution_invalid` (sólo al vaciar una anotación de §6bis);
- `remember_id_collision` con `idempotency_key_other_anchors`.

Todos con JSON y código estable, sin rutas locales (#218 y #224).

**Al leer:** sólo el vocabulario cerrado de `reason` de C3.

### 8. Pruebas y aceptación

- **Arnés de vectores**, en `tests/`. Copia fijada por hash de `vectores.json` y `fact-checks-v1-vectors.json`, comprobada contra los sha256 de C3. Cada `expect` se exige campo a campo:
  - `cita` (24) y `busqueda` (25), unitarias;
  - `repo_file` (48), materializados con Git real en un repo desechable dentro del directorio temporal de la prueba, con las operaciones `setup` de C3;
  - `conversation` (11), con un resolutor de prueba. La resolución se inyecta como registro de anotación (§6bis);
  - `document` (17): cada vector declara `supported`.
    - E1.d2 no soporta `document`, así que el arnés ejecuta como norma los casos con `supported: false` (D17).
    - Los casos con `supported: true` (D01–D16, y D18 de la errata 1) se marcan «no aplicable a esta implementación», y se comprueba que cada uno da `unverified` con `kind_not_supported` y no rechaza el ancla bien formada.
    - Implementar `document` los volverá exigibles. E1.d2 no incluye custodio, ni siquiera de prueba: llegará con esa implementación;
  - `cobertura` (6) y los 63 de agora;
  - `frescura` (110);
  - los 6 casos de la errata 1 (`vectores-errata-1.json`, sha256 `1f723643…e6`): Q25, W24, R26, S12, S13 y D18;
  - los casos de la errata 2 (`vectores-errata-2.json`): rechazos de forma y su orden. Todos son igual de exigibles que los congelados;
  - la errata 3 no trae vectores: sus nueve lecturas se prueban con casos propios. Si un caso propio discrepa del verificador de agora, se resuelve proponiendo un vector a C3, no cambiando la lectura por cuenta propia.
  - Campos adicionales en la salida (p. ej. `seal`, `modality`) se permiten (errata E9). El arnés sólo compara los de cada `expect`.
- **Criterios del plan:**
  - el hecho del 8080 con cita del 8081 queda con `level: none` y `missing` con `{type: number, value: "8080"}`, como campos de primer nivel;
  - una `--idempotency-key` reutilizada con anclas distintas da `remember_id_collision`;
  - un `dispute` sobre un `state` no lo jubila, y el `state` sigue como cabeza de su casilla;
  - una `anchor-resolution-v1` con un índice fuera de rango da `anchor_resolution_invalid`;
  - una cita inexistente da `anchor_quote_not_found`, con la bandeja sin la entrada y el store sin cambio.
- **Decisiones del orquestador:**
  - 17 anclas dan `anchor_too_many`;
  - un `document` mal formado da `anchor_schema_invalid`;
  - `dispute --verdict supported` da `dispute_verdict_invalid`;
  - el agregado `anchors_freshness` toma la peor frescura, en el orden de §4;
  - con 40 anclas servidas se comprueban las 32 primeras en orden de servicio, y 8 salen con `anchor_limit`;
  - `AN_KLA_DEFAULT_BRANCH=""` da `no_default_branch`;
  - la cobertura se mide contra `quote`, no contra `matched_text`, con un caso en que difieren;
  - la última resolución de un ancla de conversación es la que gana en la vista.
- **Sin regresión:**
  - `retrieve` y los goldens de beta.35, sin regenerar;
  - los registros sin anclas, idénticos byte a byte a los de hoy;
  - beta.36 lee un store con anclas sin error, porque los campos de primer nivel son aditivos, igual que `slot`. Se comprueba con la etiqueta extraída, como en el release.

## 9. Ambigüedades resueltas por el orquestador (respuesta al informe 13)

| # | Pregunta del implementador | Decisión | Dónde |
|---|---|---|---|
| A1 | Más de 16 anclas | Se rechaza el registro con `anchor_too_many`, antes de comprobar ninguna (errata 2 de C3) | §1, §2, §7 |
| A2 | Comprobar al encolar o también al vaciar | Sólo al encolar. La entrada lleva las tres comprobaciones y su `at`, y el vaciado no relee | §1, §2 |
| A3 | Cobertura contra `quote` o contra `matched_text` | Contra `quote`, nunca contra `matched_text` | §3 |
| A4 | Configuración de la rama por defecto | Clave `default_branch` del proyecto del store y variable `AN_KLA_DEFAULT_BRANCH` que la sustituye; vacía significa «no hay rama por defecto», y ausentes las dos, `origin/HEAD` | §4 |
| A5 | De `pending` a `resolved` en un store que sólo añade | Registro de anotación con `record_id` e índice del ancla; la vista aplica la última. E1.d2 sólo trae el esquema y la vista | §6bis |
| A6 | `supported` como disputa | No: `dispute` sólo acepta `contradicted` e `insufficient` | §6 |
| A7 | Frescura por ancla o por registro | Las dos: por ancla siempre, y `anchors_freshness`, la peor, por registro | §4 |
| A8 | Orden del tope de 32 | Orden de servicio de los registros y orden guardado de sus anclas; la salida dice cuántas se comprobaron y cuántas no | §4 |
| A9 | Forma de `document` | Se valida sólo la forma (`anchor_schema_invalid`, errata 2); el significado responde `kind_not_supported` | §2, §7 |

## Consecuencias

- El agente ve si la prueba de un recuerdo sigue ahí, sin fiarse de quien lo escribió y sin ningún modelo.
- Escribir con ancla cuesta lecturas de Git en `remember`. Leer cuesta una lectura por lotes con tope, y `retrieve` no cambia.
- Un dictamen externo entra como dato disputado, nunca como verdad ni como sustitución.
- Pendiente fuera de E1.d2: `document` con custodio, el resolutor de `conversation` que escriba resoluciones (C2, E2/E4) y seguir renombres (v2 de C3).
