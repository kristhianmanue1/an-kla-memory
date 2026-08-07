# ADR-0019: operación `supersede` gobernada en `write-policy/v1`

- **Estado:** Propuesta (v2, tras ronda adversarial)
- **Fecha:** 2026-08-07
- **Decide sobre:** cómo el flujo gobernado ejecuta la sustitución de vigencia de un registro, sin mutar contenido CAS.

## Contexto

`write-policy/v1` sólo ejecuta `operation=add` (ADR-0007). El modelo de vigencia
define `sustituida` pero **sin operación ejecutable**: una corrección se escribe
como *fact nuevo al lado* del obsoleto, sin vínculo. Eso deja vigencias
inconsistentes (dos facts contradictorios coexisten como `vigente`), dificulta la
recuperación y obliga a reconstruir la línea temporal a mano.

`supersede` es la **primera operación que muta vigencia** (oculta el target de
`retrieve`). Eso introduce un vector que `add` no tiene: el silenciamiento de un
fact vigente. La frontera de confianza exige (a) no borrar evidencia (el CAS es
inmutable) y (b) impedir que memoria recuperada (dato no confiable) silencie
facts.

Restricciones verificadas en código: los segments son inmutables
content-addressed con `O_EXCL` (`store.py`); `snapshot()` hoy no aplica overlay
de vigencia; `evaluate_write` es pura («sin leer ni escribir estado»,
`write_policy.py` docstring + ADR-0007); los schemas son cerrados
(`additionalProperties:false`); el bloque gestionado declara literalmente «sólo
`operation=add`» (`context_text.py`).

## Decisión

1. **Operación propia.** `supersede` es un valor nuevo admitido de
   `WriteProposal.operation`. `add` no muta vigencia (sin cambio).
2. **Target por `id`, único dentro del stream.** El proposal lleva `supersedes:
   <id>` (string). La unicidad es por-stream (`store.py`), no global; la
   resolución ocurre dentro del mismo stream (decisión 3). No se usa sha de
   revisión: supersede actúa sobre el *registro* (vigencia), no sobre el
   *contenido* (CAS inmutable).
3. **Mismo stream obligatorio.** El target debe existir, estar `vigente` y ser
   del **mismo stream** que el nuevo. Los ejes no son intercambiables
   (`AN-KLA.md`).
4. **Autoridad heredada de `add`, excluyendo `derived_from_retrieval`.**
   `model_derived` → techo `summary` sí puede `supersede`. `derived_from_retrieval`
   **no** puede `supersede` (sólo `add`): mitiga el silenciamiento por memoria
   recuperada. Esta rama es decisión **pura** en `evaluate_write` (no requiere
   store) → reason `skip` con `supersede_requires_non_derived_authority`.
5. **Schema evolutivo con propagación al plan.** `supersedes` es campo opcional en
   `write-proposal-v1` y viaja al item del plan (`records[].record` o campo del
   item) para que el store conozca el target. Co-ocurrencia exigida:
   `operation="supersede" ↔ supersedes presente`. Se abren ambos schemas
   (`write-proposal-v1`, `write-plan-v1`) con esa co-ocurrencia; **no** se publica
   `write-proposal-v2`.
6. **Mecanismo de vigencia: `supersede-map` a nivel revisión.** La revisión lleva
   un mapa `target_id → sustituida_por` (lista de pares). `snapshot()` lo aplica
   como **overlay**: el registro target se observa con `status="sustituida"` sin
   reescribir bytes inmutables. Así `retrieve`, `build_index` y `record_text` ven
   al target como sustituido de forma consistente. Define el «dónde» que el v1
   omitía.
7. **Partición de la guarda (pureza preservada).**
   - `evaluate_write` **permanece pura**: decide autoridad + representación +
     operación (incluida la exclusión de `derived_from_retrieval`, decisión 4).
   - `commit_write_plan` añade, **dentro del `write_lock`, tras
     `verify_write_plan` y antes de construir objetos**, una guarda contra
     `snapshot(observed)`: target existe, `vigente`, mismo stream, y
     `supersedes != proposal.record.id`. Fracaso → código terminal
   **`invalid_supersede_target`** (añadido a
     `_POLICY_CONFIGURATION["terminal_error_codes"]`). Secuencia:
     `lock → CAS → revalidate → [GUARDA SUPERSEDE] → journal → objetos (nuevo + entrada supersede-map) → CURRENT`.
8. **Release beta.8.** `TEMPLATE_VERSION` → `0.1.0-beta.8`, nueva entrada en
   `_KNOWN_CONTEXT_TEMPLATES`, y actualización del bloque gestionado vía el flujo
   `upgrade` (no edición directa): el enunciado «sólo `operation=add`» pasa a
   «`operation=add` y `operation=supersede` gobernado». ADR-0007 gana nota
   apuntando aquí.
9. **Casos edge explícitos.**
   - Target ya `sustituida`/`refutada` → error `invalid_supersede_target`.
   - Cadenas A→B, luego C→A: válidas; la guarda rechaza re-sustituir un
     no-vigente, así B queda `sustituida`, A `sustituida`, C `vigente`.
   - `supersedes == proposal.record.id` → prohibido (error).
   - `eliminada` queda fuera de alcance (sin operación gobernada).
   - `supersedes` es **1-a-1 en beta** (un id, no lista); flexibilidad futura
     requeriría ADR adicional.

`refute` y `decay` quedan fuera de este ADR (siguen `skip` con
`operation_not_supported`).

## Por qué no [alternativa]

- **Reutilizar `add` + campo `target`**: `add` no debe mutar vigencia; el enum
  `{add, supersede, refute, decay}` ya existe en ADR-0007 con semántica propia.
- **Target por sha de revisión**: el CAS es inmutable; supersede opera sobre el
  registro (vigencia), no el contenido. El `id` es la clave natural.
- **Permitir distinto stream**: mezclaría ejes. Conservador para beta.
- **Permitir `derived_from_retrieval` en `supersede`**: descartado por el vector
  de silenciamiento (memoria recuperada ocultando facts). `add` no silencia;
  `supersede` sí; la asimetría exige restringir.
- **Meter la guarda de existencia en `evaluate_write`**: rompería ADR-0007
  (pureza) y el patrón `plan_write` fuera del lock. Se sede al store bajo lock.
- **`write-proposal-v2`**: `supersedes` opcional con co-ocurrencia es aditivo y no
  rompe consumers de v1.

## Consecuencias

- **Positivas:** vigencia consistente (un solo `vigente` por línea); línea
  temporal recuperable; fin del «fact nuevo al lado»; `derived_from_retrieval` no
  puede silenciar; base para `refute`/`decay`.
- **Negativas:** `policy_fingerprint()` cambia por **4 vectores**
  (`supported_operations` + `derived_authority.allowed_operations=["add","supersede"]`
  + `reason_codes` (+`supersede_requires_non_derived_authority`) +
  `terminal_error_codes` (+`invalid_supersede_target`)); es **beta.8**, no hotfix;
  `capabilities()` cambia (público).
- **Neutras:** `rebuild-index` tras migrar; doble ronda adversarial
  (`write_policy.py` + `store.py`); `lineage.refs` al target quedan como
  soft-orphan (documentado: trazar vía revisions).

## Test de regresión

- `validate_write_proposal`: `supersedes` ausente con `add`, presente con
  `supersede`, id bien formado, `supersedes != record.id`.
- `evaluate_write`: `supersede` con `authority_class="derived_from_retrieval"` →
  `skip` + `supersede_requires_non_derived_authority`.
- `commit_write_plan` (store): target inexistente / no-vigente / distinto-stream
  / self-ref → `invalid_supersede_target`.
- End-to-end: tras commit, `snapshot()` reporta target `sustituida` y nuevo
  `vigente`; `retrieve` excluye al target; `record_text` del target inalterado.
- Cadena A→B→C: vigencias correctas; CAS inmutable.
- Concurrencia: dos proposals superseden el mismo target → la segunda recibe
  `write_plan_base_changed` y, tras re-plan, `invalid_supersede_target`.

## Referencias

- Issue #17. Actualiza ADR-0007 (nota) y ADR-0001 (supersede-map en revision-v1).
- Relacionado: ADR-0015 (excluded_detail), ADR-0018 (indexable_text).
- Ronda adversarial previa: `fix-and-retry` (2 BLOCKER + 4 HIGH absorbidos aquí).
