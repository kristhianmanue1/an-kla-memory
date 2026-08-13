# ADR-0032: vista contextual vigente derivada sobre el sustrato de afirmaciones

- **Estado:** Aceptada
- **Implementación:** Publicada en
  [`v0.1.0-beta.13`](../releases/v0.1.0-beta.13.md); contrato ejecutable en
  ADR-0034
- **Fecha:** 2026-08-11
- **Decide sobre:** la forma del contenido y la superficie de lectura de AN-KLA:
  un sustrato físico de afirmaciones inmutables más una vista contextual vigente
  derivada, determinista, read-only y non-authoritative. No decide schema,
  comando, campo `subject_ref`, cardinalidad, namespaces, serialización ni
  código; ésos se congelan en fases posteriores (G-SUBJECT, G-VIEW) con su
  propia ronda adversarial.

## Contexto

Este ADR resuelve la **frontera de forma del contenido** que los issues #48 y
#53 plantearon y que ningún ADR previo cerró. Es **ortogonal** a ADR-0031
(propiedad lógica, custodia, ubicación e integración): ambos se declaran no
overlapping y se cruzan sólo en referencias normativas. La ortogonalidad se
detalla en §Por qué no y en Referencias.

### Invariante del maintainer (precisión vinculante)

Un **proyecto** es **scope compuesto**: posee y expone contexto formado por
issues, documentación, decisiones, servicios, dependencias, actores, APIs,
entornos e integraciones; puede ser subsistema de un sistema mayor y
relacionarse con otros proyectos, de forma potencialmente jerárquica y
cross-system. **AN-KLA es la memoria contextual del agente sobre esas
superficies y relaciones**, con referencias, procedencia, observaciones y
vigencia. Las fuentes originales siguen siendo canónicas y deben revalidarse.
Hoy el store es project-local y no existe vista: no hay memoria global
implícita. La ausencia de contaminación cross-project es **restricción de
diseño** que G-SUBJECT deberá preservar al introducir `subject_ref`/namespaces,
no garantía de una capacidad futura ya implementada. Un proyecto delimita el
alcance temático de recuperación, no a la memoria como propietaria ni como
estado canónico del producto.

### Tensión observable en el código actual

El motor actual es **event-shaped**: cada `fact` es una afirmación inmutable con
un `id` físico por stream (`an_kla/store.py:49`, `an_kla/store.py:755-772`).
`supersede` marca vigencia por `target_id` físico sin reescribir bytes
(`an_kla/store.py:213-228`, ADR-0019). El refresco oficial de frescura es
`supersede` con nuevo `verified_at` (ADR-0021 §7), lo que **renombra el `id`**
en cada reconfirmación y rompe referencias cruzadas estables. No existe
enumeración de vigentes: `retrieve` puntúa por query y descarta todo lo que no
hace match como `zero_score` (`an_kla/retrieval.py:211-215`), de modo que una
query vacía devuelve `selected: 0` aun con un store poblado.

Tres consumidores externos conocidos (kairos-controller, argos-epistemic,
kratos) usan `facts` simultáneamente como **eventos fechados** y como
**entidades persistentes reconfirmables** (perfil de usuario, iniciativas,
servicios); #53 registra además el dogfooding interno del Mediador como cuarto
reporte del mismo muro. Esa ambigüedad no está declarada y los issues #47
(churn de identidad al refrescar) y #49 (sin enumeración) la destapan. El issue
#48 formula la distinción real como **catálogo vs. bitácora**; este ADR la
reformula en términos que no requieren dos perfiles de escritura ni un
catálogo autoritativo.

### Corrección al spike previo (vinculante)

`lineage.refs` (`an_kla/write_policy.py:236-237`, kinds
`artifact|event|fact|episode|revision|external`) es **procedencia/evidencia**,
no identidad de subject. Reutilizarlo como clave de subject mezclaría evidencia
con entidad recordada y produciría vistas incorrectas. Este ADR congela
**conceptualmente** un `subject_ref` estable, separado del `id` físico (que
identifica una afirmación inmutable) y de los evidence `refs` (que identifican
fuentes). El schema, cardinalidad, namespaces y serialización de `subject_ref`
se **difieren** al spike G-SUBJECT, previo a G-VIEW.

Restricciones vigentes respetadas: contrato gestionado (`AGENTS.md`,
`AN-KLA.md`) no se modifica aquí; ADR-0007 (pureza de `evaluate_write`);
ADR-0010 (`capabilities()` determinista, dorado por
`tests/test_agent_contracts.py`); ADR-0022 (identidad store/project, base para
extensiones futuras); ADR-0031 (`canonicality=non-authoritative`); frontera de
confianza de `AN-KLA.md:133-145`.

## Decisión

1. **AN-KLA es memoria contextual del agente respecto de un proyecto de scope
   compuesto.** El agente es propietario lógico de la memoria (ADR-0031); el
   proyecto es sólo alcance temático. La memoria describe superficies y
   relaciones del proyecto (issues, docs, decisiones, servicios, dependencias,
   actores, APIs, entornos, integraciones) con referencias, procedencia,
   observaciones y vigencia. **Nunca** es estado canónico del producto ni fuente
   reemplazada: las fuentes originales siguen siendo autoritativas y deben
   revalidarse. Hoy el store es project-local y no hay memoria global implícita;
   la ausencia de contaminación cross-project es restricción de diseño que
   G-SUBJECT deberá preservar al introducir `subject_ref`/namespaces (decisión
   9).

2. **Sustrato físico: afirmaciones inmutables, sin cambio.** Se conserva el
   modelo actual de escritura (`write-policy/v1`, `operation=add|supersede`).
   Cada `fact` sigue siendo una afirmación inmutable, content-addressed, con un
   `id` físico por stream. El `id` físico **identifica una afirmación
   inmutable**, no un elemento contextual recordado. No se introducen dos
   perfiles de escritura ni operaciones nuevas en este ADR.

3. **Vista contextual vigente, derivada y non-authoritative (fase futura).** AN-KLA
   expondrá, en una fase posterior (G-VIEW), una **vista contextual vigente**
   derivada del sustrato, **read-only**, **determinista** y **recomputable**
   respecto de una revisión AN-KLA fijada. La vista organizará las afirmaciones
   por `subject_ref` conceptual y presentará el contexto vigente conocido del
   proyecto compuesto. La vista será **non-authoritative**: recomputable,
   potencialmente desactualizada y subordinada a las fuentes canónicas.

4. **Determinismo y aislamiento del cálculo.** Para una misma revisión AN-KLA
   fijada y los mismos inputs, la vista deberá producir la misma salida. **La
   vista no deberá consultar fuentes externas en vivo** (red, Git, APIs,
   servicios, sistemas de issues) durante el cálculo: operará sólo sobre objetos
   inmutables de la revisión. Cualquier acceso a fuentes canónicas vivas es
   responsabilidad explícita del consumidor/host, fuera del cálculo de la vista.

5. **Revalidación explícita como estado/advertencia, no falsa actualidad.** La
   vista no deberá afirmar actualidad sobre issues, servicios, APIs u otras
   fuentes canónicas. La revalidación es responsabilidad del consumidor/host y
   deberá aparecer en la superficie de la vista como **estado o advertencia**
   (p. ej. marca de `non-canonical`, ausencia de confirmación viva, `verified_at`
   presentado conforme a ADR-0021 como `self_asserted_timestamp`: última
   observación registrada por el proposer, nunca confirmación presente
   garantizada por el motor). La vista no deberá prometer frescura que el
   sustrato no puede demostrar. La vista consume la semántica existente de
   `verified_at`/frescura sin redefinirla.

6. **`subject_ref` conceptual, diferido en detalle.** Se congela
   **conceptualmente** un `subject_ref` estable como identidad del elemento
   contextual recordado (un servicio, una decisión, un actor, una API, una
   relación), **distinto** del `id` físico (afirmación inmutable) y de los
   `lineage.refs` (evidencia/procedencia). El schema, cardinalidad, namespaces y
   serialización de `subject_ref` se **difieren** al spike G-SUBJECT, previo a
   G-VIEW. No se añade campo, validador ni reason code en este ADR; no se rompe
   `policy_fingerprint()`.

7. **Conflictos expuestos, nunca resueltos en silencio.** Cuando dos afirmaciones
   sobre un mismo `subject_ref` entren en conflicto de datos (vigencia,
   contenido, autoridad), la vista deberá devolver un **resultado exitoso y
   explícito** con ambas alternativas, su procedencia y su frescura: no habrá
   ganador silencioso. Cuando exista **ambigüedad o ausencia de regla
   contractual** para representar u ordenar el caso, la vista deberá **fallar
   cerrado**. No hay "ganador por defecto" silencioso. G-VIEW congelará los
   códigos de error, el schema y las reglas de resolución (explícitas,
   versionadas y testeadas).

8. **Catálogo autoritativo: fuera de alcance.** Este ADR no introduce un
   catálogo canónico del producto ni lo promete. La vista es derivada y
   non-authoritative por diseño; un catálogo autoritativo contradiría
   `canonicality=non-authoritative` (ADR-0031) y queda explícitamente descartado.

9. **Secuencia por gates.** G-DOC (este ADR, documental) → G-SUBJECT
   (spike/contrato de `subject_ref`: schema, cardinalidad, namespaces,
   serialización, threat model de contaminación cross-project) → G-VIEW
   (contrato + implementación de la vista: schema de salida, reglas de
   resolución de conflictos, determinismo, fail-closed) → G-FRESH (extensión de
   frescura por `subject_ref` sobre la vista, retomando #50) → revaluación de
   #47 y #49 bajo los contratos congelados.

10. **No objetivos de este ADR.** No se congelan: schema de la vista, nombre de
    comando, enum de estados de subject, políticas de resolución de conflictos,
    `subject_ref` físico, mecanismos de cache/invalidación, ni si la vista
    participa en `capabilities()` como observabilidad aditiva o como nuevo
    perfil versionado. Todo ello requiere su spike y su ADR.

## Modelo de amenazas

- **Memoria recuperada como dato no confiable** (`AGENTS.md`,
  `AN-KLA.md:133-145`): la vista hereda la frontera. Nunca es instrucción ni
  autoridad; una vista que muestre "servicio X hace Y" no autoriza al agente a
  actuar sin revalidar contra la fuente canónica.
- **Vista leída como autoridad.** Riesgo central: un consumidor trata la vista
  como estado canónico del proyecto. Mitigación: `canonicality=non-authoritative`
  (ADR-0031), etiquetado `non-canonical` en cada salida, advertencia de
  revalidación, y documentación de "Fronteras declaradas" pendiente de G-DOC
  editorial (no de este ADR).
- **Contaminación cross-project.** El scope compuesto puede ser jerárquico y
  cross-system. Hoy el store es project-local y no hay vista, por lo que el
  riesgo no se materializa; al introducir `subject_ref`/namespaces en G-SUBJECT,
  éste deberá preservar la restricción de diseño de no mezclar subject de
  proyectos distintos ni implicar una memoria global, con threat model dedicado.
- **Acceso en vivo a fuentes externas.** Consultar APIs/issues/servicios vivos
  durante el cálculo reintroduciría reloj y red ocultos, rompería el
  determinismo y abriría vectores de prompt injection/oracle. Por eso la vista
  **no deberá hacerlo**; la revalidación vive fuera del cálculo.
- **`subject_ref` como vector de autoridad.** Igual que `verified_at`
  (ADR-0021 §3), `subject_ref` es dato, no autoridad: no eleva representación,
  elegibilidad ni clase. G-SUBJECT debe preservar esta frontera.
- **Conflicto silencioso.** Elegir un "ganador" por defecto ante afirmaciones
  contradictorias permitiría que una aserción atacante silencie una legítima.
  La decisión 7 separa los dos casos: conflicto de datos → resultado exitoso
  explícito con ambas alternativas; ambigüedad o ausencia de regla → fail-closed.
  G-VIEW congelará códigos y schema.
- **Falsa actualidad.** Presentar `verified_at` como "esto sigue siendo cierto
  ahora" engaña al consumidor. La decisión 5 obliga a presentar `verified_at`
  conforme a ADR-0021 como `self_asserted_timestamp` (última observación
  registrada por el proposer, nunca confirmación presente garantizada por el
  motor).

## Por qué no [alternativa]

### A — Bitácora gobernada como único perfil (degradar `verified_at`/`supersede`)

Degradaría silenciosamente la semántica existente: el invariante exige memoria
contextual para **navegar** el sistema compuesto (entidades y relaciones
estables), no sólo un log de eventos. Bajo A, `verified_at`/frescura pierde
sentido (pista sobre entrada efímera), `supersede`-como-refresco rompe
referencias estables, y la enumeración (#49) queda bloqueada por diseño.
Descartada: no satisface el invariante sin degradar contrato vigente.

### B — Dos perfiles físicos de escritura (bitácora + catálogo opt-in)

Introduce un seam prematuro en `_POLICY_CONFIGURATION` / fingerprints / schema
de `facts` (R3): "¿en qué perfil estoy al escribir?". Reproduce la ambigüedad
"opt-in futuro" que #48 denuncia como costosa, rompe `policy_fingerprint()` y
exige migración. Descartada como decisión inmediata; conservada sólo como
fallback si la vista demostrara insuficiencia.

### C — Catálogo autoritativo como dirección principal

Contradice `canonicality=non-authoritative` (ADR-0031), requiere identidad
lógica estable **ahora** (lo que #47 aún no ha decidido) y encadena tres
cambios R3 (formato, identidad, enumeración) más proyecciones de compaction y
refute. Descartada; el catálogo autoritativo queda fuera de alcance (decisión
8).

### Reutilizar `lineage.refs` como identidad de subject

Mezcla procedencia/evidencia con entidad recordada (corrección vinculante del
maintainer al spike). `refs` apunta a fuentes que prueban una afirmación, no al
subject que la afirmación describe. Descartada; `subject_ref` es concepto
separado (decisión 6).

### Pre-congelar schema/cardinalidad/serialización de `subject_ref` aquí

Prematuro. ADR-0031 (`:234-240`) rechaza este patrón ("pre-congelar
enum/schema/comando de G1… crearía un contrato frágil"). G-SUBJECT debe
decidirlos con threat model de namespaces y contaminación cross-project.
Descartado.

### Vista que consulta fuentes externas en vivo

Rompe determinismo y recomputabilidad, reintroduce reloj/red ocultos y abre
vectores de prompt injection/oracle. La revalidación es responsabilidad
consumidor/host, fuera del cálculo. Descartada (decisiones 4 y 5).

### Mezclar este ADR con ADR-0031 (propiedad/scope)

Son ortogonales: ADR-0031 decide **propiedad lógica, custodia, ubicación,
integración**; este ADR decide **forma del contenido y superficie de lectura**.
Mezclarlos niega la independencia de los seis ejes de ADR-0031 (`:88-95`) y
bloquea decisiones separadas. Descartada; la ortogonalidad se declara
explícitamente.

## Consecuencias

- **Positivas:**
  - Declara contractualmente que AN-KLA es memoria contextual sobre scope
    compuesto, sin reinterpretar el sustrato ni romper contratos existentes.
  - Separa tres capas (modelo físico / semántica de registro / vistas derivadas)
    que el spike anterior no distinguía, permitiendo navegación contextual sin
    tocar `_assign_records`, `supersedes_map` ni `policy_fingerprint()`.
  - Desbloquea dirección para #49 (inventario físico ahora; enumeración
    contextual tras G-VIEW) y reencuadra #47 sin cerrarlo.
  - Mantiene `verified_at`/frescura/supersede sin degradación semántica: la
    vista los consumirá, no los redefine.
  - Preserva la frontera de confianza: vista non-authoritative + revalidación
    explícita + conflictos de datos visibles con ambas alternativas + fail-closed
    ante ambigüedad contractual.
- **Negativas:**
  - Queda pendiente el spike G-SUBJECT y el contrato G-VIEW: la vista no existe
    aún y los consumidores siguen sin navegación contractual hasta entonces.
  - `subject_ref` diferido deja a los consumidores actuales sin identidad
    estable contractual a corto plazo; deben seguir asumiendo que `id` físico
    churnea en refrescos.
  - La superficie de "Fronteras declaradas" y la heurística de amputación de #48
    no se publican aquí (requieren README raíz / `AN-KLA.md`, fuera de alcance).
  - La revalidación consume esfuerzo del host/consumidor; declararla
    responsabilidad no la hace gratis.
- **Neutras:**
  - No cambia código, schemas, `capabilities()`, contratos existentes ni el
    contrato gestionado.
  - El registro canónico gana una fila (0032) y el resumen pasa de 31 a 32 ADRs
    (30 aceptadas, 2 propuestas); el conteo explícito del test de registro se
    actualiza (Aceptada 29→30, Propuesta permanece en 2).

## Test de regresión

Este ADR es documental (G-DOC). No introduce tests automatizados funcionales
directamente. Su Test de regresión inmediato es:

- `scripts/check_adr_registry.py` pasa: fila 0032 presente, estado `Aceptada`
  coherente entre el registro y el ADR, sin huecos ni duplicados.
- `scripts/check_sizes.py` pasa: este archivo ≤ 400 líneas.
- `python3 -m unittest discover -s tests -p 'test_*.py'` pasa; el conteo
  explícito del registro en `tests/test_adr_registry.py` refleja este ADR
  (Aceptada 30, Propuesta 2).

Tests funcionales diferidos a gates posteriores (criterios de aceptación de esos
gates, no de éste):

- **G-SUBJECT:** `subject_ref` estable distinto de `id` físico y de evidence
  `refs`; sin elevar autoridad (análogo al test de `verified_at` como dato);
  namespaces sin contaminación cross-project; cardinalidad y serialización
  deterministas.
- **G-VIEW:** determinismo (misma revisión + mismos inputs ⇒ mismos bytes);
  recomputabilidad sin red ni reloj; conflicto de datos → resultado exitoso
  explícito con ambas alternativas, procedencia y frescura; ambigüedad o
  ausencia de regla → fail-closed con código congelado por G-VIEW; marca
  `non-canonical` presente en toda salida; advertencia de revalidación
  presente; `verified_at` presentado conforme a ADR-0021 como
  `self_asserted_timestamp`; `lineage.refs` sigue siendo sólo evidencia; la
  vista crea cero objetos y no adquiere lock de escritura.
- **G-FRESH:** frescura por `subject_ref` se calcula sobre `verified_at` del
  sustrato, sin mutarlo; el denominador y la agregación se definen por envolvente
  (coherente con #50).
- **Revaluación #47/#49:** tras G-VIEW, confirmar si el churn de `id` físico en
  refresco es aceptable para navegación (la vista colapsa por `subject_ref`) o
  si un consumidor necesita `id` físico estable para citación externa.

## Referencias

- **Issues #48 y #53** — frontera de forma del contenido y síntesis
  cross-issue. Este ADR les da dirección sin cerrarlos por GitHub.
- **Issue #47** — churn de identidad al refrescar. **No se cierra aquí**; se
  reencuadra como requisito/diseño de identidad de `subject_ref` y
  compatibilidad de referencias, a revaluar tras G-SUBJECT/G-VIEW.
- **Issue #49** — enumeración. Se divide: **inventario físico** (metadata-only,
  viable antes de G-VIEW) y **enumeración contextual** (tras G-VIEW).
- **Issue #50** — cobertura computable de frescura. Se extiende por
  `subject_ref` sólo después de la vista (G-FRESH).
- **ADR-0031** — propiedad lógica, custodia, scope e integración. Ortogonal a
  este ADR; comparten el invariante de `canonicality=non-authoritative` y el
  scope compuesto.
- **ADR-0019** — `supersede` gobernada; base del sustrato que esta vista
  consume sin modificar.
- **ADR-0021** — `verified_at` como `self_asserted_timestamp` y frescura
  computada en lectura; la vista la consume, no la redefine.
- **ADR-0007** — pureza de `evaluate_write`; preservada (este ADR no toca
  policy).
- **ADR-0010** — `capabilities()` determinista; no se rompe aquí.
- **ADR-0022** — identidad store/project; base para eventuales namespaces de
  `subject_ref` en G-SUBJECT.
- `AGENTS.md`, `AN-KLA.md:133-145` — frontera de confianza.
- `docs/practicas-ingenieria.md` §3 (ADR antes que el código).
