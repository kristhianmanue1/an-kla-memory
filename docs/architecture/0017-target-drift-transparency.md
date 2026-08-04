# ADR-0017: Transparencia de target drift en el flujo de upgrade

- **Estado:** Aceptado
- **Fecha:** 2026-08-04
- **Cierra:** issue #12
- **Actualiza:** ADR-0011 (governed-agent-upgrade)

## Contexto

El issue #12 (reportado por `argos-epistemic`, confirmado en sesión independiente)
documenta que `upgrade apply` absorbe silenciosamente el drift del target
completo (`AGENTS.md`) fuera del bloque gestionado. La secuencia:

1. `context status` reporta `warnings: ["context_target_changed_outside_managed_block"]`
   cuando el operador editó contenido fuera del bloque.
2. `upgrade inspect --target <tag>` genera un plan **sin mencionar** el drift.
3. `upgrade apply` ejecuta con `ok: true` y reescribe el manifiesto local con el
   nuevo `target_sha256`.
4. `context status` post-apply reporta `warnings: []` — el drift quedó normalizado
   en la baseline sin dejar huella.

Esto contradice el principio declarado en `AN-KLA.md`:

> "No repares, reinstales ni sobrescribas automáticamente instrucciones
> modificadas."

y:

> "Informa toda discrepancia."

## Causa raíz

`an_kla/upgrade.py:50-75` (`inspect_upgrade`) llama a `context_status` pero
**descarta el campo `warnings`**. El plan `an-kla/upgrade-plan-v1` sólo incluye
`context_plan_sha256` y los hashes del target en `core`, sin exponer si el
target observado difiere del manifiesto local previo.

Cuando `apply_upgrade` reescribe el manifiesto (`an_kla/context_package.py:827`)
con el nuevo `target_sha256`, el warning desaparece automáticamente porque la
baseline se "promueve" al estado actual del archivo.

## Decisión

### 1. `inspect_upgrade` expone el drift

Añadir al `core` del plan:

```json
"target_drift": {
  "outside_managed_block": <bool>,
  "manifest_target_sha256_at_install": "<valor previo en .an-kla/context/manifest.json>",
  "observed_target_sha256": "<valor actual en disco>",
  "managed_content_sha256": "<sin cambios|cambiado>",
  "will_be_absorbed_by_apply": <bool>
}
```

`outside_managed_block` se calcula comparando
`manifest.get("target_sha256")` contra `_sha(target_bytes)` (la misma
comprobación que hace `context_status`). `will_be_absorbed_by_apply` es siempre
`true` cuando `outside_managed_block == true`, porque la nueva baseline siempre
refleja el estado actual del target.

### 2. `apply_upgrade` declara la absorción

Cuando `target_drift.outside_managed_block == true`, el resultado de `apply`
lleva:

```json
{
  "ok": true,
  "warnings": ["target_drift_absorbed_into_new_baseline"],
  "absorbed_target_sha256_before": "<hash previo>",
  "absorbed_target_sha256_after": "<hash nuevo>"
}
```

El flag `--confirm-target-drift` (nuevo en el CLI) **exige** confirmación
explícita cuando el drift existe. Sin él, `apply` falla con
`target_drift_requires_confirmation` (fail-closed).

### 3. Schema bump

`an-kla/upgrade-plan-v1` → `an-kla/upgrade-plan-v2` (additivo, no rompe
consumidores que validen loose):

- Campos nuevos en `core`: `target_drift` (objeto, opcional).
- `_validate_plan` en `upgrade.py` acepta v1 y v2.

Marcar `docs/schemas/upgrade-plan-v1.schema.json` como deprecated en el
comentario superior, sin borrar el archivo.

### 4. `AN-KLA.md` — Protocolo de actualización

Añadir un caso al *Protocolo de actualización* (después del flujo `inspect →
apply → verify`):

> Si `upgrade inspect` reporta `target_drift.outside_managed_block: true`,
> revisa manualmente el diff entre `manifest_target_sha256_at_install` y
> `observed_target_sha256`. `apply --confirm-target-drift` confirma que
> aceptas que el contenido fuera-del-bloque actual se convierta en la nueva
> baseline. Sin el flag, `apply` falla cerrado.

### 5. Tests

- `tests/test_upgrade.py::test_inspect_reports_target_drift_when_target_changed`
- `tests/test_upgrade.py::test_inspect_reports_no_drift_when_target_unchanged`
- `tests/test_upgrade.py::test_apply_fails_closed_without_confirm_flag_on_drift`
- `tests/test_upgrade.py::test_apply_declares_target_drift_absorbed_with_confirm`
- `tests/test_upgrade.py::test_validate_plan_accepts_v1_and_v2_schemas`

## Por qué no [alternativa]

- **No absorber el drift automáticamente** (mantener warning activo tras
  upgrade): rechazado porque rompe el caso de uso legítimo de evolución del
  `AGENTS.md` fuera del bloque gestionado. El operador debe poder añadir notas,
  políticas, secciones de equipo — todo eso es drift intencional.
- **Bloquear `apply` siempre que haya drift**: rechazado porque el 90% de los
  upgrades ocurrirán con drift intencional; el operador tendría que pasar el
  flag siempre. El flag es **required-only-when-drift**.
- **No añadir schema bump**: rechazado porque `target_drift` es información
  nueva; mezclarlo en v1 rompe la promesa de inmutabilidad del schema
  publicado.

## Consecuencias

- **Positivas:** el flujo `upgrade` cumple su contrato de transparencia. El
  operador tiene evidencia explícita de qué se absorbió. Las herramientas
  downstream (argos, otros consumidores) pueden leer `target_drift` y decidir
  automáticamente.
- **Negativas:** bump de schema (v1 → v2); un flag nuevo en el CLI; un paso
  más cuando hay drift intencional frecuente.
- **Neutras:** el warning `context_target_changed_outside_managed_block`
  sigue existiendo en `context status` (no se elimina); simplemente el flujo
  `upgrade` deja de silenciarlo.

## Migración

Para `v0.1.0-beta.5`:

1. Implementar la lógica de `target_drift` en `inspect_upgrade`.
2. Añadir flag `--confirm-target-drift` a `apply_upgrade` vía CLI.
3. Bump schema a `v2` con backwards compatibility en `_validate_plan`.
4. Tests como se listan arriba.
5. Documentar el caso en `AN-KLA.md` (requiere `context plan/apply` para
   mutar el contrato administrado).
6. Release notes de `v0.1.0-beta.5` mencionan el fix explícitamente con link
   al issue #12.

## No incluye

Este ADR **no** aborda la cobertura FTS para `events`/`episodes` sin campos
`text|render|summary|p` — eso es una decisión de diseño aparte (issue #14).

## Referencias

- Issue #12: https://github.com/kristhianmanue1/an-kla-memory/issues/12
- ADR-0011: governed-agent-upgrade
- Issue #14: Cobertura FTS para events/episodes
