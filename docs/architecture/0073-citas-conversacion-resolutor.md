# ADR-0073: Citas de conversación con resolutor (`fact`, `decision` y `state`)

- **Estado:** Aceptada por delegación del orquestador (mandato 16, con el cambio de alcance del Operador), 2026-11-20, tras r3 `proceed` sin hallazgos. r1 de otra familia (Gemini): `fix-and-retry` (3 HIGH, 1 MEDIUM, 1 LOW). Se incorporan R73-01, R73-02 y R73-05. R73-03 y R73-04 eran sobre `directive` y caen con el cambio de alcance (abajo). r2: `fix-and-retry` (1 HIGH, 1 LOW), incorporado
- **Implementación:** No iniciada
- **Fecha:** 2026-11-20
- **Decide sobre:**
  - la llamada al resolutor de conversaciones;
  - dónde se guarda lo que responde, en los tres momentos;
  - la regla de «concluyente» para las citas de conversación;
  - la voz (`speaker`), que viaja aparte del ancla;
  - `served` siempre presente en `anchors verify`;
  - la evidencia de cobertura de un ancla `document` (errata 7 de `ancla/v1`, §8).
- **Enmienda:** ADR-0066 §6bis (las resoluciones ya no sólo se leen: ahora se escriben) y ADR-0072 §2 (`served`).
- **Cambio de alcance (decisión del Operador, 2026-11-20):** la política de órdenes se aplaza: quién las escribe, qué sesiones cuentan y cuándo se verifican. **Este ADR no toca `directive`.** Sus anclas no se resuelven, y siguen `pending` y `unverified` exactamente como en beta.40 (§5).
- **Contrato:** `memoria/conversacion-resolutor/v1`, congelado (`coordination` `c77d75e`; 31 casos, sha256 `1e9187a9…7e78`). Errata 6 de `memoria/ancla/v1`. C0 sin cambios.

## Contexto

Un ancla `conversation` nace `pending` y así se queda, porque no había resolutor. Desde ADR-0066 hay un esquema de anotación (`anchor-resolution-v1`), pero ninguna orden pública lo escribe.

El resolutor de skopos ya está integrado (`a0dc57b`). Busca la cita en un mensaje de la sesión, la sella y dice en qué voz está. El texto no sale de su proceso.

Con eso, an-kla puede saber que una cita **entró por el canal de usuario** de una sesión. **No puede saber que hablara el Operador**: en una sesión orquestada, el «usuario» es otro agente (README, «Lo que `user` no prueba»). Lo que eso implica para una orden se deja para cuando el Operador decida esa política.

## Decisión

### 1. La llamada

- **Configuración:** en el mismo archivo que la tabla de custodios (`AN_KLA_CUSTODIANS`, o `config.json` del store, con las mismas reglas y el mismo «tabla ilegible» de ADR-0071 §3), con otra clave:
  ```json
  {"custodians": {…}, "conversation_resolver": {"custodian": "skopos", "argv": ["/ruta/python", "-B", "/ruta/resolver.py", "…"]}}
  ```
  - **Un único resolutor.** Un ancla `conversation` no nombra custodio, y su forma cerrada de `ancla/v1` no lo admite. El resolutor de skopos cubre Claude Code y Codex. `custodian` sólo sirve para informar y para el aviso.
  - **Ausente:** «sin resolutor» (`no_verifier` en una `resolved`; `resolution_pending` en una `pending`).
- **Proceso:** el mismo de ADR-0071 §3, reutilizado:
  - un proceso por petición, `argv` sin intérprete de órdenes;
  - entorno mínimo y `cwd` `/`;
  - tope de 8 MiB y plazo de 10 s inyectable;
  - muerte del grupo de procesos.
- **Validación de la respuesta:** forma cerrada (exactamente sus claves) y coherencia, según el README del resolutor:
  - `resolved` exige `speaker: user`, `turn_id`, `seal`, `match` y `candidates.user ≥ 1`;
  - `not_found` exige `tail: closed` y `candidates` todo a 0;
  - `pending` exige `candidates.user = 0`, y con `origin_unreadable`, `tail: open`;
  - `session: unknown` exige `session_unavailable` y `tail` nulo;
  - en `verify`, `turn_missing` exige `quote: unknown` y `speaker` nulo, y la sesión no disponible lleva `seal`/`quote` en `unknown`.

  El objeto `{"schema": "invalid", …}`, otro `schema`, una incoherencia (C13–C17, C31), el plazo, rc ≠ 0 o una salida que no es JSON dan **`resolver_error`**: nunca excepción ni `broken`.
- **La petición** lleva `session` (la del ancla), `quote` y `quote_sha256`, y en `verify` también `turn_id` y `seal` del último resultado concluyente.

### 2. Los tres momentos y dónde se guarda (un solo mecanismo para `document` y `conversation`)

- **Al escribir,** `remember` llama a `resolve` por cada ancla `conversation` de un `fact`, una `decision` o un `state` (no de una `directive`, §5). El resultado se guarda en `anchor_checks` del registro, el mismo campo que ya usa `document` (ADR-0071 §5).
  - El ancla **se guarda siempre como nace** (`resolution: pending`, `turn_id` y `seal` nulos). Su forma cerrada y su clave de idempotencia no cambian (A5).
  - Lo que dijo el resolutor vive en el resultado: `resolution`, `turn_id`, `seal`, `speaker`, `candidates`, `match`, `detail`, las tres comprobaciones con sus motivos, la frescura y `checked_at`.
  - **El «ancla resultante» de la tabla del contrato** (`resolved`, con `turn_id` y `seal`, o `not_found`) es el **ancla servida**. Al leer se construye aplicando el último resultado concluyente, como ya hace la vista de §6bis con una anotación de resolución. Lo que se guarda no cambia; lo que se sirve es lo que dice el contrato.
  - Un ancla que queda `pending` es válida y se escribe: no hay rechazo por resolución, ni por `not_found`.
- **Al auditar,** `anchors verify` llama, en las anclas `conversation` de esos mismos tipos, a `resolve` en las que su último resultado concluyente no es `resolved`, y a `verify` en las que sí. Guarda el resultado como anotación `anchor-check` en `events`, igual que `document`.
- **Al leer** no se llama a nadie. Se sirve lo guardado con su fecha (ADR-0071 §5, orden total incluido).
- **Esquema de lo guardado:**
  - `anchor_checks` y la anotación ganan, **sólo para entradas de `conversation`**, las claves `resolution`, `turn_id`, `seal`, `speaker`, `candidates` y `detail`, y pierden las de `document` (`manifest_sha256`, `derivation`, `custody`);
  - la anotación con alguna entrada de `conversation` sube a `an-kla/anchor-check-v2`. `anchor-check-v1` está publicado y sólo describe `document`;
  - `candidates` tiene una forma cerrada: `{"user": n, "pasted": n, "other": n}`, con enteros no negativos (r1, R73-05). Es **nulo en un resultado de `verify`**, que no lo trae; el esquema admite `null` (r2, R73-07);
  - **la bandeja** (r1, R73-02): `inbox-entry-v4` está publicado (beta.39) y referencia `anchor-check-v1`. Una entrada que lleva una anotación `anchor-check-v2`, o un resultado de `resolve` en sus anclas, sube a **`inbox-entry-v5`**, que es v4 más eso. beta.40 rechaza entera una entrada v5 al vaciar (`inbox_entry_invalid`): se cubre con la regla de siempre («`inbox drain` y pendientes a 0 antes de bajar») y con el remedio `inbox requeue --all-format && inbox drain` de vuelta en esta versión;
  - beta.40 ignora una entrada que no reconoce (`valid_check`): no rompe, y sirve esas anclas como hasta ahora (§7).
- **Las anotaciones `anchor-resolution-v1` ya escritas** (sólo por pruebas: ninguna orden pública las escribía) se siguen leyendo. Si un ancla tiene las dos, gana el resultado guardado más reciente, por el orden total.

### 3. Concluyente: una sola regla, con el criterio de cada contrato

La regla es la de ADR-0072 §1, para los dos tipos: **al leer, se sirve el último concluyente; si no hay ninguno, el último a secas**. Lo que cambia es el criterio de «concluyente», que fija cada contrato:

- **`document`** (errata 6 de `ancla/v2`): concluye si `integrity_reason` no es `no_adapter` ni `adapter_error`. Sin cambio.
- **`conversation`** (README del resolutor): concluye si el ancla pasa a `not_found`, si alguna comprobación es `not_found`, o si las tres son `verified`.
  - No concluyen `pending`, `no_verifier`, `resolver_error`, `session_unavailable` ni `seal_unverifiable` (C25–C29).
  - Sí concluye la rotura comprobada (C32).

Una función, `is_conclusive(check, kind)`, con los dos criterios.

### 4. La voz viaja aparte

- `speaker` y `candidates` se guardan en el resultado, no en el ancla. Se sirven junto a las tres comprobaciones en `history`, `state show` y `anchors verify`.
- **Reclasificación (C30):** si en una auditoría el custodio dice que la cita está en otra voz, el ancla sigue `fresh` y el resultado nuevo lleva el `speaker` nuevo. Lo que eso signifique para una orden es de la política aplazada.

### 5. `directive`: sin cambio

- **No se llama al resolutor para las anclas de una `directive`,** ni al escribir ni al auditar. Siguen `pending`, y la `directive` sigue `unverified`, con la misma regla de `actionable` que en ADR-0069 §5. Si se las resolviera, la precedencia de ADR-0069 §5 llevaría una cita `fresh` a `verified`, y eso es justo lo que el Operador ha aplazado.
- Ninguna `directive` se inyecta (`directive_not_injected`), y en los stores reales todavía no se escriben.
- Cuando el Operador decida la política, el resultado ya se podrá guardar con el mismo mecanismo (§2). Ese ADR dirá qué estado da.

### 6. `anchors verify` y la segunda anotación

- **`served` siempre** (fricción de beta.40). En una auditoría, toda ancla `document` o `conversation` lleva `served`, sea igual al intento o no. En ADR-0072 §2, `served` sólo salía cuando el intento no concluía.
- **Esquemas** (r1, R73-01): `anchors-verify-v3` está publicado (beta.40) y su `served` no admite `pending` ni las claves de conversación.
  - Con sólo anclas `document` auditadas, la respuesta es **siempre `anchors-verify-v3`**: v3 ya admite `served` en toda ancla `document`.
  - Con alguna ancla `conversation` auditada, la respuesta es **`anchors-verify-v4`**. Es v3 más, por ancla, `speaker`, `candidates`, `resolution`, `turn_id`, `seal` y `detail`, y `served.freshness` con `pending`.
  - Una auditoría sin anclas de esos tipos sale como antes.
- **Las demás salidas que sirven el resultado** (r2, R73-06) están publicadas y cerradas: `remember-result-v3`, `history-result-v2` y `state-result-v2`. Así que una respuesta que lleva el resultado de un ancla `conversation` con resolutor sube, de forma dispersa, a **`remember-result-v4`**, **`history-result-v3`** o **`state-result-v3`**.
  - Ese resultado lleva `speaker`, `candidates`, `resolution`, `turn_id`, `seal` y `detail`, y los motivos nuevos de la errata 6: `session_unavailable`, `resolver_error`, `seal_unverifiable` y `session_lacks_quote`.
  - Cada versión nueva es la anterior más esas claves y esos valores.
  - Sin un resultado así, el esquema es el de hoy.
- **El segundo registro de cada auditoría,** que se documenta en la guía: cada auditoría que guarda añade a `events` la anotación `anchor-check` y **el registro de la política de escritura** (`e-write-policy-…`, ADR-0007). Ese registro lo añade todo commit de la bandeja, también cada `remember`. No es un duplicado.

### 7. Compatibilidad y vuelta atrás

- **Un store sin anclas `conversation`** se lee igual que en beta.40, y `retrieve` y MCP no cambian. Una `conversation` sin resultado guardado se sirve como hasta ahora: `pending`, con la vista de §6bis.
- **beta.40 sobre un store de esta versión:**
  - ignora las entradas `conversation` de `anchor_checks` y las anotaciones `anchor-check-v2`;
  - sirve esas anclas `pending`;
  - no rompe. Se prueba.

### 8. Evidencia de cobertura de un ancla `document` (errata 7 de `ancla/v1`, añadida por orden del orquestador)

- **Contrato:** la errata 7 de `ancla/v1` y `coverage-evidence-vectors.json` (34 casos, sha256 `b3034270…3f50`). La implementó agora en `6bdfa88`. Resuelve la fricción 7.1 de beta.39: una cita correcta de documento salía `none`, porque la página y la clave del documento contaban como números ausentes. Sustituye a la propuesta de un `fact-checks-rules/v3`, que agora aparca.
- **La cobertura se mide contra una evidencia por ancla:**
  - en `repo-file` y `conversation`, la evidencia es la cita, como hasta ahora;
  - en `document` (esquema v1 o v2), es `quote`, más `"\n" + str(locator.page)` si `locator` es un objeto con `page` entero, más `"\n" + copy.path` si lleva `copy`. `item_id` e `item_ids` no entran.

  Las reglas (`fact-checks-rules/v2`) y su función no cambian.
- **Se declara:**
  - si el registro tiene al menos un ancla `document` de forma válida, `coverage` lleva `evidence: "ancla-document/v1"` junto a `rules`;
  - sin anclas `document`, la salida es byte a byte la de antes;
  - sólo se aplica con v2, y lo guardado no se recalcula;
  - una evidencia de más de 16 384 bytes anula la cobertura de todo el registro (`coverage_error`); no se trunca.
- **Esquemas:** la clave `evidence` entra en las versiones dispersas nuevas de §6 (`remember-result-v4`, `history-result-v3` y `state-result-v3`), que todavía no están publicadas. Una respuesta con `coverage.evidence` también las dispara.
- **`anchors verify` también sirve la cobertura del registro** (ronda de código r1, Q-04). Una auditoría cuya respuesta lleva `coverage.evidence` sube a **`anchors-verify-v4`**, aunque sólo tenga anclas `document`, porque `anchors-verify-v3` (publicado) no admite esa clave. Sin `coverage.evidence` ni anclas `conversation`, la auditoría de un `document` sigue en v3.
- **Prueba de aceptación:** los 34 casos, exactos, con su sha256 comprobado.

## Por qué no

- **Escribir el ancla ya `resolved` al nacer:** cambiaría su forma guardada en un store que sólo añade, y la regla A5 de C3 («nace `pending`»). El resultado guardado da lo mismo sin tocar el ancla.
- **Una tabla por cliente** (`claude`, `codex`): el resolutor de skopos cubre los dos, y el ancla no dice cuál.
- **Resolver también las anclas de las `directive`:** con ADR-0069 §5, una cita resuelta daría `verified`, que sería afirmar que habló el Operador. El contrato dice expresamente que no lo prueba, y el Operador ha aplazado esa política.
- **Seguir con `anchor-resolution-v1`:** describe sólo la resolución. Faltan la voz, los candidatos y las tres comprobaciones, y habría dos mecanismos para lo mismo.

## Consecuencias

- **Positivas:**
  - las citas de conversación se comprueban de verdad;
  - una cita dada en el canal de usuario se distingue de una pegada o reclasificada;
  - un solo mecanismo y una sola regla de concluyente.
- **Negativas:**
  - escribir una `conversation` tarda lo que tarde el resolutor (≈0,5 s en skopos);
  - las anotaciones siguen sin poda;
  - las `directive` siguen sin comprobar, hasta la política aplazada.
- **Neutras:** los orígenes se borran a plazo (30 días en Claude Code). Pasado ese plazo, se sirve el último concluyente con su fecha.

## Pruebas de aceptación

1. **Examen:** los 31 casos con un resolutor de prueba que es un **proceso real**. Cada campo de `expect` es exacto: `resolver_called`, `resolution`, `turn_id`, `seal`, las tres comprobaciones con su motivo, la frescura, `speaker`, `detail` y `served` (`new` o `stored`).
2. **`ancla/v1`:** los casos S01–S13 siguen pasando, leídos con la errata 6.
3. **Pruebas de proceso:** plazo (corto, y el de 10 s por defecto), rc ≠ 0, salida que no es JSON, stderr ruidosa, salida de más de 8 MiB, y el nombre del custodio fuera de rutas y de `argv`.
4. **Los tres momentos:**
   - escribir guarda el resultado y el ancla queda `pending`;
   - auditar guarda la anotación, con `resolve` o `verify` según el último concluyente;
   - leer no lanza ningún proceso;
   - una auditoría fallida no rebaja un `fresh` (C28, C29).
5. **`directive`:** con un resolutor configurado y una `directive` con ancla `conversation`, **no se lanza ningún proceso**, ni al escribir ni al auditar; su `status` y su `actionable` son byte a byte los de beta.40.
6. **`anchors verify`:** `served` en toda ancla auditada, también cuando el intento concluye; `anchors-verify-v3` con sólo `document`, `anchors-verify-v4` con alguna `conversation`. Y una entrada `inbox-entry-v5` rechazada por beta.40 se recupera con `inbox requeue --all-format && inbox drain`.
7. **Resolutor real** (skopos `a0dc57b`, sólo lectura, con la orden de su informe 35): una cita de una sesión del capitán con el orquestador, escrita, auditada y leída. El informe da sólo cuentas, huellas y resultado, **ningún texto de turno**, y comprueba que el resolutor no escribe nada.
8. **Compatibilidad:** los goldens de `retrieve` y MCP sin regenerar. `test_scope_compat`, `test_document_v2_compat` y `test_friccion_b39` pasan. Se prueba la vuelta atrás a beta.40.

## Para el orquestador

- **La política de órdenes** queda aplazada por decisión del Operador. Cuando llegue, el resultado guardado y la voz ya estarán disponibles para ella.
- **Un solo resolutor en la tabla.** Si algún día hay dos custodios de conversaciones, hará falta otra forma, y un ancla que nombre custodio, que es un cambio de C3.

## Referencias

`memoria/conversacion-resolutor/v1`; errata 6 de `ancla/v1`; skopos ADR-029 y `docs/resolutor-conversacion.md`; ADR-0066 §6bis, ADR-0069 §5, ADR-0071 §3 y §5, ADR-0072.
