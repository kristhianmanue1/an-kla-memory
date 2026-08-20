# ADR-0037: declarar los denominadores de la frescura (G-FRESH)

- **Estado:** Aceptada
- **Implementación:** CORE+CLI+MCP+CAP en `plan/backlog-prioridades-2026-08-20`
  (post-beta.15)
- **Fecha:** 2026-08-20
- **Decide sobre:** qué recuentos debe exponer el bloque `freshness` para
  que "nada está desfasado" sea distinguible de "nada era evaluable";
  no decide ranking, exclusión por frescura, verificación contra fuentes
  vivas ni autoridad de `verified_at`

## Contexto

`retrieve` con `--freshness-profile computed-age/v1` proyecta
`verified_at/days_since_verified/stale/freshness_error` por registro
seleccionado (ADR-0021) y emite un bloque global con
`semantics/source_field/computed_at/stale_after_days`. Cuando ningún
registro trae `verified_at`, la respuesta es indistinguible de un corpus
sano: la única señal es una ausencia que hay que recorrer registro a
registro. El riesgo se concentra en corpus a medio migrar: reportan
`stale` sobre la fracción evaluable y silencio sobre el resto. Medido en
el store de este repositorio (2026-08-20): 4 seleccionados, 1 evaluable,
3 no evaluables, `0 stale` (
`docs/planning/issue-50-gfresh-spike-2026-08-20.md`).

`excluded_summary` ya resuelve el problema análogo para la omisión de
registros en ese mismo payload. La frescura carece de su equivalente
(#50).

## Decisión

**Extender el bloque `freshness` con recuentos de la población final
seleccionada**, en el espíritu de `excluded_summary`:

```json
"freshness": {
  "semantics": "self_asserted_timestamp",
  "source_field": "record.verified_at",
  "computed_at": "2026-08-20T15:45:55.510705Z",
  "stale_after_days": 30,
  "evaluated": 1,
  "not_evaluable": 3,
  "unparseable": 0,
  "stale": 0
}
```

Propiedades:

1. **Población**: los recuentos describen la selección final (post
   filtros de vigencia, ranking y recorte por presupuesto), porque
   describen lo que el consumidor vio. Los excluidos ya tienen su propio
   sumario.
2. **Estados totales y mutuamente excluyentes por registro**:
   - `evaluated`: proyectó `days_since_verified` (campo presente y
     parseable);
   - `not_evaluable`: carece de `verified_at`;
   - `unparseable`: trae el campo pero proyectó `freshness_error`
     (`unparseable_verified_at`/`unrepresentable_verified_at`).
3. **Invariantes comprobables**: `evaluated + not_evaluable +
   unparseable = |selected|`; `stale ≤ evaluated`. Se afirman en pruebas
   sobre la salida de las tres capas; el runtime los satisface por
   construcción (clasificación if/elif/else de estados totales).
4. **`stale` global** cuenta los seleccionados con `stale: true`. No es
   un cuarto estado: es un subconjunto de `evaluated`.
5. **Aditivo dentro del bloque existente**: un consumidor que no lee los
   nuevos campos no se rompe; el bloque sólo existe cuando la frescura
   está activa y el schema ya versiona esa envolvente
   (`an-kla/retrieval-result-v2`). Sin cambio de ranking, exclusión,
   exit codes, CLI flags ni `policy_fingerprint`.
6. **Alcance de contratos**: `retrieve` emite los recuentos sobre su
   selección final; `assemble-context`
   (`an-kla/context-assembly-v2`) re-expone los metadatos verbatim y
   **recomputa** los cuatro recuentos sobre los registros que sirve tras
   su recorte de presupuesto global; el servidor MCP read-only
   (`an-kla/mcp-retrieve-v2`) hace lo mismo tras su recorte de sobre.
   La vista `view context` también emite un bloque global de frescura,
   pero su población es subjects paginados con proyección por record
   interno: definir el denominador ahí (¿records de la página? ¿del
   subject?) exige decisión propia y **queda expresamente diferido** a
   una revisión posterior del contrato de vista.

## Por qué contar sobre la selección final y no sobre el corpus

Los recuentos responden la pregunta del consumidor — "¿cuánto de lo que
acabo de ver era evaluable?" — sin obligarlo a cruzar contra
`excluded_summary`. Contar sobre el corpus mezclaría poblaciones que el
payload no entrega y sugeriría una cobertura que la respuesta no tiene.
Es la misma decisión de diseño que `excluded_summary` ya tomó para la
omisión.

## Por qué tres estados y no dos

#50 planteó contar `unparseable` dentro de `not_evaluable` "a criterio
del equipo". Separarlo es más honesto: un campo ausente (decisión de
procedencia) no es un campo corrupto (defecto de dato). El costo es un
entero; el beneficio es que la alarma de corrupción no se diluya en la de
migración.

## Límites

- `verified_at` sigue siendo un timestamp autodeclarado
  (`self_asserted_timestamp`): nada de esto convierte la frescura en
  verificación externa ni en vigencia frente al repositorio (eso es
  #79, eje distinto).
- Los recuentos no cambian la selección: un corpus 100% no evaluable
  responde igual que hoy, pero ahora lo declara.
- El bloque no aparece en resultados v1 (sin `--freshness-profile`):
  superficie anterior intacta.
- **Crecimiento del sobre mínimo**: los cuatro enteros agrandan el
  bloque (~58 bytes canónicos); un presupuesto v2 que apenas cabía puede
  pasar a `budget_too_small_for_envelope` /
  `budget_too_small_for_required_context` sin cambio de datos. Es costo
  del contrato, no degradación: la frontera se fija en pruebas.
- `view context` conserva su bloque global de frescura **sin** recuentos
  en esta decisión: su población es paginada y el denominador exige
  diseño propio (ver propiedad 6).

## Alternativas descartadas

- **Denominador sobre el corpus completo**: mezcla poblaciones no
  entregadas (ver arriba).
- **`not_evaluable` absorbiendo `unparseable`**: diluye corrupción en
  migración (ver arriba).
- **Recalcular antes del recorte por presupuesto**: describiría
  registros que el consumidor no vio; incoherente con el propósito.
- **Campo por item en lugar de bloque**: la ausencia por item es
  precisamente la señal que hoy falla; el consumidor no debe recorrer
  items para contar.

## Referencias

- ADR-0021 — `verified_at`, frescura computada en lectura, semántica
  autodeclarada.
- ADR-0025 — evaluación v2; los recuentos son observables de la misma
  población.
- Issues #50 (esta decisión) y #79 (desfase memoria↔repo, eje ortogonal).
- Spike `docs/planning/issue-50-gfresh-spike-2026-08-20.md`.
