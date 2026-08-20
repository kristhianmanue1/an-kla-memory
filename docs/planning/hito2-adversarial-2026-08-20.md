# Ronda adversarial HITO 2 — puntos 1–8 (2026-08-20)

Re-ataque de conjunto tras cerrar los puntos 5–8, incluida la
interacción con el HITO 1. Revisor independiente con sondas propias
(store real con checkpoint git/v1 + records con/sin verified_at,
réplicas de fingerprints pre/post, cmp par a par de schemas).
Veredicto: **proceed**.

## Alcance

Commits: `78b2048` (#45), `4b27c41` (#79), `e0a1b9a` (#67), `65e8e79`
(#71), contra el fondo del HITO 1 (`e15f019`…`a060e4b`).

## Hallazgos y correcciones

| Hallazgo | Resolución |
|---|---|
| La lista de decisiones acumulada del plan (escrita antes del hito 2) omitía #79 y #67 | Este documento fija la lista completa de 6 ítems (abajo); el reporte final la usa |
| Error de conteo heredado del HITO 1: "66/66 schemas" — son **65/65** pares JSON (sustancia correcta: byte-idénticos) | Corregido aquí; docs fechados no se reescriben (convención del repo) |
| Nit: anotación del supersede en 0023 no nombra la cláusula de bump de checkpoint | Sin acción (ADR-0038 §Supersede cubre el fondo); nombrarla si 0030 se reevalúa |

## Verificación de interacciones (evidencia del revisor)

- **#79 × #50**: sin interferencia. `write_policy.py` byte-idéntico
  desde `f9984ef`; fingerprints separados (write sin cambio, checkpoint
  con el previsto por ADR-0038 §5). Sonda integrada: checkpoint git/v1 +
  corpus 1-evaluable/2-sin-campo → counts correctos `1/2/0` sobre la
  población servida; `retrieve` no expone `source_state`.
- **Registro**: gate OK 38/35/3, filas 0023/0030 anotadas con precisión.
- **#67 × #71**: coherentes; ninguno autoriza cambio de motor.
- **#45 × ADR-0035**: sin choque; la recomendación exige la secuencia
  que el propio ADR-0035 impone.
- **Batería**: suite 575/575 OK; `ci_local --simulate-ci` OK 4/4;
  `check_adr_registry` OK; schemas 65/65 byte-idénticos.
- **Deriva ADR↔código**: 0037/0038 consistentes; decisiones/spikes en
  `docs/planning`; `VERSION` intacta; `capabilities()` determinista con
  ambos bloques aditivos.

## Decisiones acumuladas en la mesa del maintainer (lista vigente)

1. **Tag beta.15 sobre `f9984ef` exacto** (HITO 1); todo lo posterior
   viaja en beta.16 con ronda REL propia.
2. **#45 paso 1**: autorizar implementación de ADR-0035 (adopción
   explícita de baseline), secuencia spike→ADR→código.
3. **#79**: confirmar el supersede del nombre `git/v1` (la alternativa
   era renombrar y reservarlo para la variante tool_observed de #56).
4. **#67**: dispensar o exigir las métricas por estrategia
   (`evaluate-v2`) que el issue pedía como condición de salida.
5. **#67**: ADR density-aware futuro para la inversión de relevancia, o
   archivarla como límite conocido del contrato.
6. **#71**: cerrar el issue con la decisión `no-action` (+ #46 cuando
   se ejecute el punto 10 de este plan).

## Decisión

- [x] proceed
- [ ] fix-and-retry
- [ ] escalate
