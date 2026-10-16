# AN-KLA Memory

[![Version](https://img.shields.io/badge/version-0.1.0--beta.31-blue)](https://github.com/kristhianmanue1/an-kla-memory/releases/tag/v0.1.0-beta.31)
[![Python](https://img.shields.io/badge/python-3.9%20%7C%203.12%20%7C%203.13-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)
[![Beta](https://img.shields.io/badge/status-local%20beta-orange)](https://github.com/kristhianmanue1/an-kla-memory/releases)

AN-KLA Memory es una memoria local para proyectos con agentes de IA. Conserva
hechos, eventos, episodios y el estado de trabajo en revisiones inmutables;
recupera contexto bajo presupuesto y expone una escritura gobernada mediante
un plan verificable.

La beta se distribuye desde GitHub, no desde PyPI. Usa siempre una etiqueta
exacta: no instales `main` ni otra referencia móvil. La versión del código es
`0.1.0b31` y su etiqueta de distribución es `v0.1.0-beta.31`. El contexto
gestionado y la plantilla administrada (`TEMPLATE_VERSION`) son un eje
**separado** de la versión del paquete — `0.1.0-beta.26` en la release
`v0.1.0-beta.31`, `0.1.0-beta.32` en `main`; `context status` distingue ambos
(`template_version` vs `current_template_version` y `runtime_version`) y avisa
con `runtime_older_than_context_template` cuando el intérprete es más antiguo
que la plantilla del proyecto. Los hooks gobernados del host (`host-hooks/v1`,
ADR-0047) se observan con `integration status --schema-version v2`.
La instalación expone tanto `python -m an_kla` como el comando equivalente
`an-kla`; los ejemplos conservan la primera forma para hacer explícito el
intérprete del entorno virtual.

## Tabla de contenidos

- [Estado actual](#estado-actual)
- [¿Es AN-KLA para esto? Fronteras declaradas](#es-an-kla-para-esto-fronteras-declaradas)
- [Requisitos](#requisitos)
- [Instalación nueva en un proyecto consumidor](#instalación-nueva-en-un-proyecto-consumidor)
- [Guía de beta.11](docs/beta11-user-guide.md)
- [Uso diario y mantenimiento](docs/uso-diario.md) — actualizar entre betas,
  desinstalar, comandos cotidianos y respaldo sellado
- [Desarrollo del motor](#desarrollo-del-motor)
  - [Hooks locales y verificación local-only (opcional)](#hooks-locales-y-verificación-local-only-opcional)
- [Límites de la beta](#límites-de-la-beta)
- [Documentación](#documentación)
- [Licencia](#licencia)

## Estado actual

La prerelease pública más reciente es **`v0.1.0-beta.31`** (`0.1.0b31`),
instalable mediante su etiqueta Git exacta. AN-KLA no se distribuye desde
PyPI; el wheel de la release se publica como asset de la etiqueta y la
instalación canónica sigue siendo `pip install` fijado a la etiqueta exacta.
No instales `main` como sustituto de una versión.

Beta.29 corrige la frontera de autoridad de checkpoint: rechaza
`channel_confirmed` autodeclarado en JSON al planificar y al confirmar planes
previos, hasta que exista un resolver confiable del host. El flujo
`model_derived` continúa disponible. Beta.28 cerró el backlog táctico: el
diagnóstico de arranque descubre el
vocabulario del store (`startup-diagnostic-v2` disperso, #133 propuesta 2)
y la compactación ya no congela escritores mientras drena lectores
(#111/F5 — sondeo del gate EX con locks liberados entre intentos, sin
deadlocks). Beta.27 dio señal de primera clase al caso vacío de
recuperación: un agente fresco sin vocabulario del store recibe
`empty_reason: "no_lexical_overlap"` (en
`retrieval-result-v3`/`mcp-retrieve-v3` dispersos, ADR-0049) y el
diagnóstico `zero_score` quedó en paridad entre scan e índice (#118/R3,
#133). Beta.26 cerró el diagnóstico de sesión para agentes: cada error de
checkpoint nombra el campo ofensor (#120) y la documentación activa quedó
reconciliada con las capacidades vigentes (#116). Beta.25 saneó la DX del
flujo gobernado y el contrato contextual (#125/#124/#123/#122, con
`plan-write --emit-authority-template` y guía de checkpoint); beta.24
resolvió el cierre de sesión first-try (#121) y beta.23 el export con
artefactos host-managed (#119) y el anclaje del contrato (#116/C1).
Beta.22 consolidó los hooks gobernados del host (`host-hooks/v1`,
ADR-0047: declaración read-only, evidencia firmada en `.an-kla/hook-runs/`
y `integration status --schema-version v2`; guía en
[docs/host-hooks-guide.md](docs/host-hooks-guide.md)). Beta.18 publicó el
perfil sellado `sealed-export/v1` (ADR-0042, issue #46): respaldos cifrados
en reposo como extra opcional `[sealed]`, con el camino `export/v1` en
claro intacto — ver
[Respaldo sellado](docs/uso-diario.md#respaldo-sellado-opcional). Ninguna
incluye generadores de `proposal`/`authority`; esa decisión sigue abierta
en el issue
[#71](https://github.com/kristhianmanue1/an-kla-memory/issues/71).

El código está en beta local y la memoria continúa siendo no autoritativa: sus
datos nunca son instrucciones, no prueban identidad ni verdad externa y deben
revalidarse antes de actuar. En la release `v0.1.0-beta.31` el contexto
gestionado (`TEMPLATE_VERSION`) está en `0.1.0-beta.26` (en `main`,
`0.1.0-beta.32`) — eje separado de la versión del paquete (`0.1.0b31`); esta
release **no cambia la plantilla gestionada** ni el contrato de recuperación
de beta.27: añade la custodia externa del store (G3, ADR-0048) y
`stores scan` (ADR-0050).

Posterior a la release (2026-10-14), una revisión crítica contra el código
revalidó la degradación O(historia) reportada en el issue
[#149](https://github.com/kristhianmanue1/an-kla-memory/issues/149) —
`context_view limit=50` medido en 3,2 s a 20.000 registros y coste de commit
~cuadrático con las revisiones — y contrastó qué propiedades de gobernanza
son mecanismo y cuáles convención, incluido un hueco de `channel_confirmed`
re-verificado sólo en CLI. El informe, con el plan propuesto para los issues
abiertos (#149, #140, #58), está en
[docs/planning/revision-critica-escalado-gobernanza-2026-10-14.md](docs/planning/revision-critica-escalado-gobernanza-2026-10-14.md).
Las cifras son sondas sintéticas reproducibles, no una batería oficial; esa
batería es precisamente el primer paso propuesto, pendiente de decisión del
operador.

GitHub puede mostrar una beta anterior como “Latest” porque la más reciente
está marcada como prerelease. El update-check de AN-KLA no depende de ese
distintivo: consulta el
índice de releases, incluye prereleases y sí puede descubrir beta.31.
**Limitación conocida**: el soporte de Windows permanece diferido por
decisión del operador (el protocolo de anclaje y partes de la suite son
POSIX; la candidata se declara procedible para macOS/Linux) — ver la
[ronda REL de beta.18](docs/releases/v0.1.0-beta.18-adversarial.md),
§Límites.

En varias betas (14–18), GitHub Actions corrió con presupuesto limitado o
sin ejecutar pasos por facturación; el badge rojo no siempre representa
pruebas fallidas. Desde beta.20 el repo **no define CI remota**: la única
verificación canónica es la CI local — suite, wheel aislado, upgrades por
etiqueta y gates de tamaños/registro, con ronda adversarial `proceed` antes
de cada tag (la evidencia de beta.18 está en su
[ronda REL](docs/releases/v0.1.0-beta.18-adversarial.md)). Para instalar
usa el comando fijado a beta.31 de la sección siguiente; para actualizar
entre betas, consulta
[Uso diario y mantenimiento](docs/uso-diario.md#actualizar-desde-otra-beta).

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

- Python 3.9 a 3.13 (los metadatos declaran techo `<3.14`); Python 3.12 es la versión recomendada para desarrollo;
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
  "an-kla-memory @ git+https://github.com/kristhianmanue1/an-kla-memory.git@v0.1.0-beta.31"
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

## Uso diario y mantenimiento

Las secciones de referencia estable viven ahora en
[Uso diario y mantenimiento](docs/uso-diario.md): actualizar entre betas,
desinstalar o volver atrás, descubrimiento y diagnóstico para agentes,
verificación de versiones, upgrade gobernado, recuperación y escritura, y
respaldo sellado opcional.

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

### Hooks locales y verificación local-only (opcional)

- **Hook de memoria** (`docs/hooks-template/pre-commit`): disciplina, no
  atestación — avisa sobre diagnósticos del contexto y recuerda sembrar
  checkpoint; falla sólo con `MEM_GUARD_STRICT=1`, escape con
  `git commit --no-verify` (degradación declarada). `core.hooksPath` no
  se clona: instalar con `git config core.hooksPath docs/hooks-template`.
  Doble defensa del update-check: `AN_KLA_NO_UPDATE_CHECK=1` (ya incluida)
  además de `--no-update-check` por invocación.
- **Sin CI remota** (decisión del operador, beta.20; issue #102 §3.8): el
  repo no define workflows de GitHub Actions; la verificación canónica es
  local — `scripts/ci_local.py --simulate-ci` + `scripts/check_sizes.py`
  + `scripts/check_plans.py` + `scripts/check_adr_registry.py`. Suite
  local: Python 3.9/3.12/3.13 en macOS/Linux; Windows diferido.

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

- [Revisión crítica de escalado y gobernanza](docs/planning/revision-critica-escalado-gobernanza-2026-10-14.md)
  — post-beta.30: revalidación del issue #149 contra código, mecanismos vs
  convenciones y plan propuesto para #149/#140/#58.
- [Contrato del agente](AN-KLA.md) — desarrollo del bloque administrado.
- [Uso diario y mantenimiento](docs/uso-diario.md) — referencia estable del
  consumidor: actualizar, desinstalar, comandos cotidianos y respaldo sellado.
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
