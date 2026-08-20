# Ronda adversarial — decisión #45 (2026-08-20)

Punto 5 del plan `plan-backlog-2026-08-20.md`. Revisor independiente.
Dos pasadas: fix-and-retry → proceed. Resultado del punto: **escalate**
(decisión final del maintainer; sin implementación).

## Alcance

`docs/planning/issue-45-decision-2026-08-20.md` (v2). Documento de
decisión sobre cómo AGENTS.md referencía docs del proyecto sin drift.

## Hallazgos y correcciones

Ronda 1 (fix-and-retry; premisa empírica verificada con comandos por el
revisor: warning y `will_be_absorbed_by_apply` reproducidos al byte):

| Hallazgo | Corrección en v2 |
|---|---|
| Omitía la variante doble huella que el plan prescribía | Sección "Requisito mecánico común": la doble huella es el mecanismo, no una opción |
| No enfrentaba el rechazo explícito de ADR-0035 §"Por qué no un segundo bloque project" a (a) | (a) rebajada a DIFERIDA aceptando las objeciones sin refutarlas; paso 2 exige ADR que las resuelva |
| Semántica de (a) indeterminada; sin matriz ni costos | Matriz de interacción + costos por fila |
| #44, actores/riesgos, número ADR reservado, autoridad presumida | Todos nombrados/corregidos |

Ronda 2: 7/7 cerrados; verificación contra código real de la fila crítica
("la ceremonia de (d) es una vez"): confirmada contra `upgrade.py:88-99`,
`context_package.py:607-616` y ADR-0035 §4 ("un upgrade posterior no debe
pedir confirmación por esos mismos bytes"). Nits N1-N3 aplicados.

## Decisión

- [x] proceed (documento de decisión publicable; el issue queda escalate)
- [ ] fix-and-retry
- [ ] escalate

En la mesa del maintainer: autorizar paso 1 (implementar ADR-0035:
adopción explícita de baseline, con su secuencia spike→ADR→código).
