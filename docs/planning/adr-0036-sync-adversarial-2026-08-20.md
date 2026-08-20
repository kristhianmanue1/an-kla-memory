# Ronda adversarial — sincronización ADR-0036 con la implementación (2026-08-20)

Punto 2 del plan `plan-backlog-2026-08-20.md`. Revisor independiente
(subagente). Una pasada: fix-and-retry (1 fix obligatorio) → aplicado →
proceed.

## Alcance

`docs/architecture/0036-*.md` (Estado, celda de `repo_context`, sección
"Historia del mecanismo"), `docs/README.md` (fila 0036 del registro +
resumen), `tests/test_adr_registry.py` (recuentos 33/3). Docs-only; sin
cambios de código ni contrato.

## Modelo de amenazas

Deriva documento↔implementación: un ADR que contradice el código publicado
erosiona la autoridad del registro. El gate `check_adr_registry` sólo valida
registro↔archivo↔vocabulario, no estado↔implementación: la deriva era
estructuralmente invisible y esta ronda ataca también los residuos que el
gate no ve (texto de resumen).

## Hallazgos y correcciones

| Hallazgo | Riesgo | Corrección |
|---|---|---|
| Resumen del registro decía "32 aceptadas / 4 propuestas" tras mover 0036: inconsistencia invisible para gate y test | Exactamente la clase de deriva silenciosa que este punto pretende eliminar | Resumen actualizado a 33/3 |
| Celda omitía dos mapeos a `git_unavailable` existentes en código (stdout ≠ 2 líneas; OSError al resolver rutas) | Descripción incompleta del contrato de fallo | "Git ausente, timeout o salida inesperada → git_unavailable" |
| Línea en blanco partía la tabla Markdown del registro (preexistente) | Cosmético | Corregido de paso |

## Errata registrada (no retroactiva)

La premisa (b) del hallazgo H2 en `backlog-prioridades-adversarial-2026-08-20.md`
y del punto 2 del plan ("la implementación lee `.git` como archivo") era
falsa respecto de `main` final: esa desviación (commit `a8e94b5`) fue
revertida dentro del propio #83 (`e249994`) tras ronda adversarial con
Gemini; `b70561e` ya contiene el mecanismo `git rev-parse`. Los documentos
fechados no se editan retroactivamente; esta errata es el registro vigente.
La parte (a) de H2 (estado "Propuesta/No iniciada" pese a implementación)
sí era real y es lo que este punto corrige.

## Verificación de canonicidad / determinismo

Fidelidad verificada por el revisor contra `an_kla/startup.py`
(`--git-dir` vs `--git-common-dir`, `GIT_TIMEOUT_SECONDS=5`, saneo `GIT_*`,
mapeos de fallo), contra Git (`a8e94b5`/`e249994` existen; `#83` fue
squash; `git describe` → sin tag post-beta.14) y contra el gate:
`check_adr_registry: OK — 36 ADRs (aceptada=33, propuesta=3)`.
Suite completa: 544/544 OK.

## Límites declarados

- El gate sigue sin cruzar estado↔implementación; esta ronda fue manual.
  Endurecer `check_adr_registry` para detectarlo automáticamente queda
  como mejora propuesta al maintainer (no gate de este ciclo).
- `ADR-0030` ("Propuesta en reevaluación") y `ADR-0035`/`ADR-0029`
  ("Propuesta") son correctas hoy; sin acción.

## Decisión

- [x] proceed
- [ ] fix-and-retry
- [ ] escalate
