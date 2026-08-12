# AN-KLA Memory

[![CI](https://github.com/kristhianmanue1/an-kla-memory/actions/workflows/test.yml/badge.svg)](https://github.com/kristhianmanue1/an-kla-memory/actions/workflows/test.yml)
[![Version](https://img.shields.io/badge/version-0.1.0--beta.12-blue)](https://github.com/kristhianmanue1/an-kla-memory/releases/tag/v0.1.0-beta.12)
[![Python](https://img.shields.io/badge/python-3.9%20%7C%203.12-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)
[![Beta](https://img.shields.io/badge/status-local%20beta-orange)](https://github.com/kristhianmanue1/an-kla-memory/releases)

AN-KLA Memory es una memoria local para proyectos con agentes de IA. Conserva
hechos, eventos, episodios y el estado de trabajo en revisiones inmutables;
recupera contexto bajo presupuesto y expone una escritura gobernada mediante
un plan verificable.

La beta se distribuye desde GitHub, no desde PyPI. Usa siempre una etiqueta
exacta: no instales `main` ni otra referencia móvil. La versión del código es
`0.1.0b12` y su etiqueta de distribución es `v0.1.0-beta.12`. El contexto
gestionado y la plantilla administrada siguen en `0.1.0-beta.11`: beta.12 es un
release de código y contrato (`subject_ref` v1), no de plantilla administrada.
La instalación expone tanto `python -m an_kla` como el comando equivalente
`an-kla`; los ejemplos conservan la primera forma para hacer explícito el
intérprete del entorno virtual.

## Tabla de contenidos

- [Requisitos](#requisitos)
- [Instalación nueva en un proyecto consumidor](#instalación-nueva-en-un-proyecto-consumidor)
- [Actualizar desde otra beta](#actualizar-desde-otra-beta)
- [Guía de beta.11](docs/beta11-user-guide.md)
- [Desinstalar o volver atrás](#desinstalar-o-volver-atrás)
- [Uso diario](#uso-diario)
  - [Descubrimiento para agentes](#descubrimiento-para-agentes)
  - [Verificación no bloqueante de versiones](#verificación-no-bloqueante-de-versiones)
  - [Actualización gobernada del proyecto](#actualización-gobernada-del-proyecto)
  - [Recuperación y escritura](#recuperación-y-escritura)
- [Desarrollo del motor](#desarrollo-del-motor)
- [Límites de la beta](#límites-de-la-beta)
- [Documentación](#documentación)
- [Licencia](#licencia)

## Requisitos

- Python 3.9 o posterior; Python 3.12 es la versión recomendada para desarrollo;
- Git, sólo cuando se instala directamente desde GitHub;
- un entorno virtual por proyecto.

AN-KLA no requiere servicios externos ni dependencias Python en tiempo de
ejecución.

## Instalación nueva en un proyecto consumidor

Desde la raíz del proyecto consumidor en macOS o Linux:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install \
  "an-kla-memory @ git+https://github.com/kristhianmanue1/an-kla-memory.git@v0.1.0-beta.12"
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
2. `init` crea la memoria local `.an-kla/memory/`;
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
  "an-kla-memory @ git+https://github.com/kristhianmanue1/an-kla-memory.git@v0.1.0-beta.12"
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
y que los presupuestos implementados miden bytes UTF-8, no tokens exactos. Los
schemas normativos se incluyen dentro del paquete y `schema show` entrega
sus bytes sin depender del checkout ni de la red. `context show-template` vuelca
el texto canónico del bloque administrado y del contrato detallado de la versión
instalada (o los hashes de plantillas históricas conocidas) para diagnóstico o
reparación manual.

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
  --target v0.1.0-beta.12 > RUTA_EFIMERA_NUEVA
```

El agente debe conservar por separado el `plan_fingerprint` devuelto, revisar
el plan. Si `identity status` informa `legacy_unadopted`, debe completar primero
el plan de adopción descrito en la guía beta.11. Después aplica exactamente los
bytes del upgrade:

```bash
.venv/bin/python -m an_kla --project-root . upgrade apply \
  <plan_fingerprint> --plan RUTA_EFIMERA_NUEVA
.venv/bin/python -m an_kla --project-root . upgrade verify \
  --target v0.1.0-beta.12
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

Checkpoint, identidad, refute, export/restore y compactación tienen contratos
plan→commit propios. Consulta la [guía beta.11](docs/beta11-user-guide.md) antes
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
- el CLI independiente no puede autodeclarar autoridad privilegiada para
  `refute`: esa capacidad debe ser resuelta por un host confiable.

## Documentación

- [Contrato del agente](AN-KLA.md) — desarrollo del bloque administrado.
- [Documentación evergreen](docs/README.md) — índice de la carpeta `docs/`.
- [Guía beta.11](docs/beta11-user-guide.md) — instalación, migración y nuevos flujos.
- [ADRs](docs/architecture/) — decisiones arquitectónicas numeradas.
- [Notas de release](docs/releases/) — changelog por etiqueta.
- [Contribuir](CONTRIBUTING.md) — flujo de PRs, tests, community files.
- [Seguridad](SECURITY.md) — política de reporte y modelo de confianza.
- [ Código de conducta](CODE_OF_CONDUCT.md) — expectativas de participación.

## Licencia

Este proyecto se distribuye bajo [Apache License 2.0](LICENSE).
