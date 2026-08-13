# Ronda adversarial — issue #45 / ADR-0035

> **Estado:** `proceed`
> **Fecha:** 2026-08-12
> **Alcance:** arquitectura de adopción explícita de baseline project-owned;
> sin implementación

## Invariantes atacados

- `AGENTS.md` completo conserva detección de drift conforme a ADR-0017.
- Adoptar una baseline no interpreta bytes project-owned ni cambia la autoridad
  que les otorgue el host.
- El bloque gestionado y `AN-KLA.md` no pueden blanquearse mediante adopción.
- Target y manifiesto participan en CAS bajo el lock de contexto.
- Manifest v1 no se reutiliza si cambia shape o semántica persistente.
- El plan no expone contenido ni un digest project-owned más preciso.
- Un spike pre-code permanece solo lectura.

## Intento 1 — `fix-and-retry`

Hallazgos:

1. **HIGH:** el ADR difería nombre, schema, códigos y compatibilidad de
   `context update` a implementación.
2. **HIGH:** no resolvía el gate histórico manifest v1/v2, readers-first,
   downgrade y replay.
3. **MEDIUM:** `project_owned_content_sha256` no tenía framing normativo y
   creaba un oráculo de igualdad innecesario.
4. **MEDIUM:** el smoke estaba afirmado sin registrar comando→resultado.

Correcciones:

- ADR-0035 se limitó a arquitectura y secuencia obligatoria
  `spike → ADR de contrato → implementación`; no autoriza código.
- `context update` con drift no reconocido quedó decidido fail-closed.
- manifest v1 quedó como hipótesis refutable: el spike debe cubrir v1/v2,
  readers, downgrade, replay, templates históricos y fallos de atomic write;
  cualquier cambio de shape/semántica exige v2.
- se eliminó el digest project-owned público y se conservó el target hash CAS.
- se registró el smoke before→after y su explicación contra el path de código.

## Intento 2 — `fix-and-retry`

Único hallazgo **MEDIUM**: el ADR llamaba “read-only” al spike pero le exigía
añadir un test. Se separó la responsabilidad: el spike entrega repro, mapa de
código, diseño de fixture y matriz; implementación añade el test antes de
cambiar comportamiento.

## Intento 3 — `proceed`

Sin hallazgos restantes. El revisor confirmó la secuencia y las fronteras de
autoridad, CAS, migración y exposición.

## Revisión focal adicional — `fix-and-retry`

Antes del push, una segunda revisión independiente detectó:

1. **HIGH:** actualizar sólo `target_sha256` podía conservar hashes no-target
   bien formados pero semánticamente falsos y eliminar el único warning.
2. **MEDIUM:** `manifest_target_sha256_at_install` del upgrade-plan v2 pasaría a
   contener una baseline adoptada, contradiciendo su nombre público.

El ADR exige ahora validar bloque, contrato y template contra todos los campos
no-target verificables antes de adoptar. También exige un upgrade-plan nuevo
con semántica de baseline; v2 no se reinterpreta y un plan previo falla CAS tras
la adopción.

## Revisión focal final — `proceed`

Sin hallazgos restantes. El revisor confirmó que las precondiciones se aplican
al planificar y bajo lock; un hash falso falla sin mutación; upgrade-plan v2
conserva su significado; y la viabilidad del manifest v1 permanece como
hipótesis refutable del spike, separada del versionado obligatorio del plan.

## Evidencia

- `git diff --check` → sin salida.
- `python3 scripts/check_sizes.py` → `check_sizes: OK`.
- `python3 scripts/check_adr_registry.py` → `35 ADRs (aceptada=32,
  propuesta=3)`.
- `python3 -m unittest tests.test_adr_registry` → 3 tests, `OK`.
- `python3 scripts/ci_local.py --simulate-ci` → 511 tests, tamaños y registro,
  todos `OK`.

Los revisores trabajaron solo lectura y no editaron archivos ni GitHub.
