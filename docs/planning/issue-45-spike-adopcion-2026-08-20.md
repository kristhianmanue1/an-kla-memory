# Spike #45 — adopción explícita de baseline (ADR-0035 §secuencia, 2026-08-20)

Spike read-only + repro ejecutado contra beta.16 (instalación real del
repo vía PYTHONPATH sobre tempdir). Entrega lo que ADR-0035 exige:
mapa `archivo:línea`, repro comando→resultado, matriz
v1/v2/downgrade/replay/faults y veredicto.

## Mapa código:línea (beta.16, `main`@`a99316e`)

| Mecanismo | Ubicación | Rol en la adopción |
|---|---|---|
| Drift fuera-del-bloque | `context_package.py:721` (`context_status`: `manifest.target_sha256 != _sha(target_bytes)`) | El warning que motiva todo |
| Plan read-only | `context_package.py:343-405` (`plan_context_change`) | Patrón a replicar para la operación de adopción (incluye `base_manifest_sha256` ya presente) |
| CAS del apply | `context_package.py:536-541` (rebuild + igualdad exacta; `context_file_concurrent_update`) | El commit de adopción lo reutiliza tal cual |
| **Fast-path noop** | `context_package.py:552-569` | NO aplica con drift (exige `manifest.target_sha256 == plan.result_target_sha256`): cae a la ruta general |
| **Absorción silenciosa** | `context_package.py:609-635` (ruta general: `_atomic_write(target)` en 609 + manifiesto con `target_sha256=_sha(result_bytes)` en 616) | El comportamiento que ADR-0035 §4 prohíbe seguir usando como vía de adopción |
| Lock de contexto | `context_package.py:436-467` (`.install.lock`, `ContextLockBusy`) | El commit de adopción corre bajo el mismo lock |
| Manifiesto v1 | `context_package.py:469+` (`_load_manifest`), schema `context-installation/v1` | `target_sha256` ya significa "baseline del target completo"; `original_target_sha256`/`original_backup` se conservan |
| Drift de upgrade | `upgrade.py:60-97` (`manifest_target_sha256_at_install`, `outside_managed_block`, `observed_target_sha256`) | Lectura del drift por upgrade inspect |
| Upgrade-plan v2 | `upgrade.py:25,126,141-164` (schema **cerrado** con `manifest_target_sha256_at_install`) | El campo miente tras una adopción → exige plan v3 (ADR-0035 §4) |
| Apply de upgrade | `upgrade.py:218-222` (fail-closed sin `confirm_target_drift`) | Tras adopción, `outside_managed_block` debe ser false para esos bytes |

## Repro comando→resultado (beta.16, ejecutado 2026-08-20)

```text
init; context install           → result.action=create
editar fuera del bloque         → status: ok=true,
                                   warnings=[context_target_changed_outside_managed_block]
context update                  → plan.action=noop; result.action=noop
context status                  → ok=true; warnings=[]
```

Confirmación del mecanismo (mapa arriba): con drift, el fast-path no
aplica (hash de manifiesto ≠ observado), la ruta general reescribe
target (bytes idénticos) y manifiesto con el hash observado. La
adopción ocurre sin declararse: exactamente el defecto de intención de
ADR-0035.

## Matriz de refutación del manifest v1

| Pregunta | Método | Resultado |
|---|---|---|
| ¿Alguna lectura distingue baseline instalada vs adoptada? | Readers: `context_status` (comparación por igualdad), `plan_context_change` (usa manifiesto para backups/original), `apply_context_plan` (CAS por hashes), `upgrade.py` inspect/apply (comparación) | **No**: todos consumen `target_sha256` como "baseline vigente del target completo"; ninguno interpreta su provenance temporal |
| ¿Replay de planes v1 de context rompe? | Plan v1 se rebuild y compara exacto (`536-541`); la adopción cambia el manifiesto → `base_manifest_sha256` difiere → replay falla por CAS, como cualquier mutación concurrente | Correcto por diseño |
| ¿Downgrade? | Manifiesto v1 sin campos nuevos → un binario anterior lo lee igual | Sin caso especial |
| ¿Faults en `_atomic_write`? | Escritura atómica temp+rename (`context_package.py:408-427`); el commit de adopción sólo toca `manifest.json` con la misma primitiva | Hereda atomicidad |
| ¿`original_target_sha256`/`original_backup` cambian? | La adopción NO los toca (conservan la primera instalación) | Confirmado por lectura |

**Veredicto de la matriz: `proceed`** — `context-installation/v1`
conserva shape y semántica; **no** se requiere manifest v2 (ADR-0035 §5
lo condicionaba a esta refutación). El versionado exigido es el del
**upgrade plan** (v2→v3 con `manifest_target_sha256_at_baseline`), porque
su schema cerrado nombra `at_install`.

## Cambios de comportamiento que el contrato debe congelar

1. `context update` ante drift fuera-del-bloque **deja de absorber**:
   fail-closed con código nuevo (remite a la operación explícita). Es
   ruptura deliberada (ADR-0035 §4); tests vigentes del noop absorbente
   se actualizan.
2. Upgrade: tras adopción, esos bytes no vuelven a pedir
   `--confirm-target-drift` (flujo existente ya lo garantiza al comparar
   contra la baseline nueva; se fija en test).
3. `context update` con bloque canónico y **sin** drift conserva el
   noop actual (nadie pierde el flujo sano).

## Fixture para los tests 1-12 de ADR-0035

Helper `AdoptionProject` (tempdir): `init` + `context install` +
`_edit_project_owned(text)` que sólo toca bytes fuera del bloque, con
accesores `manifest()`, `status()` y `plan(operation)`. Cubre: smoke
completo, CAS (editar post-plan), bloque/contrato corruptos (fail-closed
sin adopción), hash falso bien formado, no-fuga (plan/result sin texto
project-owned ni rutas absolutas), noop idempotente (segunda adopción
sin drift), doble proceso bajo lock (simulado por segundo plan con
manifiesto cambiado), upgrade-plan v3 con baseline + v2 previo falla CAS,
upgrade posterior sin confirmación, re-drift tras editar de nuevo, y
compatibilidad install/update/uninstall.

## Veredicto del spike

**`proceed`** a ADR-0040 (contrato): manifest v1 suficiente; operación
`adopt-baseline` plan→commit reutilizando lock, CAS y primitivas
atómicas existentes; upgrade-plan v3; `context update` fail-closed ante
drift. Ningún hallazgo `refine`.
