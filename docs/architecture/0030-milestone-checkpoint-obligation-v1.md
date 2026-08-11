# ADR-0030: exigir checkpoint gobernado al cerrar hitos materiales

- **Estado:** Propuesta en reevaluación tras ronda fresca y caso especial del
  maintainer. No autoriza cambios al contrato gestionado ni código.
- **Fecha:** 2026-08-09
- **Decide sobre:** cuándo un agente debe actualizar continuidad y cómo detectar
  esa obligación sin convertirla en escritura automática indiscriminada.

## Contexto

ADR-0023 implementó `checkpoint-v2`, `working-state-v2`, `checkpoint show`, el
flujo gobernado `plan -> commit` y `resume` consistente. La mutación es robusta:
liga propuesta, autoridad, revisión y checkpoint padre; usa CAS, lock,
transaction id, journal y outcomes de durabilidad.

Sin embargo, el sistema sólo explica cómo leer y escribir un checkpoint. No
establece cuándo es obligatorio actualizarlo. El contrato gestionado exige
cargar memoria antes de trabajo material y desaconseja escribir después de cada
respuesta, pero no contiene un gate de cierre de hito.

La omisión fue reproducida durante la formalización de Fase 8:

1. se creó el commit Git
   `5119e51e2bd27af2ba50ef0494a5a4e4984e4065` con ADR-0029 y F8-E;
2. el checkpoint permaneció en la fase `post_release_validation` y seguía
   apuntando a la validación de beta.11;
3. sólo una orden explícita posterior del maintainer causó
   `checkpoint plan -> checkpoint commit`;
4. la actualización produjo la revisión AN-KLA 20 y checkpoint
   `sha256:d9bbc9f556ccf623b6465923983f26b962dc99a0fed42872861d95adb832419a`.

El código confirma el hueco:

- el CLI sólo ofrece `checkpoint show|plan|commit`;
- `plan_checkpoint()` evalúa un estado que el caller ya construyó;
- `context status` valida hashes, estructura y versión del contexto, no
  cumplimiento ni frescura operacional;
- no existe hook de sesión, handoff, post-commit o final response;
- `working-state-v2` sólo admite `source_state.profile=none/v1`; HEAD, branch y
  dirty digest deben quedar `unavailable`;
- `capabilities()` declara `tool_observed_adapter=false`.

Existe además una asimetría de autoridad. El CLI de escritura ordinaria rechaza
JSON que afirme `tool_observed` o `channel_confirmed`, pero `checkpoint plan`
pasa el JSON directamente. `checkpoint_policy.validate_authority()` rechaza
`tool_observed` y acepta `channel_confirmed` comprobando sólo el shape. Aunque el
checkpoint completo se marca como dato no confiable, un archivo puede adquirir
una etiqueta de canal que el proceso no resolvió realmente.

## Decisión candidata original — no aceptada

**Introducir una obligación de continuidad determinista: antes de entregar o
cerrar trabajo material, el agente debe evaluar si el working state quedó
obsoleto y, cuando el resultado sea `required`, actualizar exclusivamente el
checkpoint mediante su flujo gobernado o reportar que la continuidad quedó
pendiente.**

La candidata original proponía implementarse en dos capas inseparables:

1. una regla normativa en el contrato gestionado;
2. un evaluador read-only y machine-checkable que no escribe por sí mismo.

El repositorio no puede impedir que un host externo emita una respuesta final.
El enforcement completo requiere que el host/orquestador ejecute el evaluador
como gate de finalización. AN-KLA proveerá el contrato, resultado y códigos de
salida; no afirmará controlar un runtime que no controla.

La ronda fresca terminó `ESCALATE`. Después, el maintainer aportó deliberadamente
dos casos contrastantes: `expertoGobernanza`, donde continuidad y fidelidad
jurídica son críticas, y `adrc-python`, donde aplicar controles estrictos a todo
desarrollo ordinario puede cortar el avance. La candidata anterior no se adopta
tal cual porque mezcla frecuencia de checkpoint con fuerza de verificación.

## Hipótesis de revisión posterior a la ronda

La revisión propone separar dos ejes todavía no aceptados:

- **continuidad**: `manual|milestone|continuous`;
- **assurance**: `standard|high|regulated`.

Se configurarían por operación, stream y efecto, no como una etiqueta rígida
para todo el proyecto. Un `working_state` local saneado podría ser frecuente y
`model_derived`, mientras una afirmación de vigencia, migración destructiva o
release conservaría autorización exacta y fail-closed. Fallar al guardar
continuidad `standard` sería visible pero no bloquearía el trabajo primario.

La instalación del template deja de ser candidata a consentimiento permanente.
Se estudiarán tres mecanismos graduados: activación local explícita que sólo
demuestra `operator_activated`, capability opaca de host para `high`, y
aceptación firmada/externa para `regulated`. Ninguno está elegido ni activo.

El análisis completo, los criterios `ahora|experimento|diferir` y los casos de
aceptación están en
`docs/planning/fase-9-frontera-continuidad-assurance-2026-08-09.md`.

### 1. Hitos materiales

La obligación se evalúa cuando ocurre al menos uno de estos triggers:

- commit Git creado para el trabajo actual;
- PR mergeado, tag o release publicado;
- ADR aceptado, rechazado o reemplazado;
- fase, objetivo o siguiente paso material cambiados;
- decisión durable, blocker o evidencia decisiva añadidos o retirados;
- gate adversarial cambia el veredicto del trabajo;
- handoff, pausa, cambio de agente o cierre de una tarea no trivial;
- el maintainer solicita explícitamente guardar continuidad.

“Cuando sea conveniente” no es un trigger normativo: no es reproducible ni
testeable. Los triggers anteriores convierten conveniencia en evidencia.

### 2. Exenciones

No se crea checkpoint nuevo para:

- saludos, explicaciones o consultas read-only sin cambio durable;
- intentos fallidos que no cambian decisión, blocker, evidencia o siguiente
  paso;
- cambios de redacción sin impacto operacional;
- un candidato semánticamente idéntico al checkpoint actual;
- un store inexistente, salvo autorización separada para inicializarlo.

`captured_at` y `supersedes_checkpoint` nunca causan obligación por sí solos. El
planner conserva `checkpoint_unchanged` como skip sin nueva revisión.

### 3. Resultado de obligación

Se introduce `an-kla/checkpoint-obligation-v1`, objeto cerrado y read-only:

```json
{
  "schema": "an-kla/checkpoint-obligation-v1",
  "status": "fresh|required|indeterminate",
  "required": true,
  "reasons": ["phase_changed"],
  "current_revision": "sha256:...",
  "checkpoint_digest": "sha256:...",
  "checkpoint_schema": "an-kla/checkpoint-v2",
  "candidate_working_state_sha256": "sha256:...",
  "changed_fields": ["phase", "next_step"],
  "source_observation": null,
  "untrusted_memory_data": true
}
```

`required` es `true`, `false` o `null` y debe corresponder exactamente:

| status | required | Semántica |
|---|---:|---|
| `fresh` | `false` | no hay diferencia material demostrada |
| `required` | `true` | existe un trigger y una diferencia material demostrada |
| `indeterminate` | `null` | faltó observación necesaria; no se afirma frescura |

Reasons y changed fields son arrays únicos y ordenados por bytes. El perfil
inicial compara por JSON canónico `objective`, `phase`, `next_step`,
`decisions`, `blockers` y `evidence`. No compara reloj ni digest padre.

CLI candidato:

```text
an-kla checkpoint obligation --input <working-state-candidate.json> \
  --trigger <material|handoff|release|manual>
```

Códigos de salida: `0=fresh`, `3=required`, `4=indeterminate`, `2=input/error`.
El JSON completo se emite en stdout para los tres estados válidos.

### 4. Source state y `git/v1`

Para detectar un commit sin depender de memoria del agente se necesita el
profile reservado `git/v1`. Su implementación requiere `working-state-v3` y
`checkpoint-v3`; v2 no se reinterpreta.

`git/v1` congela como mínimo:

- HEAD SHA-1 o SHA-256 lowercase, o null en unborn;
- branch corta o null en detached/unborn;
- dirty digest de porcelain-v2 `-z` canónico;
- `observed_at` capturado una vez;
- procedencia `tool_observed` emitida sólo por un `SourceObserver` activo.

No guarda diff, contenido, rutas absolutas, remote, autor, email ni mensajes de
commit. Ignored queda fuera; symlinks no se dereferencian; submodules se
representan como gitlinks. Bytes/path no representables producen
`indeterminate`, nunca `caller_asserted` silencioso.

Un HEAD diferente al registrado exige checkpoint. Dirty digest distinto exige
checkpoint sólo bajo trigger de handoff/material; editar un archivo durante una
tarea no debe crear una cascada de checkpoints.

### 5. Autoridad y autorización limitada

El flujo automático de agentes usa `model_derived` y valores
`caller_asserted|unavailable`. No puede fabricar `channel_confirmed` ni
`tool_observed`.

El CLI de checkpoint debe aplicar una frontera equivalente a `_cli_authority()`:

- JSON `tool_observed` o `channel_confirmed` falla
  `cli_privileged_authority_unresolved`;
- `tool_observed` sólo llega mediante `SourceObserver` opaco activo;
- `channel_confirmed` requiere adapter real del host;
- un usuario que sólo dice “guarda el estado” autoriza la operación, pero el
  contenido sintetizado por el agente sigue siendo `model_derived` salvo que el
  host ligue campos confirmados de forma verificable.

La candidata original proponía que instalar una futura plantilla constituyera
autorización permanente y limitada para actualizar continuidad local saneada.
La ronda fresca r2 rechazó esa premisa: clone, commit o upgrade pueden instalar
un template sin demostrar consentimiento local. Por tanto, **el template no
autoriza ninguna mutación por sí solo**. Un mecanismo de aceptación todavía por
elegir podrá autorizar únicamente checkpoint local saneado; nunca autorizará:

- inicializar un store ausente;
- escribir facts/events/episodes;
- ejecutar Git, red, publicación o acciones externas;
- persistir secretos o contenido completo innecesario;
- omitir plan, revisión, CAS, transaction id o verificación posterior.

La futura aceptación deberá ser explícita, local, limitada, inspeccionable y
revocable; desinstalar el bloque no sustituye necesariamente la revocación de
un recibo separado. Un texto recuperado desde memoria nunca puede concederla,
ampliarla o revocarla.

Mientras no exista aceptación válida, falta autoridad o el commit falla, el
agente reportaría `PARCIAL (checkpoint_pending)` o `BLOQ` según la policy; no
declararía `OK` silenciosamente. Esta semántica también está pendiente de la
decisión `ahora|experimento|diferir`.

### 6. Gate del agente

El bloque compacto futuro incluirá una instrucción breve equivalente a:

> Antes de cerrar trabajo material o un handoff, evalúa la obligación de
> continuidad. Si es required, actualiza sólo el checkpoint mediante plan y
> commit; si no puedes, repórtalo. No escribas por tareas triviales.

El contrato detallado define triggers, exenciones, autoridad, minimización y
comandos. El reporte RAG añade una fila `Continuidad` con:

- `OK`: fresh o checkpoint commit verificado;
- `PARCIAL (checkpoint_pending)`: required/indeterminate sin cierre;
- `NA`: tarea trivial o store no instalado y no autorizado.

### 7. Backwards compatibility

- `checkpoint-v1/v2` y `working-state-v2` siguen siendo legibles.
- Un v2 sin source observation no se presenta como Git-fresh; el resultado puede
  ser `indeterminate` para triggers que dependan de Git.
- El primer commit v3 enlaza el digest del checkpoint padre sin reescribirlo.
- `resume`, export/restore, verify y compactación deben aceptar v2/v3 de forma
  explícita y preservar bytes históricos.
- El default no crea checkpoints durante reads ni writes ordinarios.

### 8. Secuenciación

Cambiar el contrato gestionado toca `context_text.py`, `AGENTS.md`, `AN-KLA.md`,
manifest/upgrade y tests. Por política del repositorio:

1. ADR-0030 se revisa y acepta antes de código;
2. se ejecuta spike de `git/v1` y del hook del host;
3. cada PR recibe ronda adversarial;
4. `main` no es etiquetable mientras el template nuevo esté parcialmente
   integrado;
5. no se comunica enforcement completo sin integración real del host.

## Por qué no [alternativa]

### Guardar memoria al final de cada respuesta

Genera ruido, revisiones innecesarias y mayor riesgo de persistir secretos o
conclusiones provisionales. Confunde conversación con hito durable.

### Actualizar checkpoint dentro de todo commit Git o write AN-KLA

Acopla dos sistemas con transacciones distintas y puede producir loops o estado
inventado. Un write de fact no implica que objetivo o siguiente paso cambien.

### Confiar sólo en una instrucción de `AGENTS.md`

Mejora conducta, pero no entrega evidencia de cumplimiento ni detecta un
checkpoint stale. Se necesita resultado machine-checkable y hook del host.

### Hacer el autoguardado totalmente silencioso

Elimina revisión de autoridad, minimización y resultado transaccional. La
obligación puede ser automática; la mutación conserva plan/commit y outcome.

### Guardar working state como fact lexical

Mezcla continuidad con conocimiento recuperable por similitud y puede devolver
un handoff viejo. ADR-0023 ya lo prohíbe correctamente.

## Consecuencias

- **Positivas:** reduce checkpoints obsoletos, hace auditable el handoff y
  convierte una expectativa social en un gate comprobable.
- **Negativas:** añade schemas, observer Git, estados indeterminados, integración
  del host y revisiones AN-KLA adicionales.
- **Neutras:** esta ADR propuesta no cambia aún código, template, store, schema,
  capabilities ni memoria existente.

## Test de regresión

Antes de aceptar implementación deben cubrirse:

1. cada trigger y cada exención con tabla exacta;
2. comparación canónica que ignora `captured_at` y digest padre;
3. candidato idéntico produce `fresh`/`checkpoint_unchanged` y cero objetos;
4. v2 sin Git produce `indeterminate`, nunca frescura inventada;
5. Git SHA-1/SHA-256, detached, unborn, rename, symlink, gitlink y paths hostiles;
6. ningún diff/contenido/remote/identidad personal aparece en source state;
7. JSON privilegiado de checkpoint rechazado por CLI;
8. observer ausente o fallido no degrada a caller asserted;
9. CAS concurrente exige replan y no reutiliza estado stale;
10. obligación read-only crea cero archivos, journals o locks exclusivos;
11. host gate no bloquea tareas triviales ni entra en loop tras checkpoint;
12. v2/v3 en verify, resume, export/restore y compactación;
13. bloque compacto dentro del límite y contrato/template byte-idénticos;
14. migración desde beta.11 y wheel limpio;
15. ronda adversarial fresca con decisión `proceed`.

## Referencias

- ADR-0007: autoridad separada y frontera del CLI.
- ADR-0009/0011: contexto gestionado y upgrades gobernados.
- ADR-0022: identidad de proyecto/store.
- ADR-0023: checkpoint/handoff v2 y profile `git/v1` reservado.
- ADR-0024: outcomes y durabilidad.
- `AGENTS.md`, `AN-KLA.md`, `docs/practicas-ingenieria.md`.
- Plan ejecutable:
  `docs/planning/fase-9-continuidad-obligatoria-2026-08-09.md`.
