# ADR-0023: checkpoint y handoff gobernado v2

## Estado

Aceptada e implementada localmente el 2026-08-08 por autorización del roadmap
del maintainer. Diseño e implementación cerraron sus rondas adversariales en
`proceed`, después de ADR-0024 y ADR-0022 en ese orden.

## Contexto

El checkpoint es exacto y ligado a revisión, pero no tiene superficie gobernada
de actualización. Buscar continuidad como fact por similitud mezcla estado
operacional con conocimiento durable. Además un JSON que dice “Git observado”
no demuestra que AN-KLA ejecutó una herramienta.

## Forma exacta y procedencia

`checkpoint-v2` sigue siendo un objeto único, nunca un stream:

```json
{
  "schema": "an-kla/checkpoint-v2",
  "revision": 18,
  "working_state": {
    "schema": "an-kla/working-state-v2",
    "objective": {"value": "...", "provenance": "caller_asserted"},
    "phase": {"value": "...", "provenance": "caller_asserted"},
    "next_step": {"value": "...", "provenance": "caller_asserted"},
    "decisions": [],
    "blockers": [],
    "evidence": [],
    "source_state": {
      "profile": "none/v1",
      "head": {"value": null, "provenance": "unavailable"},
      "branch": {"value": null, "provenance": "unavailable"},
      "dirty_digest": {"value": null, "provenance": "unavailable"}
    },
    "captured_at": {
      "value": "2026-08-08T00:00:00.000000Z",
      "provenance": "caller_asserted"
    },
    "supersedes_checkpoint": "sha256:..."
  }
}
```

Todos los objetos usan claves exactas. Provenance es
`tool_observed|caller_asserted|unavailable`; `unavailable` exige `value=null`.
Los tres campos escalares aceptan string o null. `captured_at` usa la gramática
UTC canónica o null. Es obligatorio dentro de `working_state` antes de invocar
el planner y en el core inicial sólo puede ser caller_asserted o unavailable;
el planner puro nunca lee reloj. Una capa futura que observe reloj debe producir
primero bytes de proposal mediante un boundary autorizado.

Listas contienen hasta 50 objetos exactos:

```json
{"id":"estable","value":{},"provenance":"caller_asserted"}
```

IDs son únicos; cada value canónico ≤8192 bytes y working_state completo ≤65536
bytes. Provenance cubre el item entero: valores nested no mezclan procedencias.

## Frontera de adapter

JSON de input y `authority.json` nunca prueban `tool_observed`. El core CLI de
esta iteración sólo acepta `caller_asserted|unavailable`. Una futura API Python
puede recibir un `SourceObserver` configurado y un handle opaco no serializable;
plan y commit deben invocarlo/verificarlo en el mismo boundary y ligar su
attestation digest al plan. Copiar el digest no basta sin el observer activo.

No se integra adapter Git/proveedor sin orden explícita. La implementación v2
sólo admite `source_state.profile=none/v1` con los tres valores unavailable.
`git/v1` queda reservado, no normativo y rechazado por el schema inicial; una
versión futura necesita ADR y bump de checkpoint porque aún no existe un digest
interoperable congelado.

## Profile reservado `git/v1`

Estas propiedades son requisitos de investigación, no un contrato aceptado:

- `head`: object id lowercase (40 o 64 hex), o null en unborn;
- `branch`: ref corta UTF-8, o null en detached/unborn;
- `dirty_digest`: SHA-256 de JSON canónico de entradas porcelain-v2 `-z`,
  ordenadas por bytes de path, incluyendo tracked, untracked y gitlinks;
- ignored se excluye; renames conservan par origen/destino; symlinks no se
  dereferencian; submodules se representan sólo por estado gitlink;
- no se guarda diff, contenido, ruta absoluta, remote, autor o email.

Errores, bytes no UTF-8 o repo no disponible producen unavailable; nunca se
degradan a caller_asserted automáticamente. Una observación live se captura una
vez y lleva su propio `observed_at`. Antes de implementarlo habrá que congelar
shape de entry, campos status/mode/OID, representación de rename, orden binario
y vectores de digest; hasta entonces ningún output puede llamarse `git/v1`.

## Semántica de checkpoint por revisión

Writes ordinarios de facts/events/episodes reutilizan exactamente el digest del
checkpoint padre. No incrementan `checkpoint.revision` ni cambian
`base_event_id`; por ello ese número representa la revisión de captura y puede
ser menor que `manifest.revision`.
Toda lectura central valida que sea entero no booleano y cumpla
`1 <= checkpoint.revision <= manifest.revision`; negativo, cero o futuro falla
cerrado en snapshot, verify, retrieval y antes de un write descendiente.

Sólo `checkpoint commit` crea checkpoint nuevo, fija su `revision` al manifest
candidato y enlaza `supersedes_checkpoint` al digest padre. Esto corrige el
acoplamiento implícito actual de `_commit_locked()`; revisiones históricas no se
reescriben.

## Autoridad y plan exactos

`write-authority-v1` no autoriza checkpoints. Esta superficie introduce cuatro
schemas cerrados, sin reinterpretar el contrato de facts:

- `checkpoint-proposal-v1`: `schema`, `base_revision`,
  `parent_checkpoint`, `working_state`;
- `checkpoint-authority-v1`: `schema`, `proposal_sha256`, `base_revision`,
  `authority_class`, `issuer`, `evidence`, `scope`;
- `checkpoint-decision-v1`: `schema`, ambos hashes, `decision` y `reasons`;
- `checkpoint-plan-v1`: `schema`, `core`, `checkpoint` y `plan_fingerprint`.

Authority reutiliza shapes exactos de issuer/evidence de ADR-0007. Sus clases
son `tool_observed|channel_confirmed|model_derived|unresolved`; scope es
exactamente `{"operation":"checkpoint","fields":[...]}`, donde fields es un
array único/no vacío ordenado por bytes y limitado al enum
`objective|phase|next_step|decisions|blockers|evidence|source_state|captured_at`.
Issuer kind debe corresponder `tool|channel|model|unknown`; evidence conserva
`artifact|event|revision|external`, resolution
`verified|unresolved|invalid` y exige sha256 cuando verified.

La decisión es `skip|write`; reasons es un array ordenado/único del enum
`authority_binding_mismatch`, `authority_scope_mismatch`,
`unresolved_authority`, `invalid_checkpoint_provenance`,
`checkpoint_unchanged`. `model_derived` puede
autorizar sólo campos caller_asserted/unavailable y nunca elevar
tool_observed. Sin observer activo, cualquier provenance o authority class
`tool_observed` es error terminal `tool_observed_requires_adapter` antes de
evaluar decisión; no aparece simultáneamente como reason de skip.

El core del plan liga `base_revision`, `parent_checkpoint`,
`proposal_sha256`, `authority_sha256`, `policy_fingerprint`, `decision_sha256`
y `checkpoint_sha256`; fingerprint es SHA-256 del core canónico. Proposal,
decision y plan son deterministas. El txid vive exclusivamente en
`transaction-attempt-v1` de ADR-0024, de modo que replanear iguales inputs da
bytes iguales y planes pendientes no cambian.

## Flujo gobernado

```text
an-kla checkpoint show
an-kla checkpoint plan --input state.json --authority authority.json
an-kla checkpoint commit --plan plan.json --expected-current sha256:... \
  --transaction-id UUID
an-kla resume --budget 4096 [--query "..."]
```

Show es read-only/untrusted. Plan liga parent revision, parent checkpoint,
input+authority hashes, policy fingerprint y candidato exacto. Commit recibe el
transaction-attempt de ADR-0024 con un `transaction_id` preasignado y
obligatorio para toda decisión `write`; revalida identidad, adapter boundary,
plan y CURRENT bajo lock y no usa el write legado. Repetir exactamente plan,
base y UUID reconcilia el mismo candidato incluso si la primera respuesta se
perdió después de avanzar CURRENT. Omitir el UUID falla antes de I/O y no crea
objetos. Model-derived sólo puede producir caller_asserted/unavailable.

## Resume consistente

Resume lee CURRENT exactamente una vez, obtiene snapshot/checkpoint de esa
revisión y pasa el mismo `revision_id` a retrieval. Se añade retrieval exacto
por revisión (o helper sobre Snapshot); nunca vuelve a seleccionar CURRENT.
Una carrera A→B puede producir sólo snapshot A + evidence A, no mezcla A/B.

`--query` es opcional. Ausente → retrieval deshabilitado, evidence vacía y no se
lee índice. Presente → string no vacío y retrieval sin frescura sobre la
revisión fijada. La v1 inicial no acepta live observation: live_delta queda
null/unavailable; añadirla requiere bump de resume y no cambia la revisión de
memoria.

Resultado exacto:

```json
{
  "schema":"an-kla/resume-v1",
  "untrusted_memory_data":true,
  "revision":"sha256:...",
  "budget_bytes":4096,
  "used_bytes":0,
  "snapshot":{
    "schema":"an-kla/resume-snapshot-v1",
    "checkpoint_digest":"sha256:...",
    "checkpoint_schema":"an-kla/checkpoint-v2",
    "checkpoint":{}
  },
  "live_delta":null,
  "retrieved_evidence":[],
  "warnings":[],
  "provenance":{
    "memory":{"source":"revision_snapshot","revision":"sha256:..."},
    "retrieval":{"source":"disabled","revision":null,"query":"disabled"},
    "live_delta":{"source":"unavailable"}
  },
  "excluded_summary":{
    "inactive":0,
    "zero_score":0,
    "budget":0,
    "invalid_record":0,
    "no_text":0
  }
}
```

`snapshot` tiene dos variantes de claves exactas. Para v2, `checkpoint` es el
objeto `checkpoint-v2` validado completo. Para legacy, sustituye esa clave por
`legacy_checkpoint_json`, string de JSON canónico, y
`checkpoint_schema=an-kla/checkpoint-v1`; así datos legacy no abren
`additionalProperties`. `checkpoint_digest` siempre se verifica contra los
bytes del objeto de la revisión fijada.

La implementación inicial no tiene observer: `live_delta` es siempre null y
su provenance siempre `{"source":"unavailable"}`. Incorporarlo requiere bump
del schema resume. Cada `retrieved_evidence` usa el schema exacto
`an-kla/resume-evidence-v1` con `source="retrieval-result-v1"`, `revision`,
`id`, `stream`, `score`, `render` y `cost_bytes`; no admite frescura ni otras
claves. Los últimos cinco campos copian el selected item v1 sin reparsear ni
rerankear. La provenance de retrieval
es exactamente una de:

```json
{"source":"disabled","revision":null,"query":"disabled"}
{"source":"scan-fallback/v1","revision":"sha256:...","query":"caller_asserted"}
{"source":"sqlite-fts5/v1","revision":"sha256:...","query":"caller_asserted"}
```

`excluded_summary` siempre contiene las cinco razones mostradas, incluso en
cero; su fuente son los contadores homónimos de retrieval. No se agregan ni
omiten razones por perfil.
Warnings enum v1: `legacy_checkpoint_v1`,
`retrieval_degraded_to_scan`; orden
lexicográfico, sin duplicados.

Prioridad bajo budget UTF-8 exacto:

1. envelope, snapshot exacto, provenance y warnings obligatorios;
2. evidence en ranking determinista; candidatos que no caben incrementan
   `excluded_summary.budget`.

Se reserva desde el inicio el peor diagnóstico aplicable para evitar expulsión
sin reconsideración. `used_bytes` es el tamaño del JSON canónico completo
incluyendo el propio entero; el encoder itera hasta el punto fijo decimal y
elige la única serialización estable. Root/snapshot nunca se truncan; si no
caben falla `budget_too_small_for_resume_snapshot`.

## Compatibilidad

Checkpoint-v1 se muestra como snapshot legacy con warning
`legacy_checkpoint_v1`; no inventa fields ni provenance. El primer checkpoint
commit v2 enlaza el digest v1. Ordinary writes posteriores ya reutilizan ese
digest. Working_state jamás entra a segmentos/FTS.

## Errores y pruebas

Códigos: `invalid_working_state`, `invalid_checkpoint_authority`,
`invalid_checkpoint_plan`, `invalid_checkpoint_provenance`,
`tool_observed_requires_adapter`, `checkpoint_plan_base_changed`,
`checkpoint_parent_mismatch`, `budget_too_small_for_resume_snapshot`.

Pruebas: shape/provenance exacta, unavailable/null, límites de bytes/items,
spoofing JSON, planner sin reloj, v1→v2, ordinary write reutiliza digest, carrera A→B,
resume con/sin query, live delta fijo null, evidence budget, identidad y outcomes
post-CURRENT. Se prueba que working_state no es recuperable lexicalmente.

## Dependencias y alternativas

ADR-0024 primitives/outcome primero; ADR-0022 identidad después; este ADR al
final. Se descarta fact lexical, confianza en texto Git, checkpoint implícito en
cualquier write y resume mutativo.
