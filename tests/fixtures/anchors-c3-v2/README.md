# `memoria/ancla/v2` — citas de documentos custodiados, comprobables sin servicio

**Estado: congelado el 2026-11-19.** `vectores.json`: 49 casos, sha256
`11917a3fa91acd40cbb89bf44b4e01c6a4e2c4b52fa43ac80a771918501588c5`. Desde aquí este README y
los vectores no se editan: las precisiones van a un `ERRATAS.md` y los casos nuevos, a
archivos aparte.

Congelado tras dos pasadas del prototipo del implementador (la segunda, 19 casos sobre
manifiestos reales, sin nada que bloquee) y dos rondas externas (Gemini: `fix-and-retry`,
luego `proceed` con dos correcciones, aplicadas). La primera redacción se reescribió con:

- **Prototipo del implementador** (capitán de skopos, adaptador real sobre sus manifiestos):
  cuatro cosas que el contrato no dejaba hacer bien (la modalidad es de cada elemento, no de
  la derivación; «el puntero no casa» no es «la cita falta»; hay derivaciones sustituidas;
  hay derivaciones de derivaciones) y dos medidas (el 95 % de las líneas de OCR mide menos
  que el mínimo de cita; el tope sin localizador no cubre un manual real).
- **Ronda externa** (Gemini, `fix-and-retry`): los casos no usaban el ancla canónica; `source`
  estaba definida de dos maneras; una cita se daba por comprobada sobre un documento ajeno; al
  escribir se colaban citas inventadas por una respuesta truncada; el nombre del custodio era
  una vía de inyección.

## Qué cambia respecto de `memoria/ancla/v1`

**Sólo el tipo de fuente `document`.** `repo-file` y `conversation` no cambian: su texto, sus
erratas y sus vectores de v1 siguen valiendo, y una implementación de v2 debe seguir
pasándolos. Los vectores de `document` de v1 (D01–D18) quedan sustituidos por los de aquí.

Cambios de comportamiento respecto de v1, deliberados: una copia local que se movió ya no da
`broken`; al leer no se recalcula; al escribir se exige localizador de página; aparecen los
motivos de este documento y dejan de usarse `custodian_offline` y `copy_missing` como
`not_found`. Un resultado guardado con v1 se conserva hasta la siguiente auditoría.

Diseño y motivos: `devHerdrExpert` · `docs/memoria-ecosistema/07-diseno-cobertura-documentos-ambito.md`, sección B.

## Forma del ancla

```json
{"schema": "memoria/ancla/v2",
 "source": {"kind": "document",
            "document_sha256": "719d6da3…",
            "copy": {"repo": "<repo.id C0>", "path": "docs/fuentes/imss/2000-002-001.pdf"},
            "derivation": {"custodian": "skopos", "derivation_id": "372fdaef…",
                           "manifest_sha256": "7f81b161…", "modality": "native_text"},
            "locator": {"page": 188, "item_ids": ["<id>", "<id>"]}},
 "quote": "…", "quote_sha256": "…"}
```

- `custodian`: identificador simple, `^[a-z0-9][a-z0-9_-]{0,31}$`. Otro valor es
  `anchor_schema_invalid`. El ejecutable del adaptador sale **sólo** de una tabla de
  configuración explícita, nunca de componer una ruta con ese nombre.
- `derivation.modality`: la modalidad **de los elementos citados** (`native_text`, `ocr_text`,
  `visual`). Una derivación puede mezclar modalidades; el ancla dice de cuál es su cita.
- `locator`: `{page, item_id}`, `{page, item_ids: […]}` (elementos consecutivos en el orden
  del custodio, todos de la modalidad declarada) o `{page}` (todos los elementos de esa
  modalidad en la página). `page` es la página **física** del archivo (1…N), no la impresa.
  Una cita no cruza páginas. `"unknown"` o ausente sólo vale para anclas ya guardadas.
- `copy` es opcional. Mínimo de cita: 40 bytes sin contar espacio en blanco. En OCR casi
  ninguna cita cabe en un solo elemento: lo normal es `item_ids` o `{page}`.
- Un ancla `memoria/ancla/v1` de tipo `document` ya guardada es válida en v2 tal cual.
- Una implementación que sólo conoce v1 rechaza un ancla v2 (`anchor_schema_invalid`): un
  almacén con anclas v2 necesita una implementación de v2.
- Una implementación de v2 sin soporte de `document` la guarda intacta y responde
  `unverified` con `reason: kind_not_supported`.

## El adaptador de custodio (`memoria/custodio-adaptador/v1`)

Quien guarda recuerdos **no lee archivos del custodio ni conoce cómo los guarda**.

- **Llamada:** un proceso por petición. Recibe un objeto JSON en UTF-8 por la entrada estándar
  y escribe otro en UTF-8 por la salida estándar, con código de salida 0. La salida de error
  se ignora. No arranca servicios, no usa red y no escribe nada. Plazo: 10 segundos.
- **Petición:**

```json
{"schema": "memoria/custodio-adaptador/v1", "op": "locate",
 "document_sha256": "…", "derivation_id": "…", "manifest_sha256": "…",
 "modality": "native_text",
 "locator": {"page": 188, "item_ids": ["…", "…"]}}
```

- **Respuesta** (todas las claves, siempre):

```json
{"schema": "memoria/custodio-adaptador/v1",
 "document": "known",
 "manifest": "match",
 "derivation": "current",
 "derivation_parent_sha256": "…",
 "locator": "match",
 "items": [{"item_id": "…", "page": 188, "modality": "native_text", "text": "…"}],
 "truncated": false,
 "custody": {"retention": "effective"}}
```

  - `document`: `known` si el custodio tiene ese documento bajo custodia, tenga o no esa
    derivación; `unknown` si no. Con `unknown`: `manifest: "missing"`, `derivation` y
    `derivation_parent_sha256` nulos, `locator: "not_found"`, `items` vacío.
  - `manifest`: `match` (la derivación existe y el sha256 de los bytes de su manifiesto es el
    pedido), `mismatch` o `missing`.
  - `derivation`: `current` (el custodio responde hoy por ella; lo decide con lo que puede
    comprobar **sin servicios**, y su propio servicio puede ser más estricto), `superseded` (existe pero ya
    no la sirve) o `unsupported` (no deriva directamente de un documento, o no tiene
    manifiesto: derivaciones de derivaciones, texto de HTML). Nulo si `manifest` no es `match`.
  - `derivation_parent_sha256`: el documento del que esa derivación dice derivar.
  - `locator`: `match`; `not_found` (esa página o esos elementos no existen en la derivación,
    o no hay elementos de esa modalidad); `invalid` (elementos de modalidades distintas o no
    consecutivos).
  - `items`: los elementos pedidos, en el **orden del custodio** (el de su manifiesto, que no
    tiene por qué ser el visual), cada uno con su `modality`. Sin localizador, los de toda la
    derivación en esa modalidad hasta 256 KiB de **texto**, y `truncated` dice si hubo más.
  - `custody.retention`: `effective`, `expired` o `unknown`, **de la política de esa
    derivación**; `unknown` si esa política ya no se conserva. Informativo.
- **Quien llama comprueba lo que puede:** que cada elemento devuelto es de la página y la
  modalidad pedidas y, si pidió elementos concretos, que vienen exactamente esos y en ese
  orden. Si no, la respuesta no vale.
- **Fallo del adaptador:** plazo agotado, código de salida distinto de 0, salida que no es
  JSON, sin este `schema`, o respuesta que no supera la comprobación anterior. Se traduce en
  `unverifiable` con `reason: adapter_error`. Nunca en `broken`, nunca en una excepción.
- **Confianza:** es un programa que configura el Operador, como el adaptador de claves. El
  texto que devuelve se le cree.

## Las tres comprobaciones

`source` responde a «¿existe el documento donde se mira?»; `integrity`, a «¿es el documento y
la derivación que se citaron?»; `quote`, a «¿está la cita?». `quote` sólo se comprueba con las
otras dos en `verified`: una cita no se da por buena sobre un texto que no se sabe de quién es.

| | `verified` | `not_found` | `unverifiable` |
|---|---|---|---|
| `source` | hay un archivo en la ruta de la copia declarada (tenga el sha256 que tenga), **o** el custodio conoce el documento | no hay archivo local y el custodio dice que no conoce el documento (`document_unknown`) | copia declarada ausente y sin respuesta del custodio (`copy_missing`); sin copia y sin adaptador (`no_adapter`) o con fallo (`adapter_error`) |
| `integrity` | el manifiesto coincide, la derivación es `current` y deriva de `document_sha256` | sha256 de la copia local distinto (`copy_sha_mismatch`); `manifest_mismatch`; `derivation_parent_mismatch` | `no_adapter`, `adapter_error`, `document_unknown`, `manifest_missing`, `derivation_superseded`, `derivation_unsupported` |
| `quote` | la cita está, con los perfiles de búsqueda de v1, en los textos de `items` unidos por salto de línea | no está, con localizador que casó y respuesta sin truncar (`quote_absent`) | `source_not_verified`, `integrity_not_verified`, `derived_modality` (visual), `locator_not_found`, `locator_invalid`, `adapter_truncated` |

## Frescura

| Si | Frescura |
|---|---|
| alguna comprobación = `not_found` | `broken` (un documento fijado no cambia: no hay `stale`) |
| las tres = `verified` y `modality` = `native_text` | `fresh` |
| las tres = `verified` y otra `modality` | `unverified` (`derived_modality`) |
| cualquier otro caso | `unverified` |

El `reason` de la frescura es el de la primera comprobación que no es `verified`, en el orden
`source`, `integrity`, `quote`: sale la causa, no su consecuencia. `custody.retention` no
interviene.

## Cuándo se comprueba, y qué se exige al escribir

- **Al escribir** y **al auditar** se llama al adaptador y se guarda el resultado con su
  fecha (`checked_at`), el `manifest_sha256` y el estado de la derivación.
- **Al leer** no se llama al adaptador ni se recalcula nada: se sirve lo guardado. Un ancla
  nunca comprobada sale `unverified` con `reason: not_checked`.
- **Al escribir se exige todo lo que se puede exigir.** Sin llamar a nadie:
  `anchor_schema_invalid`, los rechazos de tamaño de la cita, `anchor_locator_required` (sin
  `page` no se escribe un ancla de documento, lleve o no elementos) y `anchor_copy_not_found` (se declaró una copia
  que no existe). Con el adaptador respondiendo, se rechaza todo lo que no sea una cita
  comprobada, con el código de la causa: `anchor_source_not_found`,
  `anchor_integrity_not_found`, `anchor_derivation_not_found`,
  `anchor_derivation_superseded`, `anchor_derivation_unsupported`,
  `anchor_locator_not_found`, `anchor_locator_invalid`, `anchor_quote_not_found`. Dos
  excepciones, que se aceptan como `unverified`: copia local correcta y custodio que no conoce
  el documento; y modalidad `visual`, donde se exigen documento y derivación pero la cita no
  se comprueba (`derived_modality`).
- **Sin adaptador o con el adaptador fallando**, al escribir se acepta y queda `unverified`:
  no poder comprobar no es fallar. Un sha256 de copia distinto se rechaza siempre.
- **Al auditar** nada se rechaza: `broken` sólo lo que contradice (copia con otro sha256,
  manifiesto distinto, derivación de otro documento, cita ausente del elemento localizado, o documento que el
  custodio dice no conocer cuando tampoco hay copia local).
  Un puntero que ya no casa, una derivación sustituida o desaparecida y un adaptador que
  falla dan `unverified`.

## Límites declarados

- No juzga si la cita respalda el hecho. Una cita de un encabezado repetido sale comprobada.
- `visual`, las etiquetas y nodos de grafo, y los textos derivados de HTML no se comprueban
  en v2.
- El orden de los elementos es el del custodio. En un documento a dos columnas, una cita
  continua puede no encontrarse con `{page}`; se cita por `item_ids`. Una palabra partida con
  guion al final de línea no casa.
- La página del localizador no cuenta en la cobertura.

## Vectores

`vectores.json`: 49 casos, cada uno con un ancla canónica completa, el estado de la copia
local (`copy_state`), lo que responde el adaptador (o cómo falla), el momento y el resultado
exigible campo a campo, incluido `adapter_called`. Escritos a mano por el orquestador y
contrastados por `construir_vectores.py` (`--check`).

**Pruebas de proceso obligatorias**, que un archivo de casos no puede fijar: quien implementa
la llamada debe probar con un proceso real el plazo, el código de salida distinto de 0, la
salida que no es JSON, la salida de error ruidosa y que el nombre del custodio nunca llega a
una ruta ni a una línea de órdenes.

## Fuera de v2, para una versión posterior

1. ¿El resultado guardado vive en el registro o en un índice derivado? Es de quien guarda; el
   contrato sólo exige que leer no recalcule y que el resultado lleve `manifest_sha256` y el
   estado de la derivación.
2. Citas que cruzan páginas y citas visuales: fuera de v2. ¿Hacen falta para el consumidor?
