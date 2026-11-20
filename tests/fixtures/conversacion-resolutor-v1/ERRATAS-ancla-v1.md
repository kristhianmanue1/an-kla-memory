# Erratas de `memoria/ancla/v1`

El contrato se congeló el 2026-11-16 (`798e247`). `README.md` y
`vectores.json` no se editan desde entonces; lo que sigue **prevalece**
sobre el README donde lo contradiga. `vectores.json` conserva su sha256
(`948a1130…32a9`): los casos nuevos van en archivos aparte.

## Errata 0 — 2026-11-16 (redacción, sin efecto)

El commit `168e199`, posterior al congelado, cambió una frase del README
(«que se copiará aquí con su digest al congelar» → «copiado aquí byte a
byte al congelar») sin registrarlo. No altera ninguna regla ni ningún
vector. Lo señaló el segundo implementador; queda registrado aquí.

## Errata 1 — 2026-11-18 (precisiones del segundo implementador)

Origen: agora implementó el contrato por su cuenta (241 de 241 casos con
Git real) y su revisor externo elevó nueve puntos donde el texto no
bastaba o no coincidía con el modelo de referencia. Ningún vector
congelado cambia. Casos nuevos: `vectores-errata-1.json`, sha256
`1f7236430cd9d9a6c23c8e2b7000f43e83306dfd86d67e44a6928d654eb145e6`
(exigibles igual que los congelados). `construir_vectores.py` pasa a
sha256 `b7150cef985576f49fcfe4884e3acc7e6c312504113e6a546a6fca5d923e9a87`
y sigue reproduciendo `vectores.json` byte a byte (`--check`).

| # | Punto | Regla | Caso |
|---|---|---|---|
| E1 | Cita a la vez de más de 300 bytes y con menos del mínimo de bytes útiles | Se comprueba primero el mínimo: `anchor_quote_too_short` | Q25 |
| E2 | `state` sobre un archivo nuevo, sin añadir al índice y no ignorado | Cuenta. Para un `state` «versionado» significa: existe en el árbol de trabajo y Git no lo ignora. El índice no interviene | W24 |
| E3 | Sesión sellada con un turno purgado y **otro** turno que contiene la cita | Se resuelve con ese turno. Un turno purgado sólo impide concluir `not_found`; el README («con algún turno purgado… sigue `pending`») era demasiado estricto | S12 |
| E4 | La fuente está, pero Git o el sistema de archivos fallan al leerla (error distinto de «no existe») | `source: unverifiable` con `reason: repo_unavailable`; `quote` e `integrity`, `source_not_verified`. Nunca `not_found`. No hay vector: depende de provocar un fallo de E/S | — |
| E5 | `default_branch` | En la configuración de la herramienta: clave **ausente** = usar `origin/HEAD`; valor **nulo** = no hay rama por defecto (`no_default_branch`). En los vectores, `default_branch: null` es el segundo caso | R17 (ya existía) |
| E6 | `document` con copia correcta y custodio en marcha que no conoce el documento | `source: verified` (la copia existe); `quote` e `integrity`: `unverifiable` con `reason: document_unknown`. Frescura `unverified`. **Amplía el vocabulario**: `document_unknown` vale también como `unverifiable` de `quote` y de `integrity` | D18 |
| E7 | Ancla `resolved` cuyo `turn_id` no está en la sesión | Igual que purgado: `source: not_found`, `reason: turn_purged`. `turn_purged` significa «el turno no está», se haya purgado o no conste | S13 |
| E8 | `repo-file` cuya ruta, en el commit declarado, es un enlace simbólico | No se sigue: `integrity: not_found`, `reason: commit_blob_lacks_quote`, aunque el destino contenga la cita | R26 |
| E9 | Campos de la salida que el examen no exige (`seal`, `modality` y otros) | Una implementación puede emitir campos adicionales. El examen sólo exige los de cada `expect`; los demás no son parte de v1 | — |

Efecto sobre implementaciones existentes: sólo agora (PR #17, sin
fusionar), que ajusta E1, E2, E6 y E7.

## Errata 2 — 2026-11-18 (rechazos de forma)

Origen: el diseño de la implementación de an-kla (ADR-0066) encontró dos
rechazos que el contrato exigía sin darles código. Casos:
`vectores-errata-2.json` (escritos a mano; no dependen del modelo de
referencia).

- **`anchor_too_many`**: un registro con más de 16 anclas se rechaza
  entero, antes de comprobar ninguna.
- **`anchor_schema_invalid`**: un ancla cuya forma no es la del contrato
  (`schema` desconocido, `kind` fuera del conjunto cerrado, campo
  obligatorio ausente, `modality` fuera de su conjunto, `commit` ausente
  en un `repo-file` de `fact` o `decision`). Vale para los tres tipos de
  fuente, también para `document` en una implementación que no lo soporta:
  la forma se valida siempre; el significado, no.
- **Orden de los rechazos al escribir**: `anchor_too_many`,
  `anchor_schema_invalid`, `anchor_quote_too_short` /
  `anchor_quote_too_long`, `anchor_path_invalid`,
  `anchor_source_not_found`, `anchor_quote_not_found`,
  `anchor_integrity_not_found`.
- **Momento de la comprobación** (precisión, no regla nueva): «al
  escribir» es el momento en que el agente entrega el registro. Una
  implementación con cola no vuelve a comprobar al vaciarla.
- **La cobertura** se calcula contra `quote`, lo guardado, nunca contra
  `matched_text`.

## Errata 3 — 2026-11-18 (lecturas del segundo implementador, aceptadas)

Origen: la segunda y la tercera ronda externa de la implementación de
agora (PR #17, integrado; 241 de 241 congelados, 6 de 6 de la errata 1 y
10 de 10 de la errata 2). Nueve puntos donde el texto admitía dos
lecturas; se fija la que tomó el código. Sin casos nuevos: quien
discrepe en uno, propone su vector.

1. Para un `state`, un archivo rastreado por Git es versionado aunque
   case con un patrón de ignorados. «El índice no interviene» (E2)
   significa que no hace falta que el archivo esté en el índice.
2. «Ignorado» se decide sólo con las reglas del repositorio: los
   `.gitignore` del árbol y el archivo de exclusiones local del clon.
   Nunca con el ignore global de quien ejecuta ni con un
   `core.excludesFile` configurado en el clon: el resultado no puede
   depender de la máquina.
3. En un `state`, si la lectura de la fuente falla (E4), `integrity` es
   `unverifiable` con `source_not_verified`; si la lectura va bien,
   `working_tree`.
4. Un registro rechazado con `anchor_too_many` no lleva `coverage`.
5. El orden de rechazos de la errata 2 se aplica ancla por ancla, tras
   comprobar el número de anclas del registro.
6. En un `document`, `locator` y `copy` no son obligatorios para la forma:
   `locator` ausente equivale a `"unknown"`.
7. Un ancla `resolved` con `turn_id` nulo se trata como turno ausente:
   `turn_purged` (E7).
8. Los sha256 del ancla (`quote_sha256`, `document_sha256`, `commit`) van
   en hexadecimal en minúsculas; en otra forma, `anchor_schema_invalid`.
   El formato de `manifest_sha256` y de `derivation_id` es del custodio y
   no se valida.
9. Una cita **guardada** que no está en NFC o que empieza o acaba en
   espacio se rechaza con `anchor_quote_not_normalized`, antes de medir
   su tamaño. Sólo afecta a quien lee o importa anclas ya guardadas: la
   herramienta que escribe normaliza y recorta antes de guardar. El
   código se añade a los rechazos, entre `anchor_schema_invalid` y los de
   tamaño.

## Errata 4 — 2026-11-19 (reglas de cobertura v2)

Origen: el uso real de la beta.38 de an-kla por sus dos primeros usuarios. Con las reglas v1
una fecha contaba como tres números sueltos, las huellas cortas no eran elemento, y en un
estado de trabajo la cobertura salía casi siempre `none`. Diseño: `devHerdrExpert` ·
`docs/memoria-ecosistema/07-diseno-cobertura-documentos-ambito.md`, sección A, con la
corrección del implementador. Reglas y casos: agora, `fact-checks-rules/v2` (PR #29,
`3c0b14c`), copiados aquí byte a byte: `fact-checks-v2-vectors.json`, 74 casos, sha256
`9b06bbe7eded09989d207ae3d7d580be44e1b2f0fae042778a85015cc53b7ca8`.

- **La cobertura dice con qué reglas se calculó** (`rules`). `fact-checks-rules/v1` sigue
  siendo válida y sus 63 casos no cambian; lo ya guardado con v1 no se recalcula.
- **Con v2**, los elementos son `identifier`, `path`, `hash`, `version`, `date` y `number`, y
  `missing` va en ese orden.
- **En un registro `state`**, con v2, la cobertura cuenta sólo `identifier`, `path`, `hash` y
  `version`. Sin ninguno de ellos el nivel es `unchecked`. Así `none` sigue avisando cuando un
  estado cita algo ajeno y deja de avisar por cifras de avance.
- Una implementación puede ofrecer v1, v2 o las dos; lo que no puede es calcular con unas
  reglas y declarar otras.
- Límites declarados de v2, cada uno con su caso en el archivo: un año suelto no casa con una
  fecha completa; una fecha escrita en palabras no es la fecha canónica; `beta.38` y
  `0.1.0b38` no son equivalentes; una hora separada por espacio deja números sueltos;
  `deface1` cuenta como `hash`.

## Errata 5 — 2026-11-19 (la cobertura: el texto manda, y casos que faltaban)

Origen: an-kla implementó `fact-checks-rules/v2` del texto de las reglas (PR #241) y midió
contra agora con entradas aleatorias: los 74 casos pasaban y aun así había cientos de
discrepancias. Las cerró todas siguiendo el texto y escribió los casos que faltaban. agora
los pasó por su implementación: casan 23 de 23.

- **v2: 23 casos más**, exigibles como los 74: `fact-checks-v2-vectors-errata-5.json`, copia
  byte a byte del archivo de an-kla, sha256
  `1486b9c2b3696e2cda8195e2d4876e208c2727bcd1eea141b86fde96ba60df94`. Fijan: pares vacíos de
  comillas invertidas, CR como salto de línea, desfase ISO con y sin dos puntos, presencia de
  `version` por subcadena, rutas pegadas a comillas o sin letra ASCII, números con
  separadores mezclados, `V` mayúscula, tokens de hash de la cita y su elipsis, y sufijos de
  prelanzamiento.
- **El texto de las reglas es la norma**, en v1 y en v2: el de agora
  (`fact_checks.py` y `fact_checks_v2.py`). Los casos lo ilustran; pasar los casos no basta
  para ser conforme. Quien implemente contrasta además con entradas aleatorias contra otra
  implementación.
- **v1, precisión:** en la regla de identificadores, «salto de línea» es `\n` o `\r`.
- **v1, desvío declarado de an-kla beta.37 y beta.38.** Su cálculo de v1 se aparta del texto
  en casos que los 63 casos no fijan (medido: 0 de 63; 5,7 % de 20 000 entradas aleatorias):
  presencia de `version` por conjunto y no por subcadena; un par vacío de comillas invertidas
  tratado como identificador; rutas extraídas por palabras y con letras no ASCII; `V`
  mayúscula y sufijos libres en versiones; números con separadores mezclados; `\r` dentro de
  un identificador. Las coberturas ya guardadas con v1 por esas versiones **no se
  recalculan** y pueden diferir del texto en esos casos; como la cobertura es un aviso y no
  un rechazo, no cambia ninguna frescura. Desde la siguiente versión an-kla escribe sólo con
  v2.

## Errata 6 — 2026-11-20 (citas de conversación: qué es «sellada», y motivos nuevos)

Origen: el primer resolutor real (`memoria/conversacion-resolutor/v1`, prototipo de skopos) y
su ronda externa. Medido: en Claude Code 230 de 231 sesiones nunca se cierran, y un turno sólo
se cierra con el mensaje siguiente. Leído al pie de la letra, el README («sin sellar: sigue
`pending`») dejaría sin resolver para siempre casi toda cita, y siempre la de una orden dada
en el último mensaje. Ningún caso congelado cambia.

- **«Sellado» se predica de lo que contiene la cita, no de la sesión.** Un ancla pasa a
  `resolved` cuando el mensaje que contiene la cita está sellado por el custodio, aunque la
  sesión siga abierta. En los casos S, `session.state: "sealed"` significa, para resolver,
  «el custodio puede sellar ese mensaje»; S03 (`unsealed`, sigue `pending`) es el caso en que
  no puede todavía.
- **`not_found` sigue exigiendo la sesión cerrada entera** (S05), sin turnos purgados (S06), y
  además que la cita no esté en ninguna voz: una cita que sólo aparece en texto pegado, en una
  notificación o en un resumen del sistema queda `pending`, nunca `not_found`.
- **El resolutor sólo resuelve contra lo tecleado en el canal de usuario de una sesión raíz**
  (`memoria/conversacion-resolutor/v1`, «Las voces»). Qué prueba eso y qué no, está allí.
- **`seal` es una cadena opaca del custodio**, que lleva dentro su propio tipo; no se valida
  su formato.
- **Amplía el vocabulario** de `unverifiable`, para `source` e `integrity`:
  `session_unavailable` (el custodio no tiene la sesión o su origen ya no existe) y
  `resolver_error` (el resolutor falló); y sólo para `integrity`: `seal_unverifiable` (el
  sello es de un tipo que el custodio ya no calcula).
- **Un turno que falta es `turn_purged` sólo si la sesión existe y se leyó entera** (S07,
  S13). Si la sesión no está disponible, es `session_unavailable`: no comprobable, nunca rota.
- **Leer no llama al resolutor**, y un intento que no concluye no sustituye a un resultado
  concluyente guardado (la misma regla que la errata 6 de `memoria/ancla/v2`).
