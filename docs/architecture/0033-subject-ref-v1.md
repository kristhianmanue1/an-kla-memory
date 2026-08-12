# ADR-0033: identidad contextual estable `subject_ref` v1

- **Estado:** Aceptada
- **Implementación:** Completada en candidata `v0.1.0-beta.12` (sin publicar);
  fases y evidencia en el [reporte adversarial](../releases/v0.1.0-beta.12-adversarial.md).
- **Fecha:** 2026-08-11
- **Decide sobre:** la identidad contextual estable `subject_ref` (elemento
  contextual recordado: servicio, decisión, actor, API, etc.), separada del
  `record.id` físico (afirmación inmutable) y de los `lineage.refs`
  (evidencia/procedencia). No decide la vista (G-VIEW), los endpoints de
  relación ni los namespaces cross-project. Ejecuta documentalmente el gate
  G-SUBJECT de ADR-0032.

## Contexto

ADR-0032 congeló **conceptualmente** `subject_ref` y **diferió** a este gate el
schema, cardinalidad, namespaces y serialización. El issue #59 pide cerrar ese
contrato antes de cualquier vista o código. Este ADR es documental: no añade
campo, validador ni command; la ronda adversarial independiente concluyó
`proceed` antes de aceptar esta decisión.

El código actual es event-shaped y sin `subject_ref`: el `fact` es inmutable
con `id` físico por stream, asignado por `_assign_records`
(`store.py:49`, `store.py:755-772`); el record persiste **verbatim** al
segmento (`store.py:411-420`); `supersedes_map`
es keyed por `(stream, target_id)` físico con comparación byte-exacta **sin
NFC/casefold** (`store.py:213-218`, `store.py:380-387`); el refresco oficial
`supersede` con nuevo `verified_at` (ADR-0021 §7) renombra el `id` y rompe
referencias estables (#47); `lineage.refs` (`write_policy.py:236-237`) es
**procedencia/evidencia**, no identidad (corrección vinculante del spike
previo, ADR-0032). Patrón de validador establecido por `verified_at`: tag en
`temporal.py:10`, registro en `_POLICY_CONFIGURATION["record_validators"]`
(`write_policy.py:84`), rama en `write_policy.py:212-216`, digest dorado en
`tests/test_write_policy.py` (`test_verified_at_validator_changes_and_freezes_policy_fingerprint`,
`test_policy_fingerprint_binds_reason_and_terminal_code_catalogs`). El store ya
lanza `WritePolicyError` desde `commit_write_plan` para bindings tipo supersede
(`store.py:379,389,396`); `IdentityError(RuntimeError)` (`identity.py:32`) es
jerarquía hermana de `StoreError(RuntimeError)` (`store.py:53`), **distinta**
de `WritePolicyError(ValueError)` (`write_policy.py:89`); el CLI captura ambas
(`__main__.py:530`). `commit_write_plan` adquiere `write_lock` (`store.py:321`),
lee `CURRENT`, llama `assert_unchanged` (`store.py:325`,
`identity.py:174-192`) — cubre TOCTOU — y después valida bindings antes de
efectos. `binding["project_bytes"]` ya está materializado por `read_binding`
(`identity.py:167`); `compaction.py:59,167` ya usa
`digest_bytes(binding["project_bytes"])` como digest canónico de
`project-identity-v1`. `identity_status` (`identity.py:622-726`) clasifica
**sin crear `.an-kla/`**, sin `write_lock`, sin mutar; con `include_ids=True`
(`identity.py:724-725`) expone `project_uuid`. El schema `project-identity-v1`
es público, así que el digest canónico es **recomputable** desde
`identity status --show-ids`. Los schemas v2 de retrieve/mcp/assembly
**cierran** `selected_item`/`record` (`additionalProperties:false`):
`retrieval-result-v2.schema.json:148`, `mcp-retrieve-v2.schema.json:44`,
`context-assembly-v2.schema.json:65`. `capabilities()` es stateless
(ADR-0010); hoy **no enumera** `record_validators`, sólo expone el
`fingerprint` agregado (`capabilities.py:141-158`). Restricciones vigentes:
contrato gestionado, ADR-0007/0010/0019/0021/0022/0026/0027/0028/0031/0032,
frontera de confianza de `AN-KLA.md:133-145`.

## Decisión

1. **Forma canónica.** `subject_ref` es un string `"an-kla:subject:v1:" kind ":"
   namespace ":" id`. No es URN (no sigue RFC 8141, no requiere registro IANA,
   no admite r/q/f-components). **Una sola gramática normativa anclada y con
   enum embebido**, copiable byte por byte al JSON Schema (sin validación
   separada de `kind`, sin segunda gramática):

   ```python
   SUBJECT_REF_PATTERN = (
       r"^an-kla:subject:v1:"
       r"(?:actor|api|decision|dependency|doc|environment|integration|issue|project|service|system)"
       r":p-[0-9a-f]{32}:[a-z0-9._-]{1,64}$"
   )
   ```

   Uso normativo: `re.compile(SUBJECT_REF_PATTERN).fullmatch(value)`. El
   `pattern` del campo `record.subject_ref` en `write-proposal-v1.schema.json`
   es exactamente el mismo string. `kind` e `id` no admiten `:` (la regex lo
   impone). **Longitud válida 58-129 bytes** (prefijo 18 + kind 3-11 + `:` 1
   + namespace 34 + `:` 1 + id 1-64). Todo `subject_ref` mayor a 129 bytes es
   rechazado por la regex.

2. **Namespace explícito y host-bound.** El caller lo declara, el host lo
   deriva y verifica desde el digest canónico de `project-identity-v1`:
   `namespace = "p-" + digest_bytes(canonical_json(project-identity-v1))[7:39]`.
   **128 bits de entropía** (32 hex); probabilidad de colisión ≈ n²/2¹²⁹ (≈
   1.5 × 10⁻²⁷ para 10⁶ proyectos). **Permite correlación** dentro y entre
   stores del mismo digest. **No ofrece privacidad (M2):** no expone el UUID
   crudo, pero `identity status --show-ids` ya lo expone (`identity.py:724-725`)
   y el schema `project-identity-v1` es público, así que digest y namespace
   son **recomputables**. **No ofrece autoridad** (dato; `evaluate_write` no
   lo lee; el binding no eleva techo). **No es path, URL ni UUID crudo.**

3. **Cardinalidad uno + ASCII lowercase reject-only.** Un `record` lleva cero
   o un `subject_ref` (string). Relaciones múltiples requieren contrato
   diferido (decisión 6). No se aplica NFC ni casefold: bytes fuera del
   alfabeto se rechazan, no se normalizan. Eco verbatim del válido. Coherente
   con `canonical_json` (`canonical.py:10-17`), `bare_digest`
   (`canonical.py:48-54`) y `PROFILE` regex (`refute_contracts.py:21`).

4. **Enum cerrado de 11 kinds + precedencia semántica (M3).** Los kinds son:
   `actor` (persona/equipo/rol/organización que actúa), `api` (contrato de
   interfaz: REST/gRPC/GraphQL/SDL), `decision` (resolución arquitectónica o de
   gobierno registrada), `dependency` (artefacto externo versionado consumido:
   librería, imagen, servicio externo empaquetado), `doc` (artefacto documental:
   README, SPEC, guía), `environment` (contexto de despliegue: prod/staging/dev;
   instancia, no código), `integration` (conexión operativa configurada con un
   sistema externo: webhook, OAuth, SSO), `issue` (tracker item: ticket, bug,
   task), `project` (repositorio/unidad con ciclo de vida propio), `service`
   (proceso desplegable con interfaz de red o IPC), `system` (composición de
   varios `project`: plataforma, producto). **Precedencia semántica normativa,
   no ejecutable:** la guarda sólo comprueba pertenencia al enum; no elige ni
   desambigua `kind`. El kind lo determina la faceta que la afirmación describe
   conforme a las definiciones. Una entidad con facetas distintas tiene
   `subject_ref` distintos (p. ej. un ADR como archivo → `doc`; la resolución
   que contiene → `decision`). Una afirmación multifacética **se divide en
   varios records, uno por `subject_ref`**, en lugar de elegir un único kind.
   **Si ninguna definición aplica inequívocamente, el writer no emite
   `subject_ref`** (el campo es opcional; el record puede escribirse sin él).
   No elige arbitrariamente. Añadidos futuros al enum rompen
   `policy_fingerprint()` (actualizar digest dorado, bump beta). El coste
   operacional (parada o emisión como múltiples records) se declara en
   Consecuencias.

5. **Partición de la guarda (ADR-0019 §7).**
   - `evaluate_write`/`validate_write_proposal` (pura) valida **forma y
     pertenencia al enum** en una sola pasada:
     `re.compile(SUBJECT_REF_PATTERN).fullmatch(record["subject_ref"])`. La
     regex embebe el enum; no hay validación separada de `kind`. Fallo →
     `WritePolicyError("invalid_write_proposal", "record.subject_ref")`. No
     lee estado.
   - `commit_write_plan` (bajo `write_lock`, **después** de `assert_unchanged`
     y `verify_write_plan`, **antes** de construir `pending`) valida **binding
     de namespace**: para cada `record` con `subject_ref`, compara el
     `namespace` declarado contra el derivado de
     `digest_bytes(binding["project_bytes"])` (M4). El `binding` es el capturado
     por `mutation_preflight` (`identity.py:613-619`) y revalidado por
     `assert_unchanged` (`identity.py:174-192`); **no se relee project-identity
     ni se recalcula su digest fuera del binding ya materializado** (patrón
     idéntico a `compaction.py:59,167`). Discrepancia →
     `WritePolicyError("subject_ref_namespace_mismatch")` (decisión 9), sin
     efectos (cero objetos, cero journal, cero revisión; análogo al bloque
     supersede en `store.py:368-404`). TOCTOU cubierto: si la identidad migra
     entre consulta y commit, `assert_unchanged` falla **primero** con
     `IdentityError("store_identity_changed")` (`identity.py:184`); si no
     migró pero el caller declaró namespace incorrecto, falla con
     `subject_ref_namespace_mismatch`. No se mezclan jerarquías.

6. **Relaciones y endpoints diferidos (H4).** `relation` **no** es un kind v1.
   Relaciones (sujeto↔objeto con predicado) y endpoints explícitos
   (sujeto+predicado+`object_ref`) requieren un **ADR posterior**. **G-VIEW v1
   no navegará relaciones**: agrupará y ordenará por `subject_ref` atómico, sin
   resolver aristas. Los aliases como claves de resolución alternativas también
   se descartan para v1 (reintroducirían el churn de #47); son metadata en el
   payload, no identidad.

7. **`subject_ref` es opcional, verbatim y dato no autoridad.** Viaja al
   segmento sin proyección (`write_policy.py:513` → `store.py:411-420`).
   Registros legacy sin `subject_ref` siguen siendo legibles; `snapshot`,
   `verify`, `retrieve`, `refute`, `compaction` y `export/restore` operan sin
   cambio. El `record` permanece **abierto** (precedente `verified_at`). No
   entra en `_SELF_ASSERTED_AUTHORITY_KEYS` (`write_policy.py:35-46`);
   `evaluate_write` no lo lee para decidir (análogo a `verified_at`, ADR-0021 §3).

8. **Sin proyección a v2; descubrimiento en `write-proposal-v1` (B3, L2).**
   `subject_ref` no se proyecta a `retrieval-result-v2`, `mcp-retrieve-v2` ni
   `context-assembly-v2` (cerrados); G-VIEW definirá schema v3. **Gramática y
   kinds se publican exclusivamente en `write-proposal-v1.schema.json` como
   `record.properties.subject_ref` con el `pattern` exacto de la decisión 1.**
   No existe enumeración de kinds en `subject-namespace-result-v1` ni en
   `capabilities()`. **Este ADR no modifica `capabilities()` ni schemas
   ejecutables todavía.** La implementación añadirá: (a) la clave `subject_ref`
   en el dict existente `_POLICY_CONFIGURATION["record_validators"]`
   (`write_policy.py:84`) — la exposición enumerable de `record_validators` en
   `capabilities()` es **aditiva nueva** (hoy no existe); (b) el campo
   `record.subject_ref` con `pattern` en `docs/schemas/write-proposal-v1.schema.json`
   y gemelo byte-idéntico en `an_kla/schemas/` (precedente ADR-0021 §6), `record`
   sigue abierto; (c) el comando `subject namespace` + schema
   `subject-namespace-result-v1` (decisión 10). El bloque `subject_view` no se
   añade (la vista no existe; duplicaría el contrato de G-VIEW).

9. **Código terminal nuevo.** `"subject_ref_namespace_mismatch"` en
   `_POLICY_CONFIGURATION["terminal_error_codes"]` (`write_policy.py:68-78`),
   análogo a `invalid_supersede_target`. `str(error) == code` estable
   (`write_policy.py:99-102`); `detail` evolutivo. No se añaden reason codes.

10. **Superficie observable del namespace (H1/H2/H3/M1/M2).** Un comando de
    **resolución**, no de inspección: devuelve el `namespace` que el caller
    debe usar en `subject_ref` para que el binding del commit pase. Va
    **acompañado** de su schema de salida versionado (alternativa consolidada:
    no existen comandos sin schema ni schemas sin comando). **Comando:**
    `an-kla --project-root <root> subject namespace`. **Schema:**
    `an-kla/subject-namespace-result-v1`, shape cerrada con claves exactas
    `{schema, result, namespace}` (**no expone `project_identity_sha256`**,
    M1). **`result`** es un enum **desacoplado** de `identity_status` con sólo
    dos valores; el mapeo a los 9 estados vigentes (`identity.py:622-726`):

    | `identity_status` | `result` | `namespace` | exit |
    |---|---|---|---|
    | `complete` | `namespace_available` | `p-<32hex>` | 0 |
    | `absent` / `legacy_unadopted` / `intent_only` / `store_only` / `project_only` / `partial_consistent` / `identities_ready_root_pending` / `conflict` | `namespace_unavailable` | `null` | 3 |

    `subject-namespace-result-v1` no expone el estado específico; **`identity
    status` es la única superficie diagnóstica** del mismo, lo que permite a
    `identity_status` evolucionar sin romper el contrato de resolución.

    **Flujo normativo (N5b):** el comando llama primero a `identity_status`;
    si no es `complete`, devuelve `namespace_unavailable`/exit 3 sin más
    lectura. Sólo si es `complete` llama a `read_binding` y deriva el
    `namespace` vía `digest_bytes(binding["project_bytes"])`. Si entre ambas
    lecturas aparece drift o `IdentityError` esperado, se mapea a
    `namespace_unavailable`/exit 3. **stderr vacío sólo para los nueve estados
    clasificados y esos `IdentityError` esperados**; `OSError` y fallos
    inesperados capturados siguen el handler general del CLI
    (`an_kla/__main__.py:541-555`): exit 1 y un mensaje de una línea que puede
    incluir la ruta que falló; excepciones fuera del conjunto capturado pueden
    conservar traceback. El commit sigue revalidando bajo lock (decisión 5);
    la salida del comando es sólo input para construir proposals.
    **Diferencia frente a `identity status` (H2):** `identity status` es de
    **inspección** (diagnóstico; con `--show-ids` expone UUIDs); `subject
    namespace` es de **resolución** (produce el `namespace` a usar, fail-closed
    si la identidad no está `complete`). Reproducción empírica cancelada por el
    operador; la ronda adversarial independiente debe confirmarla runtime.

11. **Sistemas externos como subjects locales al proyecto en fase 1.** Un
    subject que represente un sistema externo vive dentro del namespace del
    proyecto actual. **No existe namespace global ni cross-project en fase 1.**
    Dos proyectos que mencionan el mismo externo (p. ej. `gh-59`) producen dos
    subjects distintos; correlación cross-project es **offline**. Namespace
    cross-project y registry de authorities externos se difieren a un ADR
    dedicado (depende de ADR-0031 G3/G4).

12. **Inmutabilidad + frontera de estabilidad del namespace (M5).** Los
    registros históricos son inmutables: este ADR no ordena reescribir bytes,
    `subject_ref` históricos ni namespaces. Los registros previos a este gate
    no portan `subject_ref`; G-VIEW definirá su tratamiento (fail-closed o
    enum de estado, fuera de este ADR). **Mientras el project identity anchor
    se conserva:** la **relocación** del store preserva el namespace (se deriva
    del digest, no de la ruta; ADR-0022 §"Backup, clone y worktree"); el
    **restore** desde bundle export-v1 también (`project-identity.json`
    byte-idéntico, ADR-0027). **Si el anchor se reemplaza** (recuperación de
    desastre, borrado de `.an-kla/` seguido de `init`, o reemplazo deliberado):
    acuña identidad nueva con namespace distinto; los registros históricos
    **retienen sus bytes y su namespace anterior** (no se reescriben); nuevas
    escrituras con el namespace anterior fallan binding con
    `subject_ref_namespace_mismatch`. **Migración o remapeo de namespaces
    queda fuera de v1 y requiere ADR posterior.**

## Modelo de amenazas

- **Memoria recuperada / confused deputy / refute:** `subject_ref` hereda la
  frontera de `AGENTS.md` y `AN-KLA.md:133-145` (nunca instrucción ni
  autoridad); ADR-0032 §5 obliga a `non-canonical` y `verified_at` como
  `self_asserted_timestamp`. No se añade selector por `subject_ref` para
  refute: sigue usando `target_record_sha256` físico (`refute_contracts.py:69`,
  `refutations.py:198-204`); ambigüedad prohibida (`refutations.py:202-203`).
- **Forma / longitud / cardinalidad:** ASCII lowercase reject-only (decisión 3);
  regex rechaza `/`, `\`, `@`, `?`, `#`, espacios y `:` en `kind`/`id`;
  namespace es digest, no path/URL. **El único límite de longitud de
  `subject_ref` es la regex** (58-129 bytes); `_validate_json_value`
  (`write_policy.py:131-161`) limita profundidad y nodos del JSON contenedor,
  no longitud de strings. Cardinalidad 1.
- **Cross-project / traversal / disclosure (M1/M2):** namespace derivado de
  `project_identity_sha256` aleatorio; namespace implícito preserva la
  restricción de diseño; cross-project es stop-condition (decisión 11).
  Identificador opaco; consumers no lo resuelven (ADR-0032 §4). El UUID no
  está en claro, pero es recomputable desde `identity status --show-ids` y el
  schema público: **no ofrece privacidad adicional**. La proyección a v2
  queda fuera de este gate; la disclosure por envolvente la decide G-VIEW.
- **Fingerprint drift / TOCTOU / reemplazo de anchor:** fingerprint controlado
  por nuevo validador (precedente `verified_at`); TOCTOU cubierto por
  `assert_unchanged` (decisión 5); si el anchor se reemplaza, los registros
  históricos **retienen sus bytes y su namespace anterior**, las nuevas
  escrituras con namespace anterior fallan binding sin migración
  automática en v1 (decisión 12). Limitación documentada, no silenciada.

## Por qué no [alternativa]

- **URN / base32 / objeto estructurado:** URN exige `urn:`, registro IANA y
  r/q/f-components ambiguos; base32/base64url es ilegible en logs
  (contradice ADR-0031 §4-5); objeto estructurado choca con
  `_contains_self_asserted_authority` (`write_policy.py:331-338`), multiplica
  coste de `canonical_json` y duplica superficie frente a `lineage.refs`.
  `subject_ref` es string.
- **Cardinalidad N:** pierde determinismo; `supersede` es 1-a-1
  (`write_policy.py:224`); relaciones requieren ADR posterior (decisión 6).
- **Namespace UUID crudo / path / URL / cross-project:** UUID filtra
  directamente; path-as-authority descartado por ADR-0022; URL abre
  SSRF/oracle; cross-project rompe ADR-0032 y requiere threat model de
  ADR-0031 G4 (diferido).
- **`relation` como kind v1 (H4) / aliases como claves / `subject_view` antes
  de G-VIEW:** `relation` requiere contrato de endpoints y ADR dedicado;
  G-VIEW v1 no navega relaciones. Los aliases son metadata en el payload, no
  claves (reintroducirían el churn de #47). Los schemas v2 cierran
  `selected_item`/`record` (`additionalProperties:false`); rompería golden
  tests (ADR-0010). `subject_view` duplicaría el contrato de G-VIEW. Los kinds
  se descubren en `write-proposal-v1.schema.json`.
- **Reutilizar `lineage.refs` como identidad de subject / `kind` genérico:**
  corrección vinculante del maintainer al spike previo (ADR-0032 §"Corrección
  al spike previo"). `kind` genérico pierde semántica para G-VIEW; enum
  cerrado adoptado.
- **Exponer `project_identity_sha256` en `subject-namespace-result-v1` (M1):**
  innecesario para la resolución y amplía la disclosure sin ganancia operativa.

## Consecuencias

- **Positivas:** identidad contextual estable separada del `id` físico y de
  `refs`; #47 deja de romper referencias contextuales; ASCII reject-only
  elimina NFC/casefold; cardinalidad 1 y enum cerrado preservan determinismo
  para G-VIEW; partición de la guarda preserva ADR-0007 y reutiliza el digest
  pre-computado `digest_bytes(binding["project_bytes"])`; compatibilidad
  legacy; namespace sobrevive relocación y restore; v2 dorado intacto.
- **Negativas:** `policy_fingerprint()` cambia y todo plan pendiente debe
  replantearse (precedente ADR-0021 §8); hasta G-VIEW los consumidores siguen
  sin navegación contractual; sin namespace cross-project en fase 1; el caller
  debe consultar `subject namespace` antes de `plan-write` (exit 3 sin
  namespace si la identidad no está `complete`); **afirmaciones multifacéticas
  se dividen en múltiples records (uno por `subject_ref`), con coste
  operacional y de storage (decisión 4); si ninguna definición de kind aplica
  inequívocamente el writer debe parar y no escribir**; si el anchor se
  reemplaza, los registros históricos retienen su namespace anterior y las
  nuevas escrituras con ese namespace fallan binding (decisión 12);
  migración/remapeo fuera de v1.
- **Neutras:** no cambia código ni schemas ejecutables todavía; el registro
  gana una fila (0033); 33 ADRs (31 aceptadas, 2 propuestas); test de registro
  actualizado (Aceptada 30 → 31).

## Test de regresión

Este ADR es documental. Test inmediato: `scripts/check_adr_registry.py`,
`scripts/check_sizes.py` (≤ 400 líneas) y `python3 -m unittest discover -s
tests -p 'test_*.py'` pasan; el conteo del registro en
`tests/test_adr_registry.py` refleja este ADR (Aceptada 31, Propuesta 2).

Tests funcionales diferidos a la implementación (criterios del PR):

- **Forma + no-elevación (pure):** cada caso inválido → `invalid_write_proposal`,
  detail `record.subject_ref` (uppercase, no-ASCII, `:` en kind/id, namespace
  mal formado 33/31 hex o `P-...` o hex con `g-z`, versión `v2`, kind fuera del
  enum, `:` extra, longitud > 129 bytes). Eco verbatim del válido.
  `subject_ref` no entra en `_SELF_ASSERTED_AUTHORITY_KEYS`. Patrón análogo a
  `test_invalid_verified_at_uses_stable_proposal_error` y
  `test_verified_at_is_validated_but_never_elevates_authority`.
- **Fingerprint:** nuevo digest dorado; drift análogo a
  `test_beta8_valid_plan_fails_with_policy_fingerprint_mismatch` y
  `test_policy_fingerprint_binds_reason_and_terminal_code_catalogs`.
- **Binding + TOCTOU (store-side):** namespace correcto pasa; incorrecto →
  `subject_ref_namespace_mismatch` con cero efectos (análogo a
  `invalid_supersede_target`); deriva de `digest_bytes(binding["project_bytes"])`
  sin relectura (equivalencia con el digest que produce `compaction.py`).
  Identidad migrada entre `subject namespace` y commit →
  `IdentityError("store_identity_changed")` primero.
- **Legacy + persistencia:** record sin `subject_ref` legible, `verify()` OK;
  record con `subject_ref` persiste byte-idéntico, compaction lo preserva,
  export/restore roundtrip lo preserva.
- **`subject namespace` (CLI, flujo N5b):** `identity_status == "complete"`
  → stdout JSON canónico con `schema`, `result="namespace_available"`,
  `namespace="p-<32hex>"`, exit 0, stderr vacío. Cualquier otro de los 8
  estados no-`complete` (`absent`, `legacy_unadopted`, `intent_only`,
  `store_only`, `project_only`, `partial_consistent`,
  `identities_ready_root_pending`, `conflict`), y también drift o
  `IdentityError` esperado entre `identity_status` y `read_binding`, →
  `result="namespace_unavailable"`, `namespace=null`, exit 3, stderr vacío.
  `OSError`/inesperado capturado → handler general exit 1 con mensaje de una
  línea que puede incluir la ruta que falló; una excepción no capturada puede
  conservar traceback. Sin `.an-kla/` produce `namespace_unavailable`/exit 3
  sin crear `.an-kla/`, sin `write_lock`, sin mutar `CURRENT`.
- **`capabilities()` + schema `write-proposal-v1` (B3 + N5a):** dos
  invocaciones de `capabilities()` producen JSON canónico idéntico; el bloque
  `write_policy` enumera `record_validators` (aditivo nuevo); **no**
  `subject_view`, **no** kinds, **no** namespaces. **Igualdad byte a byte del
  `pattern` de `record.subject_ref` entre `docs/schemas/write-proposal-v1.schema.json`
  y `an_kla/schemas/write-proposal-v1.schema.json`, e igualdad de ambos con
  `SUBJECT_REF_PATTERN` (decisión 1).** El `record` sigue abierto; el patrón
  compila con `re.compile(SUBJECT_REF_PATTERN).fullmatch(...)`.

## Gates y revisión adversarial requerida

Este ADR surgió de tres rondas de spike read-only y tres retries. La ronda
adversarial independiente con contexto fresco concluyó **`proceed`** tras
verificar N1-N7 contra código, probes runtime y 401 tests; por ello se acepta
la decisión, no la implementación. El PR de implementación se divide por fases
(práctica §4), con su propia ronda adversarial pre-release
(`docs/adversarial-template.md`); `main` no etiquetable entre fases; el tag
apunta al commit que cierra el release. G-VIEW (#60) consume el contrato aquí
congelado; relaciones/endpoints requieren ADR posterior; #47 y #49 se
reevalúan tras G-VIEW. Este `proceed` no autoriza publicar código ni release.

## Referencias

- **Issues:** #59 (G-SUBJECT, este ADR lo ejecuta); #47 (churn de `id` físico,
  reencuadrado, a revaluar tras G-VIEW); #49 (enumeración: inventario físico
  pre-G-VIEW, contextual G-VIEW); #50 (frescura, tras G-VIEW/G-FRESH); #60
  (G-VIEW, depende de este ADR, no navega relaciones en v1).
- **ADRs:** ADR-0032 (congeló `subject_ref` y lo difirió aquí); ADR-0031
  (scope compuesto, `canonicality=non-authoritative`); ADR-0022 (base del
  namespace, path-as-authority descartado); ADR-0021 (patrón `verified_at`);
  ADR-0019 (partición de la guarda); ADR-0010 (`capabilities()` stateless);
  ADR-0007 (pureza de `evaluate_write`).
- `AGENTS.md`, `AN-KLA.md:133-145` (frontera de confianza);
  `docs/practicas-ingenieria.md` §1/§3/§4.
