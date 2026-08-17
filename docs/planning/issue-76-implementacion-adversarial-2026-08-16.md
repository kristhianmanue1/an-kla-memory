# Ronda adversarial — implementación del diagnóstico de arranque

**Fecha:** 2026-08-16
**Artefacto:** rama `feat/issue-76-startup-diagnostic`, commits `a8e94b5` y
`836c29b` (PR #83)
**Revisor:** `agy` con `gemini-3.1-pro-high`
**Contexto:** `fresco` — sesión y proveedor distintos del autor
**Modelo:** `gemini-3.1-pro-high`
**Ejecución:** sobre un clon desechable del repositorio, sin `.an-kla`, de modo
que el revisor no podía tocar el repositorio real ni su memoria
**Decisión:** `fix-and-retry`

Es la primera ronda de este ecosistema con decorrelación **por proveedor** y no
sólo por contexto.

## Hallazgos aceptados

### [HIGH] `repo_context` clasificaba mal submódulos y subdirectorios

**Problema:** la implementación se había desviado del ADR: en vez de preguntar a
Git miraba si `.git` era archivo o directorio. Un submódulo lleva `.git` como
gitlink —archivo— y quedaba clasificado como `linked_worktree`; cualquier
subdirectorio de un repositorio quedaba como `not_a_repo`.

**Verificación independiente del autor:**

```
$ an-kla --project-root <repo>/sub startup-diagnostic  ->  "repo_context": "not_a_repo"
$ git -C <repo>/sub rev-parse --git-common-dir --git-dir  ->  ../.git  /…/repo/.git
```

**Corrección:** se revierte la desviación y se implementa el mecanismo que el
ADR especificaba, `git rev-parse --git-dir --git-common-dir`, comparando rutas
resueltas. Se añaden tests de submódulo y de subdirectorio. Las variables `GIT_*`
del entorno se retiran para que la respuesta describa la ruta dada y no el
ambiente. **Estado:** cerrado.

La lección va más allá del hallazgo: la desviación se había declarado como una
mejora —evitar un subproceso en una operación read-only— y era peor. Declararla
no la volvía correcta.

### [HIGH] `identity_status` nulo contradecía el ADR

**Problema:** el ADR exige reexpresar los nueve valores publicados "verbatim,
sin redefinir", y la implementación emitía `null` cuando no podía observarlos.

**Corrección:** el bloque `identity` gana `evaluated`. Ese campo es el que
carga "no se pudo observar"; los nueve valores conservan su significado exacto y
ninguno se reutiliza para representar un fallo. El ADR se precisa en el mismo
sentido. **Estado:** cerrado.

Se rechaza la corrección propuesta por el revisor —derivar hacia `absent` o
`conflict`—: inventar una identidad para no admitir que no se pudo observar es
exactamente el fallo que este diagnóstico existe para evitar.

### [HIGH] Excepción no prevista filtraría un traceback

**Problema:** el CLI captura una tupla de excepciones esperadas. Una no prevista
—`TypeError`, `KeyError`— aborta con traceback, que lleva rutas absolutas
(§11.1).

**Corrección, con alcance acotado:** el diagnóstico queda envuelto y responde
`an-kla error: startup_diagnostic_failed`. La red de resguardo general del CLI
es un cambio de comportamiento para todos los comandos y no se decide aquí:
queda como issue propio. **Estado:** cerrado para este comando, abierto como
issue para el CLI.

### [MED] TOCTOU entre presencia e integridad

**Problema:** si el store desaparece entre ambas comprobaciones, el resultado
era `present` + `failed`, que llama "roto" a un store que ya no existe.

**Corrección:** `FileNotFoundError` durante la verificación produce
`not_evaluated` con detalle `store_disappeared`. **Estado:** cerrado.

## Lo que el revisor atacó sin éxito

- Escrituras fuera del lease del reader gate: comprobó que un project root sin
  memoria no llega a abrir el gate, porque la integridad corta antes.
- Fugas de ruta en las excepciones ya mapeadas: la corrección de `836c29b` las
  cubre.
- Combinaciones que el schema rechazara y el código pudiera emitir.

## Hallazgo del autor, previo a la ronda

Revisando el propio código antes de someterlo se detectó que `str(exc)` sobre
`OSError` publica la ruta absoluta del store en `integrity_detail` y en
`identity.error_code`. Corregido en `836c29b`; el revisor confirmó que la
corrección era efectiva.

## Verificación posterior

- `unittest discover` → 531 tests, `OK`.
- `ci_local.py --simulate-ci` → `OK` en los cuatro pasos.
- `check_clean_wheel.py` → `OK`.

## Nota de método

Dos rondas consecutivas con contexto fresco han devuelto `fix-and-retry` sobre
artefactos que su autor daba por correctos. La segunda encontró que una
desviación **declarada** respecto del ADR era peor que lo que el ADR pedía. La
declaración de una desviación documenta la decisión; no la valida.
