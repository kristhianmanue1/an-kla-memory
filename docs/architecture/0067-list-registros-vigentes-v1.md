# ADR-0067: `list`, listado determinista de registros por stream y vigencia (#233)

- **Estado:** Aceptada por delegación del orquestador (2026-11-19), tras r1 `fix-and-retry` y r2 `proceed` (Gemini).
- **Implementación:** En la rama `feat/233-list` (sin integrar): `list`, esquema `list-result-v1`, `capabilities` y documentación de uso, con sus pruebas de aceptación
- **Fecha:** 2026-11-19
- **Decide sobre:** una orden de sólo lectura que devuelve **todos** los registros de los streams pedidos, con su vigencia, en orden total y con presupuesto exacto.
- **Depende de:** ADR-0063 (sobre C0, disputa) y ADR-0065 (casilla, vocabulario y orden de `history`). No depende de ADR-0064.

## Contexto

Antes de adoptar beta.37, un proyecto tiene que retirar los estados viejos guardados como `fact`. Para elegirlos necesita ver todos sus hechos vigentes, y hoy no hay ninguna orden que los liste:

- `retrieve` es búsqueda con presupuesto, no un listado. En el segundo piloto de adopción, `retrieve --query estado` no devolvió el único hecho vigente que era estado de trabajo, un checkpoint sin la palabra «estado».
- El método que funciona hoy lee los segmentos crudos del store y llama a `history <id> --limit 1` por cada id. Es frágil: depende del formato de los segmentos y hace una llamada por registro.

## Decisión

### 1. Orden

```
an-kla list [--streams facts[,events,episodes]] [--status active|superseded|refuted|all]
            [--kind fact|decision|state|event] [--slot <s>] [--limit <n>] [--budget <bytes>]
            [--after <cursor>] [--text]
```

Es de sólo lectura. No vacía la bandeja, no toma el candado de escritura y lee una sola revisión (`CURRENT`) bajo el gate de lectores, como `state show`.

Valores por defecto: `--streams facts`, `--status active`, sin filtro de `kind` ni de `slot`, `--limit` 1000 y `--budget` 64 KiB.

`--kind` usa el vocabulario de `history`: `fact`, `decision`, `state` y `event`, este último para el stream `events` (L67-06). Un `--kind` que no puede darse en los streams pedidos, por ejemplo `--kind state --streams facts`, devuelve una lista vacía con `total: 0`, no un error.

### 2. Qué devuelve cada registro

Los mismos campos que un nodo de `history`, con el mismo significado:
- `stream`, `id`, `kind`, `slot`, `writer`, `enqueued_at`;
- `status`: `active`, `superseded` o `refuted`.

Y además:
- `superseded_by`: el id que lo sustituyó, si lo hay.
- `disputes_count`: número de disputas vigentes que lo apuntan, contadas como en `disputes list`. No se llama `disputed`, porque en ADR-0066 ese campo es la lista de veredictos de un registro servido, y aquí sólo se da el número (L67-02). Para ver las disputas: `disputes list` o `history`.
- `anchors_count` y `coverage_level`, si tiene anclas (ADR-0066). No se comprueba ninguna ancla, porque `list` no lee Git: para comprobarlas está `anchors verify`.
- `text_bytes`.
- `text`, **sólo con `--text`**. Sin él, la salida no lleva texto de memoria y cabe en el presupuesto aunque los registros sean largos.

Un registro legado, sin sobre válido, lleva `kind` el del stream, `writer` y `enqueued_at` nulos, y `legacy: true`.

### 3. Orden total (L67-01)

**Partición por stream**, en el orden en que se pidieron en `--streams`. Dentro de cada stream, la clave de `history` (`history._order`):
1. los registros con sobre antes que los legados;
2. `enqueued_at` ascendente;
3. `id`.

No se añade `stream` como criterio, porque dentro de una partición es constante. Es un orden distinto del de `history`, que mezcla streams: `list` los separa para que «todos los hechos» se lea de una pieza.

El resultado no depende ni del orden del sistema de archivos ni del de los segmentos.

### 4. Presupuesto, límite y paginación

- **Presupuesto exacto en bytes** de la salida canónica, como `state show` y `history`. Si no cabe, se podan registros **del final del orden**. No se esconde ninguno sin decirlo.
- **Respuesta vacía que no cabe:** si ni la respuesta vacía cabe en el presupuesto, `list_budget_too_small`.
- **Límite:** `--limit` corta por número antes del presupuesto.
- **Totales:** la salida declara `total` (los que pasan los filtros), `returned`, `truncated` y `excluded: {limit, budget}`, que cuenta cuántos quedaron fuera por cada causa (L67-07).
- **Paginación** (L67-05): si `truncated` es `true`, la salida trae `next`, un cursor opaco.
  - El cursor lleva la revisión leída y la clave del último registro devuelto.
  - `--after <cursor>` continúa justo después de esa clave, con los mismos filtros.
  - Si `CURRENT` cambió entre una página y la siguiente, la respuesta es `list_cursor_stale`, y quien llama empieza de nuevo. Así nunca se mezclan dos revisiones en un mismo listado.
  - Un cursor mal formado, o pedido con otros filtros, da `list_cursor_invalid`.

### 5. Contrato

- **Esquema nuevo:** `list-result-v1`. Campos:
  - `schema`, `revision`, `used_bytes`, `items` y `untrusted_memory_data: true`;
  - `filters`: `{streams, status, kind, slot, limit, budget, text}` (L67-07);
  - `total`, `returned`, `truncated`, `excluded: {limit, budget}` y `next`, que es nulo si no hay más.
- **Errores** (L67-03): por el mismo canal que `state show` e `history` (`StateReadError`: `an-kla error: <código>` en stderr, rc 1), sin rutas locales. Códigos:
  - de entrada: `list_streams_invalid`, `list_status_invalid`, `list_kind_invalid`, `list_slot_invalid`, `list_limit_invalid` (entero positivo, máximo 10 000) y `list_budget_invalid` (entero positivo);
  - de cursor: `list_cursor_invalid` y `list_cursor_stale`;
  - de presupuesto: `list_budget_too_small`.
- **Sin cambios:** `retrieve`, el MCP y la plantilla gestionada.

## Consecuencias

- El paso 2a del procedimiento de adopción pasa a ser una sola orden: `an-kla list --status active` (con `--text` para clasificar).
- Es una lectura más del store, sin escritura ni Git.
- Con el valor por defecto, que no incluye el texto, la salida es estable y corta.

## Pruebas de aceptación

- Un store con hechos vigentes, sustituidos y refutados: `--status all` los lista todos con su `status` y su `superseded_by`; `--status active`, sólo los vigentes.
- Un checkpoint vigente sin la palabra «estado» aparece en `list`.
- `--streams facts,episodes --kind state --slot main` lista sólo los `state` de esa casilla.
- Orden determinista: el mismo store da la misma salida byte a byte, con los legados al final.
- Presupuesto: nunca se supera. Al podar se declaran `truncated`, `excluded.budget` y `next`. Un presupuesto mínimo da `list_budget_too_small`.
- Sin `--text` no sale texto de memoria. Con `--text`, el texto exacto.
- **Disputas:** un registro con dos disputas vigentes lleva `disputes_count: 2`; uno sin disputas, `0`.
- **Anclas:** un registro con anclas lleva `anchors_count` y `coverage_level`, y `list` no invoca a Git (comprobado sin repositorio). Uno sin anclas no lleva esos campos.
- **Legados:** un registro legado lleva `legacy: true`, `writer` y `enqueued_at` nulos, y sale al final de su stream.
- **`--limit`:** con 5 vigentes y `--limit 2` salen 2, con `excluded.limit: 3`, `truncated: true` y `next`.
- **Paginación:** recorrer con `--after` hasta `next` nulo devuelve exactamente lo mismo que una sola página grande, sin repetir ni saltar. Con un `remember` entre dos páginas, `list_cursor_stale`.
- **Validación:** cada flag inválido da su código y rc 1, sin rutas. `--kind state --streams facts` da lista vacía, sin error.
- `retrieve` y los goldens, sin cambios.
