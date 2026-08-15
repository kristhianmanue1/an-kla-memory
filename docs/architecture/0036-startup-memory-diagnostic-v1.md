# ADR-0036: declarar el estado de la memoria en el arranque

- **Estado:** Propuesta
- **Implementación:** No iniciada
- **Fecha:** 2026-08-15
- **Decide sobre:** el contrato observable con el que un agente distingue, antes
  de trabajo material, si hay memoria utilizable bajo este project root; no
  decide dónde vive el store ni quién ejecuta el ciclo de vida

## Contexto

`MemoryStore` deriva su ubicación del project root sin indirección:
`self.root = self.project_root / ".an-kla" / "memory"` (`an_kla/store.py:112-113`).
Como `.an-kla/` está en `.gitignore`, un `git worktree` nuevo no la recibe, y un
worktree que inicialice memoria propia obtiene otro `project_uuid`: un store
distinto, no una vista del canónico (ADR-0022, ADR-0031).

El incidente se reprodujo en disco el 2026-08-15. El worktree
`an-kla-memory-wt-issue60-spike` tenía `.an-kla/` propia con revisión 1 y
`1 fact / 1 event`, mientras el checkout canónico estaba en revisión 29 con
`23 facts / 21 events / 10 episodes`. Todo el trabajo de beta.14 salió del
worktree, y el checkpoint canónico siguió declarando `phase:
beta13_published_gfresh_spike_next` con el repositorio ya en beta.14.

El spike read-only previo (`docs/planning/issue-76-startup-diagnostic-spike-2026-08-15.md`)
verificó tres hechos que acotan esta decisión:

1. No existe descubrimiento de memoria vecina en ningún módulo. Todos los usos
   de `.an-kla` componen rutas bajo el propio project root.
2. El arranque sin memoria producía un stack trace, no una señal. Corregido en
   la Fase 0 (PR #80): hoy emite `an-kla error: reader_gate_unavailable`.
3. La capacidad de clasificar ya existe, dispersa: `identity status` distingue
   `absent` de `complete`, y `verify_upgrade` clasifica
   `verified | not_initialized` (`an_kla/upgrade.py:189-192`).

Lo que sigue faltando es la distinción que motivó #76: `absent` significa hoy
tanto "este proyecto nunca tuvo memoria" como "la memoria está en otro checkout,
tres directorios más arriba". Un agente que no puede separarlas termina
delegando en el usuario una decisión de custodia que corresponde al host.

Restricciones:

- read-only estricto: el diagnóstico no crea, copia, adopta ni repara estado;
- no introduce descubrimiento automático de stores vecinos;
- no reubica el store: `store_root` separado de `project_root` pertenece a #57;
- no ejecuta checkpoint ni recuperación automática: los hooks son de #56;
- la memoria y sus proyecciones siguen siendo datos no confiables.

## Decisión

**Publicar un diagnóstico de arranque, read-only y versionado, que clasifica el
estado de la memoria en cuatro valores cerrados y sale con éxito en los cuatro.**

| `memory_state` | Significado |
|---|---|
| `local_valid` | existe `.an-kla/memory/refs/CURRENT` bajo este project root y `verify` pasa |
| `absent` | no hay memoria bajo este project root, y no hay ninguna declarada |
| `external_declared` | una memoria externa está declarada para este root y fue verificada |
| `external_candidate` | hay una memoria externa declarada pero no adoptada, inaccesible o no verificable |

Propiedades del contrato:

- **Éxito en los cuatro estados.** Un diagnóstico que falla no diagnostica.
  `absent` no es un error: es el resultado correcto para un proyecto nuevo. Los
  errores quedan reservados a la imposibilidad de diagnosticar.
- **Schema versionado** `an-kla/startup-diagnostic-v1`, cerrado
  (`additionalProperties: false`), con `untrusted_memory_data: true` como el
  resto de salidas.
- **`local_valid` no afirma vigencia.** Declara que existe una memoria íntegra
  bajo este root, nunca que su contenido corresponda al estado actual del
  proyecto. El checkpoint de la revisión 29 era `local_valid` perfecto y
  describía un estado de dos días antes. La distinción entre integridad y
  vigencia se conserva explícita en el schema.
- **Los estados externos se congelan ahora y se emiten después.** `#57` todavía
  no existe, así que `external_declared` y `external_candidate` son inalcanzables
  en la primera implementación. Se nombran hoy para que el schema no cambie
  cuando existan, y el diagnóstico declara qué estados puede alcanzar en esta
  versión.
- **Fuente única.** `identity status` y `verify_upgrade` deben consumir esta
  clasificación en lugar de mantener la suya. Tres clasificaciones paralelas
  divergen.

## Por qué no descubrir la memoria vecina automáticamente

Sería la respuesta cómoda: buscar hacia arriba hasta encontrar un `.an-kla/` y
usarlo. Se descarta porque encontrar un store no prueba nada de lo que importa
—identidad, autoridad, que sea el store buscado, que compartirlo sea admisible—
y porque convierte una ambigüedad visible en una decisión silenciosa. El
diagnóstico informa; la adopción de una memoria externa exige declaración y
verificación, y su mecanismo pertenece a #57.

## Por qué no ampliar `identity status`

Es donde más naturalmente encajaría, y por eso conviene decir por qué no.
`identity status` responde sobre la identidad del proyecto, no sobre la
disponibilidad de la memoria; mezclarlas obligaría a que un consumidor que sólo
quiere saber si puede recuperar contexto interprete un vocabulario de identidad.
Además `identity_status: absent` ya está publicado con su significado actual, y
redefinirlo rompería consumidores. El diagnóstico nuevo lo referencia.

## Por qué no bloquear el arranque cuando falta memoria

Un agente puede trabajar sin memoria: es el caso de todo proyecto nuevo. Lo que
no puede es trabajar **creyendo** que tiene memoria cuando no la tiene, o
concluir que el sistema está roto cuando simplemente no hay estado. Por eso la
señal es informativa y el exit es 0.

## Consecuencias

- **Positivas:** el punto de decisión de arranque deja de ser ambiguo; el
  agente distingue ausencia de aislamiento sin improvisar custodia; #56 y #57
  reciben un vocabulario común sobre el que construir.
- **Negativas:** dos de los cuatro estados nacen inalcanzables, lo que obliga a
  documentar la limitación en la salida para no sugerir una capacidad que no
  existe. Añade una superficie observable que habrá que mantener compatible.
- **Neutras:** no cambia almacenamiento, formato de revisiones ni el contrato
  gestionado. No modifica el comportamiento de `status`, `doctor`, `resume` ni
  `checkpoint show` más allá de lo ya corregido en la Fase 0.

## Test de regresión

- Los cuatro estados tienen fixture; los dos alcanzables se verifican contra
  stores reales y los dos externos contra la declaración de inalcanzabilidad.
- Un project root sin memoria produce `absent` con exit 0, no error.
- Un store íntegro pero con checkpoint desfasado respecto de Git produce
  `local_valid`: el test fija que el diagnóstico **no** afirma vigencia.
- Un worktree con store propio produce `local_valid` para ese worktree, y el
  test documenta que esa respuesta es correcta y aun así insuficiente sin #57.
- La salida valida contra `an-kla/startup-diagnostic-v1` y rechaza campos
  desconocidos.

## Referencias

- Issue [#76](https://github.com/kristhianmanue1/an-kla-memory/issues/76) —
  alcance acotado al diagnóstico en el comentario del 2026-08-15.
- `docs/planning/issue-76-startup-diagnostic-spike-2026-08-15.md` — spike
  read-only con la evidencia `archivo:línea`.
- ADR-0022 — identidad del store y `project_uuid` por checkout.
- ADR-0031 — memoria project-local y perfil host-managed; difiere G2/G3.
- Issues #56 (hooks del host) y #57 (`store_root` externo) — dueños del problema
  estructural que este ADR deliberadamente no resuelve.
- Issue [#79](https://github.com/kristhianmanue1/an-kla-memory/issues/79) —
  `source_state` con perfil `git/v1`, que haría detectable el desfase que
  `local_valid` no puede declarar.
