# ADR-0071: Anclas `document` de `memoria/ancla/v2`, adaptador de custodio y resultado guardado

- **Estado:** Aceptada por delegación del orquestador (mandato 14), 2026-11-19, tras r1 `fix-and-retry` (3 HIGH, 3 MEDIUM, 3 LOW) y r2 `fix-and-retry` (1 HIGH, 2 LOW) y r3 `proceed` sin hallazgos de otra familia (Gemini), todo incorporado
- **Implementación:** No iniciada
- **Fecha:** 2026-11-19
- **Decide sobre:**
  - cómo se escribe un ancla de documento;
  - cómo se llama al adaptador de custodio;
  - dónde vive el resultado comprobado al escribir y al auditar, y cómo se sirve al leer sin llamar a nadie.
- **Depende de:** ADR-0063 (bandeja, sobre C0), ADR-0066 (anclas C3 v1, `anchors verify`, anotaciones de §6bis), ADR-0069 (esquemas dispersos), ADR-0070 (cobertura).
- **Contrato:** `memoria/ancla/v2`, congelado: README y `vectores.json` (49 casos, sha256 `11917a3f…88c5`); `ERRATAS.md`, erratas 1 a 4, que prevalecen sobre el README; `vectores-errata-1.json` (10 casos) y `vectores-errata-2.json` (3 casos). X14 no es exigible (lo sustituye E11), así que hay **61 casos exigibles**. Adaptador `memoria/custodio-adaptador/v1`.
- **Implementaciones con las que contrastar comportamiento, no código:** el adaptador real de skopos (`17a0d78`) y el verificador de agora (`b7c0f32`).

## Contexto

beta.38 guarda un ancla `document` bien formada y responde `unverified` con `kind_not_supported`: las fuentes primarias del consumidor (PDF custodiados) no se pueden citar con comprobación. `memoria/ancla/v2` lo resuelve sin que an-kla lea archivos del custodio. Un ejecutable externo por custodio, el adaptador, responde por el documento, el manifiesto, la derivación y los elementos localizados.

La diferencia de fondo con v1 es **cuándo** se comprueba. En v1, `repo-file` se vuelve a comprobar al leer, con Git. En v2, `document` se comprueba **al escribir y al auditar**; al leer se sirve lo guardado, con su fecha, y no se llama a nadie. an-kla no guarda hoy ningún resultado: `write_check` se queda en la entrada de la bandeja y nunca llega al registro (ADR-0066 §2). Hace falta, pues, un sitio para el resultado.

## Decisión

### 1. Qué se escribe como v2

- **Sólo las anclas `document` se escriben con `schema: memoria/ancla/v2`.** `repo-file` y `conversation` siguen saliendo como v1. La errata 2 (B3) deja usar v2 para todo, y sus vectores de v1 con el `schema` cambiado deben dar lo mismo, cosa que se prueba. Pero un binario que sólo conoce v1 rechaza un ancla v2 (`anchor_schema_invalid`). Escribir v2 sólo donde cambia algo deja que beta.38 siga leyendo todo lo que no es `document`.
- **Al leer y al vaciar** se aceptan anclas v2 de los tres tipos (B3): `repo-file` y `conversation` con `schema` v2 se comprueban exactamente como en v1.
- **Lo ya guardado como v1 no se reescribe.** Un ancla `document` v1 es válida en v2 tal cual.

### 2. Escribir un ancla de documento

- **Entrada:**
  - `--anchor-file` con el ancla canónica completa;
  - o el atajo en grupo, repetible: `--anchor-document <sha256> --anchor-custodian <id> --anchor-derivation <derivation_id> --anchor-manifest <sha256> --anchor-modality native_text|ocr_text|visual --anchor-page <n> [--anchor-item <id>]… [--anchor-copy <ruta>] --anchor-quote <q>`.
  - Sin `--anchor-item`, el localizador es `{page}`; con uno, `{page, item_id}`; con varios, `{page, item_ids}`, en el orden dado.
  - `copy.repo` lo pone la herramienta desde C0: el `repo.id` del proyecto. Quien llama no lo escribe.
- **Orden de los rechazos al escribir** (errata 2, precisiones menores):
  1. forma: `anchor_schema_invalid`, incluido un `custodian` fuera de `^[a-z0-9][a-z0-9_-]{0,31}$`;
  2. tamaño de la cita: 40 bytes sin espacio en blanco como mínimo y 300 como máximo;
  3. `anchor_locator_required`: sin `page` no se escribe, lleve o no elementos;
  4. la sintaxis de `copy.path`, como las rutas de v1: `anchor_path_invalid` (r1, R71-08: antes de mirar si existe);
  5. `anchor_copy_not_found`, si la copia declarada no existe;
  6. sha256 de la copia distinto: se rechaza siempre, con **`anchor_integrity_not_found`** (X13; r1, R71-07);
  7. el adaptador.
- **Con el adaptador respondiendo**, se rechaza todo lo que no sea una cita comprobada, con el código de la causa que da el contrato (`anchor_source_not_found`, `anchor_integrity_not_found`, `anchor_derivation_*`, `anchor_locator_*`, `anchor_quote_not_found`), con sus dos excepciones aceptadas como `unverified`: copia correcta con un custodio que no conoce el documento, y modalidad `visual`. Sin adaptador o con el adaptador fallando, se acepta como `unverified`.
- **La copia local** se lee **por Git, de la rama por defecto, en los dos momentos** (escribir y auditar), nunca del árbol de trabajo. Es lo que hace el verificador de agora (`document_copy_state` lee de `clone.default()`, `b7c0f32`): así escritor y auditor externo miran lo mismo (r1, R71-01).
  - La rama por defecto es la de ADR-0066 §4 (`AN_KLA_DEFAULT_BRANCH`, `default_branch` o `origin/HEAD`). Sin rama por defecto, la copia cuenta como ausente.
  - Consecuencia declarada: una copia añadida en una rama de trabajo y aún no integrada cuenta como ausente al escribir (`anchor_copy_not_found`). `copy` es opcional, así que quien escribe puede omitirla y dejar que el custodio responda por el documento (X02), o integrar antes la copia.
  - La ruta sigue las reglas de v1: relativa, sin `..`. Un enlace, un directorio o un objeto que Git no lee cuentan como ausentes.
  - El sha256 se calcula sobre los bytes del blob, por bloques y sin el tope de 4 MiB de lectura de `repo-file`: un PDF custodiado puede pesar más.
  - Se mira **sólo** cuando `copy.repo` es el `repo.id` del proyecto. Si nombra otro repositorio, an-kla no tiene su clon: la copia cuenta como **ausente aquí**, igual que en agora con un clon que no está en su mapa. Al escribir eso es `anchor_copy_not_found`; al auditar, `copy_missing` si el custodio no responde. Ver «Para el orquestador».
- **Idempotencia:** igual que ADR-0066: la fuente canónica y el `quote_sha256` de cada ancla entran en la clave. El resultado comprobado no entra: dos escrituras de la misma cita son la misma intención aunque el custodio haya cambiado entre medias.

### 3. El adaptador

- **Configuración:** una tabla explícita **custodio → orden** en la configuración del proyecto del store (`<store>/config.json`, la misma que lleva `default_branch`):
  ```json
  {"custodians": {"skopos": {"argv": ["/ruta/python", "-B", "/ruta/adaptador.py", "--runs-root", "…"]}}}
  ```
  `argv` es una lista: nunca se pasa por un intérprete de órdenes, nunca se compone una ruta con el nombre del custodio y el nombre nunca entra en `argv`. Un custodio que no está en la tabla equivale a «sin adaptador» (`no_adapter`). La variable `AN_KLA_CUSTODIANS`, si existe, apunta a otro archivo con la misma tabla y la sustituye entera. Así un consumidor la tiene fuera del store. **Tabla ilegible** (archivo ausente, JSON inválido o forma que no es la de arriba), en el store o en la variable (r2, R71-11): no es «sin adaptador», porque el Operador sí configuró algo. Todo custodio da `adapter_error` (sin lanzar ningún proceso, `adapter_called: false`) y la respuesta lleva `custodians_config_error: <código>`. Nunca es excepción.
- **Llamada:** un proceso por petición.
  - La petición `memoria/custodio-adaptador/v1` va por la entrada estándar. Lleva siempre la clave `locator`, que vale `"unknown"` sin localizador (A1).
  - La respuesta se lee por la salida estándar, con un **tope de 8 MiB**; si lo pasa, es un fallo. La salida de error se descarta.
  - Plazo de **10 s**, inyectable en la API para las pruebas (A7). Al vencer se mata el grupo de procesos.
  - Entorno mínimo, `{"PATH": "/usr/bin:/bin", "LC_ALL": "C"}`, y directorio de trabajo `/`, como agora (r1, R71-09): el adaptador no hereda secretos ni ve el árbol del proyecto. Lo que necesite (sus raíces, su intérprete) va en su `argv`, con rutas absolutas.
- **Fallo = `adapter_error`, nunca excepción ni `broken`:**
  - plazo agotado o salida mayor que el tope;
  - código de salida distinto de 0;
  - salida que no es JSON UTF-8 o que no lleva este `schema` (incluida la salida de fallo de skopos, `{"schema": "invalid", …}`);
  - respuesta mal formada o incoherente (A2, B1, B2, F1, F2);
  - respuesta que no supera la **comprobación de quien llama** (C1): sólo con `locator: match` y modalidad no `visual`, que cada elemento sea de la página y la modalidad pedidas y, si se pidieron elementos, que vengan exactamente esos y en ese orden. Con `locator` distinto de `match`, `items` vacío en todas las modalidades.
- **Confianza:** el texto que devuelve se le cree, como al adaptador de claves. Es un programa que configura el Operador.

### 4. Las tres comprobaciones y la frescura

Las del README tal cual, con el orden de motivos de A3 y la frescura por la primera comprobación no `verified` (`source`, `integrity`, `quote`). La cita se busca con los perfiles de búsqueda de v1 (`anchors_search.find_quote`) en los textos de `items` unidos por salto de línea. La implementación es propia, `an_kla/anchors_document_v2.py`, derivada del contrato y sus 61 casos. `anchors_document.py` (v1) se sustituye por ella.

### 5. Dónde vive el resultado guardado

El contrato lo deja a quien guarda (README, «Fuera de v2», 1). an-kla lo guarda **en el store, como dato que sólo se añade**, en dos sitios:

- **Al escribir:** el registro lleva `anchor_checks`, una lista de primer nivel con una entrada por cada ancla `document` v2 que se comprobó:
  ```json
  {"index": 0, "quote_sha256": "…", "checked_at": "2026-11-19T21:00:00Z", "manifest_sha256": "…",
   "derivation": "current", "source": "verified", "source_reason": null, "integrity": "verified",
   "integrity_reason": null, "quote": "verified", "quote_reason": null, "match": "literal",
   "freshness": "fresh", "reason": null, "custody": {"retention": "effective"}}
  ```
  Es lo que pide el contrato (`checked_at`, `manifest_sha256` y estado de la derivación), más el resto del resultado. El ancla en sí no cambia: su digest sigue siendo el de la entrada.
- **Al auditar:** `anchors verify` llama al adaptador por cada ancla `document` que audita, **sea su `schema` v1 o v2** (r2, R71-10: un ancla v1 ya guardada se audita como en X70), y **guarda** su resultado como un registro de anotación `an-kla/anchor-check-v1` en `events`, con el mismo patrón que `anchor-resolution-v1` (ADR-0066 §6bis):
  - lleva `{target: {stream, record_id}, checks: [ … como arriba … ]}`;
  - entra por la bandeja con el sobre C0 de quien audita, y se vacía en la misma invocación;
  - **una anotación por registro auditado y auditoría**, aunque el resultado no haya cambiado: la fecha de la última comprobación también es dato;
  - si no hay identidad C0 en el entorno o la bandeja está ocupada, la auditoría devuelve igualmente el resultado, con `recorded: false` y `record_error: <código>`;
  - **idempotencia** (r1, R71-02): la clave derivada de la entrada es la de ADR-0063 con `kind: anchor_check` y, como extra, `[stream, record_id]` del destino, el digest canónico de `checks` y su `checked_at`. Dos auditorías distintas tienen `checked_at` distinto y son dos anotaciones. El reintento de la misma auditoría tras un corte trae la misma clave y responde `already_committed`, sin duplicar;
  - **invariantes al vaciar** (r1, R71-04), como §6bis: el destino existe en el snapshot y está vigente; cada `index` es un ancla de ese registro, de tipo `document` (con `schema` v1 o v2), y su `quote_sha256` coincide; cada resultado tiene la forma de arriba. Si algo falla, la entrada va a `rejected/` con **`anchor_check_invalid`**.
- **`anchors verify` deja de ser de sólo lectura, pero sólo para `document`.** Para `repo-file`, `conversation` y un store sin anclas `document` no escribe nada, y su salida sigue siendo la de hoy. Sobre un store de beta.38 con anclas `document` v1, la primera auditoría escribe sus anotaciones (también con `no_adapter` si no hay custodio configurado): desde ella, esas anclas sirven lo guardado.
- **Al leer** (`state show`, `history`, `list` y la respuesta de `anchors verify` para las anclas que no audita), un ancla `document` (v1 o v2) sirve el último resultado guardado de ese índice; una v1 sin ninguno, `kind_not_supported` (abajo); una v2 sin ninguno, `not_checked`. **Orden total** (r1, R71-03):
  - candidatos: la entrada de `anchor_checks` del propio registro con ese `index` y las anotaciones `anchor_check` vigentes cuyo destino y `index` son ése, siempre que su `quote_sha256` coincida con el del ancla;
  - gana la mayor clave `(checked_at, origen, enqueued_at, id)`, donde `origen` vale 0 para el registro y 1 para una anotación (a igual fecha, la auditoría manda), `enqueued_at` es el del sobre (`""` si no hay sobre, r2 R71-12) e `id` el del registro o la anotación, como cadenas. **Nunca se llama al adaptador.** Si no hay ninguno, sale `unverified` con `not_checked` (X61).
- **Un ancla `document` v1 ya guardada** (beta.37–38) no tiene resultado guardado, y su resultado de v1 era `kind_not_supported`. Ese resultado **se conserva hasta su primera auditoría** (README: «un resultado guardado con v1 se conserva hasta la siguiente auditoría»), así que un store de beta.38 se lee byte a byte igual. Desde la primera auditoría, sirve lo guardado.
- **Por qué en el store y no en un índice derivado:** el resultado tiene que viajar con el store (`export`, `relocate`), sobrevivir a una reconstrucción del índice y ser auditable (quién comprobó, cuándo, con qué manifiesto). Un índice derivado se puede borrar y regenerar; el resultado de una comprobación pasada no se puede regenerar.

### 6. Esquemas

Regla dispersa de ADR-0069 §6:
- `history-result-v2`, `state-result-v2` y `anchors-verify-v2` (aún sin etiqueta) se amplían en el sitio con `checked_at`, `manifest_sha256`, `derivation` y `custody` opcionales por ancla, y `anchors-verify-v2` además con `recorded`/`record_error`;
- `inbox-entry-v4` (sin etiqueta) admite anclas v2 y la operación `anchor_check`;
- `remember-result-v2` lleva el resultado por ancla.

Sin anclas `document` v2 ni anotaciones `anchor_check`, todo sale como hoy.

### 7. Vuelta atrás

beta.38 rechaza un ancla v2 (`anchor_schema_invalid`) al vaciar una entrada v4 que la lleve: la regla de siempre («`inbox drain` y pendientes a 0 antes de bajar») lo cubre. Un registro ya comprometido con anclas v2 lo lee beta.38 sin entenderlo:
- las sirve como `document` con `kind_not_supported`, o las rechaza al validarlas, según el camino;
- ignora `anchor_checks` y las anotaciones `anchor_check`.

La prueba 7 lo fija.

## Por qué no

- **Todo v2 desde ahora:** lo permite B3, pero cada ancla `repo-file` escrita con v2 sería ilegible para beta.38, sin ganar nada.
- **Recalcular al leer con el adaptador:** el contrato lo prohíbe. Leer sigue siendo barato y no depende de la máquina.
- **Guardar el resultado dentro del ancla:** cambiaría el digest del ancla, y con él la clave de idempotencia y el `payload_sha256`. Y al auditar habría que reescribir el registro, cuando el store sólo añade.
- **Una orden aparte `anchors audit`:** C3 ya llama auditoría a `anchors verify` (ADR-0066 §5). Dos órdenes para el mismo momento confundirían. Lo que cambia es que ahora guarda.
- **Una ruta compuesta con el nombre del custodio:** el contrato lo prohíbe; es una vía de inyección.

## Consecuencias

- **Positivas:** se puede citar una página de un PDF custodiado con comprobación real. Leer no depende del custodio. La auditoría deja rastro.
- **Negativas:**
  - `anchors verify` escribe cuando hay anclas `document`;
  - cada auditoría añade una anotación por registro, y **la compactación de hoy (ADR-0028) no las poda** (r1, R71-05): crecen con el número de auditorías. Conservar sólo la última por ancla es trabajo de una versión posterior de la compactación. Mientras, se audita cuando hace falta, no en bucle;
  - escribir una cita de documento tarda lo que tarde el adaptador (≈0,1 s en skopos).
- **Neutras:** citas que cruzan páginas y citas visuales siguen fuera (`derived_modality`). La página del localizador no cuenta en la cobertura.

## Pruebas de aceptación

1. **Examen:** los 61 casos exigibles con un adaptador de prueba que es un **proceso real**. El script responde lo que dice cada caso o falla como dice (`none`, `exit_nonzero`, `timeout`…), y cada campo de `expect` es exacto, `adapter_called` incluido. X14 se carga y se declara no exigible. **D01–D18 de v1 quedan sustituidos**, y la prueba lo declara.
2. **Vectores de v1** de `repo-file` y `conversation`, con el `schema` cambiado a v2: mismo resultado (B3).
3. **Pruebas de proceso obligatorias,** con un proceso real: plazo (corto por parámetro, y otra prueba que fija el valor por defecto de 10 s), código distinto de 0, salida que no es JSON, salida de error ruidosa (de varios MiB), salida mayor que el tope, y que el nombre del custodio nunca llega a una ruta ni a `argv`. Para esto último, un custodio llamado como un archivo existente y otro con caracteres de ruta, que da `anchor_schema_invalid`.
4. **Los tres momentos:**
   - escribir guarda `anchor_checks`;
   - auditar guarda una anotación y sirve su resultado;
   - leer sirve lo último guardado sin lanzar ningún proceso (se prueba con un adaptador que, si se llama, falla la prueba);
   - un ancla v2 nunca comprobada sale `not_checked`.
5. **Compatibilidad:** un store escrito por beta.38 con anclas `document` v1 se lee byte a byte igual hasta su primera auditoría.
6. **Adaptador real** (skopos `17a0d78`, sólo lectura, con la línea de órdenes de su informe 30): un ancla escrita y auditada contra un manifiesto real, `fresh`. El informe dice sólo cuentas, huellas y resultado; ningún texto del documento sale a un informe ni a un commit. **No es parte de la suite** (r1, R71-06): es un guion aparte, fuera del repo, que se ejecuta una vez en esta máquina y cuya salida (sin texto) se adjunta al informe. Ninguna prueba del repo depende de las raíces de skopos; si no están, el guion lo dice y no falla nada.
7. **Vuelta atrás:** un store con anclas `document` v2 leído por beta.38 no rompe `verify` ni las lecturas. Lo que haga con ellas se declara.

## Para el orquestador

- **La copia, de la rama por defecto en los dos momentos (§2),** como agora. Una copia todavía no integrada no cuenta al escribir.
- **La copia de otro repositorio (§2).** El contrato dice «hay un archivo en la ruta de la copia declarada» y no dice dónde está un `copy.repo` que no es el proyecto. an-kla la cuenta como ausente aquí. Si tu lectura es otra, es una errata.

## Referencias

`memoria/ancla/v2` y sus erratas 1–4; skopos ADR-028 y `docs/custodio-adaptador.md`; agora `2026-11-19-decision-ancla-v2-document.md`; ADR-0066 §2, §5 y §6bis; diseño 07, sección B.
