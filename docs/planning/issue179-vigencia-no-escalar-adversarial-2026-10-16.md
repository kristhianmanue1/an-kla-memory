# Ronda adversarial de #179: lectores tolerantes a vigencia no escalar

Rama `fix/179-vigencia-no-escalar`, commit atacado `f6ac70a`. Ronda
obligatoria: toca `store.py`, supersede, refute y compactación. Revisor de
contexto fresco, sólo lectura, diferencial contra `v0.1.0-beta.33`, Python
3.12.

## Origen

La ronda de release de beta.33 (REL-1) mostró que los records con
`status`/`nu` no escalares, escritos por lotes en b31/b32, rompían supersede,
`refute inspect` y `compact plan` con `TypeError` (`cli_unexpected_failure`).

## Verificación del revisor

- Predicado: diferencial de 121 combinaciones canónicas de `status`/`nu` entre
  las expresiones antiguas (default `"vigente"` y default `None` de
  compactación) e `is_active`: 0 diferencias.
- Sin `TypeError` en ningún comando con listas, dicts, int, bool, float y
  combinaciones mixtas: supersede (plan v1, plan lote y commit), refute (plan,
  commit e inspect), compactación con export real (plan y commit),
  `retrieve`, `resume`, `view context`, `inventory`, `verify`, `doctor`,
  `status`, `startup-diagnostic`, `integration status`, `export verify`,
  `rebuild-index`. `inactive` válido en los schemas de tombstones y de
  refute-inspect; `export verify` rc=0 tras compactar.
- Suite completa 1256 OK; gates OK.

## Decisión de la ronda: `fix-and-retry` (2 MAJOR, 5 MINOR)

| ID | Hallazgo | Corrección |
|---|---|---|
| H1 MAJOR | Regresión en `inventory`: `status` válido con `nu` no escalar salía `no_canonica` → `refute_overlay` sin refutación | `is_canonical_vigency` alineado con `is_active` (decide `status`; si falta, `nu`): ese record es canónico y `vigente`. El overlay se detecta por cambio real del `status` del snapshot |
| H2 MAJOR | Sin test que matara la reversión en el commit de supersede (`supersede.py`) ni en el commit de refute (`_target_guard`) | Tests directos de `resolve_supersede_targets` (`target_not_vigente`) y `_target_guard` (`target_not_active`) |
| H3 MINOR | `status: None` cambiaba de `"None"`/`refute_overlay` a `vigente`/`physical` sin declararlo | Fijado en test; es la corrección deseada (declarado en el PR) |
| H4 MINOR | `status: ""` producía `status: ""` (viola `minLength`) y `refute_overlay` falso (preexistente) | Resuelto con H1: `vigente`/`physical`; en test |
| H5 MINOR | `verify` (6) e `inventory` (5) no cuadraban | Resuelto con H1; el test exige que coincidan |
| H6 MINOR | Sin documentación | Enmienda 1 de ADR-0041 y párrafo en `docs/uso-diario.md` |
| H7 MINOR | `verified_at` inválido no se diagnostica | Fuera de alcance: no afecta a la vigencia (se sirve como vigente con `freshness.unparseable`); queda anotado en el PR |

## Mutantes por lector (autor, tras las correcciones)

Revertir cada endurecimiento por separado: plan v1, plan de lote, commit de
supersede, commit de refute, `refute inspect`, compactación, bucket de
`inventory` y aviso de `verify` hacen fallar los tests (8 de 9). El noveno,
volver a comparar el overlay con `physical` en vez de con el `status` crudo,
es **equivalente para todo estado que pueda escribir la vía gobernada**
(canónico, mixto, `None`, `""`, no canónico con y sin overlay). El revisor lo
distinguió sólo con un estado falsificado (un record `{"nu": "sustituida"}`
dentro de `supersedes_map`, imposible porque los guardas de commit exigen
`is_active`): ahí la forma actual da `supersede_overlay`, que es lo correcto,
y el mutante `physical`. Se conserva la forma por overlay real.

## Re-verificación de `2a481f2`: `proceed`

- Diferencial e2e sobre 20 records (supersede plan v1/lote y commit, refute
  plan/commit/inspect, compactación con export real, `retrieve`, `resume`,
  `view`, `rebuild-index`, `verify`, `doctor`, `status`, `startup`,
  `integration`, `export verify`): igual que `f6ac70a`; frente a b33 sólo
  cambian los `TypeError`, ahora errores normales, y la compactación, que
  ahora hace commit.
- Inventory con 22 records: las únicas diferencias frente a b33 son
  correcciones deseadas (`None`/`""` sin refutación falsa, no canónicos en
  `no_canonica`, mixto `vigente`); la salida valida contra `inventory-v1`
  (b33 lo violaba con `""`); `verify` y el bucket cuentan 6.
- Mutantes `sup` y `ref` (y anular `is_canonical_vigency`) mueren.
- Docs correctos.
- MINOR preexistente, seguimiento aparte: `status: ""` aparece `vigente` en
  inventory pero `is_active` lo trata como no vigente.

## Decisión

- [x] proceed
- [ ] fix-and-retry
- [ ] escalate
