# ADR-0070: Cobertura con `fact-checks-rules/v2` y modo `state` (errata 4 de C3)

- **Estado:** Aceptada por delegación del orquestador (respuesta al informe 19: «sigue con tu cola»), 2026-11-19, tras r1 `proceed` de otra familia (Gemini; 1 MEDIUM, 2 LOW, incorporados)
- **Implementación:** No iniciada
- **Fecha:** 2026-11-19
- **Decide sobre:** con qué reglas calcula an-kla la cobertura de lo que se escribe desde ahora, dónde se guarda con qué reglas se calculó, y cómo se sirve lo ya escrito con v1.
- **Depende de:** ADR-0066 §3 (cobertura determinista, guardada al escribir, sólo `none` como aviso), ADR-0069 (esquemas dispersos de lectura).
- **Contrato:** C3 `memoria/ancla/v1`, errata 4 (2026-11-19): reglas `fact-checks-rules/v2` de agora, `fact-checks-v2-vectors.json`, 74 casos, sha256 `9b06bbe7eded09989d207ae3d7d580be44e1b2f0fae042778a85015cc53b7ca8`. Los 63 casos de v1 siguen valiendo.
- **Cierra:** #239 (una fecha contaba como tres números).

## Contexto

Con v1, sobre recuerdos reales de beta.38:
- una fecha `AAAA-MM-DD` contaba como tres números sueltos, y bastaba para bajar un registro a `partial` (#239);
- las huellas cortas sin comillas invertidas no eran elemento;
- `beta.38` dejaba suelto el `38`;
- en un `state` la cobertura salía casi siempre `none`, que es el único nivel que se sirve como aviso.

agora publicó `fact-checks-rules/v2` al lado de v1, y C3 la adoptó en su errata 4, con un modo `state`. ADR-0066 §3 guarda la cobertura al escribir y nunca la recalcula. Por eso adoptar v2 es decidir qué reglas usa lo nuevo y cómo convive con lo ya guardado.

## Decisión

### 1. Reglas al escribir

- **Todo lo que se escribe desde esta versión calcula la cobertura con `fact-checks-rules/v2`:** `remember` (respuesta y registro), el vaciado de la bandeja y `dispute`. No hay opción para escribir con v1. La errata deja ofrecer las dos, pero una sola regla al escribir evita que dos escritores del mismo store calculen distinto el mismo texto.
- **Implementación propia** en `an_kla/anchors_coverage_v2.py`, derivada de los 74 vectores, como hizo ADR-0066 con v1. La de agora (`src/agora/fact_checks_v2.py`, `3c0b14c`) es sólo la referencia. `anchors_coverage.py` (v1) se queda como está, con sus 63 vectores, para lo ya escrito y para el contraste.
- **El orden de extracción es el de los vectores y el de agora:** `identifier`, `path`, `date`, `hash`, `version`, `number`. La sección A del diseño ponía `date` antes que `path`. Los vectores fijan lo contrario, «una fecha dentro de una ruta es parte de la ruta», y la norma son los vectores.
- **`missing`:** ordenado por tipo (`identifier`, `path`, `hash`, `version`, `date`, `number`) y por aparición, con 8 entradas como máximo; `missing_total` las cuenta todas, como en v1.
- **Modo por `kind`:**
  - `fact`, `decision`, `directive` y el registro de un `dispute` (que es `fact`): los seis tipos;
  - `state`: sólo `identifier`, `path`, `hash` y `version`. Sin ninguno de los cuatro, `unchecked`, nunca `none`. Es la cobertura `state` de cada vector.
  - **El modo llega a cada cálculo (r1, R70-01).** El `kind` del registro se pasa a `coverage_fields` en los dos sitios donde se calcula: al encolar, para la respuesta de `remember`, y al vaciar (`record_fields`, desde el `kind` de la entrada). Hoy `record_fields` no recibe el `kind`, así que sin ese cambio el vaciado de un `state` calcularía en modo `fact`.

### 2. Dónde dice con qué reglas se calculó

- **`coverage.rules`:** `"fact-checks-rules/v2"`, dentro del objeto `coverage` del registro, junto a `total`, `present` y `level`. La errata pide que «la cobertura diga con qué reglas se calculó»: la clave va donde está lo que describe.
- **Un registro sin `coverage.rules` se calculó con v1.** Es todo lo escrito por beta.36–beta.38. Nunca se recalcula ni se reescribe: se sirve tal cual se guardó.
- **Al servir no se añade `rules` a lo que no lo tiene.** Así un store sin registros nuevos sigue dando byte a byte lo de beta.38 en `history`, `state show`, `anchors verify` y `list`. Quien lee un `coverage` sin `rules` sabe que es v1.

### 3. Esquemas

- **Lo que sale con v2 no cabe en los esquemas cerrados de hoy.** `coverage` tiene `additionalProperties: false` y el `type` de `missing` es un enum sin `hash` ni `date`. Por eso sigue la regla dispersa de ADR-0069 §6: una respuesta sube de esquema sólo si lleva una cobertura v2.
  - `remember-result-v1`, que está publicado, pasa a `remember-result-v2` cuando la respuesta lleva cobertura v2.
  - `history-result-v2`, `state-result-v2` y `anchors-verify-v2` (ADR-0069) **no están publicados todavía**: entran en `main` con ADR-0069 y salen en la misma release que este ADR. Se amplían en el sitio con `coverage.rules` opcional y los tipos `hash` y `date` en `missing`. Su disparador de versión dispersa añade «o una cobertura con `rules`». Si esta release saliera sin este ADR, no se tocarían.
  - `remember-error-v2` y `list-result-v2` no llevan cobertura y no cambian.
- **Vuelta atrás:** un binario anterior lee `coverage.rules` y los tipos nuevos como datos que no entiende. Los sirve con los nombres tal cual, porque sus esquemas no se validan al leer. No se pierde nada. Su `remember` volvería a escribir con v1, sin `rules`, que es lo que v1 significa.

### 4. Qué no cambia

- `retrieve` y MCP no muestran cobertura (ADR-0066 §4): no cambian.
- Sólo `none` se sirve como aviso; ningún nivel afirma respaldo (ADR-0066 §3).
- Las anclas `document` (pieza B) y el ámbito (ADR-0069) no se tocan.

## Por qué no

- **Recalcular lo ya escrito con v2:** reescribiría registros que el store sólo añade, y cambiaría niveles ya servidos sin que el texto ni la cita hayan cambiado. La errata lo prohíbe: «lo ya guardado con v1 no se recalcula».
- **Elegir las reglas con una opción al escribir:** la errata lo permite, pero dos escritores con opciones distintas guardarían cosas distintas para el mismo texto. Si hiciera falta escribir con v1, la vuelta atrás ya lo da.
- **`coverage_rules` de primer nivel:** separaría el dato de lo que describe y añadiría una clave más al registro. Dentro de `coverage` también se lee junto en `remember`, `history` y `state show`.
- **Ampliar en el sitio `remember-result-v1`:** está publicado (beta.36–38), y los esquemas publicados no se editan.

## Consecuencias

- **Positivas:**
  - #239 queda cerrado, porque una fecha cuenta como una;
  - en un `state`, `none` vuelve a significar «cita algo ajeno»;
  - las huellas de commit y `beta.N` cuentan como elementos.
- **Negativas:**
  - conviven dos reglas en un mismo store, y quien compare niveles tiene que mirar `rules`;
  - los límites declarados de v2 (año suelto, fecha en palabras, `beta.38` frente a `0.1.0b38`, hora separada por espacio, `deface1` como `hash`) los hereda an-kla tal cual.
- **Neutras:**
  - `partial` y `full` siguen sin servirse como aviso;
  - entre v1 y v2, de los 63 vectores de v1 sólo uno cambia de nivel.

## Pruebas de aceptación

1. **Vectores:** los 74 casos de `fact-checks-v2-vectors.json` (sha256 comprobado en la prueba), copiados en `tests/fixtures/`, dan `elements` y `missing` exactos, y la cobertura en modo `fact` y en modo `state` exacta. Los 63 de v1 siguen pasando con `anchors_coverage.py`.
2. **Contraste con agora**, como en E1.d2. Lo que se contrasta es la extracción y la presencia (`check_fact`: `elements` y `missing` en orden de aparición). La cobertura de C3 (modo, orden por tipo, tope de 8 y `missing_total`) es de an-kla y descansa en los 74 vectores (r1, R70-03): la implementación de an-kla y `agora.fact_checks_v2.check_fact` (`3c0b14c`, por `PYTHONPATH`, sin instalar) dan los mismos `elements` y `missing` sobre los 74 vectores y sobre 20 000 entradas aleatorias, generadas con semilla fija y sesgadas a fechas, marcas ISO, huellas y versiones. Cero discrepancias. Si sale alguna, no se adapta nada: se informa.
3. **Escritura:**
   - un `fact` anclado con `2026-11-19` en el texto y una cita sin esa fecha da `missing` = `[{date, 2026-11-19}]`, no tres números;
   - un `state` con cifras de avance y sin elementos de los cuatro tipos da `unchecked`;
   - un `state` cuyo `path` no está en la cita da `none`;
   - las tres llevan `coverage.rules` = v2 en la respuesta y en el registro, y `remember-result-v2`;
   - **por la bandeja** (r1, R70-02): un `state` encolado sin vaciar y vaciado después en otra invocación queda en el registro con el mismo nivel que en modo `state` (`unchecked` o `none`), no con el de modo `fact`.
4. **Lo ya escrito:** un registro escrito con beta.38 (`git archive v0.1.0-beta.38`, `PYTHONPATH`, sin instalar) y leído con esta versión sirve su cobertura v1 sin `rules` y sin recalcular. `history`, `state show`, `anchors verify` y `list` de un store sin registros nuevos dan byte a byte lo de beta.38.
5. **Vuelta atrás:** un registro con cobertura v2 leído por beta.38 se sirve sin error.

## Referencias

- C3 `memoria/ancla/v1`, errata 4; agora PR #29 (`3c0b14c`), decisión `2026-11-19-decision-cobertura-v2.md`.
- Diseño 07, sección A, del esfuerzo de memoria agéntica.
- ADR-0066 §3–§4, ADR-0069 §6. Issue #239.
