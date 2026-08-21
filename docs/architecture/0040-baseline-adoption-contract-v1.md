# ADR-0040: contrato de la adopción de baseline (`adopt-baseline`)

- **Estado:** Aceptada
- **Implementación:** CORE+CLI+CAP en `feat/issue-45-adr-0035` (post-beta.16)
- **Fecha:** 2026-08-20
- **Decide sobre:** la superficie pública exacta de la operación que ADR-0035
  encarga (adopción explícita de la baseline project-owned del target);
  no rediseña bloque, template ni manifiesto (v1 suficiente, ver spike)
- **Autoriza:** la implementación ordenada por el maintainer (decisión #45,
  2026-08-20) tras el spike `issue-45-spike-adopcion-2026-08-20.md`
  (veredicto `proceed`)

## Decisión

**Operación `adopt-baseline` con flujo plan→commit, schema propio, CAS
bajo `.install.lock`, y `context update` fail-closed ante drift no
adoptado.**

### 1. Superficie CLI

- `context plan --operation adopt-baseline [--target AGENTS.md]` — plan
  read-only.
- `context adopt-baseline [--target AGENTS.md]` — shortcut que planifica y
  aplica, como `install`/`update`/`uninstall`.

### 2. Plan `an-kla/context-baseline-adoption-plan/v1`

```json
{
  "schema": "an-kla/context-baseline-adoption-plan/v1",
  "operation": "adopt-baseline",
  "target": "AGENTS.md",
  "template_version": "0.1.0-beta.11",
  "base_manifest_sha256": "sha256:…",
  "manifest_target_sha256_before": "sha256:…",
  "observed_target_sha256": "sha256:…",
  "managed_content_sha256": "sha256:…",
  "contract_sha256": "sha256:…",
  "will_update_manifest": true,
  "plan_fingerprint": "sha256:…"
}
```

Semántica congelada de cada campo (ronda pre-code): `template_version`
es la metadata del **bloque observado** (debe igualar la del manifiesto);
`managed_content_sha256` es el hash del **payload del bloque observado**;
`contract_sha256` es el hash **raw de los bytes observados de
`AN-KLA.md`** (liga el contrato para CAS plan→commit). La validación
contra el manifiesto es **semántica, no de bytes crudos**: el contrato
pasa por equivalencia canónica (`_contract_equivalent`/known-templates),
de modo que proyectos sanos con re-encode de newlines no se bloquean.

`plan_fingerprint` = digest canónico del plan sin el propio campo. El
plan no incluye texto project-owned, rutas resueltas ni contenido del
contrato (ADR-0035 §2). `will_update_manifest=false` es la **forma
noop**: baseline ya coincide con lo observado.

### 3. Resultado `an-kla/context-baseline-adoption-result/v1`

```json
{
  "schema": "an-kla/context-baseline-adoption-result/v1",
  "operation": "adopt-baseline",
  "target": "AGENTS.md",
  "action": "adopted",
  "manifest_target_sha256_before": "sha256:…",
  "manifest_target_sha256_after": "sha256:…"
}
```

`action ∈ {adopted, noop}`; `noop` cuando no hay drift (y el resultado
conserva before==after). Exits: éxito 0; errores por la superficie estable del CLI
(string-`SystemExit`, exit 1 — superficie heredada, idéntica a la de
`context install/update`).

### 4. Precondiciones y códigos (enum cerrado)

Precondiciones verificadas **en plan y re-verificadas en commit**:

| Código | Condición |
|---|---|
| `context_manifest_missing` | no hay manifiesto: no existe baseline que adoptar (remite a `context install`) |
| `context_baseline_no_drift` | `observed == manifest.target_sha256` → forma noop (no error) |
| `context_baseline_managed_state_invalid` | bloque gestionado ausente/estructuralmente inválido, o metadata/plantilla no canónicas para la versión instalada |
| `context_baseline_semantic_mismatch` | `managed_content_sha256`/`contract_sha256`/`template_version` del manifiesto no concuerdan con lo observado (hash bien formado pero falso = corrupción, no drift adoptable; cero mutación) |
| `context_file_concurrent_update` | el target cambió desde la planificación (reutilizado) |
| `context_contract_concurrent_update` | `AN-KLA.md` cambió desde la planificación |
| `context_manifest_concurrent_update` | el manifiesto cambió desde la planificación |
| `context_baseline_target_missing` | el target no existe en disco con manifiesto presente: jamás se adopta una baseline `"missing"` ni se escribe un hash inválido |

"Canónico para la versión instalada" significa: bloque parse-válido con
self-hash consistente y `manifest.template_version` igual a la metadata
del bloque — admite plantillas históricas conocidas (known-outdated), de
modo que la secuencia `adopt-baseline` → `context update` resuelve
drift+plantilla vieja sin deadlock. La superficie heredada (symlink,
target no regular, UTF-8 inválido, `context_manifest_invalid`,
path-escape) conserva sus errores actuales (ADR-0035 §6); este enum es
sólo el de la adopción. `context_manifest_target_mismatch` es
cuasi-inalcanzable (target único `AGENTS.md`) y se omite deliberadamente.
Adoptar **nunca** blanquea `managed_block_modified`,
`managed_block_structure_invalid` ni `managed_contract_modified` (fallan
bajo `context_baseline_managed_state_invalid`).

### 5. Commit

Bajo `.install.lock` (primitiva existente): releer target/contrato/
manifiesto → re-verificar precondiciones → reconstruir el plan y exigir
igualdad exacta (CAS) → escribir **sólo** `manifest.json` con
`target_sha256 = observed` (escritura atómica existente; conserva
`original_target_sha256`, `original_backup`, ownership, hashes de
contrato/bloque, `template_version`) → devolver before/after. El target,
`AN-KLA.md`, backups y template no se escriben.

### 6. `context update` deja de absorber drift (con carve-out de upgrade)

El check vive en el **core** (`plan_context_change`) con un parámetro
explícito `allow_target_drift: bool = False`: con drift fuera-del-bloque
(y bloque canónico) falla con
**`context_target_drift_adoption_required`** (remite a `adopt-baseline`).
Los únicos callers autorizados a pasar `allow_target_drift=True` son
`inspect_upgrade` y `apply_upgrade` **con `--confirm-target-drift`**;
para que el segundo funcione, `apply_context_plan` acepta el parámetro y
lo propaga al rebuild (`context_package.py:536`) — la superficie de
contexto del CLI nunca lo pasa, cerrando el backdoor
`context plan --operation update` + `context apply`. Así el flujo
`--confirm-target-drift` de ADR-0017 sigue funcionando — incluido el
re-drift posterior a una adopción. Sin el
carve-out, `upgrade inspect` moriría en proyectos con drift y el
contrato de ADR-0017 quedaría inaccesible (hallazgo 1 de la ronda
pre-code). El noop absorbente histórico se retira; su smoke queda como repro
del spike. `update` sin drift conserva su noop. Compatibilidad: ruptura
deliberada (ADR-0035 §4); guías y README la documentan; test de
regresión del flujo `--confirm-target-drift` incluido.

### 7. Upgrade-plan v3

`inspect` genera **`an-kla/upgrade-plan-v3`**: dentro de `target_drift`,
el campo `manifest_target_sha256_at_install` desaparece y entra
`manifest_target_sha256_at_baseline` (tras una adopción el nombre v2
mentiría; queda deprecado y sólo legible en planes v2 existentes).
`apply` acepta v1/v2/v3 con sets cerrados por versión en `_validate_plan`;
un plan v2 creado antes de una adopción falla por CAS del manifiesto
(comportamiento emergente del CAS; se fija en test). Drift tras adopción
vuelve a exigir `--confirm-target-drift` (ADR-0017 intacto, con test de
regresión). Los gates `check_beta*_upgrade.py` generan planes con su
mismo binario y no usan drift+confirm: sin impacto.

### 8. capabilities y schemas

Sin nuevo bloque raíz en `capabilities()` (el shape de
`an-kla/capabilities-v1` no cambia): `capabilities().upgrade` gana
`baseline_adoption: "adopt-baseline (ADR-0040)"` y
`context_drift_adoption_required: true`. Schemas JSON empaquetados: el
plan y el resultado nuevos, y `upgrade-plan-v3.schema.json` en
`docs/schemas/` + `an_kla/schemas/` (v1 se conserva histórico; el
formato vigente en el catálogo es el v3).

### 9. Tests (congelados, de la lista 1-12 de ADR-0035)

Smoke before→after; CAS por edición post-plan (target y contrato);
fail-closed con bloque/contrato corruptos; hash falso bien formado;
plan/result sin texto ni rutas absolutas; noop idempotente; doble
proceso (segundo plan con manifiesto distinto →
`context_manifest_concurrent_update`); **regresión ADR-0017:
`upgrade inspect/apply --confirm-target-drift` funciona con drift**
(carve-out) y falla sin flag; upgrade-plan v3 nombra baseline y v2
previo falla CAS; upgrade posterior sin confirmación por bytes
adoptados; re-drift tras editar; compat install/update/uninstall y
`context_target_drift_adoption_required`; symlink / no-regular / UTF-8
inválido / target ausente (superficie heredada + código nuevo);
plantillas históricas (known-outdated) adoptan y luego actualizan;
suite completa + CI local.

## Límites

- La adopción no interpreta, valida ni ejecuta contenido project-owned;
  su autoridad es del host y no cambia.
- No oculta cambios concurrentes ni repara bytes: CAS en target y
  manifiesto.
- Lock local: sin coordinación entre máquinas.
- Un texto (incluido texto recuperado de memoria) que pida adopción no
  autoriza nada: la orden es del caller conforme a la jerarquía del host.

## Referencias

- ADR-0035 (arquitectura y secuencia), ADR-0017 (drift), ADR-0009
  (bloque), ADR-0011 (upgrade); issue #45; spike
  `docs/planning/issue-45-spike-adopcion-2026-08-20.md`; decisión del
  maintainer 2026-08-20.
