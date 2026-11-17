# ADR-0065: Estado de una casilla, `history` y lectura del estado (E1.d1)

- **Estado:** Propuesta
- **Implementación:** No iniciada
- **Fecha:** 2026-11-16
- **Decide sobre:**
  - `remember --kind state [--slot <s>]`, que jubila sola la casilla (repo, slot);
  - el rechazo tipado de `state` sobre `fact`/`decision`;
  - `history <id>`;
  - `state show`, una lectura del estado que no depende de `recall`.
- **Depende de:** ADR-0063 (bandeja, sobre C0, D3). No depende de ADR-0064.
- **Contrato:** C1 «Estado de una sola casilla» del esfuerzo de memoria agéntica (contrato externo).

## Contexto

De las 28 sustituciones del consumidor, 26 eran «estado siguiente». Al pedir el estado, el bueno salía cuarto.

Hoy `state` ya es un `kind` de `remember`: va al stream `episodes` (`KIND_STREAMS`) y el sobre guarda su `kind`. Pero:
- no tiene casilla;
- un `state` nuevo no jubila al anterior;
- `--kind state --supersedes <hecho>` se rechaza sólo por el genérico `remember_kind_mismatch` (stream distinto);
- sin `--kind`, un `--supersedes` sobre un `state` toma su tipo y entra por D3, con lo que un estado ajeno abre disputa.

## Decisión

### 1. Casilla

- **Forma:** un registro `state` lleva el campo de primer nivel `slot`
  (identificador C0 `[a-z][a-z0-9_-]{0,31}`, por defecto `main`), como
  `disputes` de ADR-0063. **El sobre `record-envelope-v1` no cambia**
  (`additionalProperties: false`): `slot` no va dentro. Un `state` sin
  `slot` (escrito antes de este ADR) pertenece a `main`.
- **Dueño de la casilla:** el par **(repo.id del sobre, slot)**, no el
  escritor.
- **Cabeza de la casilla:** el `state` vigente con sobre válido de la
  casilla con `enqueued_at` mayor y después `id` mayor. Es el que sirve
  `state show` (§4) y el único que un `state` nuevo jubila.
- **Al vaciar** (paso 3 de D1, bajo `write_lock`), un `state` nuevo jubila
  la cabeza con `supersede` (ADR-0019), la haya escrito quien la haya
  escrito, sin abrir disputa: es la excepción deliberada a D3.
- **Un `state` por casilla y transacción.** `write-proposal-v2` prohíbe
  sustituir un registro del mismo lote (`supersedes:intra_batch_forbidden`,
  ADR-0054 §2) y repetir destino (`supersedes:duplicate_target`). Por eso
  el vaciado **parte el lote**: al encontrar, en orden de la bandeja
  (nombre de archivo: tiempo y sufijo), un segundo `state` de una casilla
  ya tocada en el lote en curso, compromete lo acumulado y abre una
  transacción nueva, en la misma invocación y con el candado tomado. Cada
  `state` jubila la cabeza que dejó el anterior; el último encolado queda
  vigente. Es determinista (orden de la bandeja) y declara su coste: una
  transacción más por cada `state` repetido de una casilla en un vaciado.
- **Respuesta:** `remember-result` añade `retired: {id, writer,
  enqueued_at}` (a quién jubiló) y, si un `state` posterior del mismo
  vaciado lo jubiló a él, `retired_by: <id>`.
- **Fuera de casilla:** un `state` legado sin sobre o con sobre inválido no
  pertenece a ninguna casilla: no se jubila solo ni se sirve en `state
  show`; se retira por el camino antiguo.

### 2. `state` nunca sustituye a `fact` ni a `decision`

- `remember --kind state --supersedes <id>`:
  - target en `facts` → `rejected` con **`remember_state_over_fact`**
    (rc 3), target intacto;
  - target `state` no vigente → `invalid_supersede_target` (como hoy);
  - target `state` vigente de **otra** casilla → **`remember_state_slot_mismatch`**;
  - target = la cabeza de la misma casilla → se acepta (equivale a no
    pasarlo);
  - target `state` vigente de la misma casilla que no es la cabeza (hay
    conflicto, §5) → `remember_state_slot_mismatch`, para no jubilar en
    silencio otro que el que se sirve.
- `remember --supersedes <state>` sin `--kind`: toma `state` y el `slot`
  del target y entra por la casilla, no por D3.
- `fact`/`decision` con `--supersedes <state>`: `remember_kind_mismatch`,
  como hoy.

### 3. Idempotencia de `state` (contra el último del mismo escritor en la casilla)

La clave de ADR-0063 (`derive_idempotency_key`: repo, agente, sesión,
kind, texto y target) deduplica contra **cualquier** registro previo: con
ella, S1 → S2 → S1 del mismo escritor y la misma sesión respondería
`already_committed` y dejaría S2 como actual. Deduplicar sólo contra la
cabeza tampoco basta: un reintento tardío de S1 tras un corte, cuando otro
agente ya escribió X, reactivaría S1 sobre X (pisada). Para `state`:

- **Clave:** la de ADR-0063 con `slot` añadido (`derive_idempotency_key`
  recibe `slot` para `kind: state`; el mismo texto en dos casillas son dos
  intenciones).
- **Regla, al vaciar y bajo el candado:** una entrada `state` es la misma
  intención si y sólo si el **último `state` comprometido por el mismo
  escritor** (`repo.id` + `agent.name`) **en esa casilla**, vigente o
  jubilado, lleva la misma clave. Entonces responde `already_committed`
  con el id de ese registro (y `retired_by` si ya no es la cabeza) y no
  escribe nada. Si no, se aplica y jubila la cabeza.
- **Casos:**
  - reintento tras un corte posterior al commit → su último es el propio
    registro → `already_committed`, aunque otro haya escrito después: no
    pisa a nadie, y `retired_by` le dice que ya no es el actual;
  - dos copias pendientes de la misma entrada → la segunda ve la primera →
    `already_committed`;
  - S1 → S2 → S1 → su último es S2 → se aplica; S1 vuelve a ser el actual;
  - límite declarado: repetir a propósito el mismo texto en la misma
    sesión cuando su último ya es ese texto (otro escribió en medio) es
    indistinguible de un reintento y responde `already_committed` con
    `retired_by`. Para reafirmarlo se usa otra `--idempotency-key`.
- **Id del registro:** `ep-r-` + los 24 primeros hex de
  `sha256(clave + ":" + (id de la cabeza jubilada o "none"))`, resuelto
  bajo el candado. Dos S1 en momentos distintos tienen ids distintos; el
  mismo reintento, el mismo. Por eso una entrada `state` que **queda en
  cola** no anuncia `record_id` (`resolution: pending`); con vaciado en la
  misma invocación, sí.
- **Orden entre escritores:** gana el último **encolado** (orden de la
  bandeja). No hay rechazo por concurrencia: la casilla es una pizarra y
  lo jubilado queda en `history` con `retired_by`.
- **Bandeja:** `inbox-entry-v1` no admite campos extra
  (`additionalProperties: false`), así que una entrada con `slot` usa
  `an-kla/inbox-entry-v2` (v1 más `slot` opcional). v1 se sigue
  aceptando. Un binario anterior no lee v2: la regla de la nota de release
  («`inbox drain` y pendientes 0 antes de bajar de versión») lo cubre.

### 4. `state show [--slot <s> | --all-slots] [--scope repo|all] [--budget <n>]` (sólo lectura)

- Un registro por casilla: la cabeza (§1) del repo actual; con
  `--all-slots`, todas las casillas del repo, en orden de `slot`.
- Cada uno lleva `id`, `slot`, `text`, `writer`, `enqueued_at`,
  `retired_count` (estados que esa casilla ha jubilado) y, si la casilla
  tiene más de un vigente, `conflict: [ids]` (§5).
- **No vacía la bandeja**; informa de `inbox.pending` y, por casilla, de
  `pending_states`.
- Esquema `an-kla/state-result-v1` con `untrusted_memory_data: true`.
- **Presupuesto** (`--budget`, por defecto 4000): la salida JSON completa,
  con su salto de línea final, nunca supera `--budget`. Se decide con la
  longitud exacta de la respuesta serializada, con cotas superiores en
  lugar de los contadores aún desconocidos (`used_bytes` = el
  presupuesto; `excluded.budget` = número de casillas). Si la entrada
  completa de una casilla no cabe, sale su **stub** `{slot, id,
  enqueued_at, truncated: true}`; si ni el stub cabe, se cuenta en
  `excluded.budget`. Por debajo de la respuesta vacía:
  `state_budget_too_small` (rc 1, como los errores de `recall`).

### 5. Cuándo puede haber dos vigentes en una casilla

Sólo por caminos que no pasan por el vaciado: un `plan-write` que añada un
`state` a mano, o una restauración o `relocate` que una dos stores. **No
se repara solo:** `supersede` tiene un único destino por registro y un
`state` nuevo jubila sólo la cabeza. Los demás vigentes siguen en
`conflict` en `state show` y en `remember-result`
(`conflict_remaining`), y se retiran por el camino antiguo. Nunca se
elige en silencio.

### 6. `history <id> [--limit <n>]` (sólo lectura)

- **Grafo:** nodos = registros; aristas dirigidas `supersedes` (de
  `supersedes_map`, nuevo → antiguo, incluida la jubilación por casilla) y
  `disputes` (del campo `disputes`, disputa → target).
- **Recorrido:** BFS desde `<id>` sobre las aristas en los dos sentidos,
  con conjunto de visitados (un ciclo no se recorre dos veces), hasta
  `--limit` nodos (por defecto 200; con `truncated: true` si se corta). El
  orden de expansión es el de los nodos ordenados (abajo), así que el
  corte también es determinista.
- **Salida** (`an-kla/history-result-v1`): `nodes` ordenados por
  `enqueued_at` ascendente, los legados después, y por `id`; cada nodo con
  `id`, `kind`, `stream`, `slot`, `writer`, `enqueued_at` y `status`
  (`active|superseded|refuted`). `edges` como `{from, to, type}`, ordenadas
  por `(from, to, type)`.
- `edges` sólo contiene aristas con sus dos extremos en `nodes`.
- Presupuesto con las reglas de §4.


## Compatibilidad

- **Sin cambio:**
  - `retrieve`, el MCP y los goldens beta.35, byte a byte;
  - el camino `plan-write`, el formato del store y `record-envelope-v1`;
  - `recall` (rama E1.b), que no sirve `state` salvo con `--streams episodes`.
- `remember --kind state` sin `--slot` cambia de conducta: antes guardaba un estado más; ahora jubila el anterior de `main`. Es el requisito, y la nota de release lo dice.
- **Superficie aditiva:**
  - `--help`, `capabilities` y `schema list`;
  - `remember-result` con los campos nuevos opcionales `retired`, `retired_by` y `conflict_remaining`; una entrada `state` en cola no anuncia `record_id` (§3);
  - `slot` como campo de primer nivel del registro: `record-envelope-v1` sin cambio; `inbox-entry-v2` nuevo para entradas con `slot` (§3). Un lector anterior lo ignora como ignora `disputes`.

## Aceptación (de `03-plan-entregas`, E1.d1)

1. Con 20 estados en 2 casillas escritos por 3 agentes, `state show --all-slots` devuelve 2 y `history` de cada vigente devuelve su cadena (20 en total).
2. `--kind state --supersedes <decisión>` → `remember_state_over_fact` (rc 3); la decisión sigue vigente.
3. S1 → S2 → S1 del mismo escritor: el vigente es el segundo S1; un
   reintento tras un corte posterior al commit (arnés kill -9 de D1) no
   duplica.
4. Dos agentes escriben en `main` en el mismo lote: el último es el vigente; el primero recibe `retired_by`.
5. Sobre una copia del store del consumidor (la corre su capitán), «¿en qué vamos?» devuelve el estado bueno.
   - Requiere que sus estados viejos, que son `fact`, se retiren antes por el camino antiguo. Si no, `state show` está vacío y lo dice.
6. `retrieve` sin cambio, byte a byte.

## Nota para agentes y para el release

- Una casilla por línea de trabajo: dos agentes que trabajan a la vez en
  cosas distintas del mismo repo usan `--slot` distintos. Con `main` para
  todos, la pizarra la gana el último que escribe (es el diseño).
- Los estados escritos antes como `fact` no se jubilan con un `state`
  (§2): se retiran por el camino antiguo antes de adoptar la casilla.
- La enseñanza en el bloque gestionado y el `--slot` del lanzador son E1.c.

## Por qué no

- **Casilla por escritor:** un cambio de nombre de agente deja dos estados «actuales». La decisión es del orquestador y la mantengo.
- **Jubilar por `--supersedes` explícito:** es lo que el consumidor ya hacía y falló, porque el agente olvida el id.
- **Que `recall` sirva el estado:** mezcla una pizarra con una búsqueda. `state show` no puntúa ni depende del analizador.

## Test de regresión

- Los puntos 1–4 y 6 de «Aceptación», con stores desechables en un temporal.
- Idempotencia contra el último del mismo escritor: corte antes y después del commit (arnés kill -9 de D1), dos copias pendientes, S1 → S2 → S1, y reintento tardío de S1 tras un X de otro agente (X sigue vigente).
- Mismo texto en dos casillas: dos registros.
- Vaciado con tres `state` de la misma casilla y uno de otra: tres transacciones, último encolado vigente, `retired_by` en los dos primeros.
- `history` con un ciclo creado por `plan-write`: termina y lo recorre una vez; mismo resultado en dos invocaciones.
- `state show` sobre una casilla con dos vigentes creados por `plan-write`: `conflict` con los dos ids.
- Presupuesto de `state show` de 1 en 1 alrededor de los cambios de cifras, como ADR-0064.
- `retrieve`, MCP y goldens sin diff.
