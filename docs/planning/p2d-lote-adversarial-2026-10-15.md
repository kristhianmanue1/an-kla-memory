# Ronda adversarial — P2d commit gobernado en lote (ADR-0054), 2026-10-15

Artefacto atacado: `feat/p2d-lote-gobernado@9597969` — `an_kla/write_batch.py`
(v2: gemelo v1, evaluación pre-lote), despachos en `write_policy.py`
(`max_batch_records=1000` en el perfil, fingerprint `21bc0dd3`→`4c5b2873`),
`plan_guard.py` (guardián por lote), `write_commit.py` (warning por razón
agregada), `tests/test_write_batch.py` y el escenario `ingest-batch` de la
batería. **Toca `write_policy.py`: ronda obligatoria.** Intérprete:
`.venv/bin/python` → Python 3.12.12.

## Alcance

1. Una sola fuente de política (el gemelo no es una segunda implementación).
2. Binding de autoridad: digest REAL liga al lote, no al gemelo.
3. Orden-independencia del lote (intra-lote, targets duplicados).
4. Atomicidad all-or-nothing y efectos cero.
5. Determinismo del plan (verify bajo lock reconstruye idéntico).
6. Frontera #152 intacta para v2 (channel_confirmed sigue fail-closed).

## Modelo de amenazas

El riesgo propio del lote es que la amortización **diluya la gobernanza**:
una política evaluada una vez aplicada distinto a registros distintos, o un
plan cuyo contenido dependa del orden interno de la lista.

## Hallazgos y correcciones

| Hallazgo | Riesgo | Corrección |
|---|---|---|
| B1 — el gemelo evaluado con la autoridad REAL producía `authority_scope_mismatch` (digest del lote ≠ digest del gemelo) | lote inservible; o peor, tentación de comparar contra el gemelo (binding roto) | escalera con autoridad ajustada al gemelo + verificación explícita del digest REAL contra el lote (skip `authority_scope_mismatch`) |
| B2 — `write_commit.py:199` accedía `proposal["record"]` (v1) | KeyError en commit de lote | warning de `record_without_indexable_text` por razón agregada de la decisión (v2), registro único intacto (v1) |
| B3 — orden de validación: intra-lote se chequeaba antes que self-reference; un self-reference también es intra-lote y enmascaraba el código estable | detalle de error inestable para el caller | self-reference primero, luego intra-batch (detalle estable) |
| B4 — ids de registro nuevos que colisionaban con el snapshot en los propios tests de la ronda | tests midiendo `plan_duplicate_id` en vez del contrato pretendido | ids frescos; el guardián por lote queda cubierto explícitamente |

## Verificación de canonicidad / determinismo (comando → resultado)

- Probe end-to-end (store temporal): lote add de 5 → UNA revisión, 5 facts +
  1 evento con `batch_records_sha256` ordenados; supersede por lote committea
  y marca `sustituida`; intra-lote rechazado
  (`supersedes:intra_batch_forbidden`).
- `tests.test_write_batch` → 13 OK (forma, duplicados, intra-lote, mapping
  parcial, self-ref, co-ocurrencia, una-revisión-un-evento, vigencia,
  all-or-nothing con efectos cero, guardián duplicate/target, agregación).
- Dirigidos: 134 OK (write_batch/policy/commit×3/supersede/attest/watermark).
- Frontera #152: el gemelo pasa por `evaluate_write` v1 — `channel_confirmed`
  sigue fallando cerrado a nivel motor para v2 (misma escalera).
- Batería (`results/20261014-222410`): ingest-batch 600 registros, 12
  revisiones, 0,2 s de pared, sin aborto; resto de escenarios sin regresión.
- Gates: check_sizes OK (538; write_policy.py 799), check_plans OK,
  check_adr_registry OK (54).
- Suite completa con Row15: ver línea final del reporte de sesión.

## Límites declarados

- `MAX_BATCH_RECORDS=1000` es constante de perfil; su ajuste futuro es bump
  de fingerprint versionado.
- La celda de lotes no midió escritores compitiendo por lotes (concurrencia
  sigue en vía single): deuda de batería v2.
- El gemelo re-evalúa la escalera con `records[0]`; las razones
  por-registro se agregan después (union) — sin segunda escalera, pero el
  lector debe saber que la decisión por registro vive en la agregación, no
  en N decisiones.

## Decisión

- [x] proceed
- [ ] fix-and-retry
- [ ] escalate
