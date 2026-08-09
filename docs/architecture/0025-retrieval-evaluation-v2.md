# ADR-0025: evaluación de recuperación v2

## Estado

Aceptada e implementada localmente el 2026-08-08 por autorización del roadmap
del maintainer. Las rondas pre-code e implementación terminaron en `proceed`;
este ADR no cambia el ranking productivo.

## Contexto

`evaluation.py` convierte `selected` en set, destruye el orden y mezcla calidad
de ranking con exclusión por bytes. Tampoco distingue profile pedido/real ni
degradación. El roadmap exige medir overlap antes de decidir BM25 o
summary-indexed. Según ADR-0005, esas métricas no prueban mejora decisional.

## Compatibilidad y entrada

`evaluate_retrieval()` y `an-kla/retrieval-eval-v1` quedan byte-compatibles. Se
añaden `evaluate_retrieval_v2()` y `evaluate-v2` como superficie separada.

Cada línea de queries tiene claves exactas:

```json
{"schema":"an-kla/retrieval-eval-query-v2","id":"handoff-exact-01","category":"handoff_exact","query":"siguiente paso exacto","relevant":["f-handoff-short"],"streams":["facts"]}
```

- id y query: strings no vacíos; IDs de query únicos;
- category: `synthetic|kairos_sanitized|handoff_exact`;
- relevant: lista no vacía, ordenada por bytes UTF-8, sin duplicados;
- streams: lista no vacía, sin duplicados, en orden canónico
  `facts,events,episodes`.

El archivo contiene al menos una query. La API general sólo agrega categorías
presentes; el runner de referencia exige al menos una de las tres.

Budgets y k-values son listas ordenadas, únicas, de enteros no booleanos
positivos. El corpus fija budgets `256,512,1024,4096`, k `1,3,5,10` y profiles
`scan-fallback/v1,sqlite-fts5/v1` en ese orden. Input inválido falla antes de
retrieval con códigos estables `invalid_evaluation_query|budget|k|profile` o
`duplicate_evaluation_query_id`.

## Revisión y fixture deterministas

La evaluación fija `revision = store.read_current()` exactamente una vez y la
pasa a cada retrieval. El runner de referencia no llama init/commit: construye
en un directorio temporal una cadena física versionada con identidades,
transaction IDs, checkpoints, segmentos y manifests constantes y canónicos.
Su constructor no lee reloj, UUID, entropía, cwd ni variables de entorno.

La cadena exacta es root→R1→R2→R3: R1 agrega corpus+A, R2 agrega B y marca A→B,
R3 agrega C y marca acumulativamente A→B→C. CURRENT apunta a R3. A y B quedan
inactivos; C es el único miembro seleccionable de la cadena.

Preimágenes:

- `queries_sha256 = digest_json(queries exactas ordenadas por id UTF-8)` y cada
  `query_sha256 = digest_json(query_object_exacto)`;
- `records_sha256 = digest_json([{stream,record}] en orden de append físico)`;
- `fixture_sha256 = digest_json(fixture_core)`. `fixture_core` tiene exactamente
  `schema,store_identity,checkpoints,segments,manifests,current`; los tres
  plurales son arrays de objetos lógicos completos en orden físico y cada
  segment es exactamente `{stream,sequence,records}`;
- `provenance_manifest_sha256 = digest_json(manifest_exacto)`;
- `corpus_sha256 = digest_json({"schema":"an-kla/reference-corpus-core-v1",
  "queries_sha256":...,"records_sha256":...,"fixture_sha256":...})`;
- `config_sha256 = digest_json({schema,budgets,k_values,profiles,
  index_fixture_states,ranking_budget_method})`;
- `revision` es directamente el content ID de R3, nunca un doble hash.

Dos construcciones deben producir los mismos seis digests, revisión y bytes
de todos los objetos. El runner sólo escribe dentro de temporales que creó.

## Ranking realmente independiente de budget

Para cada query/streams se calcula `ranking_budget` sobre el snapshot fijado:

```text
sum(len(record_text(record).encode("utf-8")))
```

La suma incluye todo record con ID, texto no vacío y estado
`vigente|active|null` de los streams pedidos, aunque su score sea cero. No usa
ningún budget del corpus, límite constante ni estimate. Con overheads cero es
un límite superior exacto al costo de todos los candidatos con score positivo.
Se llama retrieval con ese budget y se exige
`result["excluded_summary"].get("budget",0) == 0` y
`result["used_bytes"] <= ranking_budget`; retrieval omite contadores cero.

El orden se conserva como
`ranked_ids = [item["id"] for item in result["selected"]]`. El corpus incluye
un relevante de más de 4096 bytes para demostrar que sigue en ranking aunque
no quepa en los budgets de medición. `unretrieved_relevant` se calcula sólo
después de ese baseline y contiene relevantes ausentes por score/estado/shape,
no por bytes.

## Fórmulas por query/profile

Ranking:

- `P@k = relevantes en ranked_ids[:k] / k`; slots faltantes no son relevantes;
- `R@k = relevantes en ranked_ids[:k] / total_relevantes`;
- `first_relevant_rank`: índice 1-based o null;
- `MRR = 1/rank`, o 0/1 si no aparece;
- `unretrieved_relevant`: relevant menos ranked, en orden de relevant.

Budget:

- `selected_ids`: lista exacta de retrieval;
- `precision_at_budget = TP/len(selected)`, 0/1 si selected está vacío;
- `budget_recall = TP/total_relevantes`;
- `excluded_relevant_by_budget`: IDs del ranking baseline que son relevantes y
  faltan en selected, preservando orden de ranking;
- used_bytes/excluded_summary se copian sin reinterpretar.

Cada métrica se representa exactamente como
`{"numerator":N,"denominator":D,"value":N/D}`; denominador nunca es cero.
Los dos enteros son normativos, `value` es proyección conveniente. MRR usa
numerador 0 o 1 y denominador 1 o rank.

## Shape exacta del report

`retrieval-eval-report-v2` tiene claves exactas:

```text
schema, untrusted_memory_data, revision, corpus, configuration,
query_count, rows, aggregate, parity_summary, latency
```

`corpus` es one-of cerrado. Para evaluación general:

```text
{schema:"an-kla/external-eval-corpus-v1",revision,queries_sha256,
 records_sha256,corpus_sha256}
```

records_sha256 cubre `[{stream,record}]` de todo el snapshot proyectado en orden
`facts,events,episodes` y orden de snapshot; corpus_sha256 cubre exactamente las
otras cuatro claves. No inventa fixture ni procedencia. Para referencia:

```text
{schema:"an-kla/reference-eval-corpus-v1",fixture_version,queries_sha256,
 records_sha256,fixture_sha256,corpus_sha256,provenance_manifest_sha256}
```

`configuration` tiene schema, budgets, k_values, profiles,
index_fixture_states, ranking_budget_method y config_sha256. En evaluación
general states es `["external"]`; el runner de referencia usa
`["absent","fresh","corrupt","stale"]` en ese orden.

Rows se ordenan por query ID UTF-8 y tienen claves exactas `id,category,
query_sha256,relevant,streams,runs`. IDs repetidos entre streams pedidos fallan
`ambiguous_evaluation_record_id`. Runs se ordenan profile→state: scan se ejecuta
una vez con state `not_applicable`; FTS una vez por state configurado:

```text
requested_profile, index_fixture_state, actual_profile, degradation,
ranking, budgets, parity
```

Ranking: `ranking_budget,ranked_ids,ranked_scores,precision_at_k,recall_at_k,
first_relevant_rank,mrr,unretrieved_relevant`. Cada ranked_score es `{id,score}`
en el mismo orden. Cada vector at-k contiene `{k,metric}`.

Budget run: `budget_bytes,actual_profile,degradation,selected_ids,
selected_scores,precision_at_budget,budget_recall,
excluded_relevant_by_budget,used_bytes,excluded_summary`.
`selected_scores` usa `{id,score}` en el mismo orden.

Parity es null para scan. Para FTS contiene `ranking` y `budgets`; cada
comparación tiene:

```text
budget_bytes, exact_selected_equal, selected_id_set_equal,
common_order_equal, common_scores_equal, comparable_as_index
```

En ranking `budget_bytes=null`. Definiciones:

- exact: las dos listas completas son iguales;
- set: sets de IDs iguales (IDs son globalmente únicos en el corpus);
- common order: filtrar cada lista a la intersección y comparar las listas;
- common scores: mapas ID→score iguales para cada ID común;
- comparable as index: actual FTS y degradation none.

Fresh y toda degradación deben tener los cuatro booleanos true: el índice v1
sólo estrecha candidatos. Cualquier false falla el gate.

`aggregate.groups` se ordena por profile→state→category: primero `all` y después
sólo categorías presentes en orden canónico
`synthetic,kairos_sanitized,handoff_exact`. Cada grupo declara profile,
index_fixture_state, category, query_count, `mrr_macro`,
`precision_at_k_macro`, `recall_at_k_macro` y `budgets`. Cada macro es la media
aritmética de `metric.value` sobre las queries del grupo; at-k se agrupa por k y
budgets por budget. Cada budget agregado contiene
`precision_at_budget_macro,budget_recall_macro` y la suma entera
`excluded_relevant_by_budget_total`. No hay micro-promedios ocultos.

`parity_summary.by_state` sigue states y separa ranking/budget comparisons; cada
una publica `total,exact_matches,mismatches,actual_index,degraded`. Para Q
queries, S=4 states y B=4 budgets, el total global obligatorio es Q*S rankings
y Q*S*B budgets; fresh aporta Q*(1+B) actual-index y los otros tres states
3*Q*(1+B) degraded. Latency es null salvo opción explícita.

## Estados exactos del índice

Cada estado usa una copia temporal independiente del mismo fixture:

1. absent: sin directorio de índice → `index_unavailable`;
2. fresh: `build_index(R3)` → profile FTS/degradation none;
3. corrupt: tras build, append de un byte `0x00` al DB seleccionado; metadata
   sigue legible y el hash ya no coincide → `index_hash_mismatch`;
4. stale: build de R2; copiar ese DB sin modificar al directorio de R3 con su
   mismo nombre content-addressed y CURRENT exacto. Versión/hash pasan, metadata
   declara R2 y `_narrow_with_index` rechaza R3 → `index_unresolvable`.

Cada run distingue `index_fixture_state` (construcción del runner) de
degradation observada. Scan usa `not_applicable`. El reference runner exige
FTS5; si falta, falla estable
`fts5_required_for_reference_benchmark` y no produce reporte parcial. Tests de
portabilidad sí cubren `fts5_unavailable` mediante la API normal.
Cada query de referencia debe producir al menos un token con `TOKEN.findall` o
falla `invalid_reference_query_terms`; el gate exige que fresh obtenga profile
FTS/degradation none en ranking y budgets. Queries generales con sólo
puntuación siguen válidas, pero no participan en esa cardinalidad del fixture.

## Corpus y privacidad verificables

El corpus cubre corto/largo, distractores multitérmino, A→B→C, tres streams,
cuatro budgets/estados y las tres categorías. Cada relevant debe existir, estar
en streams y ser seleccionable, salvo query negativa con
`expected_unretrieved_reason` explícito en un manifest separado; v2 inicial no
incluye negativas.

`provenance-manifest-v1` tiene exactamente `schema,corpus_sha256,source_kind,
sanitization,forbidden_content,source_specific_denylist,human_review,scanner`.
`source_kind` es const `local-untrusted-memory-sanitized/v1`.
Declara que Kairos fue sólo material local no confiable, las queries son
paráfrasis y no se retienen quotes, paths, logs, usernames, URLs, hashes ni IDs
reales. El corpus usa IDs sintéticos. El denylist específico vive fuera del
repo y nunca se publica; el scanner sólo publica pass/fail y digest de su
configuración, no matches. El scan genérico cubre la preimagen canónica completa
de queries y records, incluidos IDs y todo campo textual anidado.
`human_review` liga status y el corpus_sha256 exacto.
Review `passed` y secret scan son gates antes de tag/publicación; la ejecución
local conserva status `pending` y no afirma que ese gate ocurrió.

Shapes anidadas: `sanitization={method:"manual-paraphrase/v1",
retains_verbatim_source:false}`; forbidden_content es la lista fija ordenada
`hashes,ids,logs,paths,quotes,urls,usernames`; denylist es
`{location:"operator-local-not-versioned",required_before_publication:true}`;
human_review es `{status:"pending|passed",corpus_sha256,reviewer}` con reviewer
null mientras pending y `maintainer` al pasar; scanner es `{status:
"pending|passed|failed",tool:"check_benchmark_corpus/v1",
configuration_sha256}`. Ningún bloque contiene matches ni material fuente.

## Latencia descriptiva

Por defecto `latency=null`. `--measure-latency` añade claves exactas
`non_contractual=true,clock=monotonic_ns,warmups,samples,min_ns,median_ns,max_ns`.
No entra a config_sha256, goldens, agregados, paridad ni decisión de ranking.

## Experimentos no productivos

Se ejecutan después del baseline y nunca se importan desde `retrieval.py` ni se
anuncian en capabilities. Comparten elegibilidad, streams, snapshot y costo de
render productivo para aplicar budgets.

`overlap/v1` reproduce `_terms(record_text(record))`, score por cantidad de
términos distintos comunes y desempate ID ascendente.

`bm25-experiment/v1` tokeniza como lista
`[m.casefold() for m in TOKEN.findall(text)]` (no `_terms`, que es set).
Documentos son todos los records elegibles; N es su cantidad, df cuenta
documentos que contienen t, query_terms son distintos, tf(t,d) cuenta
ocurrencias, dl es cantidad de tokens, avgdl=sum(dl)/N, k1=1.2 y b=0.75:

```text
idf(t) = ln(1 + (N-df(t)+0.5)/(df(t)+0.5))
score(d,q) = sum(idf(t) * tf(t,d)*(k1+1) /
                 (tf(t,d)+k1*(1-b+b*dl(d)/avgdl)) for t in query_terms)
```

Con N=0 o avgdl=0 el ranking es vacío. Sólo score finito >0; se ordena por el
float binary64 descendente y después ID UTF-8. El score se serializa con
`float.hex()` para no fingir precisión decimal; no entra a content digests.
Como `math.log` depende de libm, BM25 es no contractual entre runtimes: reporta
implementation/version/platform y sólo promete repetibilidad dentro del mismo
runtime descriptor. Se excluye de goldens byte-cross-runtime y ningún empate a
un ulp se usa como evidencia arquitectónica.

`summary-indexed-experiment/v1` puntúa overlap sobre la primera string no vacía
en prioridad `payload.indexable_text,record.indexable_text,payload.summary,
record.summary`; si falta, no es candidato. La selección presupuestada cobra
`len(record_text(record).encode("utf-8"))`, no el summary.

`retrieval-strategy-report-v1` tiene exactamente `schema,
untrusted_memory_data,revision,corpus,configuration,strategy,reproducibility,
query_count,rows,aggregate,latency`. Strategy es un descriptor one-of cerrado:
uno de los tres objetos literales siguientes; `strategy_sha256` es su digest:

```text
{schema:"an-kla/retrieval-strategy-v1",name:"overlap/v1",parameters:{
 tokenizer:"unicode-word-casefold/v1",query_terms:"distinct",
 score:"distinct-term-overlap",score_encoding:"integer",
 tie_break:"id-utf8-ascending"}}
{schema:"an-kla/retrieval-strategy-v1",name:"bm25-experiment/v1",parameters:{
 tokenizer:"unicode-word-casefold-list/v1",query_terms:"distinct",
 document_scope:"eligible-requested-streams",k1:1.2,b:0.75,
 formula:"okapi-bm25/v1",score_encoding:"float-hex",
 tie_break:"score-desc-id-utf8-ascending"}}
{schema:"an-kla/retrieval-strategy-v1",name:"summary-indexed-experiment/v1",
 parameters:{tokenizer:"unicode-word-casefold/v1",query_terms:"distinct",
 fields:["payload.indexable_text","record.indexable_text","payload.summary",
 "record.summary"],score:"distinct-term-overlap",score_encoding:"integer",
 selection_cost:"record-text-utf8-bytes",
 tie_break:"id-utf8-ascending"}}
```

Configuration tiene exactamente `schema,budgets,k_values,
ranking_budget_method,strategy_sha256,config_sha256`, y config_sha256 cubre las
otras cinco claves. Reproducibility tiene exactamente
`cross_runtime_byte_stable,runtime_descriptor`; descriptor es null para
overlap/summary y `{implementation,version,platform,math_backend:"system-libm"}`
para BM25.
El campo corpus reutiliza el mismo one-of external/reference del report v2.

Cada row tiene exactamente `id,category,query_sha256,relevant,streams,ranking,
budgets`; ranking y budget entries son discriminadas por strategy: `{id,score}`
entero para overlap/summary y `{id,score_hex}` para BM25. `aggregate.groups` se
ordena por `all` y sólo categorías presentes en orden canónico; tiene
query_count/mrr/P@k/R@k/budgets con las mismas fórmulas, sin profile, state,
degradation ni parity. Comparar estrategias no autoriza cambiar producto; una
decisión futura requiere ADR nuevo con reportes versionados.

El runner completo emite `an-kla/reference-benchmark-v1` con claves exactas
`schema,untrusted_memory_data,retrieval_report,strategy_reports,conclusion`.
Strategy reports se ordenan overlap,BM25,summary. Conclusion es exactamente
`{ranking_change_authorized:false,reason:"metrics_require_future_adr"}`.

Queries y manifest viven como package data bajo
`an_kla/resources/retrieval-benchmark-v2/`; no dependen de `tests/` ni del
checkout fuente. El gate construye un wheel sin red, lo instala en un venv
temporal y ejecuta el entrypoint `an-kla benchmark-reference` desde esa
instalación limpia.

## Pruebas y consecuencias

Schemas query/report son cerrados y se empaquetan. Tests cubren vectores
manuales, relevante >4096, fixture doble idéntico, paridad por estado, recipes
de índice, corpus/privacidad, shape exacta, v1 intacto y latency fuera de
fingerprints. Dos runtimes, size gate y ronda fresca cierran la fase.

La evaluación v2 es read-only sobre stores del operador. Sólo el runner crea y
altera caches dentro de temporales propios. Métricas siguen siendo datos, no
verdad, autoridad, procedencia ni prueba de mejora decisional.
