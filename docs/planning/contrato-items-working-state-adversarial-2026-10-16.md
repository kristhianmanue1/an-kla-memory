# Ronda adversarial: forma de los elementos de working-state (plantilla `0.1.0-beta.33`)

Rama `fix/contrato-items-working-state`, commit atacado `e659306`. Ronda
obligatoria (cambia el contrato gestionado). Revisor de contexto fresco,
sólo lectura, `.venv/bin/python` 3.12.

## Origen

Al guardar el checkpoint de cierre del 2026-10-16 con la receta de beta.32,
el primer intento falló con `invalid_working_state
(decisions[]:keys:missing=id)`: la referencia sólo mostraba listas vacías.
Como beta.32 ya está publicada, la corrección abre la plantilla
`0.1.0-beta.33` y congela beta.32.

## Verificación del revisor

- Hashes de beta.32 recalculados desde el tag `v0.1.0-beta.32`
  (`COMPACT_PAYLOAD` `00e57150…`, `DETAILED_CONTRACT` `7ef316dd…`): coinciden
  con la entrada congelada y con el bloque del `AGENTS.md` publicado. Fixture
  byte a byte igual al tag.
- Migración real en venv limpio desde el tag beta.32 y desde beta.31
  (plantilla beta.26): `context_template_outdated` sin
  `managed_contract_modified`, `update` y `verify` ok. Un CLI beta.32 sobre
  plantilla beta.33 falla cerrado sin degradar.
- Prosa contra `schema show working-state-v2`: `id` único por lista
  (`x-an-kla-unique-by`), `value` acepta cualquier JSON canónico, máximo 50
  elementos. `lineage.refs`: los 6 `kind`, con y sin `sha256`, aceptados; la
  receta no induce a error.

## Hallazgos y correcciones

Decisión: **proceed** (0 BLOCKER, 0 MAJOR).

| ID | Hallazgo | Corrección |
|---|---|---|
| H1 (MINOR) | Topes de tamaño no descubribles: 50 elementos por lista, 8 KiB por `value`, 64 KiB por working-state (`checkpoint_policy.py`); ni el schema ni `capabilities` los exponen | Añadidos a la prosa de la referencia; test que los compara con `_CONFIG` de la política |
| H2 (MINOR) | El test sólo rellenaba `decisions` | El test de la receta rellena también `blockers` y `evidence` |

Tras las correcciones, los 28 mutantes de deriva siguen fallando.

## Decisión

- [x] proceed
- [ ] fix-and-retry
- [ ] escalate
