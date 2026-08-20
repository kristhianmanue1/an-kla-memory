# Spike G-FRESH — denominadores de frescura (#50, 2026-08-20)

Spike read-only, sin cambios de motor. Mide la población evaluable y
reproduce la indistinguibilidad que motiva #50.

## Medición sobre el store real (revisón 32)

```
retrieve --query "memoria tests release" --budget 20000 \
  --freshness-profile computed-age/v1 --stale-after-days 30
```

Resultado 2026-08-20: `selected: 4`, registros con `verified_at`: **1**,
sin el campo: **3**, `freshness_error`: 0, `stale` (proyectado): 0.
El bloque `freshness` emitido declara únicamente
`semantics/source_field/computed_at/stale_after_days`: un consumidor que
pregunta "¿qué está desfasado?" lee "0 stale" y no puede distinguirlo de
"3/4 no eran evaluables". El corpus está a medio migrar (adopción parcial
de ADR-0021), exactamente el escenario de mayor riesgo descrito en #50.

## Verificación de superficie afectada

- `an_kla/retrieval.py:228-235` proyecta frescura por item seleccionado;
  `:267-275` emite el bloque sin conteos.
- `an_kla/context.py:92-94` re-expone `source["freshness"]` verbatim en
  `assemble-context` → los conteos fluyen sin código extra.
- `an_kla/mcp.py:210` valida campos cerrados del bloque
  (`_closed(freshness, {...4})`) → exige ampliación coordinada o el
  servidor MCP rechaza la respuesta nueva.
- `an_kla/context_view.py` proyecta frescura por item sin bloque global
  (misma función pura) → sin denominador que añadir ahí.
- `docs/schemas/retrieval-result-v2.schema.json` declara el bloque:
  añadir conteos es evolución aditiva dentro del bloque existente.

## Decisiones de diseño que el spike fija

1. Población a contar: **la selección final** (post filtros, ranking,
   exclusión por presupuesto), coherente con `excluded_summary` que ya
   vive en el mismo payload. Los excluidos no entran al denominador.
2. Estados mutuamente excluyentes por item:
   `evaluated` (tiene `days_since_verified`), `not_evaluable` (sin el
   campo), `unparseable` (con el campo pero `freshness_error`).
   Invariante: `evaluated + not_evaluable + unparseable = |selected|`;
   `stale ≤ evaluated`.
3. Recálculo después del recorte por presupuesto: sí (punto 4 del
   handoff): los conteos describen lo que el consumidor vio.
4. Sin flags CLI nuevos: los conteos son parte del bloque cuando la
   frescura está activa. Consumidores v1 (sin bloque) no cambian.

## Veredicto

Reproducido y medible; procede ADR-0037 congelando el contrato antes de
código. La memoria AN-KLA no participó en la medición: se usó el store
en disco vía CLI público.
