# Fixture `store-v0.1.0-beta.35`

Store pequeño creado con el código de `main` en la beta.35 (`VERSION =
"0.1.0b35"`), antes de cualquier cambio de la fase A de E1.a (ADR-0063,
criterio 5). Sirve para comprobar que lo que se añade es aditivo: las salidas
de lectura sobre este store no cambian.

## Contenido

- `store.tar`: el directorio `.an-kla/` del proyecto, empaquetado de forma
  determinista (sin mtime, uid ni usuario). Va en tar porque `.gitignore`
  excluye `.an-kla/`, Git no guarda directorios vacíos y el store necesita
  modos 0600 en sus claves. Contiene 3 facts (uno sustituido), 1 episode y
  los events de cada commit. No tiene `memory/inbox/`.
- `goldens.json`: `store_tar_sha256` y 24 goldens (sha256 de la salida
  normalizada de `status`, `verify`, `inventory`, `retrieve` en tres formas,
  `resume`, `assemble-context`, `plan-write` (plantilla de authority);
  manifest y digests de entradas de `export create`; `policy_fingerprint`; y
  las respuestas MCP de `initialize`, `tools/list` y cada herramienta).
- `generar_store.py` y `empaquetar.py`: cómo se construyó el store.

## Material que lleva el tar, y por qué es inocuo

- `.an-kla/attest.key` es una clave de atestación **sintética**, generada por
  `init` para este store desechable. No tiene autoridad sobre nada: no firma
  ni autoriza ningún store real, y el store del fixture sólo se abre en copias
  temporales. Un escáner de secretos puede señalarla; es un falso positivo
  conocido.
- La raíz que el store registra como suya (`canonical_project_root_at_init`)
  es la ruta inerte `/private/var/tmp/an-kla-fixture/store-v0.1.0-beta.35/project`
  (`/var/tmp/...` resuelto en macOS), no un directorio personal. Esa ruta no
  existe cuando se corren las pruebas.

## Cómo se generó

Con el código de `main` en el commit `5c5750a`, en un worktree temporal de
`main` (nunca con el código de la rama que se prueba), intérprete 3.12. Desde la
raíz de ese worktree, con `FIXTURE=tests/fixtures/store-v0.1.0-beta.35` copiado
dentro y la raíz registrada fija:

```
ROOT=/var/tmp/an-kla-fixture/store-v0.1.0-beta.35/project
mkdir -p "$ROOT"
python $FIXTURE/generar_store.py "$ROOT"
python $FIXTURE/empaquetar.py "$ROOT" $FIXTURE/store.tar
python tests/legacy_store_goldens.py --write
```

`generar_store.py` usa la CLI (`init`, `plan-write` y el commit del plan) con
`--transaction-id` fijos y `verified_at` fijos. El `project_uuid` y las claves
de atestación son aleatorios por ejecución: por eso el store se versiona y no
se regenera en cada prueba. Los goldens se calculan también con el código de
`main` (el worktree temporal), no con el de la rama.

## Determinismo

- El store se extrae de `store.tar` a un directorio temporal nuevo en cada
  corrida; el digest del tar se comprueba contra `goldens.json` **antes** de
  abrirlo y se abre el mismo contenido que se hasheó.
- La ruta de trabajo (y su forma resuelta, p. ej. `/private/var/...` en macOS)
  se sustituye por `<PROJECT_ROOT>` antes de hashear, así que el directorio
  temporal no influye.
- `retrieve` con frescura usa `--now 2026-06-01T00:00:00Z`; ninguna otra salida
  depende del reloj.
- El export se hace a un directorio temporal; sólo se hashean el manifest y los
  digests de entradas, nunca la ruta del bundle.
- Las respuestas MCP se piden en una sola sesión stdio con `protocolVersion`
  fijo; se hashea cada respuesta cruda.

## Regeneración de la beta.36

`store.tar` no cambia (su digest en `goldens.json` es el mismo). Sólo cambian
`cli.status` y `mcp.initialize`, que muestran la versión del paquete; se
recalcularon con `python tests/legacy_store_goldens.py --write` sobre el
candidato a release. Antes se comprobó que su material crudo con b36 es el de
b35 con la versión sustituida, y que con `VERSION = "0.1.0b35"` el mismo árbol
reproduce los 24 goldens anteriores.

## Regeneración de la beta.37

`store.tar` no cambia. Sólo cambian `cli.status` y `mcp.initialize`, que
muestran la versión del paquete; se recalcularon con
`python tests/legacy_store_goldens.py --write` sobre el candidato a release.
Antes se comprobó que con `VERSION = "0.1.0b36"` el mismo árbol reproduce los
24 goldens anteriores (`tests.test_legacy_store_byte_identity`, 7 pruebas OK).

## Regeneración de la beta.38

`store.tar` no cambia. Sólo cambian `cli.status` y `mcp.initialize`, que
muestran la versión del paquete; se recalcularon con
`python tests/legacy_store_goldens.py --write` sobre el candidato a release.
Antes se comprobó que con `VERSION = "0.1.0b37"` el mismo árbol reproduce los
24 goldens anteriores (`tests.test_legacy_store_byte_identity`, 7 pruebas OK) y
que con b38 sin regenerar sólo fallan esos dos.

## Regeneración de la beta.39

Igual que la de la beta.38: `store.tar` no cambia y sólo cambian `cli.status` y
`mcp.initialize` (versión del paquete), recalculados con
`python tests/legacy_store_goldens.py --write` sobre el candidato. Antes se
comprobó que con `VERSION = "0.1.0b38"` el mismo árbol reproduce los 24 goldens
anteriores (7 pruebas OK) y que con b39 sin regenerar sólo fallan esos dos.

## Lo que los goldens no cubren

Al extraerse en otro directorio, el store se abre siempre **reubicado**: los
goldens fijan `status.root_relocated: true` y
`doctor.project_root_relocated_since_init: true`. El ADR pide el fixture
«abierto desde una ruta absoluta fija»; eso no es posible sin escribir en una
ruta de la máquina, así que la rama contraria (store abierto en su propia raíz,
`root_relocated: false`) se cubre aparte, sin goldens, en
`test_store_opened_at_its_registered_root_is_not_relocated`. El resto de
superficies del criterio 5 no cambia con ese booleano.

Un cambio de comportamiento legítimo de lectura exige regenerar los goldens en
su propio commit y decirlo en el PR; en la fase A no se espera ninguno.
