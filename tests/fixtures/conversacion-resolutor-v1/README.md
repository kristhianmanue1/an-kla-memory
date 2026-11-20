# `memoria/conversacion-resolutor/v1` — resolver y comprobar citas de conversación

**Estado: congelado el 2026-11-20.** `vectores.json`: 31 casos, sha256
`1e9187a924f30fd7c3bed789487a3879f66d16f70f85efd0b08a7f1768de7e78`. Desde aquí este README y
los vectores no se editan: las precisiones van a un `ERRATAS.md` y los casos nuevos, a
archivos aparte.

Congelado tras tres pasadas del prototipo del custodio (skopos; la tercera, 30 casos sin
discrepancias y una sesión sintética con subagente) y dos rondas externas (Gemini:
`fix-and-retry`, luego `proceed` con tres notas, aplicadas). La primera redacción se
reescribió con:

- **Segunda pasada del prototipo del custodio** (skopos): el contrato se puede implementar;
  el sello por mensaje funciona (medido en 3714 turnos y en una sesión viva); lo pegado no
  siempre viene marcado; en las sesiones de agentes orquestados, lo que entra por el canal de
  usuario lo escribe otro agente.
- **Ronda externa** (Gemini, `fix-and-retry`): resolver con la sesión abierta contradecía el
  caso S03 de `ancla/v1`; `seal_scope` no cabe en la forma cerrada del ancla; faltaba la fila
  de «cita ausente»; motivos fuera del vocabulario de `ancla/v1`; sesiones de subagente;
  respuestas sin forma cerrada.

## Para qué

`memoria/ancla/v1` define la cita de tipo `conversation`: nace `pending` y «el resolutor» la
pasa a `resolved` (con `turn_id` y `seal`) o a `not_found`. Este contrato es ese resolutor.
No cambia la forma del ancla ni sus casos; lo que precisa de `ancla/v1` está en su errata 6.

## Principios

1. **Quien guarda recuerdos no lee conversaciones.** El resolutor es un programa del
   custodio: un proceso por petición, JSON en UTF-8 por entrada y salida estándar, código de
   salida 0, salida de error ignorada, sin servicios, sin red, sin escribir nada. Plazo: 10 s.
   Ejecutable sólo por tabla de configuración explícita (`custodio → orden`).
2. **La cita la busca el resolutor, y el texto no sale de su proceso.** La respuesta no lleva
   texto de ningún mensaje.
3. **La cita es de un solo mensaje.**
4. **Quién habló lo dice el custodio, con clasificación cerrada.** Lo que no reconoce no es
   voz del usuario.
5. **No poder comprobar no es fallar.** Sólo una contradicción comprobada da `broken`.

## Las voces (`speaker`)

| Valor | Qué es |
|---|---|
| `user` | lo tecleado en el canal de usuario de una sesión raíz, **quitados** los bloques que inyecta el arnés y lo que viene marcado como pegado |
| `pasted` | texto marcado como pegado dentro de un mensaje del usuario |
| `automatic` | notificaciones y mensajes que genera el arnés con forma de mensaje de usuario |
| `compact_summary` | resúmenes de compactación escritos por el sistema |
| `local_command` | salidas de órdenes locales |
| `subagent` | **todo** mensaje de una sesión de subagente: su «usuario» es el agente padre |
| `assistant` | texto del asistente |
| `unknown` | cualquier otra cosa |

El resolutor **sólo resuelve contra `user`**. El custodio debe reconocer una sesión de
subagente por las marcas de su formato; si no puede asegurar que una sesión es raíz, sus
mensajes son `unknown`.

**Lo que `user` no prueba** (límite que quien guarda debe conocer):

- **No prueba que hubiera una persona al teclado.** En la sesión de un agente orquestado, lo
  que entra por el canal de usuario lo envía otro agente. El resolutor dice *en qué sesión y
  por qué canal* entró la frase. Que esa sesión sea una donde habla el Operador es política de
  quien guarda (por ejemplo, una lista de sesiones del Operador), no un hecho de este contrato.
- **Un pegado sin marca del arnés es indistinguible de lo tecleado.**

## Petición inválida

Si la petición no es un objeto con sus claves, `quote_sha256` no es el sha256 de los bytes
UTF-8 de `quote`, la cita incumple los tamaños de `ancla/v1` o `session` no tiene la forma de
un `session.id` de C0, el resolutor responde `{"schema": "invalid", "error": "<código>"}` con
código de salida 0. Quien llama lo trata como fallo del resolutor. `session` se valida antes
de tocar ninguna ruta.

## Operación `resolve` (al escribir, y al auditar un ancla `pending`)

Petición: `{"schema": "memoria/conversacion-resolutor/v1", "op": "resolve", "session": "…",
"quote": "…", "quote_sha256": "…"}`.

Respuesta (exactamente estas claves, siempre):

```json
{"schema": "memoria/conversacion-resolutor/v1",
 "session": "known",
 "resolution": "resolved", "reason": null,
 "turn_id": "…", "seal": "m1:…",
 "speaker": "user", "match": "literal",
 "candidates": {"user": 1, "pasted": 0, "other": 2},
 "tail": "open"}
```

- `resolved`: la cita está, con los perfiles de búsqueda de `ancla/v1`, en un mensaje `user`
  de esa sesión, **y ese mensaje ya está sellado**. Si está en varios, el primero (como fija
  `ancla/v1`). `turn_id`, `seal` y `match` van rellenos; `speaker` es `user`; `reason`, nulo;
  `candidates.user` ≥ 1 (sólo cuenta mensajes ya sellados: uno que contiene la cita pero el
  custodio aún no puede sellar no se cuenta, y la respuesta es `pending`). Vale con `tail: open`: lo que se sella es el mensaje, que no cambia
  desde que se escribe.
- `not_found`: la sesión está cerrada entera (`tail: closed`) y la cita no está en **ninguna**
  voz (`candidates` todo a 0).
- `pending`, con `reason`: `tail_open` (no está en lo escrito hasta ahora),
  `only_in_other_voice` (está, pero no en voz `user`; vale también con la sesión cerrada:
  nunca es `not_found`), `origin_unreadable` (ilegible o mayor que el tope del custodio).
  `candidates.user` es 0. Con `origin_unreadable`, `tail` es `open`: lo que no se sabe
  cerrado se trata como abierto.
- Sesión que el custodio no tiene, o cuyo origen ya no existe (no los distingue):
  `session: "unknown"`, `resolution: "pending"`, `reason: "session_unavailable"`,
  `tail: null`, `candidates` a 0.
- `seal`: cadena opaca del custodio que **lleva dentro su propio tipo** (por ejemplo
  `m1:<hex>` para «sha256 de los bytes exactos del registro del mensaje en el origen»). Quien
  llama la guarda en el `seal` del ancla tal cual. Así la forma del ancla no cambia y el
  custodio puede cambiar de tipo sin romper sellos antiguos.
- `candidates`: en cuántos mensajes aparece la cita, por voz (`other` suma las demás).
  Informativo.

Una respuesta que no cumple estas reglas es un fallo del resolutor.

## Operación `verify` (al auditar un ancla `resolved`)

Petición: `{schema, op: "verify", session, turn_id, seal, quote, quote_sha256}`.

Respuesta (exactamente estas claves):

```json
{"schema": "memoria/conversacion-resolutor/v1",
 "session": "known", "seal": "match", "quote": "found", "speaker": "user", "reason": null}
```

- `seal`: `match`; `mismatch` (el mensaje existe y sus bytes son otros); `turn_missing` (la
  sesión existe, **se leyó entera** y ese mensaje no está; entonces `quote: "unknown"` y
  `speaker: null`); `unknown` (el sello es de un tipo que el custodio ya no calcula).
- `quote`: `found` o `absent`, sobre el **texto completo** de ese mensaje, en cualquier voz.
  (Si se buscara sólo en la voz `user`, un mensaje que el custodio reclasifica saldría
  «cita ausente» y por tanto roto, sin que nada haya cambiado.)
- `speaker`: la voz en que el custodio clasifica **hoy** el tramo del mensaje donde está la
  cita; si la cita no está, la del mensaje.
- Sesión no disponible: `session: "unknown"`, `seal: "unknown"`, `quote: "unknown"`,
  `speaker: null`, `reason: "session_unavailable"`.

## Qué hace quien llama (traducción a `ancla/v1`)

| Situación | Ancla | `source` | `quote` | `integrity` | Frescura |
|---|---|---|---|---|---|
| `resolve` → `resolved` | `resolved`, con `turn_id` y `seal` | `verified` | `verified` | `verified` | `fresh` |
| `resolve` → `not_found` | `not_found` | `unverifiable` (`session_lacks_quote`) | `unverifiable` | `unverifiable` (`session_lacks_quote`) | `broken` |
| `resolve` → `pending`, o sin resolutor, o fallo | sigue `pending` | `unverifiable` (`resolution_pending`) | `unverifiable` | `unverifiable` (`resolution_pending`) | `pending` |
| `verify` → `match` y `found` | sin cambio | `verified` | `verified` | `verified` | `fresh` |
| `verify` → `mismatch` | sin cambio | `verified` | según `quote` | `not_found` (`seal_mismatch`) | `broken` |
| `verify` → `match` y `absent` | sin cambio | `verified` | `not_found` (`quote_absent`) | `verified` | `broken` |
| `verify` → `turn_missing` | sin cambio | `not_found` (`turn_purged`) | `unverifiable` | `unverifiable` (`turn_purged`) | `broken` |
| `verify` → `seal: unknown` y `found` | sin cambio | `verified` | `verified` | `unverifiable` (`seal_unverifiable`) | `unverified` |
| `verify` → `seal: unknown` y `absent` | sin cambio | `verified` | `not_found` (`quote_absent`) | `unverifiable` (`seal_unverifiable`) | `broken` |
| `verify` → sesión no disponible | sin cambio | `unverifiable` (`session_unavailable`) | `unverifiable` | `unverifiable` (`session_unavailable`) | `unverified` |
| ancla `resolved`, sin resolutor | sin cambio | `unverifiable` (`no_verifier`) | `unverifiable` | `unverifiable` (`no_verifier`) | `unverified` |
| ancla `resolved`, fallo del resolutor | sin cambio | `unverifiable` (`resolver_error`) | `unverifiable` | `unverifiable` (`resolver_error`) | `unverified` |

- **Fallo del resolutor:** plazo agotado, código de salida distinto de 0, salida que no es
  JSON, objeto de fallo, otro `schema` o respuesta incoherente. Nunca `broken`, nunca una
  excepción.
- El motivo detallado de un ancla que sigue `pending` (`tail_open`, `only_in_other_voice`,
  `session_unavailable`, `origin_unreadable`, `no_verifier`, `resolver_error`) se informa en
  un campo aparte (`detail`); las comprobaciones llevan `resolution_pending`, como en
  `ancla/v1`.
- **Cuándo:** al escribir se llama a `resolve`; un ancla que queda `pending` es válida y se
  guarda. Al auditar, las `pending` se reintentan con `resolve` y las `resolved` se comprueban
  con `verify`. **Al leer no se llama a nadie**: se sirve lo guardado con su fecha.
- **Un intento que no concluye no sustituye a un resultado concluyente.** Concluye el
  resultado en que el ancla pasa a `not_found`, o alguna de las tres comprobaciones es
  `not_found`, o las tres son `verified`. Los orígenes
  de conversación se borran a plazo (30 días en Claude Code por defecto): pasado ese plazo,
  una cita resuelta se sigue sirviendo como se comprobó, con la fecha de esa comprobación.
- **La voz viaja aparte.** El ancla no guarda `speaker`; quien llama lo conserva junto al
  resultado. Quien necesite voz de usuario (una orden del Operador) exige además
  `speaker: user` en la última comprobación concluyente; si el custodio reclasifica el
  mensaje, la cita sigue `fresh` y deja de valer como orden.

## Para órdenes del Operador (recomendaciones a quien guarda, no reglas de este contrato)

- Exigir `resolved` con `speaker: user`, y una sesión que la política reconozca como del
  Operador.
- Exigir citas largas (40 bytes útiles o más) y avisar si `candidates.user` es mayor que 1:
  una cita corta («adelante») casa con el primer mensaje que la contenga, no con el que
  autorizó lo que se afirma.
- Lo que llega pegado no es una orden comprobable en v1.

## Límites declarados

- **No prueba ante terceros.** El sello lo comprueba el propio custodio. Sin firma en v1.
- **`not_found` es raro**: casi ninguna sesión se cierra entera. Lo ausente queda `pending`.
- **El sello es de bytes exactos del origen.** Reescribir o reformatear el archivo de una
  sesión con una herramienta ajena al asistente rompe el sello (`seal_mismatch`, `broken`):
  es una alteración del origen, y así se trata.
- **La clasificación de voces depende de las marcas de cada asistente**; por eso lo
  desconocido nunca es `user`.
- **Cobertura:** la del custodio. Un asistente que el custodio no lee es sesión no disponible.
- **Sin aislamiento por proyecto:** una sesión vale sea cual sea el proyecto donde ocurrió.
- **Sólo voz del usuario**; citar al asistente o lo pegado queda fuera de v1.
- **Tamaño:** el tope de lectura del origen es del custodio; por encima, `origin_unreadable`.

## Vectores

`vectores.json`: 31 casos. Cada uno da el ancla de partida, lo que responde el resolutor (o
cómo falla), si había un resultado concluyente guardado, y lo exigible: operación llamada,
ancla resultante, las tres comprobaciones con su motivo, frescura, voz, detalle y qué se
sirve después (`new` o `stored`). Escritos a mano y contrastados por `construir_vectores.py`
(`--check`).

**Pruebas obligatorias que un archivo de casos no fija:** del lado de quien llama, las de
proceso (plazo, código de salida, salida inválida, salida de error ruidosa, nombre del
custodio fuera de rutas y órdenes). Del lado del custodio, con una sesión sintética: cita
sólo en lo pegado, sólo en un bloque del arnés, sólo en un resumen, en una sesión de
subagente, en el último mensaje con la sesión abierta, y el sello intacto tras crecer la
sesión.
