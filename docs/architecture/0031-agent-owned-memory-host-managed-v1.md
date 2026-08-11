# ADR-0031: memoria del agente con alcance de proyecto y perfil host-managed

- **Estado:** Aceptada
- **Implementación:** No iniciada
- **Fecha:** 2026-08-11
- **Decide sobre:** modelo de propiedad lógica y custodia de la memoria;
  reconocimiento del perfil host-managed como soportado. No decide schema,
  comando, enum de observabilidad, formato físico ni código; esos se congelan
  en fases posteriores con su propia ronda adversarial.

## Contexto

Históricamente AN-KLA se ha descrito de forma informal como "memoria del
agente" o "memoria del proyecto" sin que ningún ADR fijara cuál de las dos
es el modelo canónico. Esa ambigüedad produjo confusiones reales en
consumidores: trataron la memoria como estado del proyecto y tropezaron con
que `supersede` renombra IDs (#47), que no hay enumeración de vigentes (#49)
y que el `export` es en claro (#46). El issue #48 formuló la distinción real
sobre la **forma del contenido** (catálogo vs. bitácora). El issue #54 abre
un eje distinto y necesario: **propiedad lógica, custodia y lifecycle** de la
memoria.

El código actual evidencia (archivo:línea, autocontenido):

- `MemoryStore(project_root)` deriva el store a
  `<project-root>/.an-kla/memory/` sin `store_root` separable
  (`an_kla/store.py:111-112`).
- `status` y `verify` son equivalentes sin `--revision`: ambos delegan en
  `store.verify()` (`an_kla/__main__.py:332-333` y `334-339`).
  `verify --revision` es distinto: invoca `store.verify_revision`
  (`an_kla/__main__.py:336`).
- `context-status/v1.ok` se computa como `block is not None and not
  diagnostics` (`an_kla/context_package.py:731`); los `warnings` no rompen
  `ok`. En particular `context_manifest_missing` es un *warning* paralelo
  (`an_kla/context_package.py:703`), no un `diagnostic`.
- `capabilities()` es determinista y stateless, congelado por
  `tests/test_agent_contracts.py:175,208`. No existe schema `capabilities-v1`
  ni fingerprint global de la envolvente; los fingerprints son por subsistema
  (`write_policy`, `refute`, `compaction`).
- Ninguna cadena `host-managed`, `integration_mode`, `integration_status` ni
  `store_root` aparece en `an_kla/`. El perfil existía **de facto** en el
  código, sin contrato público; este ADR lo reconoce contractualmente, pero la
  observabilidad y la superficie observable versionada llegan en G1.
- AN-KLA nunca modifica `.gitignore` ni `.git/info/exclude` (un solo match en
  `an_kla/`, un comentario en `an_kla/context_text.py:23`); la huella sobre
  el checkout del consumidor queda a cargo del operador.

Restricciones vigentes que este ADR respeta:

- **Contrato gestionado** (`AGENTS.md`, `AN-KLA.md`): no se modifica aquí;
  cualquier cambio requiere su flujo de versión/template.
- **ADR-0010** (capabilities-v1): envolvente stateless, determinista; este
  ADR no la rompe. La enumeración de modos de integración, si se añade, es
  aditiva y se diseña en G1.
- **ADR-0022** (identidad store/project): base física sobre la que eventuales
  `agent_id`, `host_id` o `store_root` se añadirían aditivamente en G3/G4; no
  se enmienda aquí.
- **ADR-0023 / ADR-0030** (checkpoint/handoff y obligación de continuidad):
  el "contrato de orquestación" del perfil host-managed coordina con el
  "gate del agente" de ADR-0030. Compatibles.
- **ADR-0009** (contexto gestionado): el perfil host-managed deja el bloque
  no-instalado por defecto; no se enmienda.
- **Issues #48 / #53**: la frontera catálogo/bitácora es **ortogonal** a este
  ADR (forma del contenido vs. propiedad/ubicación). No se decide aquí.

## Decisión

1. **Propietario lógico, custodia y scope.** El propietario lógico de la
   memoria es el **agente**. El **host** gestiona lifecycle, custodia e
   integración **en nombre del agente**. Un proyecto es sólo **scope
   temático** de recuperación; nunca propietario de la memoria ni fuente
   reemplazada por ella. El estado canónico del proyecto sigue en Git,
   código, tests, ADRs, SPEC y sistemas propios del proyecto. La memoria es
   dato no confiable; nunca instrucción ni autoridad (frontera de confianza
   de `AN-KLA.md:133-145`).

   Esta decisión **estrecha deliberadamente** la propuesta de #54
   (`memory_owner = agent-or-host`) a `agent` como único propietario lógico,
   separando owner (agente) de custody (host). No restringe quién puede leer
   o escribir físicamente el store; sólo fija el modelo de propiedad lógica.
   Si en el futuro se necesitara una identidad colectiva del host (varios
   agentes bajo un mismo host), se deja **diferida**: este ADR no la declara,
   no la asume privada ni la resuelve.

2. **Seis ejes independientes.** Cualquier perfil de memoria se describe por
   seis ejes ortogonales; ninguno se deduce de los otros:

   | Eje | Pregunta | Valor en el perfil inmediato |
   |---|---|---|
   | Owner | ¿quién es el propietario lógico? | agente |
   | Scope | ¿sobre qué contexto se recupera? | un proyecto (sólo alcance temático) |
   | Store_location | ¿dónde viven los bytes? | project-local (sólo compatibilidad actual) |
   | Canonicality | ¿es fuente oficial del proyecto? | non-authoritative |
   | Sharing | ¿qué procesos/agentes pueden leerlo? | filesystem-access/unverified |
   | Integration | ¿quién gestiona lifecycle y dispara recuperación/checkpoint en nombre del agente? | host-managed (custodia) |

   La independencia es estructural y **normativa**: una memoria puede ser,
   por ejemplo, owner=agente, scope=project-X, location=externa,
   canonicality=non-authoritative, y ese cruce no implica nada sobre sharing
   ni integration. La custodia del host vive en el eje Integration; no
   convierte al host en propietario lógico ni al proyecto en owner. Que los
   ejes sean normativamente independientes no niega que el perfil inmediato
   tenga **acoplamientos físicos** hoy (`store_location` atado a
   `project_root` en `an_kla/store.py:111-112`, ausencia de namespace por
   agente); ésos los resuelven G3 (`store_root` externo) y G4 (identidad de
   agente/multi-scope), no este ADR.

3. **Perfil host-managed reconocido como soportado.** Con la aceptación de
   este ADR, host-managed queda **reconocido contractualmente como perfil
   soportado**. El perfil funcionaba **de facto** antes de este ADR (`init`
   sin `context install` ya operaba); la aceptación lo eleva a decisión
   contractual. G1 sólo añade observabilidad; no determina esa propiedad (no
   la crea ni la retira).

   ```text
   memory_owner      = agent                          (propietario lógico)
   custody           = host                           (lifecycle en nombre del agente)
   scope             = single-project                 (sólo alcance temático, nunca propietario)
   store_location    = project-local                  (sólo compatibilidad actual)
   canonicality      = non-authoritative
   managed_context   = not-installed                  (opcional, no requerido)
   integration       = host-managed
   agent_binding     = unverified
   sharing_boundary  = filesystem-access/unverified
   ```

   `init` sin `context install` es la materialización mínima de este perfil y
   funciona de facto (`store.initialize_with_outcome` en
   `an_kla/store.py:142-149` es independiente de `apply_context_plan`). El
   reconocimiento contractual proviene de la aceptación de este ADR; G1 sólo
   expone el estado observable.

4. **Lo que el perfil NO prueba.** Declarar host-managed **no** afirma:

   - que el host ejecute hooks de recuperación o checkpoint (la afirmación de
     uso requiere el adaptador de G2; sin él, la documentación no puede
     prometer memoria "usada");
   - que la memoria sea privada: con `sharing_boundary=
     filesystem-access/unverified` cualquier proceso con acceso al
     filesystem puede leerla, y "memoria privada del agente" no es verdadera
     en sentido fuerte hasta G4;
   - que la memoria sea autoridad sobre el proyecto; sigue siendo dato no
     confiable.
   - que la continuidad recuperada sea necesariamente consistente con Git o
     con las políticas del proyecto. Una memoria obsoleta puede contradecirlas
     (commit distinto, política mudada, decisión superada). La mitigación es
     `canonicality=non-authoritative` combinada con verificación externa: el
     proyecto contrasta la memoria contra sus fuentes canónicas (Git, código,
     tests, ADRs, SPEC) y no la trata como fuente.

5. **Observabilidad del contexto gestionado, no congelada.** Lo que hoy
   expone `context-status/v1` opera en dos subdimensiones de la
   observabilidad del *contexto gestionado* (no de toda la integración);
   **este ADR no fija enum, schema, nombre de envolvente ni comando**:

   - **D1 — validez del bloque/contexto gestionado**: hoy cubierta por
     `installed`, `ok` y `diagnostics` de `context-status/v1`
     (`an_kla/context_package.py:723-732`).
   - **D2 — presencia/estado del manifiesto**: hoy un *warning* paralelo (p.
     ej. `context_manifest_missing`, `context_package.py:703`); no rompe
     `ok=true` por sí misma.

   El significado literal actual de `context-status/v1.ok=true` es: **bloque
   gestionado presente y sin `diagnostics` bajo el contrato vigente de esa
   envolvente**. No prueba presencia del manifiesto (que pertenece a D2 como
   warning) ni integridad del store (que corresponde a `store.verify()` y
   `doctor`). Combinaciones como `installed=true, ok=true,
   warnings=[context_manifest_missing]` son hoy válidas y observables; este
   ADR no introduce etiquetas compuestas a partir de esos warnings.

   La superficie observable versionada para el perfil host-managed —su
   schema, nombre, enum de estados, cómo se combinan D1 y D2, y si es
   envolvente nueva, versión nueva de `context-status/v1` o extensión de
   `status`— **se decide en G1** con su propia ronda adversarial. Este ADR
   no pre-decide ninguno de esos puntos.

6. **Iniciativas futuras diferidas.**

   - **G1 — contrato observable**: definir la superficie observable
     versionada del perfil host-managed (schema, nombre, enum y comando se
     deciden en G1), enumeración aditiva de modos en `capabilities()`, guía
     host-managed y advertencia de huella Git mediante `git status --porcelain`
     (no `git diff`, que no muestra untracked). Tests: `init → verify → status
     → context status` sin `context install`.
   - **G2 — adaptador del host/orquestador**: contrato de hooks de
     recuperación y checkpoint; coordina con el "gate del agente" de ADR-0030.
   - **G3 — `store_root` externo**: separar ubicación del scope; migración
     reversible, identidad sin ruta-como-autoridad, export/restore y
     concurrencia. **Diferido**; no se incorpora como cambio documental.
   - **G4 — identidad de agente y multi-scope**: `agent_id`, namespaces,
     aislamiento, política de divulgación cross-project, identidad colectiva
     del host. **Diferido**; requiere threat model dedicado (contaminación
     cross-project, falsa privacidad, disclosure a ejecutores, confused
     deputy).

7. **Huella Git.** AN-KLA no modifica `.gitignore`, `.git/info/exclude` ni
   ningún mecanismo de ignore del consumidor de forma silenciosa. La guía de
   G1 advertirá la huella con `git status --porcelain`. Si se ofrece una
   conveniencia de ignore, será operación separada, planificada y autorizada;
   nunca automática.

## Por qué no [alternativa]

### Enmendar ADR-0009 (contexto gestionado)

Mezcla contrato de contexto gestionado con modelo de propiedad lógica.
ADR-0009 está publicado y estable; las dos dimensiones tienen centros de
gravedad distintos (parser/marcadores vs. propiedad/ubicación). Mezclarlas
diluye ambos. Descartada.

### Enmendar ADR-0022 (identidad store/project)

Mezclaría identidad física (`project_uuid`/`store_uuid`) con propiedad
lógica de la memoria (`agent_id`/identidad colectiva del host). ADR-0022 es
extensible aditivamente, pero la propiedad lógica es una decisión conceptual
distinta y su evolución (G3/G4) requiere migración y threat model propios.
Descartada.

### Ninguna decisión (sólo docs de guía)

Consagra "de facto" como contrato y perpetúa que `context-status/v1.ok=true`
se lea como integridad completa pese a que sólo certifica bloque presente sin
`diagnostics` (ni manifiesto, ni store). Convierte un riesgo observado en
estado permanente. Descartada.

### Mezclar este ADR con la decisión #48 (catálogo/bitácora)

Son ortogonales: #48 decide **forma del contenido** (entidad persistente
reconfirmable vs. afirmación fechada inmutable); este ADR decide **propiedad
lógica, ubicación e integración**. Mezclarlos niega la independencia de los
seis ejes y bloquea decisiones separadas. Descartada; la ortogonalidad se
declara explícitamente en §Contexto y §Referencias.

### Pre-congelar enum/schema/comando de G1 en este ADR

Prematuro. La lista de cuatro estados propuesta en #54 no contempla
combinaciones reales y observables como `installed=true, ok=true,
warnings=[context_manifest_missing]`, ni la separación D1/D2. El enum exacto
exige ronda adversarial de G1; pre-decidirlo aquí crearía un contrato frágil.
Descartado.

### Convertir `host-managed` en una decisión de código inmediata (saltarse G0)

El perfil ya funcionaba de facto; lo que faltaba era **declaración
contractual** y **observabilidad** (G1). Saltarse G0 no habría ahorrado
trabajo: habría dejado a consumidores y a `capabilities()` sin un punto de
referencia canónico. Descartada; este ADR provee ahora ese punto de
referencia y G1 añadirá la observabilidad.

## Consecuencias

- **Positivas:**
  - Declara contractualmente que el propietario lógico de la memoria es el
    agente y que el proyecto es sólo scope, no estado canónico reemplazado por
    la memoria.
  - Reconoce host-managed como perfil soportado sin negar sus límites; el
    perfil ya operaba de facto y ahora cuenta con decisión contractual.
  - Separa seis ejes y dos subdimensiones de observabilidad del contexto
    gestionado sin acoplamiento implícito, habilitando decisiones independientes
    para #48, #47, #49 y para G2/G3/G4.
  - Fija que `init` sin `context install` es soportado, no accidental.

- **Negativas:**
  - Hasta G1, la decisión contractual y el comportamiento de facto pueden
    divergir en detalles observables: el perfil está reconocido, pero sin la
    superficie observable versionada un consumidor no puede distinguir
    host-managed de otros estados sólo desde la salida de los comandos.
  - El perfil project-local mantiene el lifecycle acoplado: borrar el
    worktree borra la memoria local. Eso sólo se resuelve en G3.
  - `sharing_boundary=filesystem-access/unverified` implica que la frase
    "memoria privada del agente" no es verdadera en sentido fuerte hasta G4;
    la documentación de G1 debe decirlo sin ambages.

- **Neutras:**
  - No cambia código, schemas, `capabilities()`, contratos existentes ni el
    contrato gestionado.
  - El registro canónico gana una fila (0031) y el resumen pasa de 30 a 31
    ADRs (29 aceptadas, 2 propuestas); el conteo explícito del test de
    registro se actualiza en consecuencia (Aceptada 28→29, Propuesta
    permanece en 2).

## Test de regresión

Este ADR es documental (G0). No introduce tests automatizados funcionales
directamente. Su Test de regresión inmediato es:

- `scripts/check_adr_registry.py` pasa: fila 0031 presente, estado
  `Aceptada` coherente entre el registro y el ADR, sin huecos ni duplicados.
- `scripts/check_sizes.py` pasa: este archivo ≤ 400 líneas.
- `python3 -m unittest discover -s tests -p 'test_*.py'` pasa; el conteo
  explícito del registro en `tests/test_adr_registry.py` refleja este ADR
  (Aceptada 29, Propuesta 2).

Tests funcionales diferidos a G1 (criterios de aceptación de ese gate, no de
éste):

- `init` sin `context install` produce un estado host-managed observable y
  reproducible.
- La superficie observable versionada (comando y schema definidos en G1)
  distingue memoria ausente, válida y corrupta, leyendo estado de forma
  read-only y **sin** crear `.an-kla/`, **sin** mutar revisión y **sin**
  adquirir lock de escritura.
- `capabilities()` enumera los modos de integración soportados sin leer
  estado del proyecto/store.
- `capabilities()` permanece determinista; el fingerprint de `write_policy`
  se preserva **sólo si** su configuración no cambia en G1.

## Referencias

- **Issue #54** — el que motiva este ADR.
- **Issues #48 y #53** — frontera catálogo/bitácora y síntesis cross-issue.
  Ortogonales a este ADR; se declaran explícitamente no resueltos aquí. La
  decisión #48 sigue determinando el destino de #47 y #49.
- **Issue #45** — referencias en `AGENTS.md`. El perfil host-managed evita el
  drift de #45 por diseño (no instala bloque gestionado); no lo reemplaza.
- **ADR-0009** — contexto gestionado. Compatible; el perfil deja el bloque
  no-instalado por defecto.
- **ADR-0010** — capabilities-v1 stateless. Compatible; la enumeración de
  modos de integración, si se añade, es aditiva y se diseña en G1.
- **ADR-0022** — identidad store/project. Base para extensiones futuras
  (`agent_id`, `store_root`, identidad colectiva del host) en G3/G4; no se
  enmienda aquí.
- **ADR-0023 y ADR-0030** — checkpoint/handoff y obligación de continuidad.
  El contrato de orquestación del perfil host-managed (G2) coordina con el
  gate del agente de ADR-0030.
- `docs/practicas-ingenieria.md` §3 (ADR antes que el código).
