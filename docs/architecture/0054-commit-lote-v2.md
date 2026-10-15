# ADR-0054: Commit gobernado en lote (write-proposal/v2)

- **Estado:** Aceptada
- **Implementación:** No iniciada
- **Fecha:** 2026-10-14
- **Decide sobre:** el contrato versionado que permite ingesta gobernada de N registros en una revisión sin debilitar CAS ni política por registro.

> Aceptada por orden del maintainer (2026-10-15: "adelante con implementación
> recomendada" sobre la mesa completa ADR-0052/0053/0054).

## Contexto

`write-proposal/v1` lleva un registro por propuesta; cada escritura gobernada
crea su revisión y paga plan + revalidación + índice. La batería P0 midió
p50 0,47–0,60 s por escritura y aborto por umbral en ~450 revisiones; el
issue #149 (P2d) pide commit en lote "un plan, N records, una revisión" sin
debilitar CAS ni política por record. Cambiar la forma del proposal toca
contrato observable: exige versión nueva, no extensión de v1 (§11.2: schemas
cerrados → versión nueva con compatibilidad demostrada).

## Decisión

Crear **`write-proposal/v2` (perfil lote)** con reglas:

1. **Forma**: una propuesta v2 lleva hasta `MAX_BATCH_RECORDS` (techo del
   perfil, p. ej. 1.000) registros homogéneos en stream y operación; produce
   UNA decisión, UN plan, UNA revisión, UN CAS. `v1` queda congelada y
   sigue siendo la vía canónica de registro único.
2. **Semántica contra estado pre-lote**: la política evalúa cada registro
   contra el estado vigente **pre-lote** (base_revision común). Un
   `supersede` del lote sólo puede apuntar a un registro vigente en ese
   estado pre-lote; **superseder a otro registro del mismo lote está
   prohibido** (validación v2) para eliminar dependencia de orden interno.
3. **Atomicidad all-or-nothing**: si algún registro no supera la política
   (techo, scope, vigencia), el lote entero es `skip` con reasons por
   registro; el caller reenvía sublotes conformes. No existe lote parcial.
4. **Auditoría**: un evento `write_policy_decision` por lote con la lista
   de digests por registro (ordenada), decisión y reasons; journal y CURRENT
   como en v1. El fingerprint del perfil v2 es distinto y viaja en
   `_POLICY_CONFIGURATION` (bump versionado como en #152).
5. **CLI**: `plan-write --batch <archivo>` y `commit-write-plan` sin
   cambios de forma (la salida del primero alimenta al segundo).

## Por qué no [alternativa]

- **N propuestas secuenciales bajo un lock**: sigue pagando N planes y N
  eventos, pierde atomicidad y agrava el CAS (74 % medido).
- **`MemoryStore.commit()` interna para ingestas**: existe, pero es
  primitiva interna **sin política de escritura** (ADR-0007 §Estado);
  usarla para ingesta real vaciaría la gobernanza.
- **Extender v1 con campo opcional de lista**: rompería el schema cerrado
  y la co-ocurrencia supersede↔record única; §11.2 exige versión nueva.

## Consecuencias

- Positivas: ingesta gobernada a escala (el techo de la batería deja de ser
  el costo por registro); CAS amortizado; política por registro intacta.
- Negativas: contrato adicional que mantener; lotes grandes requieren
  presupuesto de revalidación proporcional (se rige por los mismos
  umbrales de la batería P0).
- Neutras: requiere Enmienda ADR-0007 (referencia a v2) en la
  implementación; ronda adversarial obligatoria al tocar `store.py`/
  `write_policy.py`.

## Test de regresión

- Lote con un registro sobre el techo → `skip` del lote entero con zero
  effects (CURRENT y journals sin cambio).
- Supersede intra-lote → rechazo estable de validación v2.
- Target no vigente en pre-lote → `plan_supersede_target_not_vigente`
  (paridad con v1).
- Lote válido → una revisión, un evento con N digests, un journal.
- Batería P0 re-corrida: celda gobernada por lotes supera la línea base
  (~450 escrituras) bajo los mismos umbrales.

## Referencias

Issue #149 (P2d); ADR-0007 y su Enmienda #152; batería P0
`benchmarks/scale/results/20261014-182904/INFORME.md`; §11.2 del estándar;
acta `docs/planning/mesa-diseno-140-149-adversarial-2026-10-14.md`.
