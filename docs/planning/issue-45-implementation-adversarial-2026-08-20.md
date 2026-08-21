# Ronda adversarial — #45 adopción de baseline (ADR-0040, 2026-08-20)

Rama `feat/issue-45-adr-0035`. **Tres rondas pre-code** (diseño: hallazgo
crítico §6/carve-out + 9 más, todos corregidos; R1 residual de
propagación enmendado) y **dos rondas post-code** (pre-commit, condición
del maintainer). Cierre: **proceed**.

## Pre-code (diseño, spike `issue-45-spike-adopcion-2026-08-20.md`)

| Hallazgo | Corrección |
|---|---|
| CRÍTICO — el fail-closed de update en el core mataba `upgrade inspect` y el flujo `--confirm-target-drift` de ADR-0017 | Carve-out `allow_target_drift` que sólo `inspect_upgrade`/`apply_upgrade`(con flag) pasan; `apply_context_plan` propaga; superficie de contexto del CLI nunca |
| Ambigüedades de semántica de campos, enum incompleto, v3 subespecificado, capabilities/nuevo bloque, tests omitidos | Todo congelado en ADR-0040 v2 |
| R1: contradicción §6/§9 en el apply del upgrade | Frase de propagación en §6 |

## Post-code ronda 1 (fix-and-retry, 6 hallazgos)

| Hallazgo | Corrección |
|---|---|
| ALTA — known-outdated no adoptaba (línea letal redundante) | Eliminada; `_known_template_equivalent` decide |
| ALTA — re-encode CRLF sano de `AN-KLA.md` reportado como corrupción | Hash del contrato acepta raw/desired/canónico-LF |
| MEDIA — `context_contract_concurrent_update` inalcanzable | Alcanzable tras el fix del re-encode; test del CAS |
| MEDIA — `context install` sobre manifiesto con drift absorbía | Gate extendido a `{"update","install"}` |
| BAJA — §3 decía exit 2 (superficie real: exit 1) | ADR corregido |
| MEDIA — 4 ítems §9 sin test | 5 tests añadidos (`FrozenListGapTests`) |

## Post-code ronda 2 (fix-and-retry, 3 residuales)

| Hallazgo | Corrección |
|---|---|
| El test de known-outdated era **vacío** (label-swap dejaba hash del bloque actual; `_known_template_equivalent` daba False) | Reescrito con el fixture histórico real v0.1.0 (bloque+contrato+manifiesto coherentes), con aserción de que la rama known-outdated se ejercita |
| `__main__` a media lista; parámetro sin usar | Corregidos |

## Verificación final (evidencia de los revisores)

Gate §6 cerrado sin backdoors (CLI plan/apply, import directo, MCP no
expone); CAS de target/contrato/manifiesto con manifiesto intacto byte a
byte; adopción escribe **sólo** `target_sha256` bajo lock con
`_atomic_write`; v3 valida contra schema empaquetado; v2 pre-adopción
aplica / post-adopción rechazado por CAS; hash canónico-LF no debilita
detección (contratos a mano mueren antes, por equivalencia semántica);
gate en install no rompe gates de upgrade (exige manifiesto presente).
Suite **617/617 OK**; `ci_local --simulate-ci` OK; `check_sizes` OK;
`check_adr_registry` OK (40/38/2); `check_beta14/15_upgrade` OK.

## Decisión

- [x] proceed
- [ ] fix-and-retry
- [ ] escalate
