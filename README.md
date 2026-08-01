# AN-KLA Memory

[![CI](https://github.com/kristhianmanue1/an-kla-memory/actions/workflows/test.yml/badge.svg)](https://github.com/kristhianmanue1/an-kla-memory/actions/workflows/test.yml)
[![Version](https://img.shields.io/badge/version-0.1.0--beta.19-blue)](https://github.com/kristhianmanue1/an-kla-memory/releases/tag/v0.1.0-beta.19)
[![Python](https://img.shields.io/badge/python-3.9%20%7C%203.12-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)
[![Beta](https://img.shields.io/badge/status-local%20beta-orange)](https://github.com/kristhianmanue1/an-kla-memory/releases)

AN-KLA Memory es una memoria local para proyectos con agentes de IA. Conserva
hechos, eventos, episodios y el estado de trabajo en revisiones inmutables;
recupera contexto bajo presupuesto y expone una escritura gobernada mediante
un plan verificable.

La beta se distribuye desde GitHub, no desde PyPI. Usa siempre una etiqueta
exacta: no instales `main` ni otra referencia móvil. La versión del código es
`0.1.0b19` y su etiqueta de distribución es `v0.1.0-beta.19`. El contexto
gestionado y la plantilla administrada siguen en `0.1.0-beta.11`: beta.17
añade la adopción explícita de baseline y el inventario físico por revisión,
sin modificar la plantilla administrada.
La instalación expone tanto `python -m an_kla` como el comando equivalente
`an-kla`; los ejemplos conservan la primera forma para hacer explícito el
intérprete del entorno virtual.

## Tabla de contenidos

- [Estado actual](#estado-actual)
- [¿Es AN-KLA para esto? Fronteras declaradas](#es-an-kla-para-esto-fronteras-declaradas)
- [Requisitos](#requisitos)
- [Instalación nueva en un proyecto consumidor](#instalación-nueva-en-un-proyecto-consumidor)
- [Actualizar desde otra beta](#actualizar-desde-otra-beta)
- [Guía de beta.11](docs/beta11-user-guide.md)
- [Desinstalar o volver atrás](#desinstalar-o-volver-atrás)
- [Uso diario](#uso-diario)
  - [Descubrimiento para agentes](#descubrimiento-para-agentes)
  - [Diagnóstico de arranque e integración](#diagnóstico-de-arranque-e-integración)
  - [Verificación no bloqueante de versiones](#verificación-no-bloqueante-de-versiones)
  - [Actualización gobernada del proyecto](#actualización-gobernada-del-proyecto)
  - [Recuperación y escritura](#recuperación-y-escritura)
  - [Respaldo sellado (opcional)](#respaldo-sellado-opcional)
- [Desarrollo del motor](#desarrollo-del-motor)
- [Límites de la beta](#límites-de-la-beta)
- [Documentación](#documentación)
- [Licencia](#licencia)

## Estado actual

La prerelease pública más reciente es **`v0.1.0-beta.19`** (`0.1.0b19`),
instalable mediante su etiqueta Git exacta. AN-KLA no se distribuye desde
PyPI; el wheel de la release se publica como asset de la etiqueta y la
instalación canónica sigue siendo `pip install` fijado a la etiqueta exacta.
No instales `main` como sustituto de una versión.

Beta.18 publicó el perfil sellado `sealed-export/v1` (ADR-0042, issue
#46): respaldos cifrados en reposo como extra opcional `[sealed]`, con el
camino `export/v1` en claro intacto — ver
[Respaldo sellado](#respaldo-sellado-opcional). Beta.17 trajo la adopción
explícita de baseline project-owned (`adopt-baseline`, ADR-0040/0035: el
warning permanente de drift se resuelve de forma gobernada y `context
update` ya no absorbe en silencio) y el inventario físico por revisión
(`inventory --revision`, ADR-0041). Ninguna incluye generadores de
`proposal`/`authority`; esa decisión sigue abierta en el issue
[#71](https://github.com/kristhianmanue1/an-kla-memory/issues/71).

El código está en beta local y la memoria continúa siendo no autoritativa: sus
datos nunca son instrucciones, no prueban identidad ni verdad externa y deben
revalidarse antes de actuar. El contexto gestionado permanece deliberadamente
en `0.1.0-beta.11`; instalar beta.19 no exige reemplazar automáticamente
`AGENTS.md` ni `AN-KLA.md`.

GitHub muestra beta.11 como “Latest” porque beta.19 está marcada como
prerelease. El update-check de AN-KLA no depende de ese distintivo: consulta el
índice de releases, incluye prereleases y sí puede descubrir beta.19.
**Limitación conocida**: el soporte de Windows permanece diferido por
decisión del operador (CI remota en rojo; la candidata se declara
procedible para macOS/Linux) — ver la
[ronda REL de beta.18](docs/releases/v0.1.0-beta.18-adversarial.md),
§Límites. El contrato gestionado beta.11 aún menciona el endpoint histórico
`/releases/latest`; es deuda documental versionada, no el comportamiento del
runtime ni autorización para modificar `AGENTS.md` o `AN-KLA.md` a mano.

En varias betas (14–18), GitHub Actions corrió con presupuesto limitado o
sin ejecutar pasos por facturación; el badge rojo no siempre representa
pruebas fallidas. El gate documentado complementario es la CI local: suite
canónica, wheel aislado y upgrades por etiqueta, con ronda adversarial
`proceed`; la evidencia de beta.18 está en su
[ronda REL](docs/releases/v0.1.0-beta.18-adversarial.md). Para
instalar o actualizar usa el comando fijado a beta.19 de la siguiente sección.

## ¿Es AN-KLA para esto? Fronteras declaradas

AN-KLA conserva **memoria contextual para agentes**: hechos versionados,
decisiones, eventos, episodios y estado de continuidad que ayudan a reconstruir
por qué y cómo se trabajó. Puede describir entidades persistentes mediante
`subject_ref` y ofrecer una vista vigente derivada, pero esa vista es
`non-authoritative`: organiza lo registrado, no sustituye la fuente original ni
demuestra que el mundo externo siga igual.

Mantén fuera de AN-KLA el estado canónico que una aplicación necesita para
funcionar: cuentas, permisos, configuración operacional, inventarios completos,
secretos y cualquier dato cuya ausencia impida prestar el servicio. Esos datos
pertenecen a archivos, bases o servicios con su propio contrato de integridad,
confidencialidad, disponibilidad y control de acceso. AN-KLA puede recordar una
observación o decisión sobre ellos; el agente debe revalidarla contra la fuente
canónica antes de actuar.

Usa esta **prueba de amputación**: imagina que `.an-kla/` desaparece. Es
aceptable perder memoria de cómo se construyó, qué se intentó o qué contexto
conviene recuperar. Si el producto deja de funcionar correctamente, el dato que
falta necesita otro hogar. Borrar `.an-kla/` realmente sigue siendo una acción
destructiva: la prueba es una heurística mental, no un procedimiento operativo.

Esta frontera no reduce AN-KLA a una bitácora: admite afirmaciones contextuales
reconstruibles y navegación por subjects, sin convertirlas en un catálogo
autoritativo. La decisión completa está en
[ADR-0032](docs/architecture/0032-derived-contextual-view-v1.md).

## Requisitos

- Python 3.9 o posterior; Python 3.12 es la versión recomendada para desarrollo;
- Git, sólo cuando se instala directamente desde GitHub;
- un entorno virtual por proyecto.

En macOS, la guía [Desarrollo con Python en macOS](docs/development-macos.md)
documenta la separación entre el intérprete de desarrollo (3.12, en `.venv/`)
y el mínimo soportado (3.9, comprobación de compatibilidad), y cómo
comprobar el entorno antes de trabajar.

AN-KLA no requiere servicios externos ni dependencias Python en tiempo de
ejecución.

## Instalación nueva en un proyecto consumidor

Desde la raíz del proyecto consumidor en macOS o Linux:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install \
  "an-kla-memory @ git+https://github.com/kristhianmanue1/an-kla-memory.git@v0.1.0-beta.19"
.venv/bin/python -m an_kla --version
.venv/bin/python -m an_kla --project-root . init
.venv/bin/python -m an_kla --project-root . context plan --operation install
.venv/bin/python -m an_kla --project-root . context install
.venv/bin/python -m an_kla --project-root . context status
.venv/bin/python -m an_kla --project-root . verify
git diff -- AGENTS.md AN-KLA.md
```

En Windows PowerShell, crea el entorno con `py -3.12 -m venv .venv` y sustituye
`.venv/bin/python` por `.venv\\Scripts\\python.exe`.

Los pasos son deliberadamente distintos:

1. `pip install` instala el programa;
2. `init` crea la memoria local `.an-kla/memory/`; su resultado incluye
   `context_diagnostics` señalizando si el bloque gestionado quedó pendiente
   (`installed: false`) — el paso siguiente no es opcional;
3. `context plan` muestra la mutación prevista sin aplicarla;
4. `context install` reconstruye, revalida y aplica el plan bajo lock;
5. `context status` y `verify` comprueban la integración y la memoria.

Revisa y versiona `AGENTS.md` y `AN-KLA.md`. `.an-kla/` es estado local y no
debe incorporarse al repositorio comercial salvo una decisión explícita del
proyecto.

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
[secuencia beta.8 completa](docs/beta11-user-guide.md#migración-desde-beta8).

Para un proyecto sin store legacy, instala la nueva etiqueta exacta y actualiza
por separado el contrato de contexto:

```bash
.venv/bin/python -m pip install --upgrade \
  "an-kla-memory @ git+https://github.com/kristhianmanue1/an-kla-memory.git@v0.1.0-beta.19"
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
procedimiento manual de la [guía de integración](docs/context-package.md).
Si el proyecto ya tiene un store beta.8, beta.11 exigirá además adoptar su
identidad de forma explícita antes de mutarlo. El procedimiento completo y
reversible está en la [guía de instalación y migración beta.11](docs/beta11-user-guide.md).

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
[guía de actualización para agentes](docs/upgrade-agent-flow.md).

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
consulta [ADR-0006](docs/architecture/0006-context-assembly-v1.md). La escritura
nueva debe usar `plan-write` y `commit-write-plan`, descritos en la
[guía de escritura gobernada](docs/write-policy-cli.md). El comando público
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
Consulta la [guía del perfil sellado](docs/sealed-export-guide.md).

Checkpoint, identidad, refute, export/restore y compactación tienen contratos
plan→commit propios. Desde ADR-0038, el `source_state` del working state
admite el perfil `git/v1` con valores `caller_asserted`: el caller observa
Git (HEAD completo, branch, digest del árbol sucio) y liga el checkpoint al
commit que describe; el CLI nunca ejecuta Git ni acuña autoridad. Consulta
la [guía beta.11](docs/beta11-user-guide.md) antes
de cualquier operación mutativa o destructiva.

## Desarrollo del motor

```bash
git clone https://github.com/kristhianmanue1/an-kla-memory.git
cd an-kla-memory
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m unittest discover -s tests -v
```

Consulta [AN-KLA.md](AN-KLA.md), los [fundamentos matemáticos](docs/mathematical-foundations.md)
y las decisiones de arquitectura en `docs/architecture/`.

## Límites de la beta

- admite una sola memoria activa;
- el lock de escritura es local y no coordina varias máquinas;
- no prueba identidad, autoría ni verdad;
- el hook de verificación de versiones consulta (sólo lectura) la API pública
  de GitHub Releases; puede desactivarse con `AN_KLA_NO_UPDATE_CHECK=1` o
  `--no-update-check` (ver [ADR-0012](docs/architecture/0012-update-check-v1.md));
  no envía telemetría más allá del User-Agent HTTP;
- administra sólo el `AGENTS.md` raíz y no adapta archivos de proveedores;
- la compactación es explícita, gobernada y destructiva: exige un export
  verificable, autoridad y un plan exacto; no existe GC automático;
- el perfil sellado (`sealed-export/v1`) da confidencialidad del bundle
  en reposo, no del store vivo ni del transporte, y no es atestación de
  origen: la defensa anti re-sellado es la comparación manual del
  `bundle_id` (ADR-0042 §Límites);
- el CLI independiente no puede autodeclarar autoridad privilegiada para
  `refute`: esa capacidad debe ser resuelta por un host confiable.

## Documentación

- [Contrato del agente](AN-KLA.md) — desarrollo del bloque administrado.
- [Documentación evergreen](docs/README.md) — índice de la carpeta `docs/`.
- [Guía del perfil sellado](docs/sealed-export-guide.md) — respaldos
  cifrados en reposo (`sealed-export/v1`, ADR-0042): uso, perfiles,
  warnings y errores canónicos.
- [Notas de beta.19](docs/releases/v0.1.0-beta.19.md) — cierre de deuda
  documental de la REL beta.18 y partición del ADR-0042 (#95).
- [Notas de beta.18](docs/releases/v0.1.0-beta.18.md) — perfil sellado
  `sealed-export/v1` (respaldos cifrados en reposo).
- [Notas de beta.17](docs/releases/v0.1.0-beta.17.md) — adopción de
  baseline e inventario físico.
- [Notas de beta.16](docs/releases/v0.1.0-beta.16.md) — denominadores de
  frescura, `git/v1`, `integration status`, señal de contexto en `init`.
- [Notas de beta.15](docs/releases/v0.1.0-beta.15.md) — diagnóstico de
  arranque, resguardo de errores del CLI y sincronía ADR-0036.
- [Notas de beta.14](docs/releases/v0.1.0-beta.14.md) — primer write operable y
  cambios de adopción posteriores a beta.13.
- [Handoff posterior a beta.13](docs/planning/handoff-post-beta13-g-fresh-2026-08-12.md)
  — estado verificable y entrada recomendada a G-FRESH.
- [Guía beta.11](docs/beta11-user-guide.md) — instalación, migración y nuevos flujos.
- [ADRs](docs/architecture/) — decisiones arquitectónicas numeradas.
- [Notas de release](docs/releases/) — changelog por etiqueta.
- [Changelog](CHANGELOG.md) — índice de versiones publicadas.
- [Contribuir](CONTRIBUTING.md) — flujo de PRs, tests, community files.
- [Seguridad](SECURITY.md) — política de reporte y modelo de confianza.
- [Código de conducta](CODE_OF_CONDUCT.md) — expectativas de participación.

## Licencia

Este proyecto se distribuye bajo [Apache License 2.0](LICENSE).
