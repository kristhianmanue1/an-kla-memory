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

- **Forma:**
  - el sobre de un `state` lleva `slot`, identificador C0 `[a-z][a-z0-9_-]{0,31}`, por defecto `main`;
  - `slot` entra en la clave de idempotencia y en `payload_digest`;
  - un registro `state` sin `slot` (escrito antes de este ADR) pertenece a `main`.
- **Dueño de la casilla:** el par **(repo.id del sobre, slot)**, no el escritor.
- **Al vaciar** (paso 3 de D1, bajo `write_lock`): si existe un `state` vigente con sobre válido en la misma casilla, el nuevo lo **jubila** con `supersede` (ADR-0019).
  - Es igual si lo escribió otro agente. No abre disputa: es la excepción deliberada a D3.
  - Si hay varios vigentes en la casilla (ver §5), los jubila todos.
- **En lote:** varios `state` de la misma casilla se aplican en el orden de la bandeja (nombre de archivo: tiempo y sufijo). Cada uno jubila al anterior; el último queda vigente.
- **Respuesta:** `remember-result` añade `retired: [{id, writer, enqueued_at}]`, a quién jubiló.
  - Si quedó en cola: `resolution: pending`.
  - Si otro `state` del mismo lote lo jubiló a él: `retired_by: <id>`. El escritor sabe que su estado ya no es el actual.
- **Fuera de casilla:**
  - un `state` legado sin sobre, o con sobre inválido, no pertenece a ninguna casilla: no se jubila solo y no se sirve en `state show` (§4);
  - se retira por el camino antiguo, como los hechos legados (M1).

### 2. `state` nunca sustituye a `fact` ni a `decision`

- `remember --kind state --supersedes <id>`:
  - con target en `facts`: `rejected` con **`remember_state_over_fact`** (rc 3), y el target intacto;
  - con target `state`: no hace falta, la casilla decide. Si el target es el vigente de la misma casilla, se acepta (equivale a no pasarlo); si no, `rejected` con **`remember_state_slot_mismatch`**.
- `remember --supersedes <state>` sin `--kind`: toma `state` y el `slot` del target, y entra por la casilla, no por D3.
- `fact`/`decision` con `--supersedes <state>`: `remember_kind_mismatch`, como hoy.

### 3. Idempotencia de `state` (hallazgo del contraste, §6.1)

- La clave de un `state` incluye además el **id del estado vigente de la casilla en el momento de encolar** (`base_state`, o `null` si la casilla está vacía).
  - Volver a un texto anterior (S1 → S2 → S1) es otra intención y jubila S2.
  - Un reintento tras un corte, con la misma base, sigue siendo idempotente.
- Si al vaciar la casilla ya no tiene `base_state` como vigente (otro escribió entre medias), se aplica igual, porque la pizarra la gana el último, y la respuesta lo declara con `base_changed: true`.

### 4. `state show [--slot <s> | --all-slots] [--scope repo|all]` (sólo lectura)

- Devuelve **un registro por casilla**: el vigente del repo actual. Con `--all-slots`, todas las casillas del repo.
- Cada registro lleva `text`, `writer`, `enqueued_at`, `slot` y `retired_count`, el número de estados que la casilla ha jubilado.
- **No vacía la bandeja.** Informa de `inbox.pending` como `recall`; con estados pendientes de esa casilla, `pending_states: n`.
- Esquema nuevo `an-kla/state-result-v1`, con `untrusted_memory_data: true` y presupuesto en bytes con las reglas de ADR-0064 (stub si no cabe).
- **Casilla con más de un vigente** (§5): devuelve el de `enqueued_at` mayor y después `id`, con `conflict: [ids]`. Nunca esconde los otros.

### 5. Cuándo puede haber dos vigentes en una casilla

Sólo por caminos que no pasan por el vaciado:
- un `plan-write` que añada un `state` a mano;
- una restauración o `relocate` que una dos stores.

Se declara y se resuelve en lectura (§4) y en el siguiente `state` (que los jubila todos). No se repara en silencio.

### 6. `history <id>` (sólo lectura)

- Recorre `supersedes_map` y los registros `disputes` en las dos direcciones, desde `<id>`. Devuelve la cadena ordenada por `enqueued_at` (legado al final), con:
  - `id`, `kind`, `stream`, `slot`;
  - `writer`, `enqueued_at`;
  - `status` (`active|superseded|refuted`);
  - la arista (`supersedes`, `retired_by_slot`, `disputes`).
- Tope de nodos declarado (`--limit`, por defecto 200), con `truncated`.
- Esquema `an-kla/history-result-v1`.

## Compatibilidad

- **Sin cambio:**
  - `retrieve`, el MCP y los goldens beta.35, byte a byte;
  - el camino `plan-write` y el formato del store (el `slot` viaja en el sobre);
  - `recall` (rama E1.b), que no sirve `state` salvo con `--streams episodes`.
- `remember --kind state` sin `--slot` cambia de conducta: antes guardaba un estado más; ahora jubila el anterior de `main`. Es el requisito, y la nota de release lo dice.
- **Superficie aditiva:**
  - `--help`, `capabilities` y `schema list`;
  - `remember-result` con los campos nuevos opcionales `retired`, `retired_by` y `base_changed`.

## Aceptación (de `03-plan-entregas`, E1.d1)

1. Con 20 estados en 2 casillas escritos por 3 agentes, `state show --all-slots` devuelve 2 y `history` de cada vigente devuelve su cadena (20 en total).
2. `--kind state --supersedes <decisión>` → `remember_state_over_fact` (rc 3); la decisión sigue vigente.
3. S1 → S2 → S1 del mismo escritor: el vigente es el segundo S1.
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
- Clave de idempotencia con `base_state`: mismos bytes en un reintento tras un corte entre encolar y vaciar (arnés kill -9 de D1).
- `state show` sobre una casilla con dos vigentes creados por `plan-write`: `conflict` con los dos ids.
- Presupuesto de `state show` de 1 en 1 alrededor de los cambios de cifras, como ADR-0064.
- `retrieve`, MCP y goldens sin diff.
