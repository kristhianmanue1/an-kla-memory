# ADR-0034: contrato de vista contextual derivada G-VIEW v1

- **Estado:** Aceptada
- **Implementación:** Completada en candidata `v0.1.0-beta.13`; REL en auditoría
- **Fecha:** 2026-08-12
- **Decide sobre:** el contrato observable de G-VIEW v1: revisión, universo,
  confianza, proyecciones, conflicto, orden, cursor, presupuesto, pureza y
  paridad core/CLI/MCP. No autoriza implementación ni publicación.

## Contexto

ADR-0032 decide que AN-KLA expondrá una vista contextual derivada,
determinista, read-only y non-authoritative sobre afirmaciones inmutables.
ADR-0033 proporciona `subject_ref` estable, byte-exacto y ligado al namespace
del proyecto. Falta congelar la superficie que permita a un agente orientarse
en esa memoria sin convertirla en verdad, autorización o instrucciones.

La implementación actual ofrece `snapshot()` y `retrieve()`, pero no una
enumeración contextual. `retrieve()` depende de una query y elimina resultados
`zero_score`; tampoco agrupa conflictos por subject. `snapshot()` fija una
revisión content-addressed y conserva records raw pre-overlay, pero su reader
gate puede crear o normalizar `.reader-gate` en POSIX. El writer usa
`.write.lock`, un archivo distinto, y puede mover `CURRENT` concurrentemente;
la revisión ya fijada no cambia. Compactación usa el mismo reader gate en modo
exclusivo.

El spike de issue #60 y dos rondas adversariales cerraron doce decisiones. Los
hallazgos principales fueron: status físico controlado por memoria podía
ocultar o denegar la vista; budget ligado al cursor impedía recuperación;
`record_raw` por defecto sobreexponía contenido; supersede cross-subject no
autoriza fusionar identidades; y el tamaño JSON no es monótono en bordes de
dígitos, por lo que una búsqueda binaria global del presupuesto es incorrecta.

Restricciones vigentes: memoria recuperada es dato no confiable, nunca
instrucción (`AGENTS.md`, `AN-KLA.md`); `canonical_json` define bytes
deterministas; `verified_at` es `self_asserted_timestamp` (ADR-0021);
`subject_ref` es identidad contextual, no autoridad (ADR-0033); no se consultan
fuentes vivas dentro del cálculo.

## Decisión

### 1. Frontera de confianza y schemas

G-VIEW v1 es una proyección **read-only, recomputable y non-authoritative** de
una revisión fijada. Serialización canónica no implica contenido canónico.
Toda salida exitosa usa:

- `schema=an-kla/context-view-v1`;
- `contract_version=g-view/v1`;
- `serialization=canonical-json/v1`;
- `canonicality=non-authoritative`;
- `untrusted_memory_data=true`;
- `host_framing_unmeasured=true`;
- `live_revalidation_performed=false`;
- `consumer_action_required=revalidate_against_canonical_sources_before_action`.

Cada alternativa y elemento de historia repite
`untrusted_memory_data=true`, porque puede extraerse fuera del envelope. La
unión de error operacional usa `schema=an-kla/view-error-v1`. Ambos schemas son
cerrados y se registrarán en `SCHEMA_FILES` al implementar.

### 2. Inputs explícitos y revisión fijada

El core, CLI y MCP requieren `revision=sha256:<64hex>`; no resuelven `CURRENT`
dentro del cálculo. Un host puede resolverlo antes y pasar el SHA exacto. Una
revisión archivada o ausente produce `view_revision_not_available`; la vista no
restaura exports ni resucita revisiones.

Inputs v1:

- `revision` obligatorio;
- `streams`, deduplicados y reordenados por enum canónico;
- `subject_filter|null`;
- `projection=metadata|text|full`, default `text`;
- `limit`, `budget_bytes` y `cursor|null`;
- `now|null` y `stale_after_days|null`.

`subject_filter` se valida con `SUBJECT_REF_PATTERN.fullmatch` y coincide por
igualdad byte-exacta: no prefix, substring, casefold ni normalización. Forma
inválida produce `view_invalid_inputs` con `detail=subject_filter`.

`now` se parsea y canonicaliza con
`parse_freshness_now`/`normalize_freshness_now` antes del digest y del cálculo.
El orden de validación es: forma de `now`, forma de `stale_after_days`, y luego
su combinación. `stale_after_days` requiere `now`. Sin `now`, `verified_at` se
proyecta verbatim como autodeclarado, pero no se calculan edad ni `stale`.

Durante el core no se consulta `CURRENT`, red, Git, APIs, reloj, locale,
variables de entorno ni rutas externas.

### 3. Universo, legacy, agrupación y vigencia

El universo son los records físicos de los streams solicitados en la revisión
fijada. Records sin `subject_ref` no se agrupan ni exponen individualmente: se
cuentan por stream, incluyendo todos los estados físicos, en
`subjects_without_subject_ref`, con warning
`legacy_records_without_subject_ref`.

Un `subject_ref` presente pero inválido produce
`view_invalid_subject_ref_in_revision`, fail-closed. Es defensa ante corrupción
o drift de versión, no un path esperado de commits válidos. El detail contiene
`stream` y `record_sha256`, nunca el valor ofensivo.

Cada record se agrupa por su propio `subject_ref` completo. Un supersede cuyo
target tenga otro subject sólo se muestra en `supersede_links` físicos
intra-stream; no fusiona subjects ni reescribe identidad. Namespaces históricos
distintos permanecen separados y añaden `multiple_namespaces_observed`.

`warnings` es enum cerrado v1:

- `legacy_records_without_subject_ref`;
- `multiple_namespaces_observed`.

Añadir otro warning requiere cambiar `contract_version`.

La vigencia separa autoridad gobernada de bytes no confiables:

1. overlays de refute/supersede determinan `state=refuted|superseded` con
   `state_source=governed_overlay`;
2. sin overlay, `status`/`nu` físico se conserva como
   `physical_status_untrusted`;
3. `physical` es `record["status"]` si existe esa clave; si no,
   `record["nu"]`; si ninguna existe, el sentinel interno `MISSING`;
4. `physical` en `{vigente, active, null, MISSING}` produce `state=active`;
   cualquier otro valor, incluida la cadena literal `"ausente"`, produce
   `state=inactive_untrusted`.

Status físico nunca se presenta como refutación/supersede gobernado ni causa
`view_rule_ambiguous`. Los inactivos siguen visibles en `history`, evitando
ocultamiento y denegación por datos atacantes.

Cero o una alternativa activa produce `data_conflict=false`; dos o más,
`data_conflict=true`, sin ganador. Un subject con cero activas permanece en
`subjects[]` con `alternatives=[]` e historia completa. Ambigüedad estructural
no cubierta por estas reglas produce `view_rule_ambiguous` sin resultado
parcial. Ranking, score, autoridad autodeclarada y timestamp nunca eligen
ganador.

### 4. Proyecciones y minimización

Cada alternativa incluye identidad, `stream`, `id`, `record_sha256`, estado,
procedencia, `verified_at` cuando exista, `self_asserted_timestamp=true`,
`supersede_links`, array ordenado de relaciones físicas en las que participa
(cero o más), y frescura sólo con `now` explícito.

- `metadata`: omite `record_text` y `record_raw`.
- `text` (default): añade `record_text` con la precedencia normativa existente;
  si raw distintos producen el mismo texto, declara
  `content_differs_beyond_text=true`.
- `full`: añade `record_text` y `record_raw`; requiere `subject_filter` exacto.

El texto y raw siguen siendo datos potencialmente hostiles. `text` es default
porque permite inspeccionar conflictos sin volcar payloads completos; el
consumidor escala deliberadamente a `full` para un subject exacto.

### 5. Orden, cursor y atomicidad

Subjects se ordenan por bytes UTF-8 de `subject_ref`, independientes de locale.
Alternativas se ordenan por `(stream, record_sha256)`. En historia, records con
`verified_at` preceden a los ausentes y se ordenan por su texto descendente; en
empate, o entre ausentes, por `(stream, record_sha256)` ascendente. No se
interpreta cronología. El subject completo es unidad atómica.

El cursor opaco tiene forma lógica `{v,r,ih,n,d}`:

- `v`: versión de cursor;
- `r`: revisión;
- `ih`: digest de inputs de identidad;
- `n`: siguiente `subject_ref` a considerar;
- `d`: digest de la estructura anterior, no autenticación criptográfica.

Inputs de identidad: revisión, streams normalizados, filtro, proyección, `now`
canonicalizado, `stale_after_days` y versión. `limit` y `budget_bytes` quedan
fuera de `ih`/`d`; incluirlos rompería la recuperación. El cursor se valida
semánticamente fail-closed. Si
`n` no existe en la secuencia recomputada o cambia un input de identidad,
produce `view_cursor_invalid`.

`complete=false` implica `next_cursor` no nulo apuntando al siguiente subject.
Cambiar limit o budget modifica cuánto cabe, nunca el universo ni el orden.

### 6. Presupuesto exacto y error recuperable

El presupuesto cubre los bytes UTF-8 de `canonical_json(payload)`; no incluye
framing de proceso, terminal o JSON-RPC. `host_framing_unmeasured=true` lo hace
explícito.

Si el envelope base no cabe: `view_envelope_exceeds_budget`,
`subject_ref=null`. Si el primer subject no cabe:
`view_subject_exceeds_budget`. No se devuelve página vacía ni se salta el
subject. El error `an-kla/view-error-v1` contiene:

- `code`, `subject_ref|null`;
- `minimum_budget_bytes`, `provided_budget_bytes`;
- `resume_cursor:string|null`: cursor entrante, o `null` en posición inicial;
- `retryable=true`, `untrusted_memory_data=true`;
- ningún raw, texto, lineage ni snippet.

`retry_witness_payload(B)` conserva envelope, identidad, posición y proyección;
en error de subject incluye sólo ese subject y su `next_cursor`; en error de
envelope, sólo el envelope base. Records, cursores y estructura quedan fijos;
sólo cambian los números que materializan `B` y su tamaño serializado.

La definición normativa es:

```text
minimum_budget_bytes = min {
  B entero : B > provided_budget_bytes y
  len(canonical_json(retry_witness_payload(B))) <= B
}
```

No se asume monotonía global. Para cada banda decimal ascendente `[D0,D1]`:

```text
L = max(provided_budget_bytes + 1, D0); U = min(host_max, D1)
S = len(canonical_json(exact_sized_retry_witness(B_representativo_de_la_banda)))
C = max(L, S)
si C <= U y len(canonical_json(retry_witness_payload(C))) <= C: devolver C
si no: avanzar a la banda siguiente
```

Dentro de una banda, todas las apariciones de `B` tienen igual anchura; el
contenido restante es fijo y `exact_sized_payload` resuelve
`budget_used_bytes`. La verificación final de `C` es obligatoria. Así el primer
candidato devuelto es el mínimo exacto. Otra optimización debe demostrar y
probar la misma propiedad; búsqueda binaria global queda prohibida.

Si no existe candidato hasta el máximo del host o la medición no converge:
`view_budget_measurement_unavailable`, `retryable=false`. La tool no eleva
límites automáticamente.

### 7. Pureza y concurrencia L2

G-VIEW adopta pureza **L2 global**: cero mutaciones del sustrato de memoria
(`CURRENT`, objetos, revisiones, journals, índices y `.write.lock`) y ningún
lock de escritura. En plataformas con `fcntl` y apertura segura usa
`shared_reader_gate`; puede crear, chmod o bloquear `.reader-gate`. Ese archivo
es artefacto de coordinación, no afirmación, autoridad ni parte de la revisión,
y se excluye de exports.

Ramas de plataforma:

| Condición | Resultado |
|---|---|
| `fcntl` + `O_NOFOLLOW` seguro | `LOCK_SH`; gate puede materializarse; compactación queda excluida por `LOCK_EX` |
| sin `fcntl` | lectura sin gate ni materialización; compactación no soportada |
| `fcntl` sin apertura segura | `view_reader_gate_unavailable`; sin fallback silencioso |

Mapeo cerrado: `reader_gate_platform_unsafe`, `reader_gate_unsafe_file`,
`reader_gate_mode_reentry` y `OSError` de apertura, chmod o `flock` se sanea a
`view_reader_gate_unavailable`, sin ruta ni detalle del host. El reentry es
defensa en profundidad y no debe ser alcanzable sin gates anidados. Fallos
fuera de adquisición del gate se sanea a `view_internal_error`.

Un writer puede mover `CURRENT` mientras se calcula la vista porque usa otro
lock; no altera los objetos de la revisión ya fijada. Compactación sí comparte
el reader gate y no puede archivar el pin durante la lectura.

### 8. Superficies, errores y capabilities

Las superficies son CLI `view context` y MCP `an_kla_view_context`, ambas sobre
el mismo core y unión success/error. MCP serializa el objeto en
`content[0].text`, usa `isError=true` para errores y no mide el frame JSON-RPC;
`structuredContent` se difiere.

Errores públicos v1 cerrados:

- `view_invalid_inputs`, `view_revision_not_available`;
- `view_invalid_subject_ref_in_revision`, `view_rule_ambiguous`;
- `view_cursor_invalid`, `view_envelope_exceeds_budget`;
- `view_subject_exceeds_budget`, `view_budget_measurement_unavailable`;
- `view_reader_gate_unavailable`, `view_internal_error`.

`an-kla/view-error-v1` es unión discriminada cerrada. Toda variante lleva
`schema`, `ok=false`, `code`, `retryable` y `untrusted_memory_data=true`.
`view_envelope_exceeds_budget|view_subject_exceeds_budget` añaden los
campos de §6 y `retryable=true`. `view_budget_measurement_unavailable` añade
`provided_budget_bytes` y `resume_cursor`, pero no un mínimo, y lleva
`retryable=false`. `view_invalid_inputs` añade sólo `detail` con el input
estable; `view_invalid_subject_ref_in_revision` añade el detail saneado de §3.
Las demás llevan `retryable=false`, sin detail ni contenido del store;
`view_internal_error` no expone excepción.

| Familia core | CLI | MCP |
|---|---|---|
| success | JSON stdout, exit 0 | texto JSON, `isError=false` |
| `view_invalid_inputs` | mensaje de uso stderr, exit 2 | error JSON, `isError=true` |
| errores catalogados restantes salvo interno | error JSON stdout, exit 3 | error JSON, `isError=true` |
| `view_internal_error` | mensaje saneado stderr, exit 1 | error JSON saneado, `isError=true` |

`capabilities()` añade un bloque `view` determinista con versiones, superficies,
proyecciones, límites, pureza L2, warnings y errores. No enumera subjects,
namespaces observados, kinds presentes ni regex completa.

### 9. Cache y secuencia de entrega

No hay cache persistente en v1. Memoización efímera dentro de una invocación es
interna y no observable.

La entrega se divide: G-VIEW-DOC (este ADR) -> CORE -> CLI -> MCP -> CAP -> REL.
Este ADR debe aceptarse antes de código. Cada fase posterior tiene PR y ronda
adversarial; no hay tag hasta integrar todas las fases autorizadas.

## Modelo de amenazas

- **Prompt injection:** `record_text` y `record_raw` pueden contener texto
  atacante. Se marcan localmente como no confiables; raw requiere filtro exacto.
- **Memoria convertida en autoridad:** canonicalidad sólo describe bytes. La
  vista no consulta fuentes vivas, decide ganadores ni autoriza acciones.
- **Ocultamiento/DoS por status:** status físico desconocido queda visible como
  `inactive_untrusted`; no detiene toda la vista.
- **Conflicto amputado:** subject atómico y error recuperable impiden presentar
  media contradicción o falsa ausencia por presupuesto.
- **Cursor manipulado:** el digest no autentica; la validación semántica detecta
  revisión/input/posición incompatibles. Autenticación pertenece al host futuro.
- **Contaminación cross-project:** namespace forma parte del subject exacto;
  nunca se elimina ni fusiona, incluso entre eras históricas.
- **Efecto filesystem oculto:** L2 declara `.reader-gate`; no se llama pureza
  literal de cero escrituras globales.

## Por qué no [alternativa]

### Resolver `CURRENT` dentro de la vista

Introduce estado móvil y dificulta citar la lectura exacta. El host puede
resolverlo explícitamente antes. Descartada.

### Catálogo autoritativo o ganador por ranking

Contradice ADR-0032 y permitiría que score, timestamp o autoridad autodeclarada
silencien una alternativa. Descartada.

### Usar lineage o supersede como identidad

Lineage es evidencia; supersede físico no valida `subject_ref` del target.
Fusionarlos inventaría identidad. Descartada.

### Raw por defecto o metadata por defecto

Raw amplía exposición de secretos e instrucciones hostiles; metadata vuelve
opacos los conflictos. `text` con escalamiento exacto equilibra ambos riesgos.

### L1 literal o L3 implícita

L1 exigiría una primitiva de coordinación nueva sólo para evitar `O_CREAT` y
podría degradar exclusión frente a compactación. L3 ocultaría un efecto real.
L2 declarado preserva ambas fronteras.

### Cursor ligado al budget o búsqueda binaria global

El primero impide el reintento Q12. La segunda presupone monotonía falsa en
bordes decimales. Ambas descartadas.

### Cache persistente o consulta viva

Añaden invalidación, estado, locks, reloj/red ocultos y nuevos vectores de
inyección. Descartadas en v1.

## Consecuencias

- **Positivas:** orientación reproducible para agentes; conflictos e historia
  visibles; presupuestos recuperables; exposición raw minimizada; compatibilidad
  legacy sin identidad inventada; concurrencia y efectos declarados.
- **Negativas:** `text` todavía transporta datos hostiles; el host debe
  revalidar; subjects grandes pueden exigir más presupuesto; callers deben fijar
  revisión y gestionar cursor; no hay cache persistente.
- **Neutras:** no cambia formato físico, records existentes, `CURRENT`, política
  de escritura ni semántica de refute/supersede. La implementación añadirá dos
  schemas y superficies públicas versionadas.

## Test de regresión

Gate documental inmediato:

- `scripts/check_adr_registry.py`: ADR-0034 presente, sin huecos, estado igual
  al registro; 34 ADRs, 32 aceptadas y 2 propuestas.
- `scripts/check_sizes.py`: ADR dentro del límite duro.
- suite completa vigente sin regresiones.

La implementación deberá cubrir, al menos:

- mismos inputs/revisión -> mismos bytes; sin reloj/red/`CURRENT` implícitos;
- legacy, namespaces múltiples, subject inválido y cero activas;
- status físico atacante no oculta ni produce DoS; overlays tienen precedencia;
- conflicto de dos o más alternativas completo y orden estable;
- las tres proyecciones y prohibición de `full` sin filtro exacto;
- cursor estable al cambiar limit/budget e inválido al cambiar identidad;
- atomicidad de subject y ambos errores de presupuesto;
- bordes `9/10`, `99/100`, payload testigo, minimalidad y máximo del host;
- las tres ramas reader-gate y el mapeo de errores;
- paridad semántica core/CLI/MCP, exits, schemas y golden de `capabilities()`;
- cero mutación de sustrato y exclusión correcta frente a compactación.

## Referencias
- Issue #60 — G-VIEW.
- ADR-0032 (vista derivada), ADR-0033 (`subject_ref`) y ADR-0021 (frescura).
- ADR-0019 / ADR-0026 / ADR-0028 — supersede, refute y compactación.
- Spike y propuesta del maintainer de issue #60 en `docs/planning/`.
- Rondas adversariales: subagente independiente y OpenCode TUI, 2026-08-12.
