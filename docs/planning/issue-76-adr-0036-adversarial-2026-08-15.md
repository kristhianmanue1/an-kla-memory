# Ronda adversarial — ADR-0036 (diagnóstico de arranque)

**Fecha:** 2026-08-15
**Artefacto:** `../architecture/0036-startup-memory-diagnostic-v1.md`, primera
versión (commit `ad827b6`)
**Revisor:** subagente con contexto fresco, sesión independiente
**Contexto:** `fresco` — no compartió contexto con el autor del ADR ni del spike
**Modelo:** distinto de la sesión autora sólo en contexto, no en proveedor; la
decorrelación por proveedor (`agy`/Gemini) quedó bloqueada por permisos
**Alcance:** corrección, contrato y requisitos; no estilo ni redacción
**Decisión:** `fix-and-retry`

## Hallazgos

### [BLOCKER] Los cuatro estados no son exhaustivos

Un store con `refs/CURRENT` presente cuyo `verify` falla no es `local_valid`
(verify no pasa) ni `absent` (sí hay memoria) ni externo. El estado más
peligroso del sistema —memoria presente y rota— era el único sin nombre.

Reproducido en dos formas: borrando `revisions/` (`verify` →
`compaction_catalog_invalid`, exit 1, con `current_path.exists()` → `True`), y
con el árbol en sólo lectura (`chmod -R a-w`), donde una memoria **íntegra**
tampoco alcanza `local_valid` porque `verify` falla al no poder crear el gate.

### [BLOCKER] El ADR no cerraba el caso que lo motiva

Ambos estados externos exigían **declaración**. El escenario de #76 es una
memoria **no declarada** en otro checkout, así que caía en `absent`,
indistinguible de un proyecto nuevo.

La regresión es trazable: el spike escribió `external_candidate` = "hay
**indicio** de memoria externa" (`issue-76-startup-diagnostic-spike:102`); al
redactar el ADR se endureció a "**declarada**" (`0036:59`), cerrando el único
hueco por donde entraba el incidente. La sección de Consecuencias seguía
afirmando que el agente "distingue ausencia de aislamiento".

### [HIGH] `read-only estricto` era falso

`_open_gate` abre con `os.O_RDWR | os.O_CREAT` (`an_kla/reader_gate.py:39`), de
modo que la verificación **crea** `.reader-gate` con modo `0600` dentro del
store — incluso en un project root sin store. El ADR prohibía crear estado y a
la vez definía un estado en función de `verify`. Una de las dos cláusulas tenía
que ser falsa.

### [HIGH] La cláusula de "fuente única" era inviable y se contradecía a sí misma

El ADR exigía que `identity status` y `verify_upgrade` consumieran la nueva
clasificación "en lugar de mantener la suya", y dos secciones más abajo decía
que redefinir `identity_status: absent` rompería consumidores. Además
`identity_status` publica **nueve** valores
(`an_kla/schemas/identity-status-v1.schema.json`), no dos: la simplificación del
Contexto era lo que hacía parecer viable la absorción.

`practicas-ingenieria.md` §11.2 exige declarar precedencia, migración y
deprecación al crear una superficie paralela; el ADR declaraba la fuente única y
omitía las tres.

### [HIGH] Contradice a ADR-0031, que ya había descartado congelar este enum

`0031:234-240`, sección "Pre-congelar enum/schema/comando de G1 en este ADR":
*"Prematuro. La lista de cuatro estados propuesta en #54 no contempla
combinaciones reales y observables… El enum exacto exige ronda adversarial de
G1; pre-decidirlo aquí crearía un contrato frágil. Descartado."*

ADR-0036 congelaba exactamente esos cuatro estados y citaba ADR-0031 en
Referencias sin mencionar ni refutar la objeción. Además afirmaba que "#57
todavía no existe": #57 está abierto, y su alcance —migración reversible,
compatibilidad con stores project-local— implica que `local_valid` y
`external_declared` pueden ser verdaderos a la vez.

### [MED] `local_valid` nombraba dos ejes y omitía `root_relocated`

Un contrato que necesita un párrafo para desmentir su propio identificador está
mal nombrado. Y el ADR nunca mencionaba `root_relocated` ni `project_uuid`: un
store copiado desde otro proyecto verifica `ok=true` y habría sido `local_valid`
sin exponer la única señal que lo delata, la que ADR-0022 creó para ese caso.

### [MED] No había contrato de error

Sin exit code de fallo, envolvente ni códigos estables, un script no distingue
`absent` de "no pude diagnosticar" — que es la clase de fallo que #76 denuncia.
La superficie de error heredada además filtra rutas absolutas, contra §11.1. Y
el primitivo sobre el que se apoyaba la clasificación, `current_path.exists()`,
no es total: lanza `PermissionError` bajo `EACCES`.

### [LOW] Citas de evidencia incorrectas

`self.root = self.project_root / ".an-kla" / "memory"` está en `store.py:114`,
no en 112-113.

## Lo que el revisor atacó sin éxito

- **Contradicción con ADR-0022:** no la hay. El ADR no reintroduce la ruta como
  autoridad ni rompe la separación `project_uuid`/`store_uuid`. Lo que hay es
  omisión, reportada como MED.
- **El argumento contra el descubrimiento automático:** es correcto, y un
  experimento con symlink lo confirmó (`identity status` → `conflict`).
- **El exit 0 en sí mismo:** sólido, con precedente en `identity status`. El
  defecto era la ausencia del canal de error complementario.
- **Estructura documental:** ADR-0036 respeta la plantilla, el registro y
  `check_adr_registry`. Los incumplimientos son de §11.1 y §11.2.

## No verificado

Comportamiento en Windows; montaje de red realmente caído (`ESTALE`/`ETIMEDOUT`
podría diferir de `EACCES`); consumidores externos del enum `identity-status-v1`
fuera de este repositorio.

## Verificación independiente del autor

Antes de aceptar los hallazgos se comprobaron los cuatro que sostienen la
reescritura:

- `sed -n '30,46p' an_kla/reader_gate.py` → `flags = os.O_RDWR | os.O_CREAT …`
- enum de `identity-status-v1` → 9 valores.
- `grep -n "self.root = self.project_root" an_kla/store.py` → `114:`.
- `grep -n -A 8 "Pre-congelar enum" docs/architecture/0031-…md` → `234-240`,
  "Descartado".

## Consecuencia

El ADR se reescribe: se retira el enum de cuatro estados de la v1 y se
sustituye por ejes observables independientes, respetando la objeción de
ADR-0031 en lugar de atropellarla. Detalle en la versión siguiente del ADR.

## Nota de método

Esta ronda encontró dos BLOCKER y tres HIGH que la revisión del propio autor no
vio, y uno de ellos es una contradicción literal con un ADR aceptado del mismo
repositorio. Es la diferencia entre `contexto: mismo` y `contexto: fresco`,
medida sobre un caso real.
