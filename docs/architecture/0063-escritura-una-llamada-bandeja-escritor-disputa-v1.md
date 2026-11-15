# ADR-0063: Escribir en una llamada con bandeja, escritor declarado y disputa

- **Estado:** Propuesta
- **Implementación:** No iniciada
- **Fecha:** 2026-11-14
- **Decide sobre:** la orden aditiva `remember`, que guarda un recuerdo en una
  invocación sin perder ni pisar escrituras concurrentes, con escritor y
  tiempo declarados y sin que un agente desactive el hecho de otro.

## Contexto

Guardar un hecho hoy cuesta cuatro invocaciones y ~5 KB de JSON
(`AN-KLA.md` §Receta: `status` → proposal → `plan-write
--emit-authority-template` → `plan-write --authority` → `commit-write-plan
--expected-current`). Tres fuerzas, medidas en `main@29c5ec0`:

1. **Concurrencia.** Con 4 escritores y 8 lectores durante 60 s, 629 de 874
   intentos fallaron por CAS (72 %) y **0** por candado
   (`benchmarks/scale/results/20261028-110445/concurrency-v2.json`:
   `cas_conflicts_total: 629`, `lock_busy_total: 0`). La causa no es el
   candado (`an_kla/store_locks.py`, no bloqueante con reintento hasta
   10 s): es que cada escritor planifica **fuera** del candado contra una
   `base_revision` que caduca antes de llegar a `commit_write_plan`
   (`an_kla/write_commit.py:46-51` y `:104-109`).
2. **Procedencia.** `lineage` e `issuer` se validan
   (`an_kla/write_policy.py:335-344`) pero no se persisten: el evento
   `write_policy_decision` sólo lleva clase, hashes y razones
   (`write_policy.py:657-671`), y el manifest de revisión no tiene tiempo
   (`an_kla/revision_builder.py:22-37`). No se sabe quién escribió qué ni
   cuándo.
3. **Silenciar a otro.** Un `model_derived` puede sustituir un hecho
   ajeno (`write_policy.py:119-122`; `an_kla/supersede.py` sólo exige que el
   target exista y sea vigente) y el original pasa a `sustituida`.

Restricciones:

- **Compatibilidad.** Las órdenes de datos existentes (`status`, `verify`,
  `inventory`, `retrieve`, `resume`, `assemble-context`, `export`,
  `plan-write`, `commit-write-plan`, `refute`, el MCP actual) devuelven lo
  mismo byte a byte para el mismo store y entradas. El `policy_fingerprint`
  de `write-policy/v1` no cambia. Las superficies de descubrimiento
  (`capabilities`, `schema list`, `--help`, `tools/list` del MCP) sólo
  cambian de forma aditiva.
- **Lecturas puras.** Una lectura no muta el store (MCP de sólo lectura;
  ADR-0047 §4: una invocación plana no escribe nada).
- **`refute` no sirve.** ADR-0026 proyecta `status="refutada"` sobre el
  target (`an_kla/store.py:345-357`), que deja de ser vigente
  (`an_kla/vigency.py`), y exige autoridad privilegiada con resolver
  (`an_kla/refute_policy.py:96-104`) que un agente no tiene.
- **Records abiertos.** `validate_record_fields` sólo valida `id`,
  `verified_at`, `status`/`nu` y `subject_ref`
  (`write_policy.py:268-286`): un record admite claves adicionales sin
  cambiar el formato de segmento (JSONL canónico direccionado por
  contenido, `store.py:616-633`), cuyo versionado vive en el manifest.
- **Lote homogéneo.** `write-proposal-v2` admite hasta 1000 records del
  mismo stream y operación, sin supersede intra-lote
  (`an_kla/write_batch.py:1-7`).
- **Identidad.** El ecosistema fija la identidad C0
  `memoria/identidad/v1` (`aria/coordination`, rama `memoria/c0-identidad`,
  commit `d1d4e6b`; candidata a congelar). #58 (G4) exige threat model y
  trata la identidad sólo como routing, nunca como permiso.

## Decisión

Añadir la orden `remember` (CLI) y la herramienta MCP `an_kla_remember`,
más `inbox drain`, `inbox status` y `disputes list`. Nada existente cambia de
comportamiento. Tres decisiones:

### D1 — Bandeja de entrada y vaciado en lote bajo candado, sin demonio

- `remember --text <t> [--kind fact|decision|state] [--supersedes <id>]
  [--idempotency-key <k>]`. Único obligatorio: `--text`. `kind` por
  defecto `fact`; `fact` y `decision` van al stream `facts`, `state` a
  `episodes` (el checkpoint `working-state-v2` no se toca).
- **Encolar.** Serializa una entrada `an-kla/inbox-entry-v1` y la deja en
  `<custodia>/memory/inbox/pending/<tiempo_ns>-<clave16>.json` con escritura
  temporal en `memory/inbox/tmp/`, `os.replace` y fsync del directorio. No
  hay `done/`: una entrada comprometida se borra.
- **La bandeja no es estado durable del store.** Hoy `export`, el sellado y
  `relocate plan` recorren la custodia y fallan cerrado con
  `export_unrecognized_durable_path` ante cualquier archivo no listado
  (`an_kla/export_restore.py:84-98`; medido en el spike de E1.a). Por eso:
  1. `memory/inbox/` se añade a los prefijos excluidos de `_files`, junto a
     `memory/{indexes,leases,quarantine,watermarks}/`: nunca se exporta, se
     sella ni se reubica;
  2. `export create` y `relocate plan` (ambas direcciones) exigen
     `pending/` vacío y fallan cerrado con un código nuevo `inbox_pending`
     (pista: `inbox drain`) antes de tocar nada. Así ninguna entrada se
     pierde por exclusión;
  3. `compact` ya ignora la ruta (`compaction_inventory.py:16-31`) y hereda
     la precondición por su bundle previo;
  4. encolar no toma el candado, así que una entrada puede llegar después de
     la comprobación. En `export` no se pierde (queda en `pending/` del
     store, que sigue vivo). En `relocate commit`, justo antes de limpiar el
     origen y con `write_lock` tomado (`relocate.py:479`, `relocate_back.py`),
     las entradas que hayan llegado a `pending/` del origen se mueven con
     `os.replace` a `pending/` del destino y el resultado lo informa; la
     limpieza nunca borra una entrada pendiente.
  Un store sin `memory/inbox/` recorre exactamente el mismo camino que hoy.
- **Vaciar.** A continuación intenta `write_lock` con un plazo corto
  (constante del perfil, menor que los 10 s del candado). Con el candado:
  1. lee `CURRENT` y el snapshot **dentro** del candado;
  2. ordena las entradas pendientes por nombre de archivo; una entrada
     ilegible o que no valide `inbox-entry-v1` se mueve a
     `memory/inbox/rejected/` con su motivo y no entra en el lote, para que
     no tumbe el lote entero (v2 es todo o nada);
  3. descarta las ya comprometidas (su `record.id` está en el snapshot);
  4. construye, contra la base observada bajo el candado, la propuesta, la
     autoridad `model_derived` (la misma plantilla que emite hoy
     `plan-write --emit-authority-template`) y el plan con las funciones
     puras de política (`evaluate_write`, `build_write_plan`), y compromete
     por el cuerpo de `commit_write_plan` **con el candado ya tomado**;
  5. sólo con `committed: true`, borra las entradas de `pending/`.
- **Commit con el candado tomado.** `write_lock` es `flock` sobre un
  descriptor nuevo y no es reentrante: llamar a `commit_write_plan` dentro
  de otro `write_lock` espera 10 s y falla con `write_lock_busy` (spike).
  `an_kla/write_commit.py` se parte, sin cambio de comportamiento, en una
  envoltura pública que toma el candado (la de hoy, mismos bytes y errores)
  y un cuerpo `_commit_write_plan_locked` que exige el candado tomado y
  hace la misma revalidación completa (`verify_write_plan`, CAS contra
  `CURRENT`, supersede, `subject_ref`). Es la misma técnica que la extracción
  de `supersede.py` (#59 Fase 0). La compactación también toma
  `write_lock`, así que planificar bajo él cubre el TOCTOU que ADR-0060
  cierra con el gate de lectores.
- **Tamaño del lote.** `_MAX_JSON_NODES = 10_000` (`write_policy.py:48`) se
  aplica a la propuesta y al plan completos: con un sobre de 21 nodos por
  record el máximo real medido es ≈ 380 records, no 1000. Un vaciado arma
  lotes por presupuesto de nodos (propuesta + plan ≤ 9.000) y como máximo
  `drain_max_entries = 250` entradas; el resto queda para la siguiente
  invocación. Medido: 250 entradas con sobre cuestan 0,07 s sobre 2.000
  records y 0,19 s sobre 20.000, el 2 % del plazo del candado.
- Las altas van en un `write-proposal-v2` por stream; las sustituciones
  propias, en otro commit dentro del mismo candado.
- **Candado ocupado** → `{"state": "queued"}`. Vacían sólo `remember` e
  `inbox drain`. Las lecturas **no** vacían ni informan de la bandeja;
  `inbox status` (sólo lectura) cuenta las pendientes.
- **Idempotencia.** `idempotency_key` = la dada o
  `sha256(canonical_json({"repo": repo.id, "agent": agent.name,
  "session": session.id, "kind": kind, "text": text}))`.
  `record.id = <prefijo del stream> + "-r-" + 24 hex de la clave`. Una
  entrada cuyo id ya existe se descarta sin commit y se informa
  `deduplicated: true`; `plan_duplicate_id` sigue siendo la defensa final.
- **Representación.** `summary` (techo de `model_derived`); el texto se
  guarda íntegro, igual que hoy.

### D2 — Escritor C0 y tiempo en un sobre dentro del record

Cada record que escribe `remember` lleva una clave reservada:

```json
"an_kla_envelope": {
  "schema": "an-kla/record-envelope-v1",
  "writer": {"schema": "memoria/identidad/v1", "repo": {…}, "agent": {…}, "session": {…}},
  "time": "2026-11-14T18:30:00.123456Z",
  "time_source": "host-clock/v1",
  "idempotency_key": "sha256:…",
  "kind": "fact"
}
```

- **Sin segmento v2 ni `revision-v4`.** El sobre es una clave más del
  record; los stores existentes no se migran y se leen igual. El tiempo de
  commit por revisión queda fuera de esta decisión.
- **Quién lo rellena.** Sólo `remember`, desde el entorno:
  - `repo.id` por la derivación exacta de C0 (remoto `origin` normalizado;
    `remoto:<16 hex>` si no se normaliza; `local:<16 hex>` de
    `git rev-parse --path-format=absolute --git-common-dir` con enlaces
    resueltos si no hay remoto); `repo.branch` de la rama del checkout,
    ausente si `HEAD` está desacoplado;
  - `agent.name`, `agent.cli`, `agent.model`, `agent.role` y `session.id`
    de variables de entorno que fija el lanzador
    (`AN_KLA_AGENT_NAME`, `AN_KLA_AGENT_CLI`, `AN_KLA_AGENT_MODEL`,
    `AN_KLA_AGENT_ROLE`, `AN_KLA_SESSION_ID`), con los centinelas de C0:
    `sin-nombre`, `desconocido` y `<cli>:sin-sesion`;
  - `repo.id`, `agent.cli` y `agent.role` son obligatorios: si faltan,
    `remember` falla cerrado con `identity_incomplete` y no encola nada.
- **Validación.** an-kla implementa su propio validador C0 y pasa los
  vectores de conformidad de C0 copiados con su digest **cuando C0 esté
  congelada en `main` de `aria/coordination`**.
- **Tiempo.** Reloj del host en UTC al encolar, declarado
  `host-clock/v1`: es una observación, no un sello; el orden del vaciado
  (nombre de archivo) no es orden causal entre relojes distintos.
- **Protección del sobre.** `plan-write` no cambia: un caller puede escribir
  a mano un `an_kla_envelope` en un record. El sobre es una aserción, igual
  que C0. Endurecer `plan-write` (rechazar o marcar la clave) cambia el
  `policy_fingerprint` y queda como decisión aparte del maintainer.

### D3 — Sustitución ajena convertida en disputa

En `remember --supersedes <id>`:

- **Propia** → `supersede` normal (ADR-0019): el anterior queda
  `sustituida`. Es propia sólo si el target tiene `an_kla_envelope` y su
  `writer.repo.id` y `writer.agent.name` coinciden con los del escritor
  actual, y ese nombre no es el centinela `sin-nombre`.
- **Ajena, legada sin sobre o con `sin-nombre`** → `add` de un record
  nuevo con
  `"disputes": {"stream": …, "target_id": …, "target_record_sha256": …}`
  (`target_record_sha256` = `digest_json` del record canónico, el mismo
  selector de ADR-0026). El original **sigue vigente**; ninguna vigencia
  cambia.
- Target inexistente o no vigente → `invalid_supersede_target` (código
  existente), sin encolar.
- **Visibilidad.** La respuesta de `remember` declara `"disputed": {…}` y
  `disputes list [--target <id>]` (sólo lectura) enumera las disputas
  vigentes. La anotación de disputas en la recuperación pertenece a la orden
  nueva de recuperación de hechos (E1.b, C4a); `retrieve` no cambia.
- El camino existente `plan-write … supersede` no cambia: un
  `model_derived` sigue pudiendo sustituir un hecho ajeno por esa vía. Esta
  decisión cierra el agujero sólo en `remember`.

## Modelo de amenaza

Agentes **honestos pero falibles** en una máquina de un solo usuario del
sistema; todos los procesos pueden leer y escribir el store.

| Amenaza | Dentro o fuera | Tratamiento |
|---|---|---|
| Un agente declara la identidad de otro (suplantación) | **Fuera de alcance, declarado** | El sobre y C0 son aserciones guardadas tal cual; no prueban autoría. La memoria sigue siendo no autoritativa |
| Un agente escribe a mano un sobre falso vía `plan-write` | Fuera de alcance, declarado | Igual que el anterior; endurecer `plan-write` es decisión aparte |
| Dos escritores honestos se pisan | **Dentro** | D1: planificación bajo candado; 0 conflictos CAS en el camino nuevo |
| Corte brusco a mitad del vaciado | **Dentro** | D1: nada sale de `pending/` hasta `committed: true`; la clave impide duplicar |
| Un agente honesto desactiva por error el hecho de otro | **Dentro** | D3: disputa, no sustitución |
| Dos agentes sin nombre (`sin-nombre`) se tratan como el mismo | Dentro | D3: `sin-nombre` nunca es dueño; siempre disputa |
| Contenido de la bandeja leído por otro proceso | Fuera | Igual que el store: JSON en claro bajo el mismo usuario |
| Texto recuperado tomado como instrucción | Dentro (sin cambio) | Las salidas nuevas llevan el marcador de dato no confiable del contrato vigente |

**Relación con #58 (G4).** Esta decisión cierra sólo la parte «identidad
declarada guardada»: el escritor queda registrado y es auditable y
filtrable. No cierra namespaces, aislamiento multi-scope, divulgación entre
agentes ni identidad verificada, y no usa la identidad como permiso:
la distinción propia/ajena de D3 sólo elige entre sustituir y disputar,
nunca concede escritura. #58 sigue abierto. Tampoco cierra G1 (firma) ni G5
(CAS por objeto) de #197.

## Criterios de aceptación

1. **Una llamada.** Guardar es una invocación de CLI o una llamada MCP cuyo
   único dato obligatorio es el texto; el record resultante lleva sobre con
   `writer` válido según C0 y `time`.
2. **Concurrencia.** 8 procesos clientes, 200 `remember` en total con
   textos únicos, más un `inbox drain` final: 200 records distintos en el
   snapshot, 0 perdidos, 0 duplicados, `pending/` vacío, `verify` ok,
   **0 `write_lock_busy`**, y se reporta el p95 de `remember`.
3. **Corte brusco.** `kill -9` al proceso que vacía en tres puntos (tras
   escribir objetos, tras mover `CURRENT`, antes de retirar `pending/`):
   tras la **siguiente invocación de escritura** (`remember` o
   `inbox drain`), 0 perdidos y 0 duplicados, y `verify` ok.
4. **Disputa.** A disputa un hecho de B: el de B sigue vigente
   (`is_active`), existe el record de disputa con su `target_record_sha256`
   y aparece en la respuesta de `remember` y en `disputes list`. Control: A
   sustituye uno suyo y el anterior queda `sustituida`. Target legado sin
   sobre → disputa.
5. **Compatibilidad.** Un store creado con `v0.1.0-beta.35` (fixture
   versionado) da, antes y después, el mismo `sha256` de salida en `status`,
   `verify`, `inventory`, `retrieve`, `resume`, `assemble-context`,
   `export` y las herramientas MCP existentes; `policy_fingerprint` sin
   cambio; `capabilities`, `schema list`, `--help` y `tools/list` sólo
   añaden entradas.
6. **Lecturas puras.** Con entradas en `pending/`, ninguna lectura cambia
   `CURRENT` ni toca la bandeja.
7. **Bandeja y custodia.** Con `pending/` no vacío, `export create`,
   `--seal sealed-export/v1` y `relocate plan` (ida y `--back`) fallan con
   `inbox_pending` sin efectos; tras `inbox drain` pasan y el bundle no
   contiene `memory/inbox/`. Una entrada encolada durante `relocate commit`
   aparece en `pending/` del destino. Un store sin `memory/inbox/` produce
   el mismo bundle byte a byte que hoy.
8. **Lote.** Un vaciado de 1000 pendientes con sobre C0 completo termina en
   varios commits sin `invalid_write_proposal` ni `invalid_write_plan`; una
   entrada corrupta acaba en `rejected/` y las demás se comprometen.

## Por qué no

- **Reintento sobre el CAS actual.** Mantiene la planificación fuera del
  candado: es la causa medida del 72 %.
- **Demonio escritor.** Exige instalar y mantener un servicio y rompe «an-kla
  funciona sola».
- **Que las lecturas vacíen la bandeja.** Convierte lecturas en mutadores,
  rompe la compatibilidad byte a byte, el MCP de sólo lectura y ADR-0047 §4.
- **`refute` para la sustitución ajena.** Desactiva el original y requiere
  autoridad privilegiada (ADR-0026): lo contrario de lo pedido.
- **Segmento v2 o `revision-v4` para escritor y tiempo.** Toca validación de
  revisiones, recorridos, compactación, export y sellado, y abre una
  migración innecesaria: el record ya admite la clave.
- **Endurecer `plan-write` ya.** Cambia el `policy_fingerprint` y los bytes
  de todas las planificaciones; no protege contra suplantación, que está
  fuera de alcance.
- **Bandeja fuera de la custodia** (p. ej. en la raíz del proyecto). Ensucia
  `git status` del consumidor (ADR-0031 §7, huella Git) y no viaja con la
  bóveda; dentro de la custodia basta excluirla de `_files` y exigir
  `pending/` vacío.
- **Exportar la bandeja.** Un bundle con entradas sin comprometer mezclaría
  estado no revisado por la política con revisiones verificables.
- **Planificar bajo candado sin bandeja.** Resuelve el CAS, pero un escritor
  que no consigue el candado en su plazo pierde la escritura o espera; la
  bandeja la conserva y responde `queued`.

## Consecuencias

- Positivas: guardar cuesta una invocación; 0 conflictos CAS en el camino
  nuevo; escritor y tiempo auditables; un agente ya no silencia a otro por
  `remember`; los stores existentes no se migran.
- Negativas: dos caminos de escritura conviven (`plan-write` sigue
  permitiendo la sustitución ajena); el sobre es aserción; la bandeja es un
  directorio nuevo en la custodia que `export`, `compact`, `doctor`,
  `relocate` tratan de forma explícita (exclusión y precondición
  `inbox_pending`), así que el código toca `export_restore.py` y
  `write_commit.py` (extracción sin cambio de comportamiento) además de los
  módulos nuevos; el vaciado retiene el candado de los demás durante su
  lote (≤ 0,2 s medidos).
- Neutras: la receta del bloque gestionado no cambia en E1.a (llega en
  E1.c); la anotación de disputas en la recuperación llega en E1.b; el
  tiempo de commit por revisión queda para otra decisión.

## Test de regresión

- `tests/test_identity_c0.py`: vectores de C0 cuando esté congelada; dos
  worktrees del mismo repo dan el mismo `repo.id`; control negativo.
- `tests/test_inbox.py`: atomicidad, orden, `queued`, idempotencia,
  `deduplicated`, `inbox status`.
- `tests/test_remember_concurrency.py`: criterio 2.
- `tests/test_inbox_crash.py`: criterio 3 con `SIGKILL` en tres puntos.
- `tests/test_remember_dispute.py`: criterio 4.
- `tests/test_legacy_store_byte_identity.py`: criterios 5 y 6 sobre un
  fixture `v0.1.0-beta.35`.
- `tests/test_inbox_custody.py`: criterio 7 (export, sellado si
  `cryptography` está disponible, `relocate` ida y vuelta, carrera durante
  `relocate commit`).
- `tests/test_inbox_batch_limits.py`: criterio 8.
- Pruebas existentes de `write_commit` sin cambios y en verde tras la
  extracción de `_commit_write_plan_locked`.
- Escenario de escala nuevo en `benchmarks/scale/` (8 escritores) sobre la
  batería existente.

## Referencias

- Issues: #58 (G4, parcial), #197 (G1, G5 y G6 de forma parcial), #169
  (disparador de caché, a medir).
- ADR-0019 (supersede), ADR-0024 (outcome y replay por `transaction_id`),
  ADR-0026 (refute), ADR-0031 (G4 diferido), ADR-0047 (hooks, lecturas
  planas sin escritura), ADR-0048 (custodia), ADR-0054 (lote v2), ADR-0060
  (planificación coherente).
- C0 `memoria/identidad/v1`: `aria/coordination`, rama
  `memoria/c0-identidad`, commit `d1d4e6b`.
- Plan del capitán: `/var/tmp/orquestador-memoria/capitanes/ankla/plan-E1a.md`
  (fuera del repo); delegación: `docs/gobernanza/2026-11-14-delegacion-memoria-agentica.md`.
