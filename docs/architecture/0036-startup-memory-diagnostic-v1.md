# ADR-0036: declarar el estado de la memoria en el arranque

- **Estado:** Propuesta
- **Implementación:** No iniciada
- **Fecha:** 2026-08-15
- **Decide sobre:** qué ejes observables debe publicar un diagnóstico de
  arranque read-only para que un agente decida sin improvisar custodia; no
  decide dónde vive el store, quién ejecuta el ciclo de vida, ni un enum de
  estados compuestos

## Contexto

`MemoryStore` deriva su ubicación del project root sin indirección:
`self.root = self.project_root / ".an-kla" / "memory"` (`an_kla/store.py:114`).
Como `.an-kla/` está en `.gitignore`, un `git worktree` nuevo no la recibe, y un
worktree que inicialice memoria propia obtiene otro `project_uuid`: un store
distinto, no una vista del canónico (ADR-0022, ADR-0031).

El incidente se reprodujo en disco el 2026-08-15. El worktree
`an-kla-memory-wt-issue60-spike` tenía `.an-kla/` propia con revisión 1 y
`1 fact / 1 event`, mientras el checkout canónico estaba en revisión 29 con
`23 facts / 21 events / 10 episodes`. Todo el trabajo de beta.14 salió del
worktree, y el checkpoint canónico siguió declarando `phase:
beta13_published_gfresh_spike_next` con el repositorio ya en beta.14.

El spike read-only previo
(`docs/planning/issue-76-startup-diagnostic-spike-2026-08-15.md`) verificó que
no existe descubrimiento de memoria vecina en ningún módulo, que el arranque sin
memoria producía un stack trace —corregido en la Fase 0— y que la capacidad de
clasificar ya existe dispersa entre `identity status` y `verify_upgrade`
(`an_kla/upgrade.py:189-192`).

La ronda adversarial con contexto fresco
(`docs/planning/issue-76-adr-0036-adversarial-2026-08-15.md`) refutó la primera
versión de este ADR con dos BLOCKER y tres HIGH. Sus hallazgos determinan la
forma de la decisión actual y se citan donde corresponde.

Restricciones:

- no introduce descubrimiento automático de stores vecinos;
- no reubica el store: `store_root` separado de `project_root` pertenece a #57,
  que está **abierto y sin implementación**;
- no ejecuta checkpoint ni recuperación automática: los hooks son de #56;
- la memoria y sus proyecciones siguen siendo datos no confiables;
- no redefine ninguna superficie publicada.

## Decisión

**Publicar un diagnóstico de arranque read-only cuyo resultado son ejes
observables independientes, no un estado compuesto.** Cada eje es total: tiene
un valor definido para cualquier estado del sistema de archivos, incluida la
imposibilidad de observarlo.

| Eje | Valores | Significado |
|---|---|---|
| `store_presence` | `present` · `absent` · `unreadable` | Si hay algo bajo `.an-kla/memory/` en este project root. `unreadable` cubre permisos denegados y montaje no disponible |
| `store_integrity` | `verified` · `failed` · `not_evaluated` | Resultado de la verificación. `not_evaluated` cuando la presencia no lo permite o cuando no se pudo tomar el reader gate |
| `identity` | `evaluated` más los 9 valores publicados de `identity-status-v1` y `root_relocated` | Reexpuesto **verbatim**, sin redefinir |
| `repo_context` | `main_checkout` · `linked_worktree` · `not_a_repo` · `git_unavailable` | Derivado de `git rev-parse --git-common-dir` |

Propiedades del contrato:

- **Éxito cuando se pudo diagnosticar.** Ausencia de memoria no es error:
  `store_presence: absent` con exit 0 es el resultado correcto de un proyecto
  nuevo. Los errores quedan para la imposibilidad de diagnosticar y llevan
  envolvente propia (ver más abajo).
- **Ningún eje afirma vigencia.** `store_integrity: verified` declara que la
  memoria está íntegra, nunca que su contenido corresponda al estado actual del
  proyecto. El checkpoint de la revisión 29 estaba íntegro y describía un estado
  de dos días antes; detectarlo depende de #79.
- **Schema versionado** `an-kla/startup-diagnostic-v1`, cerrado
  (`additionalProperties: false`), con `untrusted_memory_data: true`. Añadir
  ejes es evolución aditiva conforme a §11.2 de `practicas-ingenieria.md`.
- **La identidad no evaluable se declara, no se sustituye.** Cuando el store es
  ilegible o la observación falla, `identity.evaluated` vale `false` y
  `identity_status` queda nulo. Ninguno de los nueve valores publicados se
  reutiliza para representar un fallo: inventar una identidad es peor que
  admitir que no se pudo observar. Precisión incorporada tras la ronda
  adversarial de la implementación.
- **Contrato de error explícito.** Cuando el diagnóstico no puede emitirse, sale
  con código distinto de cero y una envolvente con `error_code` de enum cerrado.
  Los mensajes no emiten rutas absolutas (§11.1). La implementación no puede
  apoyarse en `Path.exists()` desnudo: lanza `PermissionError` bajo `EACCES`, y
  por eso `store_presence` necesita el valor `unreadable`.

### Cómo se distingue ausencia de aislamiento

Es el caso que motiva #76 y la primera versión de este ADR **no lo resolvía**:
sus estados externos exigían una declaración previa, de modo que un worktree con
memoria no declarada en otro checkout caía en "ausente", indistinguible de un
proyecto nuevo.

La combinación `store_presence: absent` + `repo_context: linked_worktree` sí lo
distingue, y lo hace sin descubrir ni adoptar nada: `git rev-parse
--git-common-dir` es una respuesta de Git sobre este árbol, no una búsqueda
heurística de directorios vecinos ni una afirmación sobre la memoria de otro
checkout. El diagnóstico informa que este árbol es un worktree enlazado; qué
hacer con esa información es del host.

### Lo que la v1 deliberadamente no publica

No hay eje de memoria externa. Un `store_root` declarado fuera del project root
no existe hasta #57, y nombrar hoy sus valores sería congelar vocabulario para
una capacidad cuyo diseño todavía puede cambiar. Su ausencia significa "no
evaluado", nunca "no hay".

## Por qué no congelar un enum de cuatro estados compuestos

Era la decisión de la primera versión de este ADR y se retira, por dos razones
independientes.

**ADR-0031 ya lo había descartado.** Su sección "Pre-congelar enum/schema/
comando de G1 en este ADR" (`0031:234-240`) dice: *"Prematuro. La lista de
cuatro estados propuesta en #54 no contempla combinaciones reales y
observables… El enum exacto exige ronda adversarial de G1; pre-decidirlo aquí
crearía un contrato frágil. Descartado."* La primera versión hizo exactamente
eso y citó ADR-0031 sin abordar la objeción.

**La objeción resultó cierta al probarla.** Un estado compuesto obliga a que
cada combinación real tenga nombre, y las combinaciones reales no cabían: un
store presente cuya verificación falla no era ni "válido" ni "ausente"; una
memoria íntegra en un árbol de sólo lectura tampoco alcanzaba "válido", porque
la verificación falla al no poder crear el reader gate. Ejes independientes
representan esas combinaciones sin inventar nombres.

## Por qué no descubrir la memoria vecina automáticamente

Sería la respuesta cómoda: buscar hacia arriba hasta encontrar un `.an-kla/` y
usarlo. Se descarta porque encontrar un store no prueba nada de lo que importa
—identidad, autoridad, que sea el store buscado, que compartirlo sea admisible—
y porque convierte una ambigüedad visible en una decisión silenciosa. Un
experimento de la ronda adversarial lo confirma: un symlink al store canónico
produce `identity_status: conflict`, no una adopción válida.

`repo_context` no es descubrimiento: no lee ni valida ninguna memoria ajena.

## Por qué no absorber `identity status` ni `verify_upgrade`

La primera versión exigía que ambos consumieran la nueva clasificación "en lugar
de mantener la suya", y dos secciones más abajo reconocía que redefinir
`identity_status: absent` rompería consumidores. Las dos cosas no podían ser
ciertas, y además `identity_status` publica nueve valores, no dos.

La relación queda declarada, como pide §11.2:

- **Precedencia:** `identity-status-v1` sigue siendo canónico para preguntas de
  identidad; el diagnóstico lo **reexpone verbatim** y no lo reinterpreta.
- **Migración:** ninguna. Ningún valor publicado cambia de significado.
- **Deprecación:** ninguna en esta versión. `verify_upgrade` conserva su
  semántica de `ok`; si en el futuro deriva de estos ejes, será decisión propia
  con su ADR.

## Read-only: qué significa exactamente

La primera versión declaraba "read-only estricto: no crea estado" y a la vez
definía un estado en función de `verify`. Es falso: `_open_gate` abre con
`os.O_RDWR | os.O_CREAT` (`an_kla/reader_gate.py:39`), de modo que verificar
**crea** `.reader-gate` con modo `0600`, incluso en un project root sin store.

El contrato correcto es: el diagnóstico **no crea, copia, adopta ni repara
memoria**, y la única escritura admisible es el lease del reader gate que exige
la verificación. Cuando el árbol no admite escritura, eso no es un fallo del
diagnóstico: `store_integrity` vale `not_evaluated` con su razón, y
`store_presence` sigue siendo observable.

## Consecuencias

- **Positivas:** cada combinación real del sistema de archivos tiene
  representación sin inventar nombres; el caso de #76 queda distinguible con
  evidencia de Git; ninguna superficie publicada cambia de significado; #56 y
  #57 heredan ejes en vez de un enum que tendrían que renegociar.
- **Negativas:** el consumidor debe combinar ejes en lugar de leer un valor
  único, lo que traslada a él una decisión que un enum habría tomado por él. Es
  deliberado: esa decisión depende del host.
- **Neutras:** no cambia almacenamiento, formato de revisiones ni el contrato
  gestionado. `repo_context` introduce una dependencia opcional de Git, cuya
  ausencia es un valor del propio eje.

## Test de regresión

- Project root sin memoria → `store_presence: absent`,
  `store_integrity: not_evaluated`, exit 0.
- Store con `refs/CURRENT` presente y `revisions/` borrado → `present` +
  `failed`, exit 0. Es el caso que el enum no representaba.
- Store íntegro en árbol de sólo lectura → `present` + `not_evaluated` con razón
  `reader_gate_unavailable`, exit 0. Nunca `failed`.
- `.an-kla/memory/` con permisos `000` → `store_presence: unreadable`, exit 0, y
  el mensaje no contiene rutas absolutas.
- Store copiado desde otro project root → `identity` expone
  `root_relocated: true`.
- Worktree enlazado sin memoria → `absent` + `linked_worktree`; checkout
  principal sin memoria → `absent` + `main_checkout`. Los dos casos deben ser
  distinguibles: es el criterio de aceptación de #76.
- Directorio que no es repositorio Git → `not_a_repo`, sin error.
- La salida valida contra `an-kla/startup-diagnostic-v1` y rechaza campos
  desconocidos.

## Referencias

- Issue [#76](https://github.com/kristhianmanue1/an-kla-memory/issues/76) —
  alcance acotado al diagnóstico en el comentario del 2026-08-15.
- `docs/planning/issue-76-startup-diagnostic-spike-2026-08-15.md` — spike
  read-only.
- `docs/planning/issue-76-adr-0036-adversarial-2026-08-15.md` — ronda
  adversarial con contexto fresco que refutó la primera versión.
- ADR-0022 — identidad del store, `project_uuid` y `root_relocated`.
- ADR-0031 — memoria project-local y perfil host-managed; su objeción a
  pre-congelar enums de G1 es la que esta versión respeta.
- Issues #56 (hooks del host) y #57 (`store_root` externo), ambos abiertos.
- Issue [#79](https://github.com/kristhianmanue1/an-kla-memory/issues/79) —
  `source_state` con perfil `git/v1`, que haría detectable el desfase que
  `store_integrity: verified` no puede declarar.
