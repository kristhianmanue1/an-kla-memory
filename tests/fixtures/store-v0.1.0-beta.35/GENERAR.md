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
  los events de cada commit; revisión
  `sha256:b9a688747975cfa4453dea8d32fd112bf6c3d481e8a8311502086ec84f3b9b9c`.
  No tiene `memory/inbox/`.
- `goldens.json`: `store_tar_sha256` y 24 goldens (sha256 de la salida
  normalizada de `status`, `verify`, `inventory`, `retrieve` en tres formas,
  `resume`, `assemble-context`, `plan-write`; manifest y digests de entradas
  de `export create`; `policy_fingerprint`; y las respuestas MCP de
  `initialize`, `tools/list` y cada herramienta).
- `generar_store.py` y `empaquetar.py`: cómo se construyó el store.

## Cómo se generó

Con el árbol en el commit de `main` `5c5750a` (sin cambios), intérprete 3.12:

```
mkdir proyecto
python tests/fixtures/store-v0.1.0-beta.35/generar_store.py proyecto
python tests/fixtures/store-v0.1.0-beta.35/empaquetar.py proyecto tests/fixtures/store-v0.1.0-beta.35/store.tar
python tests/legacy_store_goldens.py --write
```

`generar_store.py` usa la CLI (`init`, `plan-write` y el commit del plan) con
`--transaction-id` fijos y `verified_at` fijos. El `project_uuid` y las claves
de atestación son aleatorios por ejecución: por eso el store se versiona y no
se regenera en cada prueba.

## Determinismo

- El store se extrae de `store.tar` a un directorio temporal nuevo en cada
  corrida; el digest del tar se comprueba antes de usarlo.
- La ruta de trabajo (y su forma resuelta, p. ej. `/private/var/...` en macOS)
  se sustituye por `<PROJECT_ROOT>` antes de hashear, así que el directorio
  temporal no influye.
- `retrieve` con frescura usa `--now 2026-06-01T00:00:00Z`; ninguna otra salida
  depende del reloj.
- El export se hace a un directorio temporal; sólo se hashean el manifest y los
  digests de entradas, nunca la ruta del bundle.
- Las respuestas MCP se piden en una sola sesión stdio con `protocolVersion`
  fijo; se hashea cada respuesta cruda.
- Verificado: dos regeneraciones en directorios distintos dan `goldens.json`
  idéntico byte a byte.

Un cambio de comportamiento legítimo de lectura exige regenerar los goldens en
su propio commit y decirlo en el PR; en la fase A no se espera ninguno.
