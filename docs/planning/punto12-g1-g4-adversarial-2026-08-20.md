# Ronda adversarial — punto 12: G1 implementado + diseños G2–G4 (2026-08-20)

Punto 12 del plan `plan-backlog-2026-08-20.md` (#55–#58). Revisor
independiente con ejecución empírica de casos (tempdir, CLI real,
validator JSON Schema). Dos pasadas: fix-and-retry → proceed.

## Alcance

G1: ADR-0039, `an_kla/integration.py`, comando `integration status`,
schema `integration-status-v1` (docs/+an_kla/), capabilities
`integration`, 8 tests. G2–G4: `docs/planning/g2-g4-disenos-2026-08-20.md`
(diseños de entrada, sin código — declarado como límite del punto).

## Hallazgos y correcciones

Ronda 1 (fix-and-retry):

| Hallazgo | Corrección |
|---|---|
| Media — exit≠0 y fuga §11.1 en el plano contexto (symlink/EACCES): contradecía la regla congelada 4 del ADR nuevo | Capa de integración captura OSError/ValueError → `presence: "unreadable"` + `observation_error` estable, exit 0; schema ampliado; verificado por el revisor con ejecución real de los 4 casos y validación de payloads |
| Med-BAJA — sin tests de footprint/symlink/EACCES/corrupt-block | 4 tests añadidos (incl. footprint VACÍO del tempdir completo) |
| Baja — ejemplo JSON del ADR imposible; cita #57/#58→G2; "verbatim" sugería copia completa; numeración 0039 colisionada; quirk integrity_detail; decisiones G2-G4 incompletas | Todo corregido (ejemplo ahora completo y válido contra su schema) |

Ronda 2: 8/8 cerrados con evidencia propia del revisor; 2 nits LOW
aplicados igualmente (numeración en docs de #46; ejemplo completado).

## Verificación

- Read-only confirmado empíricamente: cero archivos creados con store
  ausente; sólo `.reader-gate` (documentado) con store presente.
- Suite 583/583 OK; registro 39/36/3; `docs/`≡`an_kla/` schemas
  byte-idénticos; capabilities determinista.
- G2–G4 respetan ADR-0031 (secuencia G2→G3→G4 = dependencias
  declaradas; sin congelar vocabulario ajeno).

## Decisión

- [x] proceed
- [ ] fix-and-retry
- [ ] escalate
