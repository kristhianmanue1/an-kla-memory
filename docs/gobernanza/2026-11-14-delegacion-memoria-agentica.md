# Delegación del maintainer — esfuerzo de memoria agéntica

<!-- dureza: [C] acta operativa — se actualiza con registro, como el resto de docs/gobernanza -->

- **Fecha del registro:** 2026-11-14.
- **Otorga:** el Operador, dueño y maintainer de
  `github.com/kristhianmanue1/an-kla-memory`.
- **Recibe:** el capitán de an-kla-memory designado por el orquestador
  devHerdrExpert. Los ejecutores y revisores que el capitán lance actúan sólo
  dentro de su encargo (un spike o informe; un dictamen de sólo lectura);
  la potestad sobre ramas, commits, push, PR y merge es del capitán.
- **Fuente:** `mandato-2-adr.md` del orquestador al capitán (sección
  AUTORIDAD), archivo no versionado fuera del repo:
  `/var/tmp/orquestador-memoria/capitanes/ankla/mandato-2-adr.md`,
  `sha256:78d414dd8621a450cf78242d35751142a0ec9bebf3111b828c1786dd488f9cf3`.
  La fuente transcribe palabras del Operador dichas en la sesión del
  orquestador; este repo no puede verificarlas por sí mismo.

## Citas literales, tal como las transcribe la fuente

- 2026-11-13: «Para lo cual pude lanzar capitanes para cada uno de estos
  proyectos con claude opus y sus ejecutores con sonnet como modelos externos
  opencode con glm o deepseek, agy y codex».
- 2026-11-13: «nota para estas operaciones tienes permitido todo tipo de
  comandos de github , commits, pr, merges, etc».
- 2026-11-13, sobre las recomendaciones D1 a D8 (entre ellas D5, lanzar
  capitanes, y D6, registrar la delegación en cada repo): «adelante con
  recomendaciones».

## Alcance, según la fuente

«ramas, commits, push de ramas, PR contra `main` sin squash y merge de PR
tras gates en verde y revisión adversarial `proceed`, sólo para el esfuerzo
de memoria agéntica.»

- **Repo:** este registro cubre sólo an-kla-memory.
- **Gates:** los de `AGENTS.md` y `docs/practicas-ingenieria.md` (§5, §7).
- **Revisión adversarial `proceed`:** la exige la delegación para todo
  merge de este esfuerzo, además de los casos en que §1 ya la exige.

**Reservado al Operador, uno por uno:** tags, releases, instalar hooks o
servicios, visibilidad, licencia, publicar.

**Vetado:** force-push, borrar ramas remotas, reescribir historia publicada.

Si un hook o guardarraíl bloquea un comando, no se esquiva: se reporta.

## Vigencia

La delegación no autoriza trabajo por sí misma: cada paso lo abre un
mandato del orquestador, que fija su fase. El mandato que ordena este
registro dice: «Este mandato autoriza los pasos 0 y 1 de tu reparto, y nada
de código de producto todavía» y «PARA AHÍ. No empieces la fase A de
código». Una rama `feat/` o `fix/` de este esfuerzo necesita un mandato
posterior que la abra.

## Qué no cambia

El canon del repo sigue mandando: ADR antes que código en PR `docs/`
separado (`docs/practicas-ingenieria.md` §3), spike antes de tocar
almacenamiento o concurrencia (§2), Python 3.12 con `.venv/bin/python`
(§5), y el bloque gestionado de `AGENTS.md`/`AN-KLA.md` sólo vía
`context plan` → `context apply` (`CONTRIBUTING.md`). Por eso este registro
no edita `AGENTS.md`: el punto de entrada es `docs/gobernanza/INDEX.md`,
que el pre-flight de gobernanza manda leer antes de ejecutar una orden del
dueño.
