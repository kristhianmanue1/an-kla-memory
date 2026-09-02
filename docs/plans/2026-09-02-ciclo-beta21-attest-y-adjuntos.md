# Plan: ciclo beta.21 — cierre attest (#102) y adjuntos de superficie

Alcance acordado para el ciclo beta.21: cerrar el residual de attest (#102)
que bloquea la release, absorber las contribuciones baratas de la ronda
adversarial externa (#111 P4, P1, P3) y los puntos pequeños con decisión del
dueño (#109 puntos 2 y 3). Estado de partida verificado: main en ed64994
(attest S2 committeado), `pyproject.toml` sin techo de Python,
`an_kla/context_text.py` en plantilla 0.1.0-beta.11.

Ronda adversarial pre-code sobre este plan (agente fresco, read-only,
2026-09-02): veredicto fix-and-retry absorbido — secuenciación explícita,
metadata de release congelada, pins de plantilla, estado canónico del ADR,
marker del release gate y Consumes faltantes (registro en
docs/planning/plan-beta21-precode-adversarial-2026-09-02.md).

**Orden de ejecución obligatorio: T2, T3, T4, y T1 al cierre** — el tag
congela el árbol completo del ciclo, así que la release (T1) es el último
tarea; la ronda adversarial REL de T1 corre contra ese árbol final.

```text
TAREA T1 cerrar residual attest y etiquetar 0.1.0b21 (#102, P0 — se ejecuta al final)
Consumes: `an_kla/context_text.py`, `AN-KLA.md`, `AGENTS.md`,
  `docs/architecture/0046-attest-local-signed-observation-v1.md`,
  `docs/README.md`, `an_kla/version.py`,
  `tests/test_integration_status.py`, `tests/test_release_metadata.py`,
  `scripts/check_clean_wheel.py`, `README.md`, `SECURITY.md`,
  `CITATION.cff`, `CHANGELOG.md`
Produce: plantilla 0.1.0-beta.21 con pins actualizados, ADR-0046 en estado
  canónico, metadata de release coherente; crea `docs/releases/v0.1.0-beta.21.md`
  y tag v0.1.0-beta.21
Steps:
  - [ ] bump de plantilla del contrato a TEMPLATE_VERSION 0.1.0-beta.21 en
    `an_kla/context_text.py` incorporando write-authority-v2 y el
    vocabulario de attest en §Resolver autoridad (ADR-0046 §8): sólo esa
    sección del contrato cambia, la entrada histórica de
    _KNOWN_CONTEXT_TEMPLATES se preserva, y el marker del bloque gestionado
    en AGENTS.md se alinea vía el flujo explícito context plan
    --operation update; actualizar los pins congelados a la plantilla vieja
    en `tests/test_integration_status.py` y `scripts/check_clean_wheel.py`;
    verificación: context status sin context_template_outdated, suite
    focal de contrato en verde y diff limitado a lo declarado.
  - [ ] flip de estado del ADR-0046 al valor canónico Aceptada con nota
    implementada en v0.1.0-beta.21, citando el commit de S2 y su evidencia
    adversarial, más la celda de estado de la fila 0046 en `docs/README.md`;
    verificación: `scripts/check_adr_registry.py` OK con el estado
    aceptado por el registro y diff limitado a ambas líneas.
  - [ ] metadata de release congelada a la versión: badges y pin de
    instalación en `README.md` (in-place, 492/500), fila en `SECURITY.md`,
    version en `CITATION.cff`, sección en `CHANGELOG.md`, y los pins de
    `tests/test_release_metadata.py` y `scripts/check_clean_wheel.py`
    (clean_wheel 0.1.0b21); verificación: suite de release metadata en
    verde.
  - [ ] ronda adversarial REL con agente fresco contra el árbol final del
    ciclo (post T2/T3/T4 y post-bump), siguiendo
    `docs/adversarial-template.md`; el veredicto proceed se registra como
    crea `docs/releases/v0.1.0-beta.21-adversarial.md` con el marker
    an-kla:release-gate {"decision":"proceed","scope":"release-candidate","tag":"v0.1.0-beta.21"};
    verificación: documento de ronda con veredicto proceed antes de
    etiquetar.
  - [ ] release: subir VERSION a 0.1.0b21 en `an_kla/version.py`, crear la
    nota de release (ruta en Produce), correr gates y etiquetar;
    verificación: `scripts/check_sizes.py` OK, `scripts/check_plans.py`
    OK, `scripts/check_clean_wheel.py` OK, `scripts/check_release_tag.py`
    OK, suite completa en verde.
TAREA T2 adjuntos de superficie de #111: techo de Python y warning no indexable (P4+P1)
Consumes: `pyproject.toml`,
  `an_kla/schemas/write-proposal-v1.schema.json`, `an_kla/__main__.py`,
  `tests/test_commit_indexable_warning.py`,
  `docs/beta11-user-guide.md`
Produce: requires-python con techo, schema con text declarado, warning
  visible en stderr, guía actualizada
Steps:
  - [ ] fijar requires-python = ">=3.9,<3.14" en `pyproject.toml` y
    revisar coherencia de badges/README con la matriz declarada (README en
    492/500: edits in-place sin crecer); verificación: instalación del
    wheel OK con los intérpretes 3.9/3.12 disponibles localmente y
    metadatos sin drift.
  - [ ] declarar text como campo documentado y opcional del record plano
    de `an_kla/schemas/write-proposal-v1.schema.json` (el formato físico
    payload.text queda fuera; indexable_text opcional si el schema lo
    soporta), con description que explique la exclusión no_text;
    verificación: suite de schemas y validación de proposals en verde,
    sin romper fingerprints (policy no deriva del schema).
  - [ ] surface del warning record_without_indexable_text en la capa CLI
    `an_kla/__main__.py` por stderr sin contaminar el JSON canónico de
    stdout, extendiendo `tests/test_commit_indexable_warning.py` con
    harness de subprocess; verificación: suite focal y completa en verde.
  - [ ] nota en la sección de escritura de `docs/beta11-user-guide.md`:
    un hecho sin texto indexable no es recuperable; verificación:
    `scripts/check_sizes.py` OK.
TAREA T3 runbook de recuperación para agentes (#111 P3)
Consumes: `an_kla/transactions.py`, `docs/beta11-user-guide.md`
Produce: docs/agent-recovery.md con runbook ante resultado ambiguo
Steps:
  - [ ] crea `docs/agent-recovery.md` con el runbook ante resultado
    ambiguo: tabla de estados de `an_kla/transactions.py`, ejemplo real
    de durability_incomplete capturado en #111, y criterio de decisión
    entre repair, reconcile y retry con re-plan; verificación: walkthrough
    de un agente fresco que resuelve el escenario siguiendo sólo el doc.
  - [ ] enlazar el runbook desde la guía de usuario sin tocar el bloque
    gestionado de AN-KLA.md; verificación: `scripts/check_sizes.py` OK y
    diff sin cambios en marcadores gestionados.
TAREA T4 deuda pequeña de #109: mensaje canónico y anclaje LC_ALL (puntos 2+3)
Consumes: `scripts/redteam_consistent_rewrite.py`,
  `tests/test_redteam_consistent_rewrite.py`,
  `scripts/verificar_anclaje.py`, `tests/test_verificar_anclaje.py`,
  `docs/architecture/0043-store-threat-model-v1.md`,
  `docs/architecture/0044-h1c-formalizacion-v1.md`,
  `docs/gobernanza/anclajes/2026-08-31-anclaje-inicial.md`
Produce: mensaje redteam_boundary_changed unificado en ambos modos de
  fallo; decisión LC_ALL=C ejecutada o declarada aplazada
Steps:
  - [ ] unificar el mensaje canónico a ambos modos de fallo del selftest
    (hoy sólo se imprime si la forgery es rechazada) y matizar el ADR-0043
    en la misma pasada; verificación:
    `tests/test_redteam_consistent_rewrite.py` en verde con ambos caminos
    cubiertos.
  - [ ] gate de decisión del maintainer sobre LC_ALL=C en el protocolo de
    anclaje (implica re-anclaje y digest nuevo); verificación: decisión
    del dueño registrada en el issue #109 antes de tocar código.
  - [ ] si la decisión es proceed: fijar LC_ALL=C en
    `scripts/verificar_anclaje.py`, en el protocolo del ADR-0044 y en el
    helper de `tests/test_verificar_anclaje.py` (misma env en los tres),
    re-anclar añadiendo fila en el registro de anclajes y registrar el
    digest nuevo; verificación: `tests/test_verificar_anclaje.py` en verde
    y digest documentado; si es defer: punto registrado en #109 sin
    cambios de código.
```

Fuera de alcance en este ciclo: el refactor menor de store.py (800/800,
registrado en el checkpoint) y el doc-contract del write lock (P2 de #111)
tocan core y exigen ronda adversarial propia; ci_local multi-intérprete
(P5), examples/agent-integration (P6), las particiones de #106 y #95 y los
tracks G2/G3/G4 (#56/#57/#58) quedan para ciclos siguientes. La firma F0 de
#56/ADR-0047 corre en paralelo y no bloquea este ciclo.
