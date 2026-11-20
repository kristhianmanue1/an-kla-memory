# ADR-0069: Ámbito y destinatario de un recuerdo, y órdenes del Operador (`directive`)

- **Estado:** Aceptada por delegación del orquestador (mandato 13: «una ronda de otra familia, hasta tres»), 2026-11-19, tras r1 `fix-and-retry` (3 HIGH, 2 MEDIUM, 2 LOW) y r2 `proceed` (2 MEDIUM, 2 LOW) de otra familia (Gemini); todo incorporado.
- **Implementación:** No iniciada
- **Fecha:** 2026-11-19
- **Decide sobre:**
  - los campos de primer nivel `subject` y `audience` de un registro;
  - el tipo de registro `directive` (orden o preferencia del Operador): escritura, vigencia, revocación y ancla;
  - cómo filtran y marcan las lecturas (`retrieve`, MCP, `list`, `state show`, `history`, `disputes list`, `anchors verify`);
  - qué cambia y qué no en `retrieve`.
- **Depende de:** ADR-0063 (bandeja, sobre C0, D3), ADR-0065 (`slot` como campo de primer nivel, `state show`), ADR-0066 (anclas `conversation`, `anchor-resolution-v1`), ADR-0067 (`list`).
- **Diseño:** «ámbito de un recuerdo» (pieza C) del esfuerzo de memoria agéntica, aprobado por el orquestador tras dos rondas externas. Las piezas A (cobertura v2) y B (anclas `document` v2) quedan fuera.
- **Contrato:** C0 `memoria/identidad/v1` sin cambios. Se usan sus valores tal cual: `repo.id`, `agent.name` y `agent.role` (`operador`, `orquestador`, `capitan`, `ejecutor`, `revisor`, `desconocido`).

## Contexto

El 2026-11-19 un orquestador tomó como orden propia una nota que el Operador había dado a **otro** orquestador para **otro** proyecto. La nota vivía en una memoria compartida por carpeta, sin autor visible, sin destinatario, sin proyecto y sin cita.

an-kla ya guarda quién escribe (sobre C0), pero supone que el repositorio donde se escribe es el tema del recuerdo y que todo lo del store es para todos sus lectores. En un puesto de orquestación las dos cosas son falsas: varios orquestadores comparten repositorio y hablan de proyectos distintos. Inyectar memoria sin ámbito ni destinatario repetiría el incidente a escala. Este ADR es requisito de la inyección automática.

## Decisión

### 1. Campos `subject` y `audience`

- **Forma:** campos de primer nivel del registro, como `slot` (ADR-0065 §1). **`record-envelope-v1` no cambia**: el sobre sigue siendo la identidad del escritor, y `subject`/`audience` son lo que el escritor declara del recuerdo.
- **`subject`:** de qué proyecto trata. Un `repo.id` de C0 en forma canónica (`host[:puerto]/ruta`, o `local:`/`remoto:` + 16 hex). Nunca un nombre corto. Fuera de forma: `remember_subject_invalid`.
- **`audience`:** para quién es. Un único valor, de vocabulario cerrado:
  - `all`;
  - `role:<papel>`, con `<papel>` de C0 distinto de `desconocido`;
  - `agent:<nombre>`, con `<nombre>` identificador C0 (`[a-z][a-z0-9_-]{0,31}`) que no sea `desconocido`, `sin-sesion` ni `sin-nombre`.
  Cualquier otro valor: `remember_audience_invalid`. Las líneas de trabajo no son audiencia: para eso está `slot`.
- **Opcionales en `fact`, `decision` y `state`**, con `remember --subject <repo.id> --audience <a>`. Obligatorios en `directive` (§2).
- **Compatibilidad, la regla del diseño:** sin `subject`, el registro trata del repositorio de su sobre (`writer.repo.id`); sin sobre, del proyecto del store. Sin `audience`, es `all`. **Un registro sin los campos nuevos no se filtra nunca** (§4): ni se oculta ni se marca. Las lecturas que muestran el ámbito lo dan como `subject_implicit`.
- **`state`:** la casilla sigue siendo el par (`writer.repo.id`, `slot`) de ADR-0065. `subject` y `audience` no cambian qué cabeza jubila un `state` nuevo; sólo cambian quién la ve (§4).
- **Bandeja:** `an-kla/inbox-entry-v4` = v3 con el enum de `kind` ampliado a `directive` (r2, R69-2-03) y además `subject`, `audience`, `valid_until`, `until_revoked` y `revokes`, todos opcionales en el esquema. v1, v2 y v3 se siguen aceptando. Un binario anterior no lee v4: la regla de la nota de release («`inbox drain` y pendientes a 0 antes de bajar de versión») lo cubre.
- **Idempotencia:** la clave derivada de ADR-0063 y el `payload_sha256` de la entrada incluyen `subject`, `audience`, la vigencia y `revokes` cuando están. El mismo texto para dos proyectos, o para dos destinatarios, son dos intenciones.

### 2. Tipo `directive`

Una orden o preferencia del Operador, escrita por quien la recibió. `remember --kind directive`.

- **Stream:** `facts`, como `decision`. Prefijo de id el de `facts`.
- **Obligatorios, sin valor por defecto**, comprobados al encolar (y otra vez al vaciar, para entradas escritas a mano), en este orden:
  1. papel del escritor `orquestador` o `capitan` (`writer.agent.role` del sobre). Otro papel, `desconocido` incluido: **`directive_role_not_allowed`**;
  2. sesión de origen real: `writer.session.id` distinto del centinela `sin-sesion`. Si no: **`directive_session_missing`**. El sobre la guarda; el turno lo pondrá el resolutor de C2 en su anotación;
  3. `subject`: **`directive_missing_subject`** (un acta de revocación lo hereda del destino, §3);
  4. `audience`: **`directive_missing_audience`** (ídem);
  5. vigencia (§3, r2 R69-2-01): sin `revokes`, exactamente una de las dos: ninguna, **`directive_validity_missing`**; las dos, **`directive_validity_conflict`**. Con `revokes: true`, ninguna: si lleva alguna, **`directive_validity_conflict`**;
  6. al menos un ancla `conversation` (C3). Una recién escrita nace `pending`, y vale. Sin ninguna: **`directive_anchor_missing`**. Puede llevar además otras anclas.
  Todos son rechazos de `remember-error-v1` con rc 3, sin encolar nada; al vaciar, la entrada va a `rejected/` con el mismo código.
- **Los campos de vigencia y `revokes` sólo valen en `directive`.** En otro `kind`: `remember_directive_field_not_allowed`.
- **Ni `state` ni `fact` sustituyen a una `directive`, ni al revés:** `remember_kind_mismatch`, como cualquier `kind` distinto en el mismo stream que no sea `fact`/`decision`.
- **Sólo por `remember` (R69-03).** `plan-write` rechaza todo registro con `kind: directive` en su sobre o con cualquiera de `subject`, `audience`, `valid_until`, `until_revoked` o `revokes`: **`plan_write_scope_fields_not_allowed`**. El ámbito sólo se escribe por el camino que lo valida. Lo que llegue por `export restore` o `relocate` desde un store ajeno lo cubre la comprobación al leer (§5, `malformed`).

### 3. Vigencia, sustitución y revocación

- **`valid_until`:** fecha `AAAA-MM-DD` (vale hasta el final de ese día en UTC) o instante `AAAA-MM-DDTHH:MM:SSZ`. Se guarda normalizado al instante UTC del final de su vigencia, con su forma original en `valid_until_input`. Una fecha ya pasada al encolar: **`directive_valid_until_past`**.
- **`until_revoked: true`:** vale hasta que otra `directive` la sustituya o la revoque.
- **Sustituir:** `remember --kind directive --supersedes <id>` con su propio `subject`, `audience` y vigencia. El destino tiene que ser una `directive` vigente con el **mismo `subject`**; si no, `directive_subject_mismatch`.
- **Revocar:** `remember --kind directive --supersedes <id> --revoke`. El registro nuevo lleva `revokes: true`, no lleva vigencia (darla: `directive_validity_conflict`) y **nunca se sirve como orden**: es el acta de la revocación. `--revoke` sin `--supersedes`: `directive_revoke_without_target`.
- **De quién: excepción a D3 (r1, R69-01).** Una `directive` no es una observación de su escritor: es la palabra del Operador, que el escritor registró. D3 existe para que un agente no silencie lo que otro observó; aplicado aquí, haría inmortal una orden `until_revoked` en cuanto su escritor deja de existir. Por eso, entre directivas:
  - cualquier escritor con papel `orquestador` o `capitan` sustituye o revoca una `directive` vigente del **mismo `subject`**, sea suya o no, con `supersede` normal (ADR-0019) y **sin abrir disputa**;
  - el registro nuevo cumple todo §2, incluida su propia ancla `conversation`: la de la conversación en que el Operador dio la nueva orden o la revocación. Queda auditable quién la retiró, desde qué sesión y con qué cita;
  - una `directive --supersedes` de otro papel ya se rechaza en §2 (`directive_role_not_allowed`), y otro `kind` con `--supersedes`, por `remember_kind_mismatch`. El único camino de disputa sobre una `directive` es `dispute <id>` (ADR-0066 §6), abierto a cualquier papel: la `directive` sigue vigente, pero ya no es accionable (§5).
- **Revocación: ámbito heredado (r2, R69-2-02).** `--revoke` toma `subject` y `audience` del destino y los guarda en el acta. No los pide, porque no son una decisión nueva sino los de la orden que se retira. Si se dan y difieren de los del destino: `directive_subject_mismatch`, o `directive_audience_mismatch`.
- **El papel `operador` no escribe directivas (R69-06).** Lo fija el diseño: el Operador da la orden en una conversación, y el agente que la recibe la registra con el ancla a esa conversación. Lo que la sostiene es la cita, no el papel declarado por el escritor. Una `directive` escrita «como Operador» sin conversación que citar no tendría ancla que comprobar.

### 4. Lectura: quién lee y qué se le sirve

- **El lector** es la identidad C0 de quien lee, tomada como al escribir: `agent.name` y `agent.role` del entorno (`AN_KLA_AGENT_NAME`, `AN_KLA_AGENT_ROLE`). Sin ellos, `sin-nombre` y `desconocido`. Su **proyecto** es el `repo.id` del checkout del proyecto (`identity_c0.repo_id_for`), o el que declare con `--subject <repo.id>`. Un orquestador que trabaja para otro proyecto desde un puesto común lo declara así. Es una afirmación, como el sobre: sirve para filtrar, no prueba nada.
- **Coincidencia.** Un registro **es para el lector** si se cumplen las dos:
  - no tiene `subject` explícito, o su `subject` es el proyecto del lector;
  - no tiene `audience` explícito, o es `all`, o es `role:<el papel del lector>`, o es `agent:<el nombre del lector>`.
  Si no, es **para otro**.
- **Por defecto lo que es para otro no se sirve.** Se cuenta: `excluded.other_audience` (o `excluded_summary.other_audience` en `retrieve`). Con `--include-other-audience` sí se sirve, y cada uno lleva `"for_reader": false`. Lo que es para el lector no lleva el campo.
- **Cálculo perezoso:** el proyecto del lector (una llamada a `git`) sólo se calcula si algún registro leído trae un `subject` explícito. Si no se puede calcular (sin `git`, sin repositorio), todo registro con `subject` explícito es para otro: falla cerrado.
- **Superficies:**
  - **Filtran:** `retrieve` (CLI y MCP, y la evaluación), `list` y `state show`. Las tres de CLI aceptan `--subject` y `--include-other-audience`. **MCP no gana parámetros:** filtra siempre y nunca sirve lo que es para otro.
  - **Inyectan, y por eso no llevan directivas (r1, R69-02):** `assemble-context` y `resume` proyectan sólo el texto de cada registro (`text`/`render`), así que perderían el objeto `directive` y entregarían la orden como un hecho más. Hasta que la inyección automática tenga su propio ADR con la marca:
    - las dos filtran lo que es para otro, como `retrieve`, sin `--include-other-audience`;
    - y **no inyectan ninguna `directive`**, sea para el lector o no. Cuentan `directive_not_injected`. Una orden se lee por `retrieve`, `list` o `state show`, que llevan su `status` y su `actionable`;
    - sus contadores siguen la regla dispersa: `assemble-context` sube a `context-assembly-v3` sólo si `excluded_summary` lleva `other_audience`, `directive_inactive` o `directive_not_injected`. `resume`, que hoy lista sus claves fijas con ceros, añade las nuevas sólo si no son cero, y entonces sube a `resume-v2`. Sin registros nuevos, las dos salen byte a byte como en beta.38.
  - **`--subject` mal formado (R69-05):** `retrieve_subject_invalid`, `list_subject_invalid` y `state_subject_invalid`, con rc y forma de los demás errores de argumentos de cada orden (ADR-0065 y ADR-0067).
  - **Qué lleva un registro servido (R69-04):** un `fact`, `decision` o `state` con ámbito explícito que es para el lector se sirve en `retrieve` y `state show` **sin claves nuevas**: su ámbito ya coincide con quien lee. Si es para otro (con `--include-other-audience`) lleva `for_reader: false`, `subject` y `audience`. Una `directive` lleva siempre su objeto `directive`, que incluye `subject` y `audience`. `list` y `history`, que son para auditar, muestran `subject` y `audience` siempre que sean explícitos.
  - **Marcan sin filtrar**, porque piden algo por id o auditan: `history <id>`, `disputes list`, `anchors verify`. Cada registro para otro lleva `"for_reader": false`.
  - `state show`: si la cabeza de una casilla es para otro, la casilla no sale y cuenta en `excluded.other_audience`. No se sirve en su lugar el `state` anterior: la cabeza es la que es.
  - `list`: el cursor fija también `subject` e `include_other_audience`.
- **Esquemas de las otras lecturas:** la misma regla dispersa de §6. `list-result`, `state-result`, `history-result`, `disputes-list` y `anchors-verify` suben a la versión siguiente sólo cuando la respuesta lleva alguna clave nueva (`for_reader`, `directive`, `subject`, `audience`, `subject_implicit`, `other_audience`, `directive_inactive`). Si no, salen igual que en beta.38. `subject_implicit` sólo sale con `--include-other-audience`, en `list` y `history`: es información para auditar, no para servir.
- **Lo que no es lectura de servicio no cambia:** `export`, `inventory`, `verify`, `inbox status`, `compact` y `relocate` ven todos los registros.

### 5. Cómo se sirve una `directive`

Cada `directive` servida lleva un objeto `directive`:

```json
{"status": "unverified", "actionable": true, "subject": "...", "audience": "agent:...",
 "valid_until": "2026-12-01T23:59:59Z", "writer": {"name": "...", "role": "orquestador"},
 "session": "claude:...", "anchor_freshness": "pending"}
```

(`until_revoked: true` en lugar de `valid_until`; `revokes: true` en un acta de revocación.) `anchor_freshness` es informativo: el agregado de ADR-0066 sobre **todas** las anclas del registro (peor primero). `status` depende sólo de las anclas `conversation` (r2, R69-2-04).

- **`status`**, por este orden:
  0. `malformed` si el registro no cumple, al leer, las invariantes de forma de §2 y §3: sobre C0 válido, papel `orquestador`/`capitan`, sesión distinta de `sin-sesion`, `subject` y `audience` válidos, exactamente una vigencia (o `revokes` sin vigencia) y al menos un ancla `conversation`. Cubre lo que no pasó por `remember` (R69-03);
  1. `revocation` si lleva `revokes: true`;
  2. `invalidated` si algún ancla `conversation` sale `broken` en la vista de ADR-0066 §6bis (la conversación sellada no contiene la orden);
  3. `expired` si `valid_until` es anterior al reloj de lectura (inyectable en la API; el de la máquina en la CLI);
  4. `verified` si todas sus anclas `conversation` salen `fresh`;
  5. si no, `unverified`. Es el caso de toda `directive` mientras no exista el resolutor de C2.
  La frescura de las anclas `conversation` sale de la vista de resoluciones de ADR-0066 §6bis y del `ConversationVerifier` que se le pase. an-kla no trae ninguno, así que en la CLI de hoy ninguna `directive` sale `verified`: una resolución `resolved` sin verificador queda `unverified`, y una `not_found` da `broken`, o sea `invalidated`. Las pruebas inyectan un verificador por la API, como las de ADR-0066. Leer no usa Git ni arranca ningún resolutor.
- **`actionable`**, la regla de las tres condiciones del diseño. Es `true` sólo si `status` es `unverified` o `verified` y además:
  1. `writer.role` es `orquestador` o `capitan`; se vuelve a mirar al leer, por si la entrada llegó a mano;
  2. su `subject` es el proyecto del lector;
  3. su `audience` nombra al lector: `agent:<su nombre>` o `role:<su papel>`. `all` **no** basta;
  4. no tiene disputas vigentes (`disputes list --target <id>` vacío). Una disputada sale con `disputed: <n>` y `actionable: false` hasta que se resuelva o se sustituya (§3).
  Si es `false`, la `directive` vale sólo como contexto. Para cambiar una acción por ella hay que confirmarla con el Operador. `actionable: true` con `status: unverified` significa que se puede actuar sin esperar al resolutor, y que lo que se sirve es la palabra de quien la escribió.
- **Qué se sirve como orden:** sólo `unverified` y `verified`. `malformed`, `revocation`, `invalidated` y `expired` no se sirven en `retrieve` ni en `state show`; cuentan en `excluded_summary.directive_inactive` (`retrieve`) o `excluded.directive_inactive` (`state show`). `list` y `history` las muestran con su `status`, para auditar. Una sustituida ya no es vigente y sigue el camino de siempre (`inactive`).
- **Una `directive` nunca se aplica a una audiencia distinta de la declarada:** para otro, no se sirve; con `--include-other-audience`, sale con `for_reader: false` y `actionable: false`.

### 6. `retrieve` y su compatibilidad byte a byte

- **Un store sin ningún registro con `subject`, `audience` o `kind: directive` da en `retrieve` la misma salida, byte a byte, que beta.38**, en CLI y en MCP, con o sin perfil de frescura. Por eso:
  - los contadores nuevos (`other_audience`, `directive_inactive`) siguen la regla que ya tiene `excluded_summary`: sólo salen si no son cero. Lo mismo `excluded_detail.ids`;
  - un registro servido sin los campos nuevos no gana ninguna clave;
  - ninguna llamada a `git` si nadie trae `subject` explícito;
  - **versión dispersa, como ADR-0049:** los esquemas publicados de `retrieve` y MCP son cerrados (`additionalProperties: false`) y no se editan. Sólo si la respuesta lleva alguna clave nueva, su `schema` sube a `an-kla/retrieval-result-v4` o a `an-kla/mcp-retrieve-v4`. Cada v4 es el superconjunto de v1–v3 (con `freshness` y `empty_reason` opcionales) más las claves nuevas. Sin claves nuevas, el `schema` es el de hoy, decidido como hoy.
- **Con registros nuevos:** una `directive` servida lleva `directive` (§5) y, si es para otro, `for_reader`. Un registro con ámbito explícito servido a otro lleva lo que dice §4. **Su coste cuenta en el presupuesto:** `cost_bytes` = bytes de `render` + bytes UTF-8 del JSON canónico de las claves añadidas al registro + `per_record_overhead_bytes`. Así el presupuesto exacto sigue siendo exacto, y MCP sigue probando que su respuesta cabe.
- **Prueba:** los goldens de `retrieve` y MCP pasan sin regenerar, y una prueba nueva compara byte a byte la salida de un store sin campos nuevos contra la de la rama base (`git archive` de beta.38 con `PYTHONPATH`, sin instalar), igual que la vuelta atrás de las releases.

### 7. Vuelta atrás

Un binario anterior (beta.38 o menos) lee los registros nuevos sin entenderlos: ignora `subject`/`audience` y trata una `directive` como un registro más de `facts`. **Con él, `retrieve` sirve las directivas sin filtro y sin marca.** La nota de release lo declara como riesgo de bajar de versión con directivas escritas. El remedio es no bajar, o no escribir directivas hasta haber adoptado la versión en todo el puesto. No hay migración que lo evite sin reescribir el store.

## Por qué no

- **`subject`/`audience` dentro del sobre:** el sobre es la identidad de quien escribe (C0) y `additionalProperties: false`. Meterlos ahí cambiaría C0 o el sobre. Como `slot`, van fuera.
- **Valores por defecto en `directive`:** el diseño lo descarta. Un `subject` por defecto (el repo actual) reproduce el incidente (una orden para otro proyecto escrita desde el puesto común pasa por propia). Un `audience: all` por defecto la sirve a todos.
- **Filtrar también los registros sin campos nuevos por el repo de su sobre:** ocultaría registros legítimos tras un cambio de remoto o un `relocate`, rompería el byte a byte de `retrieve` y contradice «nada queda oculto».
- **D3 también entre directivas:** una orden `until_revoked` sería irrevocable en cuanto su escritor deja de existir, o el Operador cambia de orquestador (r1, R69-01). La excepción de §3 sólo vale entre orquestadores y capitanes del mismo `subject`, y exige el ancla de la conversación nueva.
- **Inyectar directivas en `assemble-context`/`resume` con el texto marcado:** mezclaría la marca con el texto del recuerdo, y el consumidor no la distinguiría de algo escrito por el propio escritor. Se queda para el ADR de la inyección automática.
- **Una lista de destinatarios:** el diseño cerró que `audience` no necesita más valores. Dos destinatarios son dos `directive`.
- **Un stream nuevo `directives`:** tocaría índice, exportación, compactación y la vuelta atrás de todas las superficies. `facts` con `kind` ya distingue.
- **`audience: all` como accionable:** el diseño exige que la `directive` nombre al lector. `all` con el `subject` del proyecto dice «todos los agentes de este proyecto», y vale como contexto.
- **Esperar al resolutor para servir:** bloquearía toda orden hasta E2/E4. `unverified` es honesto y no bloquea.

## Consecuencias

- **Positivas:** el caso del incidente deja de pasar en la memoria nueva: una orden para otro proyecto u otro agente no le llega como orden a quien no es su destinatario. La inyección automática puede apoyarse en `actionable`.
- **Negativas:**
  - `retrieve` llama a `git` una vez si algún registro trae `subject`;
  - el lector tiene que llevar su identidad C0 en el entorno para recibir lo que va dirigido a él;
  - bajar de versión con directivas escritas las expone sin filtro (§7).
- **Neutras:**
  - la memoria propia de Claude Code (archivos por carpeta) no tiene estos campos; ahí la mitigación sigue siendo de disciplina;
  - `--subject` del lector es una afirmación, igual que el sobre.

## Pruebas de aceptación

1. **El incidente.** Dos orquestadores, `orq-memoria` y `orq-otro`, en el mismo repositorio R (mismo store). `orq-otro` escribe una `directive` con `subject` P (otro proyecto) y `audience: agent:orq-otro`, con ancla `conversation` `pending`.
   - `orq-memoria` lee con `retrieve`, MCP, `list` y `state show` sin flags: no se le sirve, y `other_audience` = 1.
   - Con `--include-other-audience`, le sale con `for_reader: false` y `actionable: false`.
   - Con `--subject P` tampoco es accionable, porque `audience` no lo nombra.
   - `orq-otro` con `--subject P` la recibe con `status: unverified` y `actionable: true`; sin `--subject P`, no (su proyecto es R).
2. Escritura: cada código de §2 y §3 en su orden, sin encolar nada; la misma entrada escrita a mano en `pending/` acaba en `rejected/` con el mismo código al vaciar.
3. Vigencia: `valid_until` pasado al leer da `expired`, sin servirse y contada en `directive_inactive`; `until_revoked` sigue vigente. Rotación: `orq-a` escribe una `until_revoked`; `orq-b` (otro nombre, papel `orquestador`, mismo `subject`) la revoca sin disputa, y la original deja de servirse. Un `ejecutor` que intenta sustituirla: `directive_role_not_allowed`; un `fact --supersedes` sobre ella: `remember_kind_mismatch`; un `dispute <id>` de cualquier papel: la original sigue vigente con `disputed: 1` y `actionable: false`. Revocar heredando el ámbito, y con un `audience` distinto: `directive_audience_mismatch`. Sustituir con otro `subject`: `directive_subject_mismatch`.
4. Ancla: con una resolución `not_found` inyectada (`anchor-resolution-v1`), `invalidated`; con una `resolved` y un `ConversationVerifier` de prueba cuyo turno contiene la cita, `verified`; con `resolved` sin verificador, `unverified`.
5. Compatibilidad: goldens de `retrieve`/MCP sin regenerar; comparación byte a byte contra beta.38 de un store sin campos nuevos; ninguna llamada a `git` en ese caso (con `git` fuera del `PATH`).
6. Presupuesto: `cost_bytes` de una `directive` servida cuenta su objeto `directive`; MCP cabe en `budget_bytes`.
7. `role:` y `agent:` con el lector sin identidad en el entorno: para otro. `audience: all` con `subject` propio: se sirve, `actionable: false`.
8. Inyección: con una `directive` accionable para el lector y otra para otro, `assemble-context` y `resume` no inyectan ninguna de las dos y cuentan `other_audience` y `directive_not_injected`, con `context-assembly-v3` y `resume-v2`. Sin registros nuevos, sus salidas son byte a byte las de beta.38.
9. Escritura por otros caminos: `plan-write` con `kind: directive` o con `subject` da `plan_write_scope_fields_not_allowed`. Un registro `directive` sin ancla o con `sin-sesion`, metido en el store por un `export restore` de prueba, sale `malformed`, no se sirve y no es accionable.

## Referencias

- Diseño, pieza C («ámbito de un recuerdo»), del esfuerzo de memoria agéntica; rondas externas r1 `fix-and-retry` y r2 `proceed`.
- ADR-0063 (D2 sobre, D3 disputa), ADR-0065 §1 (`slot` de primer nivel), ADR-0066 §6bis (resolución de anclas `conversation`), ADR-0067 (`list`).
