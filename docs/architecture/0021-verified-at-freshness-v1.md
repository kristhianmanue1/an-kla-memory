# ADR-0021: `verified_at` y frescura computada en lectura

- **Estado:** Aceptado (v3 enmendada; retry adversarial focalizado `proceed`;
  aceptación explícita del maintainer el 2026-08-08)
- **Fecha:** 2026-08-08
- **Decide sobre:** cómo un registro declara su última fecha de confirmación y
  cómo la recuperación expone su antigüedad, sin jobs externos ni mutación de
  vigencia.

## Contexto

El issue #41 (consumidor kairos-controller) reporta que en beta.8 la frescura
no existe como concepto del motor: el registro no tiene campos temporales,
`write-proposal-v1` no valida ninguno, y `retrieve`/`assemble-context` no
pueden marcar antigüedad. La evidencia del consumidor es que la convención en
texto libre no basta: su primer uso real del flujo gobernado produjo registros
sin fecha pese a ser obligatoria por su política.
El mismo issue adjunta tres insumos de diseño verificados contra producción
(Atlas/Elastic, ADRC/CMF, ChromaDB de ADRC). La lección decisiva es la del
«loop»: en ADRC, todo mecanismo epistémico que dependía de un actor externo
(jobs de decay, `verify()`, migradores de tier, contadores de acceso) quedó en
0/NULL tras 6 meses y 1605 registros; lo único que funcionó fue lo que vive en
el camino de escritura gobernada y en el WHERE de lectura. Conclusión: la
antigüedad debe **computarse al servir**, nunca depender de un proceso de
refresco para ser visible.

Restricciones verificadas en código (main post-beta.8):

- `record` es un objeto abierto en `write-proposal-v1` (sin
  `additionalProperties:false`); campos extra ya viajan por `deepcopy` al plan
  (`write_policy.py:506`) y al segmento (`store.py:339-341`). No hace falta
  cambio de formato persistente.
- `_SELF_ASSERTED_AUTHORITY_KEYS` (`write_policy.py:34-45`) bloquea `verified`
  por coincidencia exacta casefold; **`verified_at` no colisiona**. El ADR debe
  fijar explícitamente esta adyacencia.
- `evaluate_write` es pura (ADR-0007): puede validar **formato**, no comparar
  contra el reloj.
- Ambos perfiles de recuperación comparten `retrieve()`: el scan
  (`retrieval.py:130-148`) construye `ranked` y el bucle de selección
  (`retrieval.py:180-199`) construye los items de `selected`; FTS5 sólo
  estrecha candidatos (`_narrow_with_index`). Un cómputo en el bucle de
  selección es automáticamente uniforme en `scan-fallback/v1` y
  `sqlite-fts5/v1` — la exigencia de uniformidad del insumo #3 se cumple por
  construcción. Todos los caminos de lectura pasan por `retrieve()`
  (`__main__.py`, `mcp.py`, `context.py`); no hay by-pass.
- El tool MCP `an_kla_retrieve` **reconstruye** cada item como
  `{id, text, score}` (`mcp.py:73`) y su sobre (`an_kla/mcp-retrieve-v1`) no
  incluye metadatos del resultado: sin cambio explícito, MCP descartaría los
  campos de frescura. MCP es la interfaz primaria del consumidor del issue.
- `assemble_context` reconstruye cada registro como `{id, text, score}`
  (`context.py:78-80`) y mide el payload completo con `exact_sized_payload`;
  campos nuevos se contabilizan solos contra el presupuesto exacto.
- El proyecto soporta Python 3.9: `datetime.fromisoformat` no acepta el
  sufijo `Z` hasta 3.11. El parseo debe normalizar `Z` a mano.
- `retrieve` se anuncia determinista. Introducir antigüedad introduce el reloj:
  debe ser **entrada explícita e inyectable**, no una variable oculta.
- MCP y `assemble-context` miden el payload JSON exacto y pueden expulsar un
  registro cuando crece el sobre. Emitir metadatos de frescura aun cuando ningún
  registro los use rompería compatibilidad observable bajo el mismo presupuesto.
- ADR-0010 congela byte a byte los payloads presupuestados v1: cualquier cambio
  de campos, selección o presupuesto exige un nuevo schema o perfil. Como
  beta.8 ya preserva claves arbitrarias en `record`, la mera presencia previa de
  `verified_at` no autoriza reinterpretar silenciosamente una respuesta v1.

Fuera de alcance (anti-lecciones documentadas en #41): `decay` como operación,
penalización de ranking por antigüedad, `valid_at`/`invalid_at`, caps de
confianza numérica, contadores de acceso, jobs en background, scoping/DLS,
búsqueda semántica. El recall lexical y el efecto del presupuesto sobre registros
largos (#10-a) son una investigación separada; el código actual no usa BM25 para
ordenar resultados: cuenta términos coincidentes y FTS5 sólo estrecha candidatos.

## Decisión

1. **Campo opcional `verified_at` en el registro, con gramática temporal
   cerrada.** Es un string del subconjunto
   `YYYY-MM-DDTHH:MM:SS[.ffffff](Z|±HH:MM)`: `T` y `Z` en mayúscula, segundos
   obligatorios, fracción opcional de 1 a 6 dígitos y offset conocido entre
   `-14:00` y `+14:00` (`14` sólo admite minutos `00`; `-00:00` se rechaza).
   La validación combina patrón léxico y `datetime.fromisoformat` tras normalizar
   `Z` a `+00:00`, exige fecha/hora reales, considera aware únicamente cuando
   `utcoffset() is not None` y exige que `astimezone(timezone.utc)` sea
   representable sin `OverflowError`. Vive en un helper puro compartido por
   proposal, CLI y MCP; no se mantienen parsers divergentes.
   `validate_write_proposal` rechaza formato inválido o naive con
   `invalid_write_proposal` y detail evolutivo `record.verified_at` (mismo patrón
   que `record:not_object`). Fechas futuras se **aceptan**: el core puro no tiene
   reloj y `verified_at` es dato, no autoridad.
2. **Schema aditivo, sin v2.** Las dos copias normativas de
   `write-proposal-v1` (`docs/schemas/` y `an_kla/schemas/`) declaran
   `record.properties.verified_at` con `pattern` ISO-8601 (documentación
   normativa para consumidores; la validación ejecutable vive en el core) y
   deben permanecer byte-idénticas. `write-plan-v1` no cambia: el plan ya porta
   `record` verbatim. Patrón idéntico a `supersedes` en ADR-0019.
3. **`verified_at` es dato, nunca autoridad.** No entra en
   `_SELF_ASSERTED_AUTHORITY_KEYS` (bloquearlo haría inútil la función), no
   eleva representación ni elegibilidad. Se declara como dato en
   `capabilities()` (`data_not_authority: true`, decisión 8) y en la guía de
   escritura, **sin tocar el contrato gestionado** (el bloque no enuncia campos
   de registro; ver decisión 9): «fecha autodeclarada por el proposer, no
   verificada por el motor».
4. **Frescura computada en lectura sólo bajo un perfil explícito y
   versionado.** `freshness_profile="computed-age/v1"` activa la función;
   ausencia del perfil conserva sin reloj ni reinterpretación el contrato
   `an-kla/retrieval-result-v1`, incluso si un registro beta.8 ya contiene una
   clave `verified_at` válida, inválida, `null` o de otro tipo. Con el perfil,
   `retrieve()` devuelve `an-kla/retrieval-result-v2`, declara
   `freshness_profile: "computed-age/v1"` y computa en el bucle de selección
   (`retrieval.py:180-199`). Por cada registro seleccionado que porte
   `verified_at` como string parseable, `retrieve()` emite en el item de
   `selected`: `verified_at` (eco verbatim), `days_since_verified` (entero,
   intervalos completos de 24 horas entre `verified_at` y `now`, sin aritmética
   flotante). Para `delta = now_utc - verified_at_utc`:
   `micros = ((delta.days*86400 + delta.seconds)*1_000_000 +
   delta.microseconds)` y `days = sign(micros) *
   (abs(micros) // 86_400_000_000)`. El truncamiento es hacia cero;
   **negativo si la fecha
   está al menos 24 horas en el futuro**, mientras una fecha futura por menos de
   24 horas produce `0`) y, sólo si el llamador fija umbral, `stale: true`
   cuando `days_since_verified > N`. `stale: false` se omite y un valor
   negativo nunca marca `stale`.
   Registros sin el campo, o con valor `null`/no-string: **sin claves nuevas**
   (aditivo puro; `null` se trata como ausente). Registros con valor string
   almacenado no parseable (legado pre-validación): eco de `verified_at` +
   `freshness_error: "unparseable_verified_at"`; un string parseable pero no
   representable en UTC produce `freshness_error:
   "unrepresentable_verified_at"`. Ambos omiten `days_since_verified` y `stale`
   (explícito, nunca silencioso).
5. **Reloj inyectable, aware y resultado autodescriptivo.**
   `retrieve()` acepta `now: datetime | None` y
   `stale_after_days: int | None`; el umbral debe ser un entero no negativo y
   `bool` no cuenta como entero válido. Un `now` inyectado debe ser
   timezone-aware y representable en UTC: uno naive, un `utcoffset()` inválido o
   cualquier `OverflowError`/`ValueError` al normalizar falla cerrado con
   `invalid_freshness_now`, nunca se interpreta silenciosamente como UTC ni
   degrada a `internal_error`. `invalid_stale_after_days` cubre un umbral
   inválido; ambos códigos son errores seguros en MCP.
   `now` y `stale_after_days` sólo son válidos junto con
   `freshness_profile="computed-age/v1"`; de otro modo fallan con
   `freshness_profile_required`. Un perfil desconocido falla con
   `unsupported_freshness_profile`. Al activar el perfil sin `now` explícito se
   usa una sola captura de `datetime.now(timezone.utc)` por invocación. Tanto esa
   captura como un `now` explícito se convierten antes de calcular a UTC y al
   string canónico `YYYY-MM-DDTHH:MM:SS.ffffffZ`. El sobre v2 siempre
   incluye `freshness: {"semantics":"self_asserted_timestamp",
   "source_field":"record.verified_at", "computed_at":<canónico>,
   "stale_after_days":<int|null>}`, aunque ningún registro final porte el campo. Mismas entradas +
   mismo `now` explícito ⇒ misma salida.
   CLI acepta `--freshness-profile computed-age/v1`,
   `--now <ISO-8601-con-offset>` y `--stale-after-days <N>` en `retrieve` y
   `assemble-context`. El sufijo `Z` se normaliza a `+00:00` antes de
   `datetime.fromisoformat` para Python 3.9.
6. **Uniformidad y propagación completa en TODOS los caminos de lectura.**
   Un helper puro recibe `record`, `computed_at` y umbral y produce sólo la
   proyección `verified_at`/`days_since_verified`/`stale`/`freshness_error`.
   Scan e índice lo comparten. `retrieve` calcula la proyección una vez; MCP y
   assembly copian exclusivamente esas claves desde cada candidato emitido y el
   mismo bloque raíz `freshness`, sin segundo parseo, captura o cálculo.
   Los contratos v1 permanecen dorados byte a byte. Al activar el perfil:
   - `retrieve` → `an-kla/retrieval-result-v2`;
   - `assemble_context` → schema `an-kla/context-assembly-v2` y profile
     `context-assembly/v2`;
   - `an_kla_retrieve` → `an-kla/mcp-retrieve-v2`;
   - MCP `an_kla_assemble_context` porta el mismo `context-assembly/v2` de la
     API, sin wrapper divergente.
   Estos nombres son schemas instalados, no meros discriminadores en prosa:
   PR-B1 añade `retrieval-result-v2.schema.json`; PR-B2 añade
   `context-assembly-v2.schema.json` y `mcp-retrieve-v2.schema.json`. Cada PR
   duplica los suyos en `docs/schemas/` y `an_kla/schemas/`, los registra en
   `schema_catalog()`, los incluye en el wheel y prueba igualdad byte a byte. Sus
   `required`, `additionalProperties:false`, co-ocurrencias y formas de records
   congelan los sobres descritos por este ADR.
   Cada sobre v2 incluye su bloque `freshness` y propaga la proyección en los
   registros **efectivamente emitidos**. MCP y assembly usan el orden de
   candidatos de retrieval, pero copian la proyección al construir cada
   candidato final con `exact_sized_payload`; `computed_at`, umbral y metadatos
   del registro participan en el mismo cálculo exacto. Un candidato que no cabe
   se retira con su proyección y no deja activación ni metadata residual; el
   bloque raíz permanece porque el perfil v2 fue solicitado explícitamente.
   Los inputs de ambos tools MCP ganan `freshness_profile` (enum
   `computed-age/v1`), `now` (string de la gramática de decisión 1) y
   `stale_after_days` (integer, mínimo 0). `call()` valida manualmente conjuntos
   exactos de claves, tipos, co-ocurrencia y semántica porque el servidor no
   ejecuta automáticamente el JSON Schema. Para retrieve las requeridas son
   `{query,budget_bytes}` y las opcionales `{freshness_profile,now,
   stale_after_days}`; para assembly se añade `new_information` a las
   opcionales. Precedencia: (1) claves extra/faltantes o tipos inválidos de
   argumentos base/perfil → `invalid_retrieve_arguments` /
   `invalid_context_arguments`; (2) perfil string desconocido →
   `unsupported_freshness_profile`; (3) `now`/umbral sin perfil →
   `freshness_profile_required` sin mirar valores; (4) con perfil, `now`
   no-string/naive/inválido/no representable → `invalid_freshness_now`; (5)
   umbral bool/no entero/negativo → `invalid_stale_after_days`.
   `SAFE_ERROR_CODES` añade `invalid_freshness_now`,
   `invalid_stale_after_days`, `freshness_profile_required` y
   `unsupported_freshness_profile`. La paridad CLI↔MCP se limita a la
   **proyección temporal**: para el mismo registro/revisión, `now` y umbral, un
   item emitido por ambas superficies porta los mismos campos de frescura. No se
   promete igualdad de selección para el mismo número de bytes: CLI retrieve
   presupuesta `render`, mientras MCP presupuesta su sobre canónico completo.
   `excluded_*` no cambia: la frescura nunca excluye, sólo informa.
7. **Sin cambio de ranking ni de vigencia.** `days_since_verified` no altera
   `score` ni el orden; el filtro de `sustituida` (ADR-0019) es ortogonal y
   previo. `decay` sigue `skip` con `operation_not_supported`; el patrón
   oficial de refresco es `supersede` del registro con nuevo `verified_at`
   (se documenta en #41 y en la guía de escritura). Coste reconocido: cada
   refresco deja un objeto CAS inmutable eterno (`garbage_collection: false`)
   — este ADR **acelera** el sumidero sin GC y convierte la compactación
   gobernada en candidata prioritaria post-beta.9 (ver Referencias). El problema
   de recuperación de registros largos de #10 se investiga aparte como recall
   lexical/presupuesto, sin presuponer BM25 como causa.
8. **`capabilities()` lo declara**: `retrieval.freshness` =
   `{field: "verified_at", computed_at_read: true, clock: "system_utc_default",
   now_injectable: true, staleness_marking: "opt_in_threshold", affects_score:
   false, data_not_authority: true, naive_now: "rejected", activation:
   "explicit_profile", result_schemas: ["an-kla/retrieval-result-v2",
   "an-kla/context-assembly-v2", "an-kla/mcp-retrieve-v2"]}`.
   `policy_fingerprint()` **cambia** aunque no haya nuevos reason codes ni
   códigos terminales de escritura: `_POLICY_CONFIGURATION` gana
   `record_validators: {verified_at: "an-kla-verified-at/v1"}`. La etiqueta
   nombra la gramática estricta de decisión 1, no RFC3339 completo. Así no se
   reinterpreta bajo el mismo fingerprint una decisión beta.8 que aceptaba el
   campo opaco. No se promete replay cross-version de planes pendientes. La
   precedencia real depende del `expected_current_hash` entregado al commit:
   1. si `observed != expected_current_hash`, el CAS exterior falla primero con
      `write_plan_base_changed`;
   2. si son iguales, `verify_write_plan` revalida estructura y proposal: una
      proposal ya inválida falla con `invalid_write_proposal`, y una aún válida
      alcanza `write_policy_fingerprint_mismatch` por la decisión beta.8;
   3. sólo después, el store comprueba que `proposal`, authority y plan estén
      ligados a `observed`; una base vieja no queda prometida como
      `write_plan_base_changed` si falló antes la revalidación.
   Ningún camino escribe y todo plan beta.8 debe replantearse.
9. **Release beta.9 code-only.** `TEMPLATE_VERSION` no cambia (el contrato
   gestionado no enuncia campos de registro; `VERSION` pasa a `0.1.0b9`).
   Secuencia (§4 de `docs/practicas-ingenieria.md`): PR-A (parser, schema y
   core), PR-B1 (retrieval v2), PR-B2 (assembly, MCP, CLI y capabilities) y
   PR-C (versión, notas, wheel y auditoría). Cada fase tiene ronda adversarial;
   `main` no es etiquetable hasta C y el tag apunta al merge de C.
10. **#32 viaja en PR independiente y serializado.** El guard de operación en `store.py:343` (el
    `else` tras `op == "add"`/`op == "supersede"` que hoy levanta
    `WritePolicyError("invalid_write_plan")` sin detail) gana
    `detail="records[]:operation:not_committable"`: expresa que el store sólo
    confirma `add` y `supersede`, sin afirmar erróneamente que sólo admite
    `add`. `validate_write_plan` conserva su detail público combinado
    `records[]:stream|operation`; este guard es defensa en profundidad y no se
    mezcla con cambios simultáneos de `write_policy.py`.

## Por qué no [alternativa]

- **`decay` como operación gobernada o job en background**: la evidencia de
  ADRC (insumo #2 de #41) es que los mecanismos que requieren actor externo no
  corren nunca. Decay como scoring queda como investigación futura ligada a
  #10-a; decay como mutación contradice la inmutabilidad CAS.
- **Penalizar el ranking por antigüedad (propuesta 2 completa del issue)**:
  cambia el orden de recuperación de todos los consumidores existentes y se
  acopla con el problema aún no caracterizado de recall lexical/presupuesto de
  registros largos (#10-a). Marcado visible primero; scoring después, con
  medición y sin presuponer BM25 como causa.
- **`valid_at`/`invalid_at` junto a `verified_at` (insumo #2)**: dobla la
  superficie de validación temporal y su semántica (validez del hecho vs.
  confirmación del registro) es independiente. Aditivo después si un consumidor
  lo necesita.
- **Bloquear `verified_at` como autoridad autoaseverada**: la lista bloquea
  campos que *elevan* autoridad (`verified`, `confidence`); `verified_at` es un
  dato temporal sin efecto en la decisión. Bloquearlo impediría la función;
  declararlo dato (decisión 3) preserva la frontera.
- **Comparar `verified_at` contra el reloj al escribir** (rechazar futuras):
  rompería la pureza de `evaluate_write` (ADR-0007). El formato se valida; el
  tiempo es dato del proposer.
- **Umbral de stale por configuración de proyecto**: AN-KLA no tiene archivo de
  configuración; crearlo por esta función es desproporcionado. Flag por
  invocación, default sin marcado.
- **`write-proposal-v2`**: campo opcional aditivo; no rompe consumers de v1
  (precedente ADR-0019).
- **Añadir frescura implícitamente a los payloads v1 cuando aparezca el campo**:
  descartado por ADR-0010. Beta.8 ya preserva claves arbitrarias, de modo que
  contenido persistente preexistente no puede negociar un contrato de respuesta
  nuevo. Perfil explícito + schemas v2 conservan los payloads dorados y hacen
  visible la intención del llamador.
- **Conservar `policy_fingerprint` porque el error code no cambia**: descartado.
  La aceptación de proposals sí cambia y un fingerprint estable reinterpretaría
  decisiones históricas, contrario a ADR-0007. El nuevo vector
  `record_validators` hace observable el cambio sin inventar otro error terminal.
- **Dejar MCP sin propagación (vista simplificada)**: descartado. MCP es la
  interfaz primaria del consumidor que reportó #41 (kairos-controller via MCP);
  una frescura visible en CLI pero invisible en MCP reproduce exactamente la
  divergencia de filtros entre caminos de lectura que el insumo #3 documenta
  como el punto de mayor dolor de ADRC. Propagación completa (decisión 6).

## Consecuencias

- **Positivas:** frescura visible sin jobs ni actores (lección del loop);
  uniformidad entre perfiles garantizada por la arquitectura (bucle único);
  validación por schema + core que cierra el modo de fallo reportado (registro
  sin fecha válida); salidas v2 autodescriptivas y reproducibles (`freshness`
  en el sobre); contratos v1 dorados intactos; refresco ya gobernado vía
  `supersede` sin código nuevo.
- **Negativas:** cambio de comportamiento en validación: proposals que beta.8
  aceptaba con `verified_at` opaco y mal formado pasan a `invalid_write_proposal`
  y todo plan beta.8 pendiente debe replantearse por el nuevo fingerprint. El
  consumidor debe solicitar el perfil v2: la presencia del campo no cambia una
  lectura v1 por sí sola. El resultado v2 depende de `now` — mitigado con
  inyección y `computed_at`, pero los consumidores que cachean salidas deben
  saberlo. En MCP/context v2 el sobre y los registros crecen y pueden seleccionar
  menos registros bajo el mismo presupuesto exacto; es efecto esperado y medido,
  no exclusión por antigüedad. `retrieval-result-v2` conserva selección e
  `used_bytes` de v1 para iguales render, budget y overheads: su metadata no
  participa en esa unidad.
- **Neutras:** en `retrieval-result-v2`, como en v1, `used_bytes` mide `render`
  más overheads reservados, no la envolvente CLI completa; los contratos MCP y
  context v2 miden el payload completo mediante `exact_sized_payload`.
  `verified_at` almacenado es parte del objeto CAS inmutable: corregirlo exige
  `supersede` (coherente con el modelo). Registros legados con valor no
  parseable quedan marcados con `freshness_error`, nunca corregidos por el
  motor. El refresco periódico de frescura por `supersede` incrementa el ritmo
  de acumulación de objetos inmutables (registro viejo + evento
  `write_policy_decision` + journal por cada reconfirmación): sin GC, un ritual
  de reconfirmación semanal deja ~52 objetos muertos por fact vivo al año; el
  roadmap prioriza un ADR de compactación gobernada post-beta.9.

## Test de regresión

- Gramática: `verified_at` ausente (OK), `Z`, `+02:00`, `-05:30`, fracciones de
  1 y 6 dígitos y fecha futura (OK); naive, espacio en lugar de `T`, `z`
  minúscula, sin segundos, 7 dígitos, fecha imposible, `-00:00`, `±14:01` y
  `±15:00` → `invalid_write_proposal`, detail `record.verified_at`. El mismo
  corpus prueba parser CLI/MCP y Python 3.9/3.12. Extremos que desbordan al
  convertir a UTC también son inválidos; como legado almacenado producen
  `unrepresentable_verified_at` sin romper retrieval.
- Pureza: `evaluate_write` con `verified_at` no lee reloj ni estado (test de
  determinismo de la decisión). `policy_configuration()` incluye
  `record_validators.verified_at == "an-kla-verified-at/v1"`; el golden de
  fingerprint cambia una vez y queda congelado.
- Compatibilidad de planes: matriz con `observed == expected_current_hash` y
  `observed != expected_current_hash`. En el primer caso, fixture beta.8 aún
  válido bajo la gramática nueva → `write_policy_fingerprint_mismatch`, y
  fixture ahora inválido → `invalid_write_proposal`; en el segundo, ambos →
  `write_plan_base_changed`. Caso adicional: `CURRENT` avanzó pero el caller
  entrega el hash nuevo junto con plan viejo; gana revalidación/fingerprint, no
  se afirma CAS conflict. Ningún caso crea objetos, journal ni revisión.
- Golden v1: sin `freshness_profile`, los bytes completos de retrieve, MCP y
  assembly permanecen idénticos a beta.8 para registros sin `verified_at`, con
  string válido, string inválido, `null` y valor no-string; no se lee reloj.
- Co-ocurrencia: `now` o `stale_after_days` sin `computed-age/v1` →
  `freshness_profile_required`; perfil desconocido →
  `unsupported_freshness_profile`.
- `retrieval-result-v2`: registro con `verified_at` hace 10 días y `now`
  inyectado →
  `days_since_verified == 10`; con `stale_after_days=7` → `stale: true`; con
  umbral 30 → sin `stale`; fecha 1 hora futura → `0`, fecha 25 horas futura →
  `-1`, ambas sin `stale`; `verified_at: null` o no-string → item sin claves
  nuevas (ausente); sin `verified_at` → item idéntico a beta.8
  (backwards-compat del item); string legado no parseable o no representable en
  UTC → su `freshness_error` específico.
  Scan e índice producen la misma proyección. `now` naive o string sin offset →
  `invalid_freshness_now`; umbral negativo, bool o no entero →
  `invalid_stale_after_days`. `computed_at` usa UTC canónico con seis
  microsegundos y una sola captura alimenta sobre e items. Casos de un millón de
  días y fronteras a un microsegundo del múltiplo de 24 horas demuestran división
  entera exacta y el mismo resultado en Python 3.9/3.12; `now` extremo que no
  puede normalizarse a UTC → `invalid_freshness_now`.
- Cost model de retrieve: con candidatos y overheads iguales, v1 y v2 eligen los
  mismos ids y reportan el mismo `used_bytes`; la proyección no consume budget
  de render.
- Presupuesto v2 en MCP/assembly: un único campo hace que un payload antes justo
  deje de caber; un candidato descartado no deja proyección residual; sólo el
  sobre requerido cabe o falla con `budget_too_small_for_required_context` /
  `budget_too_small_for_envelope`; casos UTF-8 verifican
  `used_bytes == len(canonical_json(payload)) <= budget_bytes` y exclusiones.
- MCP: schemas/validación manual cubren `freshness_profile`, `now` y umbral; los
  cuatro errores seguros nunca degradan a `internal_error`. La matriz (1)–(5)
  combina extras/faltantes y tipos erróneos, incluido `now` no-string y umbral
  bool, con/sin perfil. Un item común tiene proyección CLI/MCP idéntica; otro
  test prueba que budgets iguales no prometen la misma selección.
- Schemas duplicados: conservar el guard existente
  `test_installed_resources_match_normative_source_bytes`, sumar validación de
  `verified_at`, registrar los tres result schemas v2 y verificar que catálogo y
  wheel incluyen exactamente los bytes actualizados.
- #32: el guard de operación de `store.py:343` levanta `WritePolicyError` con
  detail `records[]:operation:not_committable`; `str(error)` sigue igualando el
  code y el detail público del validador no cambia.

## Referencias

- Issue #41 y sus tres insumos de diseño (Atlas/Elastic, ADRC/CMF, ChromaDB).
- Continúa ADR-0007 (pureza), ADR-0019 (supersede como patrón de refresco),
  ADR-0018 (detail evolutivo fuera del fingerprint), ADR-0006 (presupuesto
  exacto de assembly), ADR-0008 (cost model: `used_bytes` mide `render`).
- Relacionado sin bloquear: #10-a (recall lexical/presupuesto de registros
  largos; causa por medir), #32 (cambio independiente y serializado).
- Consenso dialéctico motor↔consumidor (2026-08-08, registrado como
  `f-roadmap-consenso-2026-08-08-post-adr0021`): el análisis crítico externo
  señaló que el refresco por `supersede` acelera el sumidero inmutable sin GC
  (absorbido en decisión 7 y Consecuencias) y que la compactación gobernada —
  con semántica de época/tombstone para que `verify` de revisiones viejas
  degrade explícito — es candidata prioritaria post-beta.9 (ADR + spike, no PR
  rápido).
- Historial, comandos y correcciones de todas las rondas:
  `docs/releases/v0.1.0-beta.9-adversarial.md`. La enmienda semántica y de
  secuencia obtuvo `proceed`; PR-A puede iniciar con su propio gate.
