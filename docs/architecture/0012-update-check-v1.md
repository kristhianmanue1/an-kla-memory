# ADR-0012: Read-only release update check

- **Estado:** Aceptada e implementada en `v0.1.0-beta.4`
- **Fecha:** 2026-08-03
- **Decide sobre:** comportamiento del CLI al detectar versiones publicadas

## Contexto

El contrato público (`AN-KLA.md`, `capabilities()`) declara que AN-KLA **no
ejecuta el gestor de paquetes ni se reemplaza a sí mismo**. Esto es correcto
como garantía de seguridad, pero deja al operador sin aviso proactivo cuando
existe una release más reciente. El issue #11 mostró además que la fricción de
migración entre betas es alta cuando el drift es cosmético.

Queremos avisar al usuario que hay una versión nueva **sin violar**:

- `package_self_update: false` en `capabilities()`;
- "AN-KLA no ejecuta el gestor ni se reemplaza a sí mismo" en `AN-KLA.md`;
- el principio de no telemetría declarado en README.

## Análisis de buenas prácticas (pip, npm, gh, poetry, uv, cargo)

De ese conjunto emergen **diez principios** comunes:

| # | Principio | Cumple AN-KLA |
|---|---|---|
| 1 | Read-only: nunca instala ni muta | ✅ |
| 2 | Cache temporal (24h típico) | ✅ (`~/.cache/an-kla/update-check.json`) |
| 3 | Timeout corto, fail-closed silencioso | ✅ (3s, status `fetch_failed`) |
| 4 | Opt-out por env var | ✅ (`AN_KLA_NO_UPDATE_CHECK`) |
| 5 | Skip en CI (CI, GITHUB_ACTIONS) | ✅ |
| 6 | Sin telemetría más allá del User-Agent | ✅ (sólo GET + UA `an-kla-memory/<v>`) |
| 7 | Aviso a stderr, no a stdout | ✅ |
| 8 | Sin auto-aplicar ni sugerir downgrade | ✅ (`is_newer_release` estricto) |
| 9 | HTTPS, endpoint canónico, source pinned | ✅ (`api.github.com/...`) |
| 10 | Canal pre-release explícito | ⚠️ acepta pre-releases porque la beta lo es |

pip, npm, poetry y gh cumplen los 10; AN-KLA cumple 9 plenos y uno matizado
(canál pre-release es el vigente en la beta).

## Decisión

Se añade `an_kla/update_check.py` con estas garantías:

- **Source:** `https://api.github.com/repos/kristhianmanue1/an-kla-memory/releases?per_page=1`
  (la ruta `/releases/latest` **excluye prereleases** por diseño de GitHub,
  lo que haría invisibles todas las betas al hook).
- **Cache:** `~/.cache/an-kla/update-check.json` (respeta `XDG_CACHE_HOME` y
  `LOCALAPPDATA` en Windows), TTL 24h.
- **Skip automático:** `CI`, `GITHUB_ACTIONS`, `AN_KLA_DISABLE_UPDATE_CHECK`,
  `AN_KLA_NO_UPDATE_CHECK=1`.
- **HTTP:** timeout 3s, UA `an-kla-memory/<VERSION>`, ningún header adicional.
- **Comparación:** `is_newer_release()` respeta orden semver PEP 440 (`alpha <
  beta < rc < final`).
- **Salida:** `UpdateNotice.notice` es una cadena multilinea a stderr. stdout
  queda limpio para JSON programático.
- **Subcomando explícito:** `an-kla check-updates` fuerza re-validación sin
  tocar la cache ni respetar los skip env.
- **Flag global:** `--no-update-check` desactiva el hook para esa invocación.
- **`capabilities()` actualizado:** nuevo bloque `update_check` declara source,
  canal, TTL, opt-out y `install_or_self_replace: false`.

## Por qué no

- **git ls-remote como fuente principal**: no resuelve `html_url`, `prerelease`
  ni `body`; requiere git en PATH y credenciales para repos privados.
- **PyPI Simple API**: el proyecto no publica en PyPI por decisión explícita del
  README ("La beta se distribuye desde GitHub, no desde PyPI").
- **Telemetría diferida / STUN de versiones**: contradice el principio de
  minimización del proyecto.

## Consecuencias

- Mientras el repo sea privado, el endpoint devuelve 404 y la cache registra
  `fetch_failed`. El comportamiento es **fail-closed silencioso**, no errores.
- Cuando el repo se haga público, la detección empezará a funcionar sin cambios
  de código.
- `capabilities()` ahora declara una superficie nueva: los consumidores pueden
  pinchar el campo `update_check.enabled` antes de habilitar el hook en su
  entorno.
- No hay changes en `package_self_update` (sigue `false`): seguimos sin
  ejecutar pip ni reemplazarnos.

## Pendiente

- Documentar el hook en `AN-KLA.md` una vez aprobado (no se incluyó en esta
  iteración para no mutar el contrato administrado sin autorización).
- Evaluar channel pre-release vs stable cuando salga `v0.1.0` final.
