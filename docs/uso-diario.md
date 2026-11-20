# Uso diario y mantenimiento de un proyecto consumidor

Guía de referencia estable para proyectos con AN-KLA instalado: actualización
entre betas, desinstalación, comandos de uso cotidiano y respaldo sellado
opcional. La primera lectura (qué es AN-KLA, fronteras, instalación) vive en
el [README](../README.md); este documento la complementa.

## Tabla de contenidos

- [Actualizar desde otra beta](#actualizar-desde-otra-beta)
- [Desinstalar o volver atrás](#desinstalar-o-volver-atrás)
- [Uso diario](#uso-diario)
  - [Descubrimiento para agentes](#descubrimiento-para-agentes)
  - [Diagnóstico de arranque e integración](#diagnóstico-de-arranque-e-integración)
  - [Verificación no bloqueante de versiones](#verificación-no-bloqueante-de-versiones)
  - [Actualización gobernada del proyecto](#actualización-gobernada-del-proyecto)
  - [Recuperación y escritura](#recuperación-y-escritura)
  - [Estado de una casilla e historia](#estado-de-una-casilla-e-historia)
  - [Ámbito, destinatario y órdenes del Operador](#ámbito-destinatario-y-órdenes-del-operador-directive)
  - [Rechazos de la bandeja](#rechazos-de-la-bandeja)
  - [Respaldo sellado (opcional)](#respaldo-sellado-opcional)

## Actualizar desde otra beta

Primero registra la línea base:

```bash
.venv/bin/python -m an_kla --version
.venv/bin/python -m an_kla --project-root . context status
.venv/bin/python -m an_kla --project-root . verify
```

**Si existe un store beta.8, no apliques todavía la actualización de contexto:**
beta.11 debe inspeccionar el upgrade, adoptar primero la identidad legacy y
sólo después ejecutar `upgrade apply/verify`. Sigue la
[secuencia beta.8 completa](beta11-user-guide.md#migración-desde-beta8).

Para un proyecto sin store legacy, instala la nueva etiqueta exacta y actualiza
por separado el contrato de contexto:

```bash
.venv/bin/python -m pip install --upgrade \
  "an-kla-memory @ git+https://github.com/kristhianmanue1/an-kla-memory.git@v0.1.0-beta.38"
.venv/bin/python -m an_kla --version
.venv/bin/python -m an_kla --project-root . context status
.venv/bin/python -m an_kla --project-root . context plan --operation update
.venv/bin/python -m an_kla --project-root . context update
git diff -- AGENTS.md AN-KLA.md
.venv/bin/python -m an_kla --project-root . context status
.venv/bin/python -m an_kla --project-root . verify
```

Con el CLI global instalado con uv, el primer paso es
`uv tool install --force "an-kla-memory @ git+https://github.com/kristhianmanue1/an-kla-memory.git@v0.1.0-beta.38"`
y los siguientes usan `an-kla --project-root .` en lugar de
`.venv/bin/python -m an_kla --project-root .`. Comprueba con `--version` que
responde la instalación que acabas de actualizar.

Una plantilla anterior reconocida por huella puede migrarse aunque falte el
manifiesto local. AN-KLA respalda el `AN-KLA.md` anterior en un directorio
identificado por contenido bajo `.an-kla/context/backups/`. Si el bloque o el
contrato fueron modificados localmente, la actualización falla en cerrado y no
sobrescribe esos cambios.

Cuando edites contenido propio fuera del bloque gestionado (referencias a
`CONTRIBUTING.md`, ADRs, convenciones), el warning
`context_target_changed_outside_managed_block` es la señal esperada.
`context update` ya no lo absorbe silenciosamente (`context plan
--operation update` y `context update` fallan con
`context_target_drift_adoption_required`): revisa el diff y, si es legítimo,
adóptalo de forma explícita para que la detección de cambios futuros siga viva:

```bash
.venv/bin/python -m an_kla --project-root . context adopt-baseline
```

La operación planifica y aplica con CAS bajo el lock de contexto: adopta los
bytes observados como nueva baseline del manifiesto, sin interpretar ni
modificar tu contenido; un cambio posterior vuelve a activar el warning
(ADR-0040).

Las integraciones alfa sin marcadores no se migran automáticamente. Sigue el
procedimiento manual de la [guía de integración](context-package.md).
Si el proyecto ya tiene un store beta.8, beta.11 exigirá además adoptar su
identidad de forma explícita antes de mutarlo. El procedimiento completo y
reversible está en la [guía de instalación y migración beta.11](beta11-user-guide.md).

## Desinstalar o volver atrás

`context uninstall` retira únicamente la integración administrada; no elimina
la memoria ni desinstala el paquete:

```bash
.venv/bin/python -m an_kla --project-root . context plan --operation uninstall
.venv/bin/python -m an_kla --project-root . context uninstall
git diff -- AGENTS.md AN-KLA.md
```

Después, si lo deseas, desinstala el programa con
`.venv/bin/python -m pip uninstall an-kla-memory`. AN-KLA nunca borra
automáticamente `.an-kla/memory/`.

Para volver a una versión anterior, reinstala una etiqueta exacta y restaura
los archivos rastreados sólo después de revisar el diff y el respaldo local.
No existe una migración automática regresiva del formato de memoria.

## Uso diario

### Descubrimiento para agentes

Un agente puede inspeccionar el contrato instalado sin inicializar ni leer una
memoria del proyecto:

```bash
.venv/bin/python -m an_kla capabilities
.venv/bin/python -m an_kla schema list
.venv/bin/python -m an_kla schema show write-plan-v1
.venv/bin/python -m an_kla --project-root . context show-template
.venv/bin/python -m an_kla --project-root . context show-template --version 0.1.0-beta.3
```

`capabilities` emite JSON canónico y declara, entre otros límites, que la
recuperación v1 busca únicamente `facts` por defecto, que MCP es de sólo lectura
y que los presupuestos implementados miden bytes UTF-8, no tokens exactos. El
bloque `view` descubre el contrato G-VIEW, sus superficies CLI/MCP, proyecciones,
límites y pureza L2 sin leer memoria; declara que `.reader-gate` puede crearse o
bloquearse como artefacto de coordinación, sin mutar el sustrato. Los
schemas normativos se incluyen dentro del paquete y `schema show` entrega
sus bytes sin depender del checkout ni de la red. `context show-template` vuelca
el texto canónico del bloque administrado y del contrato detallado de la versión
instalada (o los hashes de plantillas históricas conocidas) para diagnóstico o
reparación manual.

### Diagnóstico de arranque e integración

**Records con vigencia no canónica (#179, ampliada por #181).** Si `verify` (o
`doctor`, que lo incluye) devuelve `noncanonical_vigency`, el store tiene
records cuyo `status`/`nu` no es cadena ni `null` (lotes b31/b32) o es la
cadena vacía (escribible por v1; desde #181 deja de contar como `vigente`).
La integridad no está afectada (`ok: true`); se localizan con
`inventory --revision <rev>` (`physical_status: no_canonica`). Cuentan como no
vigentes: no se pueden superseder ni refutar, y `compact` los retira como
tombstone.

Antes de trabajo material, un agente puede clasificar qué hay integrado sin
inicializar ni adoptar nada (read-only, exit 0 en todo caso diagnosticable):

```bash
.venv/bin/python -m an_kla --project-root . startup-diagnostic
.venv/bin/python -m an_kla --project-root . integration status
```

`startup-diagnostic` (ADR-0036) expone ejes observables independientes:
presencia e integridad del store, identidad y contexto de repositorio
(`main_checkout` / `linked_worktree`). La combinación `store_presence:
absent` + `linked_worktree` distingue un worktree sin memoria de un
proyecto nuevo: la regla es apuntar al checkout canónico, nunca
inicializar memoria propia en el worktree. Con los hooks del host
declarados (ADR-0047), `integration status --schema-version v2` añade el
bloque `host_hooks` y el perfil observado — ver la
[guía de hooks](host-hooks-guide.md).

`integration status` (ADR-0039) compone store, contexto gestionado y modo
de integración en ejes separados. Declara lo que no puede verificar:
`agent_binding: unverified` y `sharing_boundary:
filesystem-access/unverified`; no promete privacidad ni distingue perfiles
en v1 (`observed_profile: unspecified` hasta que G2 exista).

### Códigos de salida del CLI

Para consumidores programáticos, la superficie es estable y está publicada
en `capabilities` (`cli_error_surface`):

- **rc 0** — comando terminado en su estado terminal firme.
- **rc 1** — error del motor: `an-kla error: <código>` en stderr, payload
  en stdout cuando existe; nunca traceback salvo `AN_KLA_DEBUG`.
- **rc 2** — uso inválido (argumentos o flags).
- **rc 3** — comando **ejecutado sin estado terminal firme**: el payload
  completo sale por stdout y **stderr queda vacío por contrato** (asumido
  por consumidores que tratan rc≠0 como ruido). No es un fallo del store:
  significa que el outcome todavía no es el terminal (p. ej.
  `transaction inspect` con `outcome_unknown`, `compact commit` sin
  `state: committed`). Un consumidor que filtra por exit code **debe leer
  también el stdout** cuando rc=3; la matriz de casos vive en
  `an_kla.__main__.pending_outcome_reason` y en `capabilities`.

### Verificación no bloqueante de versiones

Al iniciar, el CLI consulta la release más reciente publicada en GitHub
(sólo lectura, sin aplicar) y, si existe una versión más nueva, imprime el aviso
a **stderr** junto con el comando `pip` sugerido. AN-KLA **no se actualiza a sí
mismo**: el operador decide. El hook se omite en CI (`CI`, `GITHUB_ACTIONS`) y
con `AN_KLA_NO_UPDATE_CHECK=1`; el flag `--no-update-check` desactiva la
verificación por invocación, y `check-updates` fuerza una re-validación.

### Actualización gobernada del proyecto

Después de instalar una etiqueta exacta con el gestor de paquetes, un agente
puede inspeccionar la actualización de la integración sin mutar el proyecto:

```bash
.venv/bin/python -m an_kla --project-root . upgrade inspect \
  --target v0.1.0-beta.38 > RUTA_EFIMERA_NUEVA
```

El agente debe conservar por separado el `plan_fingerprint` devuelto, revisar
el plan. Si `identity status` informa `legacy_unadopted`, debe completar primero
el plan de adopción descrito en la guía beta.11. Después aplica exactamente los
bytes del upgrade:

```bash
.venv/bin/python -m an_kla --project-root . upgrade apply \
  <plan_fingerprint> --plan RUTA_EFIMERA_NUEVA
.venv/bin/python -m an_kla --project-root . upgrade verify \
  --target v0.1.0-beta.38
git diff -- AGENTS.md AN-KLA.md
```

`upgrade` no ejecuta `pip`, no descarga paquetes y no se reemplaza a sí mismo.
La etiqueta objetivo debe corresponder a la versión ya instalada. El plan se
liga por hash al estado observado de `AGENTS.md`, `AN-KLA.md` y el manifiesto;
la aplicación reutiliza CAS, lock local, escritura atómica y respaldos por
contenido de `context-package/v1`. Consulta la
[guía de actualización para agentes](upgrade-agent-flow.md).

### Recuperación y escritura

Al escribir, dos esperas comparten el mismo presupuesto (la constante única
`WRITE_LOCK_DEADLINE_SECONDS`, 10 s) y fallan reintentables con
`an-kla error: write_lock_busy` (lock de escritura ocupado) o
`an-kla error: writer_gate_busy` (ADR-0059: el escritor esperó el gate
compartido mientras `compact commit` lo excluye). Ante cualquiera de las
dos: relee `status`, reconstruye proposal/authority sobre la revisión nueva
y reintenta; los planes no se reutilizan. La planificación (`plan-write`,
`refute plan`) y el commit comparten el trato; una compactación concurrente
no produce errores de integridad en la planificación (ADR-0060: el par
`read_current`+`snapshot` es coherente bajo el gate).

```bash
.venv/bin/python -m an_kla --project-root . status
.venv/bin/python -m an_kla --project-root . verify
.venv/bin/python -m an_kla --project-root . retrieve \
  --query "estado del proyecto" --budget 1200
.venv/bin/python -m an_kla --project-root . retrieve \
  --query "lecciones aprendidas" --budget 2000 --streams facts,episodes,events
.venv/bin/python -m an_kla --project-root . retrieve \
  --query "hechos por reconfirmar" --budget 2000 \
  --freshness-profile computed-age/v1 \
  --now 2026-08-08T00:00:00Z --stale-after-days 30
.venv/bin/python -m an_kla --project-root . assemble-context \
  --query "estado del proyecto" \
  --new-information "solicitud actual" \
  --budget 2400
```

`retrieve` admite el flag `--streams` (CSV; por defecto `facts` para respetar la
beta). El resultado incluye `excluded_detail.ids` (truncado a 50 IDs por razón)
cuando los registros se excluyen por `budget`, `zero_score`, `inactive`,
`no_text` o `invalid_record`. Si la selección queda vacía por **cero
solapamiento léxico** (típico de un agente fresco que aún no conoce el
vocabulario del store), el resultado porta `empty_reason:
"no_lexical_overlap"` (schema `retrieval-result-v3` / `mcp-retrieve-v3`;
ADR-0049): la acción sugerida es descubrir el vocabulario con `inventory` o
reformular la query con términos del dominio. Los vacíos por presupuesto o
por vigencia NO emiten esa señal — la causa real es otra.

El perfil opcional `computed-age/v1` proyecta la edad de `verified_at` después
de seleccionar: no cambia score, orden, autoridad ni exclusiones de retrieval.
`verified_at` es un timestamp autodeclarado por el registro, no una verificación
realizada por AN-KLA. Sin perfil explícito, los payloads v1 permanecen iguales.
Con el perfil activo, el bloque `freshness` declara además los denominadores
de la selección final (ADR-0037): `evaluated`, `not_evaluable`,
`unparseable` y `stale`, con el invariante `evaluated + not_evaluable +
unparseable = |seleccionados|`. Así "nada está desfasado" deja de ser
indistinguible de "nada era evaluable": un corpus a medio migrar lo declara.

La salida completa de `context-assembly/v1` queda acotada en bytes UTF-8;
consulta [ADR-0006](architecture/0006-context-assembly-v1.md). La escritura
nueva debe usar `plan-write` y `commit-write-plan`, descritos en la
[guía de escritura gobernada](write-policy-cli.md). El comando público
histórico `write` fue retirado en beta.11; `MemoryStore.commit()` queda sólo
como API interna de mantenimiento y tests.

La continuidad operacional usa acceso exacto, no búsqueda por similitud:

```bash
.venv/bin/python -m an_kla --project-root . checkpoint show
.venv/bin/python -m an_kla --project-root . resume --query "siguiente paso" --budget 4096
.venv/bin/python -m an_kla --project-root . transaction inspect UUID
.venv/bin/python -m an_kla --project-root . export verify --bundle RESPALDO
```

### Estado de una casilla e historia

Un agente que reanuda trabajo necesita **el estado actual**, no una búsqueda
(ADR-0065). `remember --kind state` escribe en una **casilla** —el par
(`repo.id`, `slot`); `main` por defecto— y, al vaciar la bandeja, jubila sólo
la cabeza vigente de esa casilla, la haya escrito quien la haya escrito y sin
abrir disputa. Dos agentes que trabajan a la vez en cosas distintas del mismo
repo usan `--slot` distintos; con `main` para todos gana el último que escribe.

```bash
.venv/bin/python -m an_kla --project-root . remember --kind state --slot e1d1 \
  --text-file - <<< "Implementado el vaciado; faltan los presupuestos."
.venv/bin/python -m an_kla --project-root . state show                 # casilla main
.venv/bin/python -m an_kla --project-root . state show --slot e1d1
.venv/bin/python -m an_kla --project-root . state show --all-slots --budget 2000
.venv/bin/python -m an_kla --project-root . history ID_DE_LA_CABEZA --limit 50
```

- `state show` es de sólo lectura: **no vacía la bandeja** (informa de
  `inbox.pending` y, por casilla, de `pending_states`) y no depende de
  `recall`. Devuelve una cabeza por casilla con `retired_count`; si una casilla
  tiene más de un vigente (sólo por `plan-write`, restauración o `relocate`)
  sirve la cabeza y declara el resto en `conflict`: nunca elige en silencio. Si
  no hay ningún `state` vigente, responde `empty: true`.
- `--budget` (4000 por defecto en `state show`, 16000 en `history`) acota la
  salida completa en bytes, con su salto de línea final. Una casilla que no
  cabe sale como stub (`truncated: true`); por debajo de la respuesta vacía el
  comando falla con `state_budget_too_small` / `history_budget_too_small`
  (rc 1).
- `history <id>` recorre en anchura, en los dos sentidos, las aristas
  `supersedes` y `disputes` desde el registro dado, con `--limit` nodos
  (`truncated` si corta). Nodos en orden total (`enqueued_at`, legados al
  final, `id`) y aristas `{from, to, type}` sólo con ambos extremos presentes.
- `remember --kind state --supersedes <id>` nunca sustituye un `fact` ni una
  `decision`: responde `rejected` con `remember_state_over_fact` (rc 3) y el
  registro sigue vigente. Un `--supersedes` de un `state` de otra casilla, o de
  uno que no es la cabeza, da `remember_state_slot_mismatch`. Los estados
  escritos antes como `fact` no se jubilan con un `state`: se retiran por el
  camino antiguo antes de adoptar la casilla.
- Reintentar es idempotente contra el último `state` del mismo escritor en la
  casilla: un reintento tardío no pisa a otro agente (`already_committed` con
  `retired_by`). Para reafirmar a propósito el mismo texto, otra
  `--idempotency-key`. Un `state` en cola no anuncia `record_id`.
- Las entradas con casilla se encolan como `inbox-entry-v2`; un binario anterior
  no las lee: ejecuta `inbox drain` y comprueba `pending` 0 antes de bajar de
  versión. Si un `inbox drain` anterior ya las rechazó:
  `inbox requeue --all-format && inbox drain` (ver «Rechazos de la bandeja»).

### Listar registros (`list`)

`retrieve` busca; `list` enumera. Para ver **todos** los hechos vigentes (por ejemplo
antes de retirar los estados viejos guardados como `fact`):

```bash
.venv/bin/python -m an_kla --project-root . list                       # hechos vigentes, sin texto
.venv/bin/python -m an_kla --project-root . list --text                # con el texto, para clasificar
.venv/bin/python -m an_kla --project-root . list --streams facts,episodes --status all
.venv/bin/python -m an_kla --project-root . list --streams episodes --kind state --slot main
.venv/bin/python -m an_kla --project-root . list --limit 100 --after "$NEXT"
```

- De sólo lectura: una sola revisión, sin Git y sin tocar la bandeja. Por defecto
  `--streams facts --status active --limit 1000 --budget 65536`.
- Orden: un bloque por stream, en el orden de `--streams`; dentro, los registros con sobre
  por `enqueued_at` y `id`, y los legados al final (`legacy: true`).
- Cada registro lleva `status`, `superseded_by`, `disputes_count`, `anchors_count` y
  `coverage_level` (sólo si tiene anclas; no se comprueba ninguna: eso es `anchors verify`)
  y `text_bytes`. El texto sólo sale con `--text`.
- `total = returned + excluded.limit + excluded.budget`. Si `truncated` es `true`, `next`
  es el cursor para `--after`; con otra revisión da `list_cursor_stale` (empieza de nuevo) y
  con otros filtros, `list_cursor_invalid`. El tamaño de página (`--limit`, `--budget`) sí
  puede cambiar entre páginas.
- Errores (rc 1): `list_streams_invalid`, `list_status_invalid`, `list_kind_invalid`,
  `list_slot_invalid`, `list_limit_invalid` (máximo 10000), `list_budget_invalid`,
  `list_cursor_invalid`, `list_cursor_stale` y `list_budget_too_small` (también cuando
  cabe la respuesta vacía pero no el primer registro; el detalle da los bytes que necesita).

### Anclas, frescura y disputa

Un recuerdo sin fuente no se puede comprobar. Con **anclas** (C3,
`memoria/ancla/v1`; ADR-0066) un `remember` cita su fuente y quien lo lee ve,
sin fiarse de quien lo escribió y sin ningún modelo, si la cita sigue ahí.

```bash
# Atajo: un hecho, una afirmación, una cita literal (8 a 300 bytes).
.venv/bin/python -m an_kla --project-root . remember --text-file - \
  --anchor-path docs/config.md --anchor-quote "El servidor usa port = 8081" <<< "El servidor usa el puerto 8080"
# Forma completa: lista JSON de 0 a 16 anclas (repo y session los pone la herramienta).
.venv/bin/python -m an_kla --project-root . remember --text-file - --anchor-file anclas.json <<< "..."
.venv/bin/python -m an_kla --project-root . anchors verify ID          # volver a comprobar (auditoría)
.venv/bin/python -m an_kla --project-root . anchors verify --all --anchor-limit 32
.venv/bin/python -m an_kla --project-root . dispute ID --verdict contradicted --text-file - <<< "la cita no lo respalda"
```

- **Tres comprobaciones, nunca un booleano**: `source` (¿la fuente existe donde se
  mira?), `quote` (¿la cita está?) e `integrity` (¿la fuente es la observada?),
  cada una `verified`, `not_found` o `unverifiable` con un `reason` de
  vocabulario cerrado, más `at`, `match` y `matched_text`. De ellas sale la
  `freshness`: `fresh`, `stale`, `broken`, `unverified` o `pending`. **`fresh`
  significa que la cita sigue ahí, no que el hecho sea cierto.**
- **Al escribir** se comprueba una sola vez, al encolar, con la fuente delante: un
  `state` en el árbol de trabajo; un `fact` o una `decision` en el `commit`
  declarado (el atajo toma el `HEAD`). Una comprobación `not_found` rechaza el
  recuerdo entero, sin entrada y sin cambio en el store (`anchor_source_not_found`,
  `anchor_quote_not_found`, `anchor_integrity_not_found`); un `unverifiable` se
  acepta. Otros rechazos: `anchor_too_many` (más de 16), `anchor_schema_invalid`,
  `anchor_quote_not_normalized`, `anchor_quote_too_short`, `anchor_quote_too_long`,
  `anchor_path_invalid`, `anchor_input_invalid` (JSON mal formado).
  `--anchor-file -` no puede coincidir con `--text-file -`.
- **Cobertura determinista** (`fact-checks-rules/v2`, ADR-0070): `coverage`, `missing` y
  `missing_total` comparan los elementos del texto (identificadores entre
  comillas invertidas, rutas y URL, huellas hexadecimales de 7 a 64 caracteres,
  versiones, fechas `AAAA-MM-DD` y números) con la **cita guardada**.
  «El servidor usa el puerto 8080» con una cita que dice 8081 da `level: none` y
  `missing: [{type: number, value: "8080"}]`. El registro siempre se guarda y
  ningún nivel afirma respaldo: sólo `none` es un aviso.
  - **`coverage.rules`** dice con qué reglas se calculó. Todo lo que se escribe desde
    esta versión (`remember`, el vaciado, `dispute`) lleva `"fact-checks-rules/v2"`.
    **Un `coverage` sin `rules` es de `fact-checks-rules/v1`**: lo escrito por
    beta.36 a beta.38, que no se recalcula ni se reescribe y se sirve tal cual.
    Una fecha cuenta como un elemento, no como tres números.
  - **En un `state`** sólo cuentan identificadores, rutas, huellas y versiones: sin ninguno
    el nivel es `unchecked`, y `none` sigue avisando cuando el estado cita algo ajeno,
    no por cifras de avance. Un hecho anclado, una afirmación.
  - Una respuesta con cobertura v2 sale con `remember-result-v2` (y `history`, `state
    show` y `anchors verify` con su versión `-v2`); sin ella, el esquema es el de siempre.
  - Límites declarados: un año suelto no casa con una fecha completa, una fecha en
    palabras no es la canónica, `beta.38` y `0.1.0b38` no son equivalentes y `deface1`
    cuenta como huella.
- **Al leer** (`state show`, `history`, `anchors verify`) se vuelve a comprobar
  con el estado de ahora: el `HEAD` de la rama por defecto y, si no basta, la
  rama del sobre. La rama por defecto no se adivina: `AN_KLA_DEFAULT_BRANCH`
  (vacía = no hay) o la clave `default_branch` de `<store>/config.json` (que
  esta versión sólo lee); sin ninguna, `origin/HEAD`; sin eso, `no_default_branch`.
  Sólo se comprueban `--anchor-limit` anclas (32), en orden de servicio; el
  resto sale `unverified`/`anchor_limit` y la salida declara cuántas se
  comprobaron. No hay tope de tiempo. Leer nunca arranca un custodio.
  `anchors_freshness` de un registro es la peor de sus anclas. `retrieve` no cambia.
  Un `document` es la excepción: no se vuelve a comprobar al leer, se sirve lo guardado
  (ver «Citar un documento custodiado»).
- **`conversation` y `document`**: un ancla de conversación nace `pending` y se
  guarda siempre así; hasta que exista el resolutor de C2 no hay orden que la
  resuelva (el esquema `anchor-resolution-v1` y su vista ya están). Un `document`
  de `memoria/ancla/v1` ya guardado sigue respondiendo `unverified`/`kind_not_supported`
  hasta su primera auditoría.
- **`dispute`**: guarda un dictamen externo (`contradicted` o `insufficient`; un
  `supported` o `not_reviewed` da `dispute_verdict_invalid`) como una disputa con
  la forma de ADR-0063 D3. El objetivo sigue vigente, también un `state`: nunca se
  sustituye ni se jubila. `disputes list`, `state show` e `history` muestran el
  veredicto más reciente de cada escritor. El dictamen es dato no confiable.
- **Idempotencia**: las anclas (y el veredicto) forman parte de la clave derivada.
  Una `--idempotency-key` explícita reutilizada con otras anclas da
  `remember_id_collision` (`idempotency_key_other_anchors`).
- Las entradas con anclas se encolan como `inbox-entry-v3`; un binario anterior no
  las lee: `inbox drain` y `pending` 0 antes de bajar de versión. Si un `inbox
  drain` anterior ya las rechazó, ver «Rechazos de la bandeja». Las que llevan un
  `document` de `memoria/ancla/v2` (o la anotación de una auditoría) van como `inbox-entry-v4`.

### Citar un documento custodiado (`document`)

(ADR-0071, contrato `memoria/ancla/v2`.) Una página de un PDF que guarda un custodio
(p. ej. skopos) se cita con comprobación real, sin que an-kla lea los archivos del custodio:
un programa que configura el Operador, el **adaptador**, responde por el documento, su
derivación y los elementos de la página.

**Configurar el custodio.** Una tabla `custodians` en `<store>/config.json` (la misma que
lleva `default_branch`), o en el archivo al que apunte `AN_KLA_CUSTODIANS`, que la sustituye entera:

```json
{"custodians": {"skopos": {"argv": ["/ruta/python", "-B", "/ruta/adaptador.py", "--runs-root", "/ruta/runs"]}}}
```

`argv` es una lista con rutas absolutas; nunca pasa por un intérprete de órdenes, y el nombre del
custodio (`[a-z0-9][a-z0-9_-]{0,31}`) es sólo la clave de la tabla. El adaptador corre con
`PATH=/usr/bin:/bin`, `LC_ALL=C`, directorio `/`, 10 s de plazo y 8 MiB de salida como máximo.
Un custodio que no está en la tabla es «sin adaptador»; una tabla que no se puede leer da
`adapter_error` en todos y la respuesta lo dice (`custodians_config_error`).

**Citar.** Con el atajo (repetible, en grupo), o con `--anchor-file` y el ancla completa:

```bash
python3 -m an_kla remember --text-file - --kind fact \
  --anchor-document <sha256> --anchor-custodian skopos --anchor-derivation <derivation_id> \
  --anchor-manifest <sha256> --anchor-modality native_text --anchor-page 188 \
  --anchor-item i-12 --anchor-item i-13 --anchor-copy docs/fuentes/manual.pdf \
  --anchor-quote "El personal de base tendrá derecho a veinte días de vacaciones" < texto.txt
```

- La **página** es la física del archivo (1…N) y es obligatoria (`anchor_locator_required`). Sin
  `--anchor-item` la cita se busca en toda la página (`{page}`); con uno, en ese elemento; con
  varios, en ellos, **en el orden del custodio**. En OCR casi ninguna cita cabe en un solo
  elemento: lo normal es citar por varios elementos o por `{page}`. La cita no cruza páginas.
- La cita mide de 40 a 300 bytes sin contar espacio en blanco. Una cita `visual` no se comprueba
  (`derived_modality`).
- `--anchor-copy` es opcional: la copia local, **leída por Git de la rama por defecto** al escribir
  y al auditar, nunca del árbol de trabajo. Una copia añadida en una rama aún no integrada cuenta
  como ausente (`anchor_copy_not_found`); se omite la copia o se integra antes. El `repo` de la
  copia es el del proyecto y lo pone la herramienta.
- Al escribir se rechaza todo lo que no sea una cita comprobada, con el código de la causa
  (`anchor_source_not_found`, `anchor_integrity_not_found`, `anchor_derivation_*`,
  `anchor_locator_*`, `anchor_quote_not_found`); sin adaptador o con el adaptador fallando se
  acepta como `unverified`. Un sha256 de copia distinto se rechaza siempre.

**Comprobar y leer.** Se comprueba **al escribir y al auditar**; al leer (`history`, `state show`)
se sirve el último resultado guardado, con su fecha (`checked_at`), y **no se llama a nadie**.
`anchors verify <id>|--all` llama al adaptador por cada `document` (v1 o v2) y **guarda** una
anotación `an-kla/anchor-check-v1` en `events` por registro auditado (`recorded`, `record_error`;
sin identidad C0 audita igual y dice `recorded: false`). Es lo único que `anchors verify` escribe:
para `repo-file` y `conversation` sigue siendo de sólo lectura. Un v2 nunca comprobado sale
`unverified`/`not_checked`. Cada auditoría añade una anotación y **la compactación de hoy no las
poda**: se audita cuando hace falta, no en bucle.

Vuelta atrás: `inbox drain` y `pending` a 0 antes de bajar a beta.38, que rechaza entera la
entrada `inbox-entry-v4` pendiente; un registro ya comprometido lo lee beta.38 sin romper, sirve el
ancla como `kind_not_supported` e ignora `anchor_checks` y las anotaciones.

### Ámbito, destinatario y órdenes del Operador (`directive`)

(ADR-0069.) Un recuerdo puede decir de qué proyecto trata y para quién es. Sin los
campos nuevos nada cambia: un registro sin `subject` ni `audience` nunca se filtra.

- **Escribir el ámbito**, en `fact`, `decision` y `state`: `remember --subject <repo.id>
  --audience all|role:<papel>|agent:<nombre>`. `subject` es un `repo.id` de C0
  (`host[:puerto]/ruta`, `local:` o `remoto:` + 16 hex), nunca un nombre corto
  (`remember_subject_invalid`, `remember_audience_invalid`).
- **Escribir una orden** del Operador, la que recibió un orquestador o un capitán
  y que éste registra citando la conversación:

  ```bash
  AN_KLA_AGENT_NAME=orq-memoria AN_KLA_AGENT_ROLE=orquestador AN_KLA_SESSION_ID=<sesión> \
    an-kla --project-root . remember --kind directive --text-file - \
      --subject example.org/equipo/proyecto-p --audience agent:orq-memoria \
      --until-revoked --anchor-file conversacion.json   # o --valid-until 2026-12-01
  ```

  `conversacion.json` es `[{"source": {"kind": "conversation"}, "quote": "<cita literal>"}]`.
  Son obligatorios, sin valor por defecto, y se comprueban en este orden: papel
  `orquestador` o `capitan` (`directive_role_not_allowed`), sesión real
  (`directive_session_missing`), `--subject`, `--audience`, una sola vigencia
  (`directive_validity_missing` o `_conflict`) y un ancla `conversation`
  (`directive_anchor_missing`). El rechazo sale en JSON (`remember-error-v2`, rc 3) y
  no deja entrada. Sólo se escribe con `remember`: `plan-write` la rechaza
  (`plan_write_scope_fields_not_allowed`).
- **Cambiarla o retirarla:** `remember --kind directive --supersedes <id>` con su propio
  ámbito y vigencia (mismo `subject`, o `directive_subject_mismatch`), o `--supersedes <id>
  --revoke`, que hereda `subject` y `audience` del destino y no lleva vigencia. Cualquier
  orquestador o capitán del mismo `subject` puede hacerlo, sea suya o no, sin abrir
  disputa; también lleva su ancla `conversation`. Un `dispute <id>` de cualquier papel la
  deja vigente pero no accionable.
- **Cómo la recibe su destinatario.** El lector es la identidad C0 del entorno
  (`AN_KLA_AGENT_NAME`, `AN_KLA_AGENT_ROLE`) y su proyecto es el del checkout, o el que
  declare con `--subject <repo.id>`. `retrieve`, `list` y `state show` no sirven lo que
  es para otro y lo cuentan en `other_audience`; con `--include-other-audience` lo sirven
  con `for_reader: false`. MCP filtra siempre y no tiene el flag. `history`, `disputes
  list` y `anchors verify` marcan sin filtrar.
- **Qué lleva una `directive` servida:** el objeto `directive` con su `status`
  (`unverified` hoy; `verified` cuando exista un resolutor de conversaciones;
  `invalidated`, `expired`, `revocation` y `malformed` no se sirven como orden) y su
  `actionable`. Sólo es `true` si la orden es del proyecto del lector, **nombra** al
  lector (`agent:<su nombre>` o `role:<su papel>`; `all` no basta) y no tiene disputas
  vigentes. Si es `false`, vale como contexto: para cambiar una acción por ella hay que
  confirmarla con el Operador. `unverified` + `actionable: true` significa que se puede
  actuar sin esperar al resolutor, y que lo que se sirve es la palabra de quien la escribió.
- **`assemble-context` y `resume` no inyectan ninguna `directive`**: filtran como
  `retrieve` y cuentan `directive_not_injected`. Léelas con `retrieve`, `list` o `state show`.
- **Bajar de versión:** un binario anterior (beta.38 o menos) lee los registros nuevos sin
  entenderlos y sirve las directivas sin filtro y sin marca. No bajes con directivas
  escritas, o no las escribas hasta haber adoptado la versión en todo el puesto. Las
  entradas `inbox-entry-v4` tampoco las lee: `inbox drain` y `pending` 0 antes de bajar.

### Rechazos de la bandeja

`inbox status` cuenta en `rejected` lo que el vaciado no pudo escribir, con su
`.reason` (ADR-0068). Dos órdenes sacan algo de `rejected/`; ninguna edita ficheros
a mano y las dos toman el candado de escritura como un lote más.

- **Vuelta atrás de versión.** Un `inbox drain` de una versión anterior rechaza con
  `inbox_entry_invalid` las entradas de un formato que no conoce (v2, v3). Ya en la
  versión nueva:

  ```bash
  an-kla inbox requeue --all-format && an-kla inbox drain
  ```

  `requeue` sólo mueve a `pending/` los rechazos de inodo seguro cuyo `.reason` es
  `inbox_entry_invalid` **y** que esta versión valida ahora, con su nombre canónico (sin
  sufijo `.<n>`; si ese nombre ya existe en `pending/` recibe uno nuevo y no pisa nada).
  No vacía: ese es el `inbox drain` de después. Lo demás se informa en `skipped` y no se
  toca: `not_requeueable_policy` (un rechazo de política, p. ej.
  `remember_state_over_fact`: se rehace con un `remember` nuevo), `still_invalid`,
  `not_requeueable_unsafe` (sólo queda el `.reason`) y `orphan_reason` (un `.reason` sin
  su entrada, resto de un corte entre los dos pasos; la entrada ya está en `pending/`).
- **Purga.** Para dejar `rejected.count` en 0 (por ejemplo antes de adoptar un
  procedimiento que lo exige), lee los `.reason` y purga con respaldo obligatorio:

  ```bash
  an-kla inbox purge-rejected --all --backup /ruta/absoluta/fuera/del/store
  ```

  Cada rechazo se copia al respaldo (también su `.reason`, o sólo éste si el inodo era
  inseguro), se comprueba su sha256 y sólo entonces se borra el original. `--backup` es
  un directorio absoluto fuera de `.an-kla/`; se crea con modo 0700 si falta (su padre
  debe existir) y puede reutilizarse: las copias de purgas anteriores se aceptan si su
  sha256 coincide. No hay `--no-backup`. Un archivo ajeno o una copia con el mismo
  nombre y otro sha256 dan `inbox_purge_backup_invalid` y no se purga nada; una copia que
  falla se informa en `failed` (`backup_failed`, rc 3) y de ese rechazo no se borra nada.
- **Lotes.** Cada invocación cambia 50 rechazos como mucho; `remaining` dice cuántos
  faltan: repite la orden. Los rechazos que no se tocan no consumen lote.
- **Ocupado.** Con el candado de escritura o el de identidad tomados por otro proceso
  (una reubicación, un `drain` largo) responden `write_lock_busy` o `identity_lock_busy`:
  `remember-error-v1`, `retryable: true`, rc 3 y ningún cambio. Se reintenta igual.

### Respaldo sellado (opcional)

El perfil `sealed-export/v1` (ADR-0042) cifra el respaldo en reposo
como extra opcional — sin él, el camino `export/v1` en claro queda
intacto y el paquete sigue siendo stdlib-only:

```bash
.venv/bin/python -m pip install 'an-kla-memory[sealed]'
.venv/bin/python -m an_kla --project-root . export create \
    --bundle RESPALDO_SELLADO \
    --seal sealed-export/v1 \
    --key-adapter /ruta/al/adaptador
.venv/bin/python -m an_kla export verify --bundle RESPALDO_SELLADO \
    --key-adapter /ruta/al/adaptador
```

La CEK de cada bundle la custodia un adaptador externo de claves
(contrato JSON por stdio, sin shell; en producción: Keychain, KMS,
age). Sin clave, `export verify` es estructural y jamás afirma
`verified: true`; con clave, autentica AEAD + MAC por entrada. El
sello da integridad bajo una clave, no atestación de origen: registra
el `bundle_id` que devuelve `create` y compáralo antes de restaurar.
Consulta la [guía del perfil sellado](sealed-export-guide.md).

Checkpoint, identidad, refute, export/restore y compactación tienen contratos
plan→commit propios. Desde ADR-0038, el `source_state` del working state
admite el perfil `git/v1` con valores `caller_asserted`: el caller observa
Git (HEAD completo, branch, digest del árbol sucio) y liga el checkpoint al
commit que describe; el CLI nunca ejecuta Git ni acuña autoridad. Consulta
la [guía beta.11](beta11-user-guide.md) antes
de cualquier operación mutativa o destructiva.
