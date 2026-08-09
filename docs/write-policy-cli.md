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

La autoridad separada, `authority.json`, liga el hash canónico de la propuesta,
la misma revisión y el alcance exacto. Un agente por CLI puede usar
`model_derived` o `derived_from_retrieval`; ambas clases quedan limitadas a
`summary` por la política vigente.

Los objetos normativos completos se describen en
[ADR-0007](architecture/0007-write-policy-v1.md) y en `docs/schemas/`.

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
`input_json_invalid`; no incluyen rutas absolutas ni contenido candidato.

## API interna

El comando público heredado `write` fue retirado en beta.11. Toda escritura
pública nueva usa `plan-write` → `commit-write-plan`; pasar
`--allow-legacy-unguarded-write` también falla porque el flag ya no forma parte
del CLI.

`MemoryStore.commit()` se conserva como mecanismo interno de mantenimiento y
tests, no como superficie pública ni vía para saltar la política. MCP sigue
siendo de sólo lectura.
