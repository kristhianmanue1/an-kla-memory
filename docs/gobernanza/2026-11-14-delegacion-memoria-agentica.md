# Delegación del maintainer a agentes — esfuerzo de memoria agéntica

<!-- dureza: [B] acta de autoridad — sólo se cambia con nueva orden del dueño -->

- **Fecha del registro:** 2026-11-14.
- **Otorga:** el Operador, dueño y maintainer de
  `github.com/kristhianmanue1/an-kla-memory`.
- **Recibe:** el orquestador devHerdrExpert y los agentes que lance para este
  esfuerzo (capitán de an-kla con Claude Opus, ejecutores con Claude Sonnet y
  revisores de otra familia).
- **Registra:** el capitán de an-kla, por mandato del orquestador
  (`mandato-2-adr`, decisión D6: registrar la delegación en cada repo).

## Citas literales del Operador

Dichas en la sesión del orquestador:

- 2026-11-13: «Para lo cual pude lanzar capitanes para cada uno de estos
  proyectos con claude opus y sus ejecutores con sonnet como modelos externos
  opencode con glm o deepseek, agy y codex».
- 2026-11-13: «nota para estas operaciones tienes permitido todo tipo de
  comandos de github , commits, pr, merges, etc».
- 2026-11-13, sobre las recomendaciones D1 a D8 (entre ellas D5, lanzar
  capitanes, y D6, registrar la delegación en cada repo): «adelante con
  recomendaciones».

## Alcance

Sólo para el esfuerzo de **memoria agéntica del ecosistema** (an-kla-memory,
skopos y agora; entregas E1 y siguientes de la arquitectura del orquestador).

| Permitido | Condición |
|---|---|
| Crear ramas y worktrees, commits, push de ramas | ramas `docs/…`, `feat/…`, `fix/…` |
| Abrir PR contra `main` | sin squash (`CONTRIBUTING.md`) |
| Merge de PR | gates en verde (`AGENTS.md`, `docs/practicas-ingenieria.md` §5 y §7) y ronda adversarial `proceed` (§1) |

**Reservado al Operador, uno por uno:** tags, releases, instalar hooks o
servicios, cambiar visibilidad, elegir licencia, publicar.

**Vetado:** force-push, borrar ramas remotas, reescribir historia publicada.

Si un hook o guardarraíl bloquea un comando, no se esquiva: se reporta.

## Qué no cambia

El canon del repo sigue mandando: ADR antes que código en PR `docs/`
separado (§3), spike antes de tocar almacenamiento o concurrencia (§2), ronda
adversarial con revisor de otra familia (§1), Python 3.12 con
`.venv/bin/python` (§5), y `AGENTS.md`/`AN-KLA.md` gestionados sólo por
`context plan` → `context apply`. Esta delegación no se extiende a trabajo
fuera del esfuerzo citado.
