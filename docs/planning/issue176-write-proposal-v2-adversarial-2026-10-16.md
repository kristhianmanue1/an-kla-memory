# Ronda adversarial de #176: `write-proposal-v2` descubrible

Rama `feat/176-write-proposal-v2-descubrible`, commit atacado `f44677f`
(sobre la plantilla `0.1.0-beta.33` sin publicar, ya fusionada en #177).
Ronda obligatoria: cambia el contrato gestionado y publica un schema
normativo; tras los hallazgos toca además `write_policy.py`. Revisor de
contexto fresco, sólo lectura, `.venv/bin/python` 3.12.

## Decisión de la ronda: `fix-and-retry` (2 MAJOR, 4 MINOR)

| ID | Hallazgo | Corrección |
|---|---|---|
| 1 MAJOR | **Defecto del motor (desde beta.31):** el validador del lote sólo comprobaba `id`; el gemelo v1 revalidaba `records[0]`, así que `records[1..]` se guardaban con `verified_at` inválido o `status`/`nu` no escalares (la protección de #113). Con `status: 7` en un fact, `retrieve` lo clasificaba `inactive`: un dato del caller alteraba la vigencia | `validate_record_fields` compartida por v1 y por cada record del lote (`records[i].<campo>`); mensajes de v1 idénticos. E2E: los tres casos fallan ya en `plan-write --emit-authority-template` (misma validación); un lote válido hace commit |
| 2 MAJOR | El test de receta no protegía la línea del lote: seis mutantes pasaban (mapa→cadena, 1000→100, sin «se planifica y confirma igual», «cualquier stream», `schema show` v1, «además de `record`»). La afirmación del autor «30 mutantes fallan» no cubría esos casos | El test extrae y contrasta con el motor cada afirmación: const del schema citado, límite = `max_batch_records`, stream/operación del lote, rechazo con `record` y `records`, plan y commit, y supersede en lote con el mapa de la prosa (`sustituida`/`vigente` en `inventory`). Los 36 mutantes fallan |
| 3 MINOR | `docs/write-policy-cli.md` pedía escrituras secuenciales sin mencionar el lote | Párrafo «Varias escrituras» actualizado |
| 4 MINOR | ADR-0054 cita `plan-write --batch`, que no existe; §2 «evalúa cada registro» no era cierto | Enmienda 1 de ADR-0054 (no se edita el cuerpo aceptado) |
| 5 MINOR | `project-manifest.yaml` no publicaba `write-proposal-v2` | Añadido |
| 6 MINOR | Divergencias no declaradas: digest con salto final y valores no finitos (sólo el motor rechaza) | Declaradas en la descripción del schema y fijadas en el test |

La matriz de concordancia ahora tiene tres listas explícitas: veredicto
compartido (23 casos), sólo el motor (10) y sólo el schema (2, heredado de
v1: `text` vacío o no cadena; no se cambia la política de v1 aquí).

## Re-verificación de `9bf138d`: `proceed`

- #1 resuelto: fuzz comparando `f44677f` con `9bf138d`; todos los casos de
  `records[0]` y `records[1..]` (`verified_at` inválido o entero,
  `subject_ref` inválido, `status`/`nu` no escalares, fecha `2026-02-30`)
  se rechazan con `records[i].<campo>`. E2E: el lote de facts con
  `status: 7` + `subject_ref` inválido, que antes hacía commit, falla en el
  plan; lote add de 3 events y supersede de 2 facts hacen commit con los
  estados correctos; `verify` rc=0.
- v1 sin regresión: mismos códigos y detalles para `record.*`, mismo orden
  de error; `policy_fingerprint()` igual (`4c5b2873…`), porque
  `_POLICY_CONFIGURATION` no cambia: el arreglo sólo rechaza propuestas que
  ya eran inválidas según el perfil declarado.
- #2 resuelto: los 6 mutantes del revisor fallan.
- #3–#6 resueltos. 178 tests de los módulos afectados en verde; gates OK.

## Decisión

- [x] proceed
- [ ] fix-and-retry
- [ ] escalate
