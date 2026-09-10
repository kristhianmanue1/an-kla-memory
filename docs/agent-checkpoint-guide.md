# Guía de checkpoint para agentes — cierre de sesión gobernado

Cómo deja un agente **checkpoint de continuidad** al cerrar trabajo
material, sin leer código interno: forma exacta de cada entrada, el
binding de autoridad y el cierre canónico de sesión. Contratos de fondo:
[ADR-0023](architecture/0023-governed-checkpoint-handoff-v2.md) (formato),
[ADR-0038](architecture/0038-source-state-git-v1.md) (`source_state
git/v1`), [ADR-0046](architecture/0046-attest-local-signed-observation-v1.md)
(attest). Issue de origen: #121 (y #120, contrato de `--input`).

## Idea en una frase

`checkpoint plan --input <working_state.json> --emit-authority-template`
calcula por ti la parte no derivable (el digest de autoridad); con esa
plantilla planificas y confirmas. Tres comandos, cero reconstrucción a
mano.

## 1. Forma exacta de `--input`

`--input` espera el **`working-state-v2` directo** — NO el objeto
`checkpoint-proposal-v1` (ese lo arma el CLI por dentro;
`checkpoint-proposal-v1` en `schema show` describe ese objeto interno,
no el archivo de entrada).

Campos obligatorios (`additionalProperties: false`):

- `objective`, `phase`, `next_step`: `{"value": <str>, "provenance":
  "caller_asserted"}`.
- `decisions`, `blockers`, `evidence`: arrays de
  `{"id", "value", "provenance": "caller_asserted"}` (máx. 50,
  ids únicos).
- `source_state`: perfil `git/v1` (head/branch/dirty_digest
  caller_asserted; head sha40/sha64) o `none/v1` (todo `unavailable`).
- `captured_at`: `YYYY-MM-DDTHH:MM:SS.ffffffZ` — ojo al `.ffffff`
  (microsegundos obligatorios).
- `supersedes_checkpoint`: el digest del checkpoint vigente (lo da
  `checkpoint show`).

Reglas semánticas que el schema NO muestra y el validador sí aplica:
cada `value` serializado canónicamente ≤ 8192 bytes; `captured_at`
debe sobrevivir un round-trip UTC; `git/v1` exige `caller_asserted`
(nunca `unavailable`); `decisions/blockers/evidence` pueden ir vacíos.

## 2. Emitir la autoridad (el binding ya calculado)

La autoridad liga `proposal_sha256` al **proposal interno** que el CLI
arma (`{schema, base_revision, parent_checkpoint, working_state}` con
base/parent tomados del store). Replicarlo a mano requiere leer código;
el flag lo hace por ti:

```bash
python -m an_kla --project-root . checkpoint plan \
  --input working_state.json --emit-authority-template \
  > authority.json
```

Emite una `checkpoint-authority-v1` con `proposal_sha256` y
`base_revision` reales, clase `model_derived` e issuer genérico
(`agent-local`, config `manual-cli/v1`). Edita `issuer` sólo si tu
configuración difiere; si usas `tool_observed` necesitas el adaptador
attest (ADR-0046 — ver §4); `channel_confirmed` es de host.

## 3. Cierre canónico de sesión (copy-paste-safe)

```bash
# 0. registrar el estado de Git que describes (caller_asserted):
HEAD_SHA="$(git rev-parse HEAD)"
# captured_at con microsegundos (formato obligatorio del validador):
STAMP="$(python -c "from datetime import datetime,timezone; \
  print(datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ'))")"
```

Arma `working_state.json` con ese `captured_at` y `supersedes_checkpoint`
= digest devuelto por `checkpoint show` (§1). Después:

```bash
# 1. emitir autoridad (binding calculado):
python -m an_kla --project-root . checkpoint plan \
  --input working_state.json --emit-authority-template > authority.json

# 2. planificar (read-only; revisa decision y reason_codes):
python -m an_kla --project-root . checkpoint plan \
  --input working_state.json --authority authority.json > planning.json

# 3. confirmar (uuid SIEMPRE en minúsculas — uuidgen puede dar
#    mayúsculas y el validador lo rechaza):
TXID="$(python -c 'import uuid; print(uuid.uuid4())')"
REVISION="$(python -m an_kla --project-root . status \
  | python -c 'import json,sys; print(json.load(sys.stdin)["revision"])')"
python -m an_kla --project-root . checkpoint commit \
  --plan planning.json \
  --expected-current "$REVISION" \
  --transaction-id "$TXID"

# 4. verificar:
python -m an_kla --project-root . verify
python -m an_kla --project-root . checkpoint show
```

Nota: usa `python -m an_kla` (el binario `an-kla` puede no estar en PATH
según la instalación). Notas: `--expected-current` es la `revision` que
viste al preparar el plan; si CURRENT se movió mientras tanto, el commit
falla `checkpoint_plan_base_changed` — relee y replanifica, no fuerces.
Si el resultado es ambiguo (timeout, crash), `transaction inspect <uuid>`
antes de reintentar (`docs/agent-recovery.md`).

## 4. Clases de autoridad y attest

| Clase | Standalone por CLI | Uso típico |
|---|---|---|
| `model_derived` | ✅ (el default del template) | working_state saneado, modelo | 
| `channel_confirmed` | requiere issuer `channel` resuelto por el host | el host confirma el canal |
| `tool_observed` | ❌ el CLI lo rechaza; requiere adaptador attest (ADR-0046) | evidencia de comando ejecutado |

La vía gobernada de attest (`attest init/run` + receipt en la
`evidence` de la authority) está en la
[guía de attest](../docs/architecture/0046-attest-local-signed-observation-v1.md);
los hooks del host (`--on-behalf-of-hook`, ADR-0047) son el camino
opuesto: el host exige, el agente propone.

## 5. Errores comunes (con diagnóstico de campo — #120.1)

Cada rechazo de política imprime un `detail` que nombra el campo ofensor
(informativo y evolutivo; el código de la izquierda es el contrato estable):

```text
an-kla error: invalid_working_state (captured_at.value:not_canonical_utc)
an-kla error: invalid_working_state (source_state:keys:missing=dirty_digest)
an-kla error: invalid_checkpoint_authority (scope.fields:order)
```

| Código | Causa típica (con `detail` representativo) |
|---|---|
| `invalid_working_state` | forma/llaves: `working_state:keys:missing=…` / `extra=…`; `captured_at.value:not_canonical_utc` (exige round-trip UTC con microsegundos); `decisions[].value:too_large` (> 8192 bytes canónicos); `source_state.head.value:not_object_id`; `source_state.profile:unknown` |
| `invalid_checkpoint_provenance` | `git/v1` exige valores `caller_asserted`, nunca `unavailable` (ADR-0038): `source_state.dirty_digest.provenance` |
| `invalid_checkpoint_authority` | `scope.fields:order` (orden por bytes UTF-8); `proposal_sha256:not_digest` o binding distinto del proposal interno (usa `--emit-authority-template`); `issuer.kind:authority_class_mismatch`; `issuer.configuration_fingerprint:not_digest` |
| `checkpoint_parent_mismatch` | `supersedes_checkpoint:not_current` — tu `supersedes_checkpoint` ≠ checkpoint vigente (relee `checkpoint show`) |
| `checkpoint_plan_base_changed` | CURRENT avanzó: relee `status` y replanifica |
| `missing_checkpoint_authority` | invocaste `plan` sin `--authority` ni `--emit-authority-template` |

`detail` nombra campos y reglas, nunca valores de entrada; puede evolucionar
sin aviso — no lo trates como contrato. Los nombres de llaves extra se
sanitizan (`[unnamed]` si no encajan en el vocabulario de claves) y el
`detail` completo se trunca a 256 caracteres.

## 6. Con worktrees

La memoria vive en el checkout canónico (hasta G3, #57): si trabajas en
un worktree, apunta `--project-root` al checkout canónico; el worktree
sin `.an-kla/` propio no tiene memoria ni checkpoint.
