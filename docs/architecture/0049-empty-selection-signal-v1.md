# ADR-0049: señal de primera clase para selección vacía por solapamiento léxico cero — `retrieval-result-v3` / `mcp-retrieve-v3` dispersos

- **Estado:** Aceptada (implementación en curso — orden del maintainer,
  2026-09-11: "adelante con recomendaciones").
  Ronda adversarial pre-code ejecutada (2 atacantes de contexto fresco,
  2026-09-11; veredicto `fix-and-retry`, hallazgos F-PC1-1..7 y F-PC2-1..9
  absorbidos en este documento).
- **Fecha:** 2026-09-11
- **Decide sobre:** cómo expone AN-KLA el caso "recuperación sin resultados
  por cero solapamiento léxico" (#133) y la paridad del diagnóstico
  `zero_score` entre scan e índice (#118/R3). No decide cambios de ranking,
  scoring ni matching (ADR-0025 sigue gobernando: BM25 léxico, sin
  fallback semántico).

## Contexto

Un agente de contexto fresco no conoce el vocabulario del store; sus
primeras queries pueden no solapar léxicamente con ningún registro. El
retrieval devuelve `selected: []` con `excluded_summary.zero_score` contando
todos los activos: correcto por spec (ADR-0029), degenerado en el caso de
uso central — el agente queda sin memoria justo al retomar trabajo
(#133, repro real sobre `0.1.0b26`; evidencia de campo externa DSH en
`docs/planning/external-validation-dsh-beta26-2026-09-10.md`).

Hoy ese estado es **derivable** (`selected == []` ∧
`excluded_summary.zero_score ≥ 1` ∧ `"budget" absent`), pero nada lo
declara: el consumidor debe inferir la causa de contadores crudos, y el
diagnóstico es además **disparejo entre perfiles** — #118/R3: el scan
cuenta `zero_score` (`retrieval.py:213-217`) pero el camino índice estrecha
`ranked` con fts5 antes del loop (`retrieval.py:206`) y los zero-score
desaparecen sin contabilidad.

## Opción cero — descartada por escrito (F-PC2-6)

Documentar la derivación (guías + `--help`) sin tocar contrato: costo cero,
pero deja la señal dependiente de inferencia del consumidor — exactamente
la fricción que #133 reporta con evidencia de campo — y no cierra la
paridad R3, que es un defecto de diagnóstico independiente. Se adopta la
derivación como **documentación complementaria**, no como sustituto.

## Decisión

### 1. Paridad R3 (código, sin contrato)

El filtrado de `score == 0` con su contabilidad (`excluded["zero_score"]`,
`excluded_detail["zero_score"]`) se mueve a una pre-pasa **post-sort**
(`ranked.sort(...)` → filtro → bloque de índice), de modo que scan e índice
cuenten desde el mismo conjunto. Restricciones vinculantes (F-PC1-1/2):

- **Conteo único**: el loop principal pierde el `continue` residual —
  ninguna ruta vuelve a contar (evita doble conteo en perfiles degradados
  sin narrowing).
- **Orden determinista preservado**: la pre-pasa corre post-sort; el detail
  conserva el orden id-ascendente que hoy produce el sort `(-score, id)`
  (ADR-0015 funda el cap en determinismo).
- **Guard `index_candidate_mismatch` intacto**: prohibida su reescritura
  como igualdad de conjuntos (la asimetría unidireccional es deliberada:
  divergencia de tokenizadores unicode61 vs `\w+` produciría degradaciones
  espurias — F-PC1-2).
- Selección, `used_bytes`, presupuesto y freshness quedan observablesmente
  idénticos (los zero-score jamás tocaban `used`; freshness corre por item
  seleccionado).

### 2. Señal de primera clase — versiones **dispersas**, no sustitución

Siguiendo el precedente nativo v1→v2 (coexistencia por ruta de feature,
`05af189`): **`retrieval-result-v3` y `mcp-retrieve-v3` se emiten sólo por
la ruta donde el estado ocurre**; v1/v2 siguen emitiéndose byte-idénticos
en todos los demás casos (los goldens vigentes sobreviven).

- `retrieval-result-v3`: campos base de v1 + `empty_reason` opcional +
  bloque freshness **opcional** (`allOf` if/then: `freshness` presente ⇔
  `freshness_profile` presente), `additionalProperties: false`.
- `mcp-retrieve-v3`: análogo sobre la base del envelope MCP.
- `empty_reason` enum cerrado a `"no_lexical_overlap"` hoy.
- v1 nunca tuvo schema publicado (sólo v2 existe como archivo); v3 sí se
  distribuye. La nota de release declarará los ids emisibles por superficie.

### 3. Predicado único de emisión (tabla de verdad)

Un helper compartido por `retrieval.py` y `mcp.py` decide `empty_reason`.
Condición base: `selected == []` ∧ `excluded_summary["zero_score"] ≥ 1` ∧
`"budget" not in excluded_summary`. Tabla:

| Caso | `empty_reason` |
|---|---|
| (i) overlap cero puro (`selected==[]`, `zero_score≥1`, sin budget) | `"no_lexical_overlap"` |
| (ii) (i) + freshness activo | `"no_lexical_overlap"` (v3 con bloque freshness) |
| (iii) todos inactivos / sólo `no_text` / sólo `invalid_record` | no emitir |
| (iv) vacío por budget (`budget` en summary, con o sin zero_score) | no emitir |
| (v) store vacío / sin activos (`zero_score` ausente) | no emitir |
| (vi) degradación de índice + overlap cero (fallback escaneó todo) | `"no_lexical_overlap"` |
| (vii) MCP: `records==[]` por corte de envelope (`budget_excluded≥1`) con base no vacía | no emitir (la causa es presupuesto de transporte) |

### 4. Detectores de freshness — nunca igualdad de string (F-PC2-1/2)

`mcp.py:380` y `context.py:60` migran de `== "an-kla/retrieval-result-v2"`
a detección robusta: presencia de `"freshness" in source` **o** membresía
`{v2, v3}`. Un resultado v3 con freshness debe producir
`mcp-retrieve-v3`/`context-assembly-v2` correspondientes. Test de
no-regresión obligatorio (hoy un id nuevo degradaría silenciosamente a v1
descartando la proyección temporal).

### 5. Registro y distribución (F-PC2-3/4/5/8) — checklist normativo

1. `an_kla/schemas/retrieval-result-v3.schema.json` +
   `an_kla/schemas/mcp-retrieve-v3.schema.json`.
2. Copias byte-idénticas en `docs/schemas/` (paridad impuesta por
   `tests/test_agent_contracts.py:34,116-121`).
3. Entradas en `SCHEMA_FILES` (`an_kla/schemas/__init__.py`) — sin ellas:
   `unknown_schema`.
4. `expected_names` en `tests/test_agent_contracts.py`.
5. `capabilities.py:result_schemas` += v3.
6. Inventario en `docs/schemas/README.md`.
7. Test de que `resume()` jamás recibe v3 (su `resume-evidence-v1` congela
   `source="retrieval-result-v1"`; resume llama sin freshness y con
   selección no vacía por construcción de su presupuesto).
8. `docs/uso-diario.md`: `excluded_detail` + referencia a `empty_reason` y
   a la derivación (opción cero complementaria).

### 6. Hueco del harness de paridad (F-PC1-7)

`evaluation_v2._compare` se extiende con `excluded_summary_equal` (y su
conteo en `_counts`): hoy el harness compara selección pero nunca la
contabilidad — el defecto #118 era invisible para el benchmark. Con esto,
la regresión de R3 queda amarrada por el harness además del test dirigido.
El subschema `comparison` de `retrieval-eval-report-v2` gana
`excluded_summary_equal` (required) y `run.ranking` gana `excluded_summary`
(objeto) — edición **in place** de v2, al amparo del precedente ADR-0037
(denominadores), con paridad byte `docs/schemas/` ↔ `an_kla/schemas/`
reverificada.

## Consecuencias

- **Positivas**: diagnóstico uniforme entre perfiles (cierra #118/R3);
  señal accionable de primera clase para el caso vacío (#133 propuesta 1);
  harness de evaluación con paridad de contabilidad.
- **Negativas**: tercera versión viva de los ids de retrieval/mcp-retrieve
  (v1/v2/v3) — los consumidores que parseen `schema` deben conocer el set;
  mitigado con nota de upgrade en beta.27 y detectores robustos.
- **Neutras**: TEMPLATE_VERSION no cambia (plantilla gestionada intacta);
  ranking/scoring intactos (ADR-0025); la propuesta 2 de #133
  (vocabulario en `startup-diagnostic`) queda explícitamente fuera —
  follow-up registrado en el issue.

## Test de regresión

- Paridad `excluded_summary`/`excluded_detail` scan vs índice (índice
  fresco, queries con mezcla de matches y no-matches; 5 estados de
  degradación con query sin solape).
- Tabla de verdad §3: 7 casos, emisión y no-emisión.
- Detectores: v3 con freshness → `mcp-retrieve-v3`/`context-assembly-v2`
  correctos; sin freshness → v1 paths byte-idénticos.
- Catálogo: `schema show` v3, paridad byte docs/paquete, capabilities.

## Referencias

- Issues #118 (R3) y #133; ADR-0025 (ranking sin cambios), ADR-0029 (BM25),
  ADR-0015 (excluded_detail), ADR-0021 (mecánica de distribución y política
  "nuevo schema ante cambio de campos"), ADR-0037 (precedente de edición
  con paridad byte), ADR-0031/#57 (fuera de alcance).
- Ronda adversarial pre-code: 2 atacantes de contexto fresco (2026-09-11),
  informes F-PC1-1..7 y F-PC2-1..9 absorbidos; hallazgo F-PC1-4 (ningún
  consumidor interno perturbado por el reorden) y F-PC2-6 (opción cero
  insuficiente) registrados.
