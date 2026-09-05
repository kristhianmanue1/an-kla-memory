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
  "an-kla-memory @ git+https://github.com/kristhianmanue1/an-kla-memory.git@v0.1.0-beta.21"
.venv/bin/python -m an_kla --version
.venv/bin/python -m an_kla --project-root . context status
.venv/bin/python -m an_kla --project-root . context plan --operation update
.venv/bin/python -m an_kla --project-root . context update
git diff -- AGENTS.md AN-KLA.md
.venv/bin/python -m an_kla --project-root . context status
.venv/bin/python -m an_kla --project-root . verify
```

Una plantilla anterior reconocida por huella puede migrarse aunque falte el
manifiesto local. AN-KLA respalda el `AN-KLA.md` anterior en un directorio
identificado por contenido bajo `.an-kla/context/backups/`. Si el bloque o el
contrato fueron modificados localmente, la actualización falla en cerrado y no
sobrescribe esos cambios.

Cuando edites contenido propio fuera del bloque gestionado (referencias a
`CONTRIBUTING.md`, ADRs, convenciones), el warning
`context_target_changed_outside_managed_block` es la señal esperada.
`context update` ya no lo absorbe silenciosamente: adóptalo de forma explícita
para que la detección de cambios futuros siga viva:

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
inicializar memoria propia en el worktree.

`integration status` (ADR-0039) compone store, contexto gestionado y modo
de integración en ejes separados. Declara lo que no puede verificar:
`agent_binding: unverified` y `sharing_boundary:
filesystem-access/unverified`; no promete privacidad ni distingue perfiles
en v1 (`observed_profile: unspecified` hasta que G2 exista).

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
  --target v0.1.0-beta.19 > RUTA_EFIMERA_NUEVA
```

El agente debe conservar por separado el `plan_fingerprint` devuelto, revisar
el plan. Si `identity status` informa `legacy_unadopted`, debe completar primero
el plan de adopción descrito en la guía beta.11. Después aplica exactamente los
bytes del upgrade:

```bash
.venv/bin/python -m an_kla --project-root . upgrade apply \
  <plan_fingerprint> --plan RUTA_EFIMERA_NUEVA
.venv/bin/python -m an_kla --project-root . upgrade verify \
  --target v0.1.0-beta.19
git diff -- AGENTS.md AN-KLA.md
```

`upgrade` no ejecuta `pip`, no descarga paquetes y no se reemplaza a sí mismo.
La etiqueta objetivo debe corresponder a la versión ya instalada. El plan se
liga por hash al estado observado de `AGENTS.md`, `AN-KLA.md` y el manifiesto;
la aplicación reutiliza CAS, lock local, escritura atómica y respaldos por
contenido de `context-package/v1`. Consulta la
[guía de actualización para agentes](upgrade-agent-flow.md).

### Recuperación y escritura

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
`no_text` o `invalid_record`.

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
