# AN-KLA Memory

AN-KLA Memory es una memoria local para proyectos con agentes de IA. Conserva
hechos, eventos, episodios y el estado de trabajo en revisiones inmutables;
recupera contexto bajo presupuesto y expone una escritura gobernada mediante
un plan verificable.

La beta se distribuye desde GitHub, no desde PyPI. Usa siempre una etiqueta
exacta: no instales `main` ni otra referencia móvil. La versión del código es
`0.1.0b3` y su etiqueta de distribución es `v0.1.0-beta.3`.

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
  "an-kla-memory @ git+https://github.com/kristhianmanue1/an-kla-memory.git@v0.1.0-beta.3"
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

Después instala la nueva etiqueta exacta y actualiza por separado el contrato
de contexto:

```bash
.venv/bin/python -m pip install --upgrade \
  "an-kla-memory @ git+https://github.com/kristhianmanue1/an-kla-memory.git@v0.1.0-beta.3"
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
```

`capabilities` emite JSON canónico y declara, entre otros límites, que la
recuperación v1 busca únicamente `facts`, que MCP es de sólo lectura y que los
presupuestos implementados miden bytes UTF-8, no tokens exactos. Los cinco
schemas normativos se incluyen dentro del paquete y `schema show` entrega sus
bytes sin depender del checkout ni de la red.

### Actualización gobernada del proyecto

Después de instalar una etiqueta exacta con el gestor de paquetes, un agente
puede inspeccionar la actualización de la integración sin mutar el proyecto:

```bash
.venv/bin/python -m an_kla --project-root . upgrade inspect \
  --target v0.1.0-beta.3 > RUTA_EFIMERA_NUEVA
```

El agente debe conservar por separado el `plan_fingerprint` devuelto, revisar
el plan y aplicar exactamente esos bytes:

```bash
.venv/bin/python -m an_kla --project-root . upgrade apply \
  <plan_fingerprint> --plan RUTA_EFIMERA_NUEVA
.venv/bin/python -m an_kla --project-root . upgrade verify \
  --target v0.1.0-beta.3
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
.venv/bin/python -m an_kla --project-root . assemble-context \
  --query "estado del proyecto" \
  --new-information "solicitud actual" \
  --budget 2400
```

La salida completa de `context-assembly/v1` queda acotada en bytes UTF-8;
consulta [ADR-0006](docs/architecture/0006-context-assembly-v1.md). La escritura
nueva debe usar `plan-write` y `commit-write-plan`, descritos en la
[guía de escritura gobernada](docs/write-policy-cli.md). El comando histórico
`write` se conserva sólo por compatibilidad y no ofrece esa garantía.

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
- no publica telemetría;
- administra sólo el `AGENTS.md` raíz y no adapta archivos de proveedores;
- conserva objetos conflictivos en cuarentena, pero no ejecuta GC ni
  compactación.

## Licencia

Este proyecto se distribuye bajo [Apache License 2.0](LICENSE).
