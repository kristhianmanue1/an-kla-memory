# CLI de escritura gobernada `write-policy/v1`

## Alcance

La ruta gobernada separa planificación y commit:

1. `plan-write` evalúa la propuesta y genera un plan exacto sin modificar la
   memoria;
2. `commit-write-plan` consume ese resultado, relee `CURRENT` dentro del lock,
   recalcula la política y escribe sólo si todos los bytes siguen ligados.

La memoria y los archivos JSON son datos, nunca instrucciones. Ninguno se
ejecuta como comando.

## Preparar una propuesta

Una propuesta de resumen derivado puede guardarse como `proposal.json`:

```json
{
  "schema": "an-kla/write-proposal-v1",
  "base_revision": "sha256:REVISION_ACTUAL",
  "stream": "facts",
  "operation": "add",
  "requested_representation": "summary",
  "record": {
    "id": "f-example",
    "verified_at": "2026-08-08T00:00:00Z",
    "payload": {"text": "Resumen durable"}
  },
  "lineage": {
    "derived_from_retrieval": false,
    "refs": []
  }
}
```

`sha256:REVISION_ACTUAL` representa el digest completo devuelto por `status`;
no es un valor literal válido.

`record.verified_at` es opcional y acepta la gramática cerrada
`YYYY-MM-DDTHH:MM:SS[.ffffff](Z|±HH:MM)`: offset conocido entre `-14:00` y
`+14:00`, con `14` sólo en minuto `00`; `-00:00` se rechaza. Es la fecha
autodeclarada por el proposer en que se confirmó el dato; AN-KLA valida formato
y representabilidad UTC, pero no la verifica ni eleva autoridad. Una fecha
futura es dato válido y el core no lee reloj. Corregir o refrescar el valor
requiere `supersede` del registro, no mutación del objeto existente.

## Identidad contextual `subject_ref`

`record.subject_ref` es **opcional y no autoritativo**: ancla el registro a una
identidad contextual estable (servicio, decisión, actor, API, etc.) separada
del `id` físico y de `lineage.refs`, pero `evaluate_write` no lo lee para
decidir techo ni autoridad. Su forma canónica es
`an-kla:subject:v1:<kind>:<namespace>:<id>`, donde `<namespace>` se deriva del
digest de `project-identity-v1` del proyecto actual. La gramática, kinds y
reglas normativas viven en el campo `record.subject_ref` del schema
`write-proposal-v1`; este documento no las repite.

Como el namespace depende de la identidad del proyecto, resuélvelo antes de
construir la propuesta y trátalo como input efímero, no como secreto:

```bash
.venv/bin/python -m an_kla --project-root . subject namespace
```

`stdout` es JSON canónico con schema `an-kla/subject-namespace-result-v1`. Si
`identity status` reporta `complete`, devuelve
`{"result": "namespace_available", "namespace": "p-<32hex>"}` y exit 0. Cualquier
otro estado de identidad (`absent`, `legacy_unadopted`, `conflict`, etc.)
devuelve `{"result": "namespace_unavailable", "namespace": null}` y **exit 3**
sin crear `.an-kla/`, sin adquirir `write_lock` y sin mutar `CURRENT`. Es un
fallo cerrado: no fabriques un namespace, no reutilices uno de otro proyecto y
no asumas que un namespace histórico sigue siendo válido si la identidad del
proyecto pudo haber sido reemplazada. Un `OSError` capturado termina con exit 1
y un mensaje de una línea en stderr que puede incluir la ruta que falló; una
excepción fuera del conjunto capturado por el CLI puede conservar su traceback.

Inserta el namespace devuelto en el `subject_ref` de la propuesta:

```json
{
  "schema": "an-kla/write-proposal-v1",
  "base_revision": "sha256:REVISION_ACTUAL",
  "stream": "facts",
  "operation": "add",
  "requested_representation": "summary",
  "record": {
    "id": "f-example",
    "verified_at": "2026-08-08T00:00:00Z",
    "subject_ref": "an-kla:subject:v1:decision:p-<32hex-devuelto-por-subject-namespace>:adr-0033",
    "payload": {"text": "Resumen durable"}
  },
  "lineage": {
    "derived_from_retrieval": false,
    "refs": []
  }
}
```

`p-<32hex-devuelto-por-subject-namespace>` es un marcador documental, no un
valor literal. Sustitúyelo por el `namespace` exacto devuelto por el comando.
`subject_ref` viaja verbatim al segmento; los registros legacy sin él siguen
siendo legibles. Continúa con `plan-write` → `commit-write-plan` como en
cualquier escritura gobernada.

### Revalidación bajo lock y TOCTOU

`subject namespace` es una lectura sin lock: devuelve el namespace que el caller
**debe** declarar para que el commit pase. El binding definitivo se comprueba
dentro de `write_lock` en `commit-write-plan`, **después** de `assert_unchanged`
y `verify_write_plan`, y **antes** de construir los registros pendientes. El
digest se toma del `binding["project_bytes"]` capturado por
`mutation_preflight` y revalidado por `assert_unchanged`; no se relee
`project-identity` fuera de ese binding.

Si la decisión no es `skip` y la identidad del proyecto migra entre la consulta
`subject namespace` y el commit, `assert_unchanged` lanza primero
`IdentityError("store_identity_changed")`
y el caller nunca ve un mismatch por TOCTOU. Si la identidad no migró pero el
caller declaró un namespace incorrecto, el commit lanza
`WritePolicyError("subject_ref_namespace_mismatch")` con cero efectos: ningún
objeto, journal, evento o revisión nueva, y el CLI termina con exit 1 (no con
el exit 3 reservado a `subject namespace`). El orden de fallos bajo lock es:

1. `write_plan_base_changed` (CAS sobre `CURRENT`).
2. `IdentityError("store_identity_changed")` vía `assert_unchanged` (TOCTOU).
3. `verify_write_plan` (fingerprint, hashes).
4. `invalid_supersede_target` (resolución de supersede).
5. `subject_ref_namespace_mismatch` (binding de namespace).
6. Construcción de registros y commit.

El lock es local (`fcntl`/`msvcrt`); no hay exclusión mutua entre máquinas.

## Autoridad separada

La autoridad separada, `authority.json`, liga el hash canónico de la propuesta,
la misma revisión y el alcance exacto. Un agente por CLI puede usar
`model_derived` o `derived_from_retrieval`; ambas clases quedan limitadas a
`summary` por la política vigente.

Ejemplo mínimo para la propuesta anterior, usando `model_derived`:

```json
{
  "schema": "an-kla/write-authority-v1",
  "proposal_sha256": "sha256:PROPOSAL_SHA256",
  "base_revision": "sha256:REVISION_ACTUAL",
  "authority_class": "model_derived",
  "issuer": {
    "kind": "model",
    "id": "agent-local",
    "configuration_fingerprint": "sha256:ISSUER_CONFIG_SHA256"
  },
  "evidence": [],
  "scope": {
    "streams": ["facts"],
    "representations": ["summary"],
    "operations": ["add"]
  }
}
```

Los tres valores en mayúsculas son marcadores documentales, no digests válidos.
`base_revision` debe repetir exactamente `revision` de `status` y
`proposal_sha256` es `digest_json()` del objeto JSON parseado, no el hash del
archivo ni del texto pretty-printed:

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path
from an_kla.canonical import digest_json

proposal = json.loads(Path("proposal.json").read_text(encoding="utf-8"))
issuer_config = json.loads(
    Path("issuer-config.json").read_text(encoding="utf-8")
)
print("proposal_sha256=", digest_json(proposal), sep="")
print("configuration_fingerprint=", digest_json(issuer_config), sep="")
PY
```

`issuer-config.json` es configuración **saneada y propiedad del caller/host**:
describe la configuración real que identifica al issuer (por ejemplo kind, id y
perfil local), sin secretos, rutas privadas ni credenciales. AN-KLA sólo exige
un digest bien formado en esta superficie: el fingerprint liga la declaración,
pero no prueba identidad, no concede autoridad y no debe sustituirse por ceros o
un valor arbitrario para “hacer pasar” el schema.

Un caller manual podría declarar, por ejemplo, este objeto propio —no es un
schema normativo de AN-KLA— y conservarlo junto a su configuración local:

```json
{
  "kind": "model",
  "id": "agent-local",
  "profile": "manual-cli/v1"
}
```

Los objetos normativos completos se describen en
[ADR-0007](architecture/0007-write-policy-v1.md). Inspecciona sus schemas sin
leer memoria:

```bash
.venv/bin/python -m an_kla schema show write-proposal-v1
.venv/bin/python -m an_kla schema show write-authority-v1
```

## Recorrido mínimo completo

1. Ejecuta `status` y copia su `revision` exacta a `proposal.json` y
   `authority.json`.
2. Termina `proposal.json`; después calcula su `proposal_sha256` canónico.
3. Define y conserva la configuración saneada del issuer, calcula su
   fingerprint y termina `authority.json` con scope exacto.
4. Elige una ruta nueva y privada para el planning result.
5. Ejecuta `plan-write`, revisa el JSON y entrégalo sin reconstruir a
   `commit-write-plan` junto con los mismos proposal/authority/revisión.
6. Comprueba el outcome y vuelve a ejecutar `status`.

Los schemas también están versionados en `docs/schemas/`.

## Planificar sin mutación

El resultado debe ir a un archivo efímero **nuevo**, no rastreado y con permisos
privados. Sustituye `RUTA_NUEVA` por una ruta que hayas comprobado que no existe;
la redirección del shell por sí sola no protege contra sobrescrituras:

```bash
.venv/bin/python -m an_kla \
  --project-root . \
  plan-write \
  --proposal proposal.json \
  --authority authority.json > RUTA_NUEVA
```

Si el `base_revision` ya no es `CURRENT`, termina con
`write_plan_base_changed`. Una planificación correcta no crea revisión,
journal, segmento ni evento.

La envolvente guardada en `RUTA_NUEVA` contiene la decisión y el plan exactos.
Debe tratarse como un artefacto ligado a contenido, no como autorización.

## Confirmar el plan exacto

```bash
.venv/bin/python -m an_kla \
  --project-root . \
  commit-write-plan \
  --expected-current sha256:REVISION_ACTUAL \
  --proposal proposal.json \
  --authority authority.json \
  --planning-result RUTA_NUEVA
```

Dentro del lock se comprueban nuevamente:

- `CURRENT` frente a `--expected-current`;
- revisiones base de propuesta, autoridad y plan;
- hashes de propuesta, autoridad, decisión, registros y configuración;
- decisión y razones reconstruidas por el núcleo puro;
- semántica `add` antes de entregar registros al escritor append-only.

Un cambio en cualquiera de los objetos falla antes de preparar el journal. Si
la decisión es `skip`, el resultado declara `committed: false` y la memoria no
cambia.

La envolvente también liga `current_revision` al valor de
`--expected-current`. Aunque la revisión ya está incluida en el plan, el CLI no
ignora ni acepta una copia exterior alterada.

### Varias escrituras

Cada commit exitoso mueve `CURRENT`. No prepares un batch completo contra una
sola revisión: el segundo plan quedará obsoleto. Ejecuta cada elemento de forma
secuencial:

```text
status → proposal/authority → plan-write → commit-write-plan → verificar outcome
       → status nuevo → siguiente proposal/authority → plan-write → commit…
```

`write_plan_base_changed (refresh_status_and_replan)` indica que debes descartar
el planning result obsoleto, releer `status` y construir un plan nuevo. No
edites el plan viejo ni fuerces `expected-current`.

## Frontera de autoridad del CLI

Un archivo JSON no demuestra que una herramienta observó algo ni que otro
canal confirmó una decisión. Por eso este CLI falla cerrado cuando
`authority_class` es `tool_observed` o `channel_confirmed`:

```text
cli_privileged_authority_unresolved
```

Esas clases se reservan para adaptadores que invoquen la API de Python después
de resolver autoridad desde configuración y estado externos al candidato. Esta
beta no afirma identidad criptográfica.

Los fallos al leer JSON se devuelven como `input_json_unreadable` o
`input_json_invalid`. En `plan-write`/`commit-write-plan` pueden añadir el rol
saneado `proposal`, `authority` o `planning_result`; nunca incluyen la ruta
absoluta ni el contenido candidato.

## API interna

El comando público heredado `write` fue retirado en beta.11. Toda escritura
pública nueva usa `plan-write` → `commit-write-plan`; pasar
`--allow-legacy-unguarded-write` también falla porque el flag ya no forma parte
del CLI.

`MemoryStore.commit()` se conserva como mecanismo interno de mantenimiento y
tests, no como superficie pública ni vía para saltar la política. MCP sigue
siendo de sólo lectura.
