# Índice de gobernanza — an-kla-memory

<!-- dureza: [C] índice operativo — se actualiza con registro al crear/cerrar actas -->

> Pre-flight de Directivas v0.2.0 §3.2 (krathos): antes de ejecutar una
> instrucción del dueño con efecto en este repo, leer este índice. Orden
> inverso temporal, sin contenido normativo (solo punteros).

## Estado al 17-10

| Ítem | Estado |
|---|---|
| Base | `main@9401115` (PR #182) antes del PR de release de beta.34 |
| Release vigente | `v0.1.0-beta.34` (en publicación; anterior `v0.1.0-beta.33`). Notas y actas en `docs/releases/` |
| Plantilla gestionada | `0.1.0-beta.33` (sin cambios en beta.34) |
| CI | Sin CI remota; autoridad = `scripts/ci_local.py --simulate-ci` con `.venv/bin/python` (Python 3.12) |

## Issues abiertos (verificados 17-10)

| Issue | Tema | Prioridad |
|---|---|---|
| #140 | Autoridad humana verificable del host para checkpoint (ADR-0052 diseñada; desbloquea expertoGobernanza #90) | Alta; requiere orden explícita del dueño |
| #181 | `status`/`nu` cadena vacía: `inventory` vigente frente a `is_active` no vigente | Baja |
| #167 | Batería v2 de escala (concurrencia, compactación, crash mid-commit) | Media, si se retoma escalado |
| #166 | `retrieve` índice-primero | Baja |
| #168 | Sustrato SQLite opcional | Condicional a #167 |
| #169 | Caché de segmentos (ADR-0056) | Condicional: `snapshot()` > 0,5 s |
| #58 | G4 identidad de agente y memoria multi-scope | Horizonte, diferido por diseño |

Cerrados desde el estado anterior de este índice (29-08): #95, #56 (G2) y
#57 (G3), entre otros; el detalle está en GitHub y en `docs/releases/`.

## Decisiones de gobierno vigentes

| Fecha | Qué | Dónde |
|---|---|---|
| 17-10 | Toda release lleva ronda adversarial de release con marcador de gate, auditoría §9 en venv limpio y wheel adjunto como asset (restituidos los de beta.31–33) | `docs/practicas-ingenieria.md` §1 y §9; `docs/releases/v0.1.0-beta.34.md` §Wheels |
| 16-10 | Los consumidores se actualizan proyecto a proyecto al usarlos, con todas sus instalaciones (venv y CLI global) a la vez y luego `context update` con el mismo intérprete | `docs/releases/v0.1.0-beta.32.md` y `v0.1.0-beta.34.md` (§Actualizar, §Límites) |
| 13-10 | Python 3.12 o superior para rondas, suites y CI local (`.venv/bin/python`) | `docs/adversarial-template.md` |
| 28-08 | Deferimiento Windows vigente | memory krathos / actas beta.18 |
| 27-08 | Merge #94 + cierre #93 (orden del dueño) | git 79610ac |
