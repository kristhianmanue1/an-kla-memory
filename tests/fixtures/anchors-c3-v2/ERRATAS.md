# Erratas de `memoria/ancla/v2`

El contrato se congeló el 2026-11-19 (`ab621d0`). `README.md` y `vectores.json` (sha256
`11917a3f…88c5`) no se editan desde entonces; lo que sigue **prevalece** sobre el README donde
lo contradiga. Los casos nuevos van en archivos aparte y son exigibles igual que los
congelados.

## Errata 1 — 2026-11-19 (primera lectura del segundo implementador)

Origen: agora leyó el contrato para implementarlo sin ver el modelo de referencia y paró antes
de escribir código: la frase de la comprobación de quien llama, leída literalmente,
contradecía doce casos congelados. Tenía razón: el modelo aplicaba la comprobación sólo
cuando el localizador casaba, y el texto no lo decía. Ningún caso congelado cambia. Casos
nuevos: `vectores-errata-1.json`, 10 casos, sha256
`0841347035cbbd714498a8dc14de3e3b8278de5a779a9986df8fbae275560d46`
(`construir_errata_1.py --check`).

| # | Punto | Regla | Caso |
|---|---|---|---|
| C1 | La comprobación de quien llama (página, modalidad, elementos pedidos y orden) | Se aplica **sólo** a una respuesta con `locator: match` y modalidad distinta de `visual`. Con `locator` distinto de `match`, `items` debe venir vacío; si no, la respuesta no vale (`adapter_error`). En `visual` no se mira `items` | X14, X16, X18–X20, X22, X33, X34, X44, X46, X48, X49 (congelados); E01, E10 |
| A1 | Petición para un ancla sin localizador | La petición lleva siempre la clave `locator`; sin localizador, su valor es la cadena `"unknown"` | — |
| A2 | Respuesta mal formada | Es fallo del adaptador (`adapter_error`): una clave ausente o de más, un valor fuera de su vocabulario, o una respuesta incoherente (`document: unknown` con `manifest` distinto de `missing`; `derivation` nulo con `manifest: match`, o no nulo sin él) | E02, E03, E04 |
| A3 | Varios motivos de `integrity` a la vez | Primero lo que contradice, en este orden: `copy_sha_mismatch`, `manifest_mismatch`, `derivation_parent_mismatch`. Después lo no comprobable: `no_adapter` / `adapter_error`, `document_unknown`, `manifest_missing`, `derivation_unsupported`, `derivation_superseded`. Excepción: en una derivación `unsupported` no se compara el padre (no es un documento) | E05, E06 |
| A4 | Ancla antigua sin localizador, respuesta completa y cita no hallada | El adaptador responde `locator: match`: `quote_absent`, `broken`. Con `truncated: true`, `adapter_truncated` (X47) | E07 |
| A5 | Copia declarada ausente y adaptador que falla | `source: unverifiable` con `copy_missing`: «sin respuesta del custodio» incluye el fallo | E08 |
| A6 | Auditoría con copia de otro sha256 y adaptador configurado | Se llama al adaptador igualmente (`adapter_called: true`); el resultado es `copy_sha_mismatch`, `broken` | E09 |
| A7 | El plazo en las pruebas | El plazo es de 10 s. Una prueba de proceso puede pasar un plazo corto por parámetro; basta con que otra fije el valor por defecto | — |

Efecto sobre implementaciones: ninguna integrada todavía. El adaptador de skopos (en
construcción) toma A1 y A2; agora y an-kla, todo.

## Errata 2 — 2026-11-19 (un caso congelado incoherente y tres dobles lecturas)

Origen: agora implementó del texto (58 de 59) y su capitán escribió una segunda lectura
aparte; las dos fallaron en el mismo caso y discreparon entre sí en tres situaciones que
ningún caso decidía. Casos nuevos: `vectores-errata-2.json`, 3 casos, sha256
`3cde0a009a113d7e129544ba2366b007e87397637f6c13558c72fa1ca5fabd67`
(`construir_errata_2.py --check`).

- **X14 queda sustituido por E11.** La respuesta del adaptador de X14 traía
  `manifest: "mismatch"` con `derivation: "current"`, que el README y la errata 1 (A2)
  declaran incoherente: era un error del caso, no de la regla. E11 es el mismo caso con
  `derivation: null` y el mismo resultado (`anchor_integrity_not_found`). X14 sigue en
  `vectores.json` porque el archivo congelado no se edita, pero **no es exigible**. Comprobado
  con el modelo completo: es el único de los 49 que las erratas invalidan.
- **B1 — `locator: match` sin ningún elemento** (modalidad no visual): la respuesta no vale,
  `adapter_error`. Un «casó» sin texto no dice nada sobre la cita, y no se da `broken` por un
  adaptador que no devuelve nada. Una página sin elementos de esa modalidad se responde con
  `locator: not_found`. Caso E12.
- **B2 — derivación `current` o `superseded` con `derivation_parent_sha256` nulo**: la
  respuesta no vale, `adapter_error`. La falta de dato no contradice. Con `manifest` distinto
  de `match` o en `unsupported`, el padre puede venir o no. Caso E13.
- **B3 — un ancla con `schema: memoria/ancla/v2` puede ser de cualquier tipo de fuente.** Las
  de `repo-file` y `conversation` se aceptan y se comprueban exactamente como en v1: cada
  vector de v1 de esos tipos, con el `schema` cambiado a v2, debe dar el mismo resultado. Quien
  escribe puede usar v2 para todo.
- Precisiones menores, sin caso: `visual` con `locator` distinto de `match` sale
  `derived_modality`; el orden al escribir es forma y tamaño, `anchor_locator_required`,
  `anchor_copy_not_found`, sha256 de la copia y después el adaptador; `copy.path` se valida
  como las rutas de v1 (`anchor_path_invalid`); en el examen, el `document_sha256` de los
  casos es un valor de ejemplo que puede sustituirse por el de un archivo real.

## Errata 3 — 2026-11-19 (dos precisiones de la revisión del segundo implementador)

Origen: la ronda externa de la implementación de agora (PR #30, integrado, `b7c0f32`: 48
congelados exigibles, 10 de la errata 1 y 3 de la errata 2, con procesos reales). Sin casos
nuevos.

- **F1 — respuesta truncada al escribir.** No es una tercera excepción a «se rechaza todo lo
  que no sea una cita comprobada»: una respuesta sólo puede venir truncada sin localizador, y
  sin localizador de página no se escribe (`anchor_locator_required`). Si una implementación
  recibe `truncated: true` para una petición con `page`, la respuesta no vale
  (`adapter_error`).
- **F2 — `visual` con `locator` distinto de `match` y elementos devueltos.** Es
  `adapter_error`. «En `visual` no se mira `items`» (errata 1, C1) vale sólo con
  `locator: match`; con cualquier otro valor, `items` debe venir vacío en todas las
  modalidades.

## Errata 4 — 2026-11-19 (precisiones del primer adaptador real)

Origen: el adaptador de skopos (PR #48, integrado, `17a0d78`; ADR-028 de skopos), probado
contra los casos del contrato y contra sus manifiestos reales. Sin casos nuevos.

- **Elemento mayor que el tope.** Sin localizador, el primer elemento se devuelve entero
  aunque supere los 256 KiB (un `match` sin elementos no vale, errata 2 B1); `truncated` dice
  sólo si quedaron más.
- **`manifest: missing` incluye «no servible».** Un manifiesto vacío o mayor que el tope de
  lectura del custodio se responde `missing`: sus bytes no se leen y no hay qué comparar.
- **Campos informativos de los casos.** En X16, X18, X22, X33, X44 y X49 la respuesta de
  ejemplo trae `custody.retention: "effective"` y, en X16, X18 y X44, un
  `derivation_parent_sha256`, donde un custodio real respondería `unknown` y nulo. Quien
  llama acepta las dos formas (errata 2, B2: sin `manifest: match` o en `unsupported` el padre
  puede venir o no; la retención es informativa); ningún resultado exigible cambia. Un
  adaptador no está obligado a poder producir byte a byte las respuestas de ejemplo.
- **`current` es la vista del adaptador.** Ya escrito en el README: el servicio del custodio
  puede ser más estricto (recibo en su base, ruta de política que carga el host).
