# Índice de gobernanza — an-kla-memory

<!-- dureza: [C] índice operativo — se actualiza con registro al crear/cerrar actas -->

> Pre-flight de Directivas v0.2.0 §3.2 (krathos): antes de ejecutar una
> instrucción del dueño con efecto en este repo, leer este índice. Orden
> inverso temporal, sin contenido normativo (solo punteros).

## Estado al 29-08

| Ítem | Estado |
|---|---|
| HEAD | `01d7c788` main, árbol limpio |
| Release vigente | `v0.1.0-beta.19` (taggeada y publicada 29-08, REL proceed) |
| Ciclo #46 (sealed-export) | **CLOSED** — T1-T6 merged (#96→#101) |
| CI | GitHub Actions inactiva por presupuesto; autoridad = `scripts/ci_local.py` (4 gates) |

## Issues abiertos (verificados 29-08)

| Issue | Tema | Prioridad propuesta (especialista, run ankla-informes-20260829-01) |
|---|---|---|
| #95 | Deuda ADR-0042 → quedó C-A/C-B documental | **P1** este ciclo (≤ medio día) |
| #56 | G2 hooks gobernados | P2 próximo ciclo — primero cerrar 5 decisiones del maintainer (docs/planning/g2-g4-disenos-2026-08-20.md) |
| #57 | G3 store externo | P3 tras G2 — máximo riesgo físico; tensión DoD-Windows sin resolver |
| #58 | G4 memoria multi-scope | Diferido por diseño |

## Decisiones de gobierno vigentes

| Fecha | Qué | Dónde |
|---|---|---|
| 28-08 | TECH_DEBT grace #95 (700 líneas) registrada | scripts/check_sizes.py + issue #95 |
| 28-08 | Deferimiento Windows vigente | memory krathos / actas beta.18 |
| 27-08 | Merge #94 + cierre #93 (orden del dueño) | git 79610ac |

## Deuda documental abierta

| Qué | Issue |
|---|---|
| C-A: entrada muerta TECH_DEBT en check_sizes.py:48-56 | #95 |
| C-B: encabezados duplicados §2 apéndice ADR-0042; §5 vive en ADR corto | #95 |
