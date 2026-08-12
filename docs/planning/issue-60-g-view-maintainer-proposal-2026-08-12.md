# Propuesta al maintainer — contrato G-VIEW para agentes de IA

- **Issue:** #60 (`G-VIEW`)
- **Base:** `820b93dcedfb51831cfb9df109ebb02acc45897e`
- **Naturaleza:** propuesta documental; no es ADR ni autorización de implementación
- **Fuentes:** ADR-0032, ADR-0033 y
  `docs/planning/issue-60-g-view-spike-2026-08-12.md`
- **Estado:** corregida tras rondas adversariales interna y externa
  (`ready-for-maintainer-decision`)

## 1. Resultado propuesto

Adoptar G-VIEW v1 como una proyección **read-only, determinista,
recomputable y non-authoritative** de una revisión fijada. Está diseñada para
que un agente de IA pueda orientarse en la memoria sin confundirla con verdad
actual, autorización ni instrucciones.

La salida conserva simultáneamente dos propiedades que no deben confundirse:

- **serialización canónica:** mismos inputs + misma revisión + misma versión de
  contrato producen los mismos bytes mediante `canonical-json/v1`;
- **contenido no autoritativo:** esos bytes contienen memoria no confiable y
  posiblemente obsoleta. Requieren revalidación externa antes de actuar.

No habrá catálogo canónico, ganador silencioso, consulta viva, reloj implícito,
cache persistente ni agrupamiento heurístico.

## 2. Propuesta ejecutiva Q1–Q12

| Pregunta | Decisión propuesta | Motivo para agentes de IA |
|---|---|---|
| Q1 — legacy sin `subject_ref` | **Sólo conteos por stream solicitado**, contando todos los estados físicos; warning estable `legacy_records_without_subject_ref`. No ids, payloads ni agrupación heurística. | Declara cobertura incompleta sin inducir al agente a inventar identidad. El inventario físico pertenece a #49, no a G-VIEW. |
| Q2 — revisión | **`--revision sha256:...` obligatorio** en CLI, core y MCP. El host puede resolver `CURRENT` antes, fuera del cálculo, pero debe pasar el SHA exacto. | El agente puede citar y reproducir exactamente qué memoria leyó; evita que “ahora” cambie a mitad del razonamiento. |
| Q3 — cache | **Sin cache persistente** en v1. Memo efímera dentro de una invocación es una optimización interna no observable. | Evita estado derivado silencioso, invalidación, locks adicionales y contaminación entre proyectos/sesiones. |
| Q4 — cursor | Cursor opaco ligado a `contract_version`, revisión, digest de **inputs de identidad** normalizados y **siguiente `subject_ref` atómico**. `limit` y `budget_bytes` son controles de página y no invalidan el cursor. Digest no autenticado + validación semántica fail-closed. | Permite ajustar presupuesto/limit al recuperarse sin cambiar el universo; reanudar nunca divide un conflicto ni salta alternativas. |
| Q5 — superficies | CLI `view context`; MCP `an_kla_view_context`; schemas `an-kla/context-view-v1` y `an-kla/view-error-v1`. Mismo core y mismo resultado semántico; sólo cambia el transporte del error. | Nombres descriptivos y predecibles para tool selection. Evita mezclar la vista derivada con `context`, que hoy administra el contrato de agente. |
| Q6 — compactación | **No resucitar revisiones archivadas.** Devolver `view_revision_not_available`. Restore/export es flujo separado, explícito y autorizado. | Una tool de lectura no debe restaurar estado ni ampliar autoridad por conveniencia. |
| Q7 — frescura | `now` debe ser input explícito e incluido en `inputs_digest`. Sin `now`, `verified_at` se muestra verbatim como `self_asserted_timestamp`, pero no se calculan edad ni `stale`. | El agente distingue “observado entonces” de “cierto ahora”; no hay reloj oculto que rompa recomputabilidad. |
| Q8 — contenido | Proyección versionada `text` por defecto (`record_text` + metadata/procedencia); `full` añade `record_raw` y exige `subject_filter` exacto; `metadata` omite contenido. Todo se presupuesta y marca `untrusted_memory_data`. | Orientación amplia minimiza exposición; inspección exacta sigue disponible mediante una segunda llamada deliberada a un subject. |
| Q9 — supersede cross-subject | Agrupar cada record por su propio `subject_ref` exacto. `supersede_link` sólo expone la relación física intra-stream; nunca fusiona subjects. | Evita que una escritura mal identificada cambie silenciosamente la identidad contextual que ve el agente. |
| Q10 — presupuesto | Subject completo es la unidad atómica. Si no cabe el envelope base: `view_envelope_exceeds_budget`; si no cabe el primer subject: `view_subject_exceeds_budget`. Ambos devuelven presupuesto mínimo; nunca página vacía que salte el subject. | Un agente nunca recibe media contradicción ni una falsa ausencia causada por truncamiento, y puede recuperarse sin adivinar. |
| Q11 — pureza | Adoptar **L2 global**: cero mutaciones del sustrato (`CURRENT`, objetos, revisiones, journals, índices, `.write.lock`). En POSIX se permite declarar `.reader-gate` como artefacto de coordinación que puede crearse/chmod/LOCK_SH; en non-fcntl no se materializa. Declararlo en ADR y `capabilities()`. | Preserva protección contra compactación sin diseñar un `read_gate/v2` prematuro. Para el agente, la garantía relevante es que leer no cambia lo recordado ni crea autoridad. |
| Q12 — error de tamaño | Error estructurado con `code`, `subject_ref|null`, `minimum_budget_bytes`, `provided_budget_bytes`, `resume_cursor`, `retryable=true` y `untrusted_memory_data=true`; sin payload. | Permite reintentar la página exacta con más budget; el cursor permanece válido porque budget/limit no definen el universo. |

## 3. Contrato operacional orientado al agente

### 3.1 Entrada cerrada y normalizada

```json
{
  "revision": "sha256:<64hex>",
  "streams": ["facts", "events", "episodes"],
  "subject_filter": null,
  "projection": "text",
  "limit": 50,
  "budget_bytes": 65536,
  "cursor": null,
  "now": null,
  "stale_after_days": null
}
```

- `streams` se deduplica y reordena según el enum canónico antes de calcular.
- Inputs de identidad ligados al cursor: revisión, streams normalizados,
  `subject_filter`, `projection`, `now`, `stale_after_days` y versión.
- Controles de página no ligados: `limit` y `budget_bytes`; pueden cambiarse al
  reintentar sin alterar el universo ni el orden.
- `cursor` transporta una posición ligada al digest de identidad; no forma
  parte de ese digest.
- `limit` y `budget_bytes` quedan fuera de `inputs_digest` y del digest del
  cursor por diseño; ligarlos rompería la recuperación Q12.
- `subject_filter` se valida con `SUBJECT_REF_PATTERN` mediante `fullmatch` y
  coincide por igualdad byte-exacta; no hay prefijo, substring ni
  normalización. Forma inválida: `view_invalid_inputs` con
  `detail=subject_filter`.
- `now` se parsea y canonicaliza con
  `parse_freshness_now`/`normalize_freshness_now` antes del digest y del
  cálculo. El orden estable de validación es: forma de `now`, forma de
  `stale_after_days`, y después la combinación. `stale_after_days` requiere
  `now`; cualquier combinación incompleta falla con `view_invalid_inputs`.
- No se consultan `CURRENT`, red, Git, APIs, reloj, environment locale ni rutas
  externas durante el core.

### 3.2 Salida y frontera de confianza

Toda salida exitosa debe llevar, al menos:

```json
{
  "schema": "an-kla/context-view-v1",
  "contract_version": "g-view/v1",
  "serialization": "canonical-json/v1",
  "canonicality": "non-authoritative",
  "untrusted_memory_data": true,
  "host_framing_unmeasured": true,
  "live_revalidation_performed": false,
  "consumer_action_required": "revalidate_against_canonical_sources_before_action",
  "revision": "sha256:<pin>",
  "inputs": {},
  "subjects_without_subject_ref": {},
  "subjects": [],
  "pagination": {},
  "warnings": []
}
```

`warnings` es un enum cerrado en v1:
`legacy_records_without_subject_ref|multiple_namespaces_observed`. Añadir otro
valor requiere cambiar `contract_version`.

Cada alternativa incluye siempre:

- `subject_ref`, `stream`, `id`, `record_sha256` y estado de vigencia;
- `state` y `state_source`, calculados con precedencia de overlays gobernados;
- `verified_at` verbatim y `self_asserted_timestamp=true` cuando exista;
- `lineage_refs` sólo como procedencia/evidencia;
- `supersede_link` sólo como relación física;
- frescura computada únicamente cuando `now` sea input explícito.

Proyección:

- `metadata`: sin `record_text` ni `record_raw`;
- `text` (default): añade `record_text`; si records byte-distintos producen el
  mismo texto, declara `content_differs_beyond_text=true`;
- `full`: añade `record_text` y `record_raw`, y sólo es válida con
  `subject_filter` exacto. Así la orientación amplia no vuelca decenas de
  payloads, secretos accidentales o instrucciones hostiles en el contexto.

Un consumidor puede extraer una alternativa fuera del envelope. Por ello cada
alternativa/history debe repetir `untrusted_memory_data=true`; la redundancia es
deliberada y reduce pérdida de contexto de seguridad en tool pipelines.

### 3.3 Conflicto y ambigüedad

- La vigencia tiene dos ejes separados:
  - `state=refuted|superseded` con `state_source=governed_overlay` cuando lo
    determina `refutations_map`/`supersedes_map`;
  - sin overlay, `status`/`nu` físico se conserva como
    `physical_status_untrusted`. `vigente|active|null|ausente` produce
    `state=active`; cualquier otro valor produce `state=inactive_untrusted`.
    Nunca produce `view_rule_ambiguous` ni puede denegar toda la vista.
- `record_raw.status/nu` jamás se presenta como refutación/supersede gobernado.
  Un record inactive-untrusted sigue visible completo en `history`, por lo que
  no se oculta silenciosamente.
- Cero o una alternativa vigente: resultado exitoso, `data_conflict=false`.
- Un subject conocido con cero alternativas vigentes permanece en `subjects[]`
  con `alternatives=[]`, `history` completo y `data_conflict=false`; no se
  borra de la vista ni se confunde con “nunca existió”.
- Dos o más alternativas vigentes: resultado exitoso,
  `data_conflict=true`, todas completas y ordenadas.
- `subject_ref` presente pero inválido en una revisión produce
  `view_invalid_subject_ref_in_revision`, fail-closed; no se agrupa ni se cuenta
  como “ausente”. Es defensa en profundidad ante corrupción o drift de versión,
  no un path esperado de commits válidos. El detalle usa `stream` y
  `record_sha256`, nunca vuelca ni ejecuta el valor ofensivo.
- Ambigüedad estructural distinta del status físico: `view_rule_ambiguous`, sin
  resultado parcial.
- Ningún ranking, score, autoridad autodeclarada o timestamp elige ganador.

La vista no dice al agente qué creer. Le entrega el conjunto observable y la
procedencia necesaria para que el host decida qué fuente canónica revalidar.

### 3.4 Paginación y presupuesto

- Unidad atómica: subject completo con todas sus alternativas e historia.
- Cursor: siguiente `subject_ref` a considerar.
- `complete=false` siempre implica `next_cursor` no nulo.
- Si el primer subject no cabe, no se emite cursor: se devuelve Q12.
- El error devuelve `resume_cursor` apuntando al mismo subject. Como budget y
  limit no están ligados, el agente puede reintentarlo sin perder continuación.
- Para medir el error se construye un `retry_witness_payload(B)` fijo: mismo
  envelope, identidad, posición y proyección; incluye exactamente el subject
  que no cupo y se detiene después de él con el `next_cursor` correspondiente.
  Para `view_envelope_exceeds_budget` el testigo es el envelope base. Así el
  contenido del testigo no crece al crecer `B`.
- `minimum_budget_bytes = min { B entero : B > provided_budget_bytes y
  len(canonical_json(retry_witness_payload(B))) <= B }`.
- No se presupone monotonía global: al cruzar una potencia de diez, las
  apariciones de `B` pueden agrandar el JSON más de un byte. La medición recorre
  bandas de igual anchura decimal. En cada banda, el tamaño sólo puede cambiar
  por el punto fijo de `budget_used_bytes`; se obtiene con
  `exact_sized_payload`, se verifica el primer candidato de la banda y se avanza
  a la siguiente si no cabe. El primer candidato verificado es el mínimo exacto.
  Una implementación alternativa sólo es válida si demuestra y prueba la misma
  minimalidad; búsqueda binaria global queda prohibida.
- Si no existe candidato hasta el máximo del host o la medición no converge,
  falla `view_budget_measurement_unavailable` y `retryable=false`.
- Cambiar revisión, streams, filtro, proyección, `now` o threshold invalida el
  cursor. Cambiar budget/limit no.

## 4. Q11 — por qué L2 es la opción correcta

La frase “read-only” debe describir el efecto semántico de la tool: leer G-VIEW
no puede cambiar lo que AN-KLA recuerda. `shared_reader_gate` sí puede crear o
normalizar `.reader-gate` en POSIX, pero ese archivo:

- no contiene afirmaciones ni autoridad;
- no aparece en la revisión fijada;
- no mueve `CURRENT` ni crea objects/journals/indexes;
- se excluye del export;
- existe para impedir que compactación archive objetos durante la lectura.

Exigir L1 añadiría una nueva primitiva de coordinación sólo para evitar el
primer `O_CREAT`, sin mejorar la seguridad epistemológica del agente y con riesgo
de degradar la exclusión frente a compactación. L3 se rechaza porque ocultaría el
efecto real. L2 lo conserva y lo declara.

Texto normativo candidato:

> G-VIEW no muta el sustrato de memoria ni adquiere locks de escritura. En
> plataformas con `fcntl`, la lectura usa un lock compartido de coordinación y
> puede materializar o normalizar `.reader-gate`; este artefacto no pertenece a
> la revisión ni al sustrato de afirmaciones. En plataformas sin `fcntl`, el
> artefacto no se materializa y la compactación no está soportada.

## 5. Q12 — error recuperable para agentes

Forma candidata:

```json
{
  "schema": "an-kla/view-error-v1",
  "ok": false,
  "code": "view_subject_exceeds_budget",
  "subject_ref": "an-kla:subject:v1:service:p-<32hex>:billing-svc",
  "minimum_budget_bytes": 81234,
  "provided_budget_bytes": 65536,
  "resume_cursor": "<cursor ligado al mismo subject>",
  "retryable": true,
  "untrusted_memory_data": true
}
```

Reglas:

- no incluir `record_raw`, `record_text`, lineage ni snippets;
- tamaños exactos y deterministas para la misma revisión/inputs;
- `minimum_budget_bytes > provided_budget_bytes`;
- si ni el envelope vacío cabe, `code=view_envelope_exceeds_budget`,
  `subject_ref=null` y el presupuesto mínimo corresponde al envelope;
- el core devuelve una unión cerrada success/error. CLI imprime los outcomes
  operacionales JSON canónicos a stdout y usa exit 3 (uso inválido sigue exit 2
  por stderr). MCP conserva `isError`, serializa el mismo objeto en
  `content[0].text` y declara `host_framing_unmeasured=true`; no se presupuestan
  bytes JSON-RPC. `structuredContent` se difiere mientras el servidor actual no
  lo exponga;
- el agente puede reintentar con `budget_bytes=minimum_budget_bytes`, sujeto al
  máximo local del host; la tool nunca eleva límites automáticamente.

Plataformas Q11:

- `fcntl + O_NOFOLLOW`: gate compartido disponible; puede materializarse;
- sin `fcntl`: lectura sin gate y compactación no soportada;
- `fcntl` sin apertura segura (`O_NOFOLLOW` ausente o archivo inseguro): error
  estable `view_reader_gate_unavailable`, sin fallback silencioso.

Mapeo externo cerrado:

| Código interno | Superficie G-VIEW |
|---|---|
| `reader_gate_platform_unsafe` | `view_reader_gate_unavailable` |
| `reader_gate_unsafe_file` | `view_reader_gate_unavailable` |
| `reader_gate_mode_reentry` | `view_reader_gate_unavailable`; defensa en profundidad, no alcanzable si el core no anida gates |

## 6. Orden de congelamiento en el ADR

1. Frontera de confianza y distinción bytes-canónicos/contenido-no-autoritativo.
2. Q11 L2 y efectos observables de coordinación.
3. Universo, legacy y agrupación exacta (Q1, Q9).
4. Revisión e inputs explícitos (Q2, Q6, Q7).
5. Contenido, conflictos y errores fail-closed (Q8, Q12).
6. Orden, cursor, atomicidad y presupuesto (Q4, Q10).
7. Superficies y capabilities (Q5).
8. Cache y recomputabilidad (Q3).
9. Matriz de tests y ronda adversarial antes de implementar.

## 7. Riesgos aceptados y límites

1. Stores legacy producirán una vista vacía o parcial hasta adoptar
   `subject_ref`; el warning evita confundirlo con “no hay memoria”.
2. `record_text` también puede contener prompt injection. Se marca localmente;
   `record_raw` exige proyección `full` + filtro exacto y nunca aparece por
   defecto en una enumeración amplia.
3. El detalle Q12 revela un `subject_ref`; ya es parte del universo solicitado,
   no autoridad ni secreto. No se revela payload.
4. Un caller puede recalcular el digest del cursor; la validación es semántica,
   no autenticación. Si se necesitara cursor no falsificable, sería contrato de
   host/servidor posterior, no G-VIEW v1 local.
5. G-VIEW no revalida fuentes canónicas. Un agente que actúe sólo por la vista
   viola el contrato del consumidor aunque los bytes sean íntegros.

## 8. Decisión solicitada

Aprobar este paquete Q1–Q12 como baseline para redactar el ADR G-VIEW-DOC, con
dos elecciones explícitas:

- Q11 = L2 global, declarada y observable;
- Q12 = error recuperable con identidad del subject y tamaño mínimo, ambos
  marcados como datos no confiables.

La aprobación de esta propuesta autoriza redactar el ADR, **no** implementar,
publicar ni integrar G-VIEW.

## 9. Ronda adversarial 1 — contexto fresco

**Revisor:** subagente independiente, read-only. **Decisión inicial:**
`fix-and-retry`. **Decisión tras correcciones:** `proceed-to-external-review`.

| Severidad | Hallazgo | Corrección aplicada |
|---|---|---|
| BLOCKER | `status/nu` físico, controlado por el record, podía ocultar una afirmación o denegar toda la vista. | §3.3 separa overlays gobernados de status físico no confiable; valores desconocidos quedan visibles como `inactive_untrusted`, nunca causan DoS. |
| BLOCKER | Q12 pedía cambiar budget, pero el cursor lo ligaba y quedaba inválido. | Q4/Q12 separan identidad de controles de página; error incluye `resume_cursor`; mínimo ligado a la misma posición. |
| HIGH | No había regla para `subject_ref` presente pero inválido en revisiones legacy/anómalas. | Código estable `view_invalid_subject_ref_in_revision`, fail-closed y sin heurística. |
| HIGH | “Mismo payload MCP” ignoraba que hoy MCP usa texto y no mide el frame. | Se congela paridad semántica core/CLI/MCP, `content[0].text`, `isError` y `host_framing_unmeasured=true`; `structuredContent` diferido. |
| MED | Q11 omitía `fcntl` presente pero `O_NOFOLLOW`/archivo seguro no disponible. | Tres ramas de plataforma y error estable `view_reader_gate_unavailable`. |
| MED | `record_raw` por defecto sobreexponía contenido hostil y secretos accidentales. | Proyecciones `metadata|text|full`; default `text`; raw sólo con filtro exacto. |

No quedan BLOCKER/HIGH/MED de esta ronda sin tratamiento. La ronda externa
atacó especialmente el estado físico legacy, la medición de
`minimum_budget_bytes` y si `text` por defecto conserva suficiente capacidad de
inspección sin convertirse en resumen autoritativo.

## 10. Ronda adversarial 2 — OpenCode con contexto fresco

**Revisor:** OpenCode TUI independiente, read-only. **Resultado recibido:**
`fix-and-retry`. **Resultado después de contraste y correcciones:**
`ready-for-maintainer-decision`.

| Severidad | Hallazgo | Decisión final |
|---|---|---|
| HIGH | El predicado de tamaño no es monótono en bordes decimales; la búsqueda binaria global podía devolver un hueco. | Aceptado. §3.4 usa payload testigo fijo, bandas decimales y verificación exacta; queda prohibida la búsqueda binaria global. |
| HIGH | “Menor B que cabe” podía ser menor que el budget fallido y contradecir `minimum > provided`. | Aceptado. La definición es ahora `min {B > provided : witness(B) cabe}`. |
| MED | `warnings` no era enum cerrado. | Aceptado: dos valores v1; cualquier adición cambia versión. |
| MED | No se definía un subject con cero alternativas vigentes. | Aceptado: permanece con `alternatives=[]` e historia completa. |
| MED | Faltaba declarar el invalid `subject_ref` como defensa ante corrupción/drift. | Aceptado y sin eco del valor ofensivo. |
| MED | Faltaba el mapeo exhaustivo de errores internos del reader gate. | Aceptado; tabla cerrada en §5. |
| LOW | Canonicalización/orden de validación temporal, exclusión deliberada de page-controls y matching exacto del filtro estaban implícitos. | Aceptados y hechos normativos en §3.1. |

No se aceptó literalmente el algoritmo sugerido por el revisor (`B <-
len(payload(B)) + 1`) porque garantiza un valor suficiente, pero puede saltar
un valor anterior válido y no demuestra el **mínimo** prometido. La solución
por bandas conserva la crítica correcta del revisor y cierra además esa
segunda grieta.

## 11. Síntesis crítica y propositiva final

G-VIEW v1 debe optimizar una propiedad: **orientar a un agente sin transformar
memoria en autoridad**. El paquete corregido lo consigue mediante cuatro
fronteras que deben permanecer juntas en el ADR:

1. revisión obligatoria y cálculo recomputable, para que cada respuesta sea
   citable;
2. contenido explícitamente no confiable, sin ganador ni ranking;
3. subject atómico con conflicto e historia visibles, incluida la ausencia de
   alternativas vigentes;
4. recuperación presupuestaria determinista que nunca salta el subject ni
   obliga al agente a adivinar el siguiente tamaño.

La tensión residual es deliberada: `projection=text` todavía puede transportar
prompt injection. Cambiar el default a `metadata` haría la orientación más
segura pero volvería opacos los conflictos; usar `full` por defecto expondría
demasiado. `text` + marcas locales de no confianza + escalamiento deliberado a
`full` con filtro exacto es el equilibrio recomendado para v1.

El siguiente artefacto debe ser **ADR G-VIEW-DOC**, no código. Debe congelar
este contrato, sus dos schemas, enum de warnings, tabla de errores, algoritmo
de medición y matriz de pruebas. Implementación posterior conserva el DAG
G-VIEW-DOC -> CORE -> CLI -> MCP -> CAP -> REL, con ronda adversarial por fase.
