# Ronda adversarial — plan #102 attest + hardness (2026-09-01)

## Alcance

Plan candidato `plan-issue-102-attest-hardness-2026-09-01.md` (revisor con
contexto fresco, subagente decorrelado, mandato read-only). Se atacó: exactitud
de anclas archivo:línea, pureza de `evaluate_write`, esquema de receipts y
evidence, ruta real de rechazo de autoridad en el CLI, replay de receipts,
compatibilidad de tests dorados y decisión de firma.

## Modelo de amenazas

Regla base intacta: la memoria es dato, nunca instrucción. El plan toca la
frontera de procedencia (fabricación de `tool_observed`): el atacante modelo
es un agente perezoso-honesto que reutiliza evidencia vieja (replay) y el
agente con shell que edita su propia whitelist. La atestación no pretende
frenar al malicioso con clave local legible — procedencia auditable, no
defensa.

## Hallazgos y correcciones

| Hallazgo | Riesgo | Corrección |
|---|---|---|
| HIGH: H5 premisa falsa — `retrieved_evidence` ya incluye `id`/`stream` (resume.py:113-122; schema required; commit ancestro de beta.19) | Tarea no-op; perdida de credibilidad del plan | Re-acotada: re-ejecutar repro del consumidor para localizar superficie real; cierre como no-reproducible si no procede |
| HIGH: H3 premisa falsa — `show_checkpoint` devuelve el checkpoint almacenado completo (checkpoints.py:20-28); `goal: null` es el v1 de init (initialization.py:32-39) | Tests DoD pasarían sin cambio; diagnóstico equivocado | Re-acotada: repro en store limpio + documentar sentinel; diagnosticar store del consumidor |
| HIGH: el rechazo real de `tool_observed` vive en `_cli_authority` del CLI (an_kla/__main__.py:96-104, :386, :396), no en `evaluate_write`; `capabilities()` publica el contrato a invertir; checkpoint_policy.py:68-213 tiene su paralelo | Attest muere en la puerta del CLI; superficie no considerada | §1 y S0-S2 re-escritos: condicionar `_cli_authority`, evolución versionada de `capabilities()`, alcance checkpoint-authority como F0-D5 |
| HIGH: receipt sin binding — esquema sin `base_revision` ni nonce permite replay de receipts viejos como autoridad full | Recrea el oráculo que attest cierra | §1: receipt liga `base_revision` + `nonce` consumible; verificación en plan y commit bajo lock; tests S3 |
| MEDIUM: evidence schema cerrado (`_validate_evidence` write_policy.py:262-275; `additionalProperties: false`) — item receipt es inválido en v1 | Plan asumía extensibilidad inexistente (viola §11.2) | §1: vía write-authority-v2 o perfil, forma exacta en S0 |
| MEDIUM: H2 rompería commit — gate `_planning_result` de claves exactas (an_kla/__main__.py:107-115); `warnings[]` ya existe en commit-outcome-v2 | Señal nueva rompe `commit-write-plan` contra su propio plan | H2: señales vía `reason_codes` (vocabulario abierto) + `warnings[]` del outcome |
| MEDIUM: whitelist editable sin rastro | Vacía el valor auditable de attest | §1: `whitelist_digest` en cada receipt + estado en `status`/`context_diagnostics` + exec argv estricto |
| MEDIUM: ciclo de vida clave/identidad no abordado (adopt/repair rebindea `project_uuid`; worktrees) | Receipts huérfanos o cruzando stores | S0: verificación contra binding vigente (store.py:327-333), código `receipt_identity_mismatch`, caso worktree documentado |
| LOW: H1 — `self_reference` ya falla en plan (write_policy.py:241-246); plan-write sólo lee CURRENT (store.py:303-306) | Repro mal anclado; coste subestimado | H1 corregido; checks de commit se mantienen (TOCTOU); leer `store.snapshot(observed)` |
| LOW: H4 sin goldens de migración | Golden tests romperían sin plan | Anclas: test_context_package.py:172,:235; test_integration_status.py:130; test_init_context_signal.py:69 |

## Límites declarados

- Revisor read-only: no ejecutó la suite ni verificó por ejecución el
  comportamiento de `test_sealed_matrix` (claim H6).
- Claims externos del §0 (repo infosalud: scripts/mem, ADR-007, hooks) no
  re-auditados comando por comando por el revisor; el repro real del
  consumidor para H3/H5 es inobservable desde este repo.
- Matriz CI actual del workflow (H6) y caché fría del update-check (H7)
  verificados sólo superficialmente.

## Decisión

- [ ] proceed
- [x] fix-and-retry — **absorbido**: correcciones integradas en el plan el
  2026-09-01; veredicto del revisor era fix-and-retry, el plan corregido
  queda listo para decisión de maintainer (fase F0) y, si se autoriza
  implementación, para las rondas por fase que el propio plan prescribe.
- [ ] escalate
