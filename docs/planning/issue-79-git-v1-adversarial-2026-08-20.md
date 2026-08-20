# Ronda adversarial — #79 `source_state` git/v1 / ADR-0038 (2026-08-20)

Punto 6 del plan `plan-backlog-2026-08-20.md`. Revisor independiente con
probes propios (e2e commit→show→resume, réplica de policy pre-0038,
jsonschema). Tres pasadas: fix-and-retry → fix-and-retry (1 acción) →
corregida. Cierre: **proceed**.

## Alcance

`checkpoint_policy.py` (`SOURCE_PROFILES`, `_git_source_field`,
`policy_fingerprint`), schema `working-state-v2` (oneOf aditivo, docs/ y
an_kla/), `capabilities()`, ADR-0038, registro (38 ADRs, 35/3), 15
tests.

## Hallazgos y correcciones

Ronda 1 (fix-and-retry):

| Hallazgo | Corrección |
|---|---|
| Colisión normativa: ADR-0023 §"Profile reservado" y ADR-0030 §4 reservaban `git/v1` para tool_observed/porcelain | Sección "Supersede normativo" en ADR-0038 (el issue #79 pide `git/v1` con esta semántica); filas 0023/0030 del registro anotadas; variante por-adaptador queda para perfil futuro con otro nombre |
| Newline en `head` pasaba el schema (`$` ECMA) pero no la policy | Patrón con `(?![\s\S])` en ambos schemas + test policy/schema |
| Downgrade unidireccional no documentado | Límite explícito (binario ≥ 0038 para resume/show) |
| Gaps de test (numéricos, bool, newline, e2e) | Tests añadidos incl. commit→show→resume real |

Ronda 2 (fix-and-retry, 1 acción): la deuda del patrón `digest`
(preexistente, tolera `\n` bajo ECMA; runtime fail-closed) quedó
declarada en Límites de ADR-0038.

Verificado por el revisor: flujo completo con CAS bajo lock; stale plan
con fingerprint viejo rechazado; ningún consumidor eleva autoridad desde
`source_state` (sólo validadores y emisores `untrusted_memory_data`);
schemas byte-idénticos; 575/575 OK.

## Decisión

- [x] proceed
- [ ] fix-and-retry
- [ ] escalate

En la mesa del maintainer: confirmar el supersede del nombre `git/v1`
(la alternativa era renombrar y dejar el nombre para la variante
tool_observed de #56; el issue #79 inclinó la balanza).
