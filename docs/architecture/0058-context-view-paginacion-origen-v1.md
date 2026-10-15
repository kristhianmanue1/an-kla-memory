# ADR-0058: Paginación de context_view por sujeto en el origen

- **Estado:** Aceptada (implementada)
- **Implementación:** Implementada (`context_view::_derive_universe` + proyección perezosa memoizada)
- **Fecha:** 2026-10-15
- **Decide sobre:** eliminar la proyección pesada del universo completo en `context_view`, proyectando perezosamente sólo la ventana servida, sin cambiar el contrato observable.

## Contexto

`_derive()` (`an_kla/context_view.py`) proyecta **todos** los registros de
los streams pedidos antes de que el bucle de presupuesto seleccione
`limit` sujetos: por cada registro calcula `digest_json(raw)`
(canonicalización completa), `record_text()` en proyecciones `text`/`full`,
`deepcopy` de lineage/links/raw, y además `_governed_states()` repite un
segundo `digest_json(raw)` por registro para detectar refutados. La
paginación por cursor sobre sujetos ya existe (el cursor codifica
`next_subject`), pero la derivación del universo completo ocurre en cada
llamada. Medido en la batería P0 de #149 (régimen de sujeto único,
20.000 registros, `limit=50`): **0,442 s en el camino feliz y 3,2–5,1 s
cuando la página cae en `view_subject_exceeds_budget`** — el coste crece
con el universo, no con la página, y el régimen patológico es justamente
el camino de error de presupuesto, que la memoización de la pasada 2
cura.

Restricciones: el payload `an-kla/context-view-v1` es un contrato público
(CLI `view context` y MCP `an_kla_view_context`); `total_subjects`,
`truncated_subjects`, los warnings `legacy_records_without_subject_ref` y
`multiple_namespaces_observed`, el error fail-closed
`view_invalid_subject_ref_in_revision` para cualquier registro inválido de
la revisión, y la semántica del cursor (índice en la lista ordenada de
sujetos) son observables que los tests fijan.

## Decisión

`context_view` trabaja en **dos pasadas con proyección perezosa**:

1. **Pasada ligera** (por cada registro de los streams pedidos): extraer el
   string `subject_ref`, contar ausencias por stream, recolectar
   namespaces (warning), validar `parse_subject_ref` de **toda** la
   revisión (preserva el fail-closed fuera de ventana) y agrupar
   referencias `(stream, registro)` por sujeto — sin canonicalizar, sin
   proyectar, sin copiar.
2. La lista ordenada de sujetos produce `total_subjects`, `truncated` y la
   resolución del cursor exactamente como hoy.
3. **Pasada pesada perezosa**: los sujetos se proyectan (con su
   governed-state, enlaces de supersede y chequeo de refutación reutilizando
   el `record_sha256` ya calculado) uno a uno, sólo conforme el bucle de
   presupuesto los sirve.

Detalles de paridad que el spike fijó (2026-10-15):

- **Memoización por sujeto**: cada sujeto se proyecta exactamente una vez y
  la proyección se reutiliza en las reconstrucciones de `_minimum_budget` y
  del payload final; sin memo, `record_text`/`digest_json` se recomputarían
  justo en los caminos de error de presupuesto.
- **Precedencia refutación > supersede**: hoy `superseded` se asienta y
  `refuted` sobrescribe; el chequeo perezoso replica ese orden
  (`refuted` si el digest está en el mapa; si no, `superseded` por id).
- **Fuente cruda**: la pasada ligera y la proyección leen `raw_records`
  (pre-overlay), no `records`.
- **Orden de la pasada ligera**: missing cuenta sobre el universo completo;
  la validación `parse_subject_ref` falla con el **primer** ref inválido en
  orden `(streams normalizados, posición)` y antecede a los errores de
  cursor y presupuesto; namespaces y agrupamiento sólo sobre el universo
  filtrado.
- **Construcciones previas al bucle**: `_supersede_links` y el conjunto de
  digests refutados se levantan al inicio de la pasada ligera (como hoy);
  un manifiesto malformado sigue ganando sobre
  `view_invalid_subject_ref_in_revision`.
- **Un digest por registro proyectado**: `digest_json` se computa una sola
  vez por registro y alimenta tanto `record_sha256` como el chequeo de
  refutación; los errores de proyección en la ventana
  (`KeyError`/`TypeError`/`ValueError`) conservan la clasificación
  `view_rule_ambiguous`.

El resultado observable es byte a byte el mismo: mismo schema, mismos
campos, mismos warnings y errores, misma semántica de cursor y paginación.

## Por qué no [alternativa]

- **Índice persistido de sujetos (O(página) estricto)**: cambia el formato
  persistente, exige migración y un ADR de formato; tras quitar la
  proyección pesada su beneficio marginal es pequeño. Queda como ruta del
  sustrato P3 si la batería v2 vuelve a encontrar el cuello.
- **Caché del universo derivado entre llamadas de la misma revisión**:
  introduce estado mutable en el camino de lectura y repite el tradeoff de
  tamper-evidence que ADR-0056 dejó abierto y ADR-0057 evitó.
- **Paginar registros en vez de sujetos**: rompe G-VIEW; la unidad de
  página es el sujeto con sus `alternatives`/`history`.
- **Validar `subject_ref` sólo en la ventana servida**: abarataría la
  pasada ligera, pero cambiaría el error observable para revisiones con
  subject_refs inválidos fuera de la ventana — regresión silenciosa del
  contrato fail-closed.

## Consecuencias

- Positivas: el coste por página pasa de "proyección pesada del universo"
  a "pasada ligera O(N) sin canonicalización ni texto + proyección pesada
  sólo de la ventana"; `total_subjects` y warnings siguen siendo exactos;
  cero cambio de contrato ni de formato persistente. Medido a 20.000
  registros con `limit=50` (misma metodología de la batería P0): camino
  feliz multi-sujeto **0,442 → 0,114 s (~3,9×)**; régimen de sujeto único
  gigante **4,080 → 3,028 s (~1,35×)** — la memoización elimina la
  re-proyección en `_minimum_budget`, y el coste residual es la única
  proyección del sujeto gigante, inherente a medir su payload para
  clasificar el error.
- Negativas: persiste una pasada O(N) de lectura de referencias — la
  mejora es de constante, no de complejidad asintótica; el criterio estricto
  "tiempo independiente del N" queda reservado al sustrato P3. En stores con
  refutaciones, `snapshot()` sigue pagando pases de digest propios
  (`validate_lifecycle` y overlay refutado), lo que acota la mejora
  alcanzable en ese perfil — coste del snapshot, no de `_derive`.
  **Estrechamiento declarado**: un registro crudo no serializable (p. ej.
  un float NaN inyectado vía `Snapshot` directo) fuera de la ventana
  servida deja de convertir la llamada completa en `view_rule_ambiguous` y
  pasa a ignorarse; en la ventana el código se conserva. Ese fallo global
  es inalcanzable vía `MemoryStore` (segmentos canónicos por construcción);
  preservarlo exigiría sondear la serialización de cada registro en la
  pasada ligera — re-canonicalizar el universo, justo lo que esta ADR
  elimina.
- Neutras: la memoria de la pasada ligera (strings de sujetos) ya se pagaba
  hoy; la pasada pesada usa menos.

## Test de regresión

- Suite existente `tests/test_context_view.py` y
  `tests/test_context_view_cli.py` **sin cambios** (paridad del contrato).
  El canario `test_reader_gate_is_held_during_projection` cuenta llamadas a
  `record_text` y caza la doble proyección sin memo.
- Matriz de paridad antes/después: tres proyecciones × con/sin
  `subject_filter` × con/sin cursor (incluidos cursor huérfano →
  `view_cursor_invalid` y cursor en el último sujeto exacto →
  `complete=True`), payload idéntico byte a byte.
- Casos de orden semántico: primer ref inválido fuera de ventana →
  `view_invalid_subject_ref_in_revision` con su digest; registro refutado y
  superseado simultáneamente (donde exista) → `refuted`; warning de
  namespaces con universo filtrado, no página.
- Casos de la ronda adversarial (2026-10-15): registro con NaN fuera de
  ventana → éxito y el mismo en ventana → `view_rule_ambiguous` (fija el
  estrechamiento declarado); sonda de conteo de `record_text` en el camino
  de reanudación tras `view_subject_exceeds_budget` (exactamente 1 llamada
  por registro proyectado) y en `view_envelope_exceeds_budget` (0); dos
  registros de contenido idéntico con ids distintos y una entrada en
  `refutations_map` → ambos `refuted`; ambos warnings simultáneos en orden
  (legacy, namespaces); `subject_filter` que excluye un registro con ref
  inválido → sigue fallando cerrado.
- Nuevo test de escala ligera (universo sintético en memoria, `limit=50`)
  con umbral documentado, para detectar regresiones de constante.

## Referencias

Issue #149 (propuesta P2b, sub-issue #165); ADR-0057 (lectura de segmentos
sin re-canonicalización — optimiza el coste de `snapshot()` que esta ADR
tiene por dado); ADR-0056 (caché rechazada/condicionada); batería P0
(`benchmarks/scale/results/20261014-182904`); spike pre-implementación y
ronda adversarial 2026-10-15
(`planning/adr0058-adversarial-2026-10-15.md`, veredicto fix-and-retry
absorbido); aceptada e implementada por orden del maintainer (2026-10-15:
"ADELANTE CON PENDIENTES"), mismo patrón que P2c/P2d.
