# G4 · A0 — threat model de identidad de agente y multi-scope (#58), en lectura

- **Tarea:** A0 del plan `docs/plans/2026-10-10-g3-discovery-agent-roadmap.md`.
- **Estado:** `verified` como documento de lectura.
  - No implementa G4, no fija schema y no promete privacidad.
  - No sustituye el spike ni el ADR que exige #58.
- **Fecha:** 2026-10-13.
- **Base:** `main` con G3 R0–R2b fusionado. R3 está en revisión en la PR #145.
- **Ejecutor:** agente Claude Code (modelo efectivo `unknown`).
- **Revisión:** autorrevisión; sin revisor independiente.

## Estado actual que este modelo asume (fuentes)

- **El binding de agente no está verificado.**
  - `agent_binding = "unverified"` en `an_kla/capabilities.py:103` y en
    `an_kla/integration.py:95,160`.
  - ADR-0031 (`docs/architecture/0031-agent-owned-memory-host-managed-v1.md:123,141,271`)
    declara que «memoria privada del agente» no es verdadera en sentido
    fuerte hasta G4.
- **La identidad de custodia es por proyecto y por bytes.**
  - El binding es `project_uuid` + `store_identity`.
  - Tras G3, `custody_fingerprint` (ADR-0048 §1–§2) identifica *qué bóveda*,
    no *quién escribe*.
- **Un worktree no aísla autoridad.**
  - Un worktree con la custodia resuelta comparte identidad y revisión.
  - `root_relocated` es observacional (ADR-0048 §2;
    `tests/test_custody_entries.py::test_worktree_without_and_with_resolution`).
- **La autoridad de escritura viene del caller.**
  - Escribir exige un plan y su commit con `authority`.
  - Esa autoridad la declara quien llama; AN-KLA no la autentica
    (ADR-0031, modelo host-managed).

## Matriz de amenazas

| Amenaza | Contraejemplo concreto hoy | Control actual y su fuente | Brecha para G4 |
| --- | --- | --- | --- |
| Contaminación cross-project | Dos proyectos con `AN_KLA_STORE_ROOT` igual en el mismo shell escriben en una bóveda | Aviso `store_root_env_unbound_project`; el puntero fija la bóveda por proyecto (R1c, `store_resolution.py`) | El aviso no bloquea: sin binding verificado no se distingue un worktree legítimo de otro proyecto |
| Divulgación | Un agente externo recibe `assemble-context` con registros de otro scope | Ninguno por scope; sólo un proyecto por bóveda | Default deny cross-scope inexistente porque no existe el scope |
| Suplantación de agente | Cualquier proceso local declara `authority` en un plan | `authority` declarada, no autenticada (ADR-0031) | Sin `agent_id` verificable; `unverified` debe seguir explícito |
| Confused deputy | Un hook acuña hook-runs o attest a nombre del proyecto activo cuando el operador apuntó la env a otra bóveda | La plantilla de hook hace `unset AN_KLA_STORE_ROOT`; `check_custody` corre antes de acuñar (R1c) | Sólo cubre la custodia, no qué agente pidió la acción |
| Falsa privacidad | Llamar «privada» a una bóveda externa en `~/vaults` | El puntero no es control de acceso (registros R1a y R1b); relocate y export crean archivos 0600 y directorios 0700 (`relocate.py`, `export_io.py`); el resto del store usa los permisos del proceso | Ningún aislamiento entre agentes del mismo usuario POSIX |
| Colisión de namespace | Dos agentes usan el mismo `id` de registro | `plan_duplicate_id` dentro de una bóveda (`plan_guard.py`) | No hay namespaces; la colisión entre scopes no está definida |

## Separación conceptual que G4 debe preservar

1. **Identidad:** quién es un agente. Útil para routing y auditoría.
2. **Routing:** a qué bóveda o scope va una lectura o escritura. Hoy lo
   resuelve custodia: flag > env > puntero > project-local.
3. **Acceso al filesystem:** lo decide el sistema operativo. Ni un worktree
   ni un namespace lo cambian.
4. **Autoridad de escritura:** quién puede cambiar la memoria. Hoy la declara
   el caller; un `agent_id` no debe convertirse en permiso implícito
   (ADR-0031: identidad nunca como autoridad).

Ningún namespace ni worktree se presenta aquí como enforcement: no existe
prueba que lo respalde.

## Gates propuestos para pilotos (opciones, no decisión)

| Opción | Qué probaría | Riesgo |
| --- | --- | --- |
| G4-a: `agent_id` sólo observacional en receipts (`unverified`) | Trazabilidad de quién declaró qué, sin autoridad | Se lea como verificación; mitigar con el campo `agent_binding` |
| G4-b: scopes como bóvedas separadas, con selección explícita (sin bóveda multi-scope) | Aislamiento por custodia reutilizando G3 | Más bóvedas que descubrir (#134 / ADR-0050) |
| G4-c: namespaces dentro de una bóveda con default deny en `assemble-context` | Minimización de contexto | Falsa privacidad: mismo archivo y mismo usuario POSIX |

Recomendación de lectura: G4-a y G4-b son compatibles con lo verificado en
G3; G4-c exige un threat model de enforcement que hoy no existe. La decisión
y cualquier schema son del maintainer, con un ADR propio. Este documento no
promueve ninguna fase.

## Límites

- No hay spike de código, piloto ni test nuevo en este corte.
- Las fuentes citadas reflejan `main` al 2026-10-13; las líneas pueden moverse.
