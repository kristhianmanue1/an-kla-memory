# Ronda adversarial de #171 PR B (plantilla `0.1.0-beta.32`)

Rama `fix/171-pr-b-plantilla-runtime`, commit atacado `fcdb776`. Ronda
obligatoria: toca el contrato gestionado. Revisor de contexto fresco
(subagente `Explore`, sólo lectura, `git archive` en `/private/tmp`),
`.venv/bin/python` 3.12.12. El diseño viene de la ronda pre-code de PR A
(`issue171-pr-a-adversarial-2026-10-15.md`, BLOCKER P4).

## Alcance

`context_package.py` (`_block_newer_than_runtime`, `context_status`,
`plan_context_change`), `version.compare_template_versions`, `DETAILED_CONTRACT`,
bump `0.1.0-beta.26` → `0.1.0-beta.32` con beta.26 congelada, `AGENTS.md` y
`AN-KLA.md` del repo, ADR-0009 Enmienda 1.

## Modelo de amenazas

La etiqueta `version` del bloque viene de `AGENTS.md` (no confiable). Sólo
puede cambiar un diagnóstico por otro igual de bloqueante o negar
`install`/`update`; nunca suprimir uno.

## Verificación

- Fuzz con 24 etiquetas × 4 estados de contrato: ninguna da `ok:true` con
  contrato editado; `orphan_managed_contract` y `managed_block_modified`
  intactos; los tipos no-string fallan en el parse.
- Hashes de beta.26 recalculados desde los tags `v0.1.0-beta.25`…`beta.31` y
  `1a6721f`: los ocho coinciden. El fixture es byte a byte la release.
- `upgrade inspect` niega, `upgrade verify` e `integration status` dan
  `ok:false`, `adopt-baseline` falla cerrado y `uninstall` es seguro.
- Mutantes: 9 de 11 detectados en la ronda; los 2 supervivientes se
  detectan tras las correcciones (abajo).
- Suite completa en el archive: 1228 tests OK (skipped=74).

## Hallazgos y correcciones

Decisión de la ronda: **proceed** (0 BLOCKER, 0 MAJOR, 8 MINOR). Todos
aplicados antes de publicar beta.32, porque el texto del contrato todavía
no tiene etiqueta publicada:

| ID | Hallazgo | Corrección |
|---|---|---|
| m1 | Mutante: suprimir `managed_contract_missing` con etiqueta nueva sobrevivía | Test `test_newer_label_never_hides_missing_contract`; ahora el mutante falla |
| m2 | Mutante: chequeo de `plan` tras el de contrato sobrevivía | Test `test_refusal_precedes_contract_check`; ahora el mutante falla (4 fallos) |
| m3 | Runtimes ≤ b31 siguen dando el veredicto engañoso | El contrato indica comparar `current_template_version` con `template_version` |
| m4 | `status` sin memoria no informa `runtime`; faltaba `runtime_version` | Contrato: `--version`, `context status` → `runtime_version`, `status` sólo con memoria |
| m5 | "usa la instalación vigente" podía leerse como permiso para instalar | Reformulado: reportar, usar otro intérprete ya instalado, sin instalar ni modificar sin el operador; la etiqueta puede estar alterada |
| m6 | `0.1.0` congelada no podrá ser `TEMPLATE_VERSION` | Declarado en la Enmienda 1; el test de #124 ya lo impide |
| m7 | Dígitos no ASCII y ceros a la izquierda contaban como etiqueta más nueva | `compare_template_versions` exige etiquetas ASCII canónicas; tests |
| m8 | Tablas de diagnósticos y README desfasados | `docs/context-package.md`, `docs/upgrade-agent-flow.md`, README alineados |

`AN-KLA.md` del repo regenerado desde `DETAILED_CONTRACT`; `context update` da
`noop` y `context status` da `ok:true` sin diagnósticos.

## Límites declarados

- Las versiones ya publicadas (≤ b31) no emiten las señales nuevas: no se
  arreglan hacia atrás; lo mitiga la instrucción m3 del contrato.
- `adopt-baseline` con bloque más nuevo responde el genérico
  `context_baseline_managed_state_invalid` (falla cerrado; no se cambia aquí).

## Decisión

- [x] proceed (ronda); correcciones MINOR aplicadas y verificadas con mutantes.
- [ ] fix-and-retry
- [ ] escalate
