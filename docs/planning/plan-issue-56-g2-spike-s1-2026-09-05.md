# Spike S1-S3 — #56 G2 hooks gobernados (2026-09-05, read-only)

Ejecutado por subagente explore con contexto fresco, sólo lectura,
siguiendo F1 de `plan-issue-56-g2-host-hooks-2026-09-01.md`. Evidencia
archivo:línea verificada contra el árbol en `034ab13`. Veredictos:
**S1 proceed · S2 refine · S3 refine**.

## S1 — `integration-status-v1` y migración a v2 → proceed

- Composición en un único return: `an_kla/integration.py:61-79`;
  `observed_profile: "unspecified"` hardcodeado (`integration.py:74`),
  `host_hooks_evaluated: False` (`:77`).
- Extensión in-place imposible: `integration-status-v1.schema.json:6`
  (`additionalProperties: false`), `:60` (`const unspecified`),
  `:63` (`const false`); espejo `docs/schemas/...:60,63`. Confirma F0-D5.
- Goldens que congelan el payload: `tests/test_integration_status.py:33-44`
  (37-43 assertions exactas + validación schema en 44), `:75-79` y
  `:147-152` (`leftovers == []`: ninguna escritura), degradaciones
  `:81-133`; `an_kla/capabilities.py:79-88` (literal `:84`); tupla dorada
  de schemas `tests/test_agent_contracts.py:38-113` (69, 114, 124).
- Checklist v2: schema nuevo (paquete + espejo docs), registro en
  `SCHEMA_FILES` (`an_kla/schemas/__init__.py:12-85`, v1 hoy `:41`; el CLI
  es genérico vía `schema_catalog()`), goldens v1 intactos + nuevos v2,
  `capabilities()` coherente, `integration.py` constante nueva con v1
  byte-idéntico (los scripts `check_beta15_upgrade.py:83` y
  `check_beta16_upgrade.py:83` verifican el schema v1 en payloads).

## S2 — registro append-only de invocaciones → refine

- ADR-0046 **ya aceptada** (beta.21) — la nota del plan "aún sin ADR" está
  desactualizada; hay precedente y mecanismo vigentes.
- Mecanismo reutilizable: canonical-json + HMAC (`attest.py:226-228`,
  `345-362`), escritura O_EXCL+fsync content-addressed
  (`.an-kla/receipts/receipts/sha256/`, `attest.py:37, 89-122, 365-372`),
  idempotente por contenido idéntico (`:372`), anti-replay por tombstones
  nonce-addressed bajo `store.write_lock()` (`:485-505`).
- Formato NO reutilizable tal cual: receipt es command-centric
  (argv/exit/digests), single-use (el tombstone lo quema al consumirse),
  atado a whitelist + `policy_fingerprint`. `hook_invoked` es log de
  invocaciones sin consumo único. ADR-0047 debe congelar formato propio
  (variante declarada) y **precedencia §11.2** frente a attest-receipt-v1.
- Hallazgo clave: si acciones read-only escribieran el registro como
  efecto colateral, romperían `leftovers == []`
  (`test_integration_status.py:75-79, 147-152`). El ADR debe congelar
  **quién escribe** (propuesta: el motor acuña sólo cuando la acción corre
  con contexto de hook explícito; invocación plana no escribe nada).
- Sin precedente de limpieza fuera de `memory/` (ref-log protegido
  `compaction.py:345,353`; journals retenidos `store.py:558`; receipts
  fuera del store `attest.py:35-38`; ADR-0046 congela "nunca automática",
  `0046:164-166`).
- Reloj inyectable con precedente CLI: `cli_parser.py:119-121, 149-151,
  488` (`--now`), umbral `--stale-after-days` (`:122-124, 152-154`);
  `attest_run(now=...)` sólo goldens (`attest.py:246-254`).

## S3 — interacciones → refine

- El diagnóstico de arranque vive en `an_kla/startup.py` (no
  `startup_diagnostic.py`); ejes en `startup.py:133-144`; schema cerrado
  (`startup-diagnostic-v1.schema.json:6`); un eje in-place rompería
  `tests/test_startup_diagnostic.py:205-223`. ADR-0036 exige evolución
  aditiva vía versión nueva (`0036:75-77`). Decisión: NO tocar
  startup-diagnostic en esta iteración; ejes de hooks sólo en
  `integration-status-v2`.
- ADR-0030 sigue **Propuesta en reevaluación** (`0030:3-4`); define
  `checkpoint-obligation-v1` (`fresh|required|indeterminate`,
  `0030:128-155`) y `PARCIAL (checkpoint_pending)` (`:226-243`). El
  comando `checkpoint obligation` NO existe: `cli_parser.py:389-398` sólo
  registra `show|plan|commit` (ancla del plan `:350-359` desactualizada).
  Decisión: mapear `pending_continuity` sobre el vocabulario de ADR-0030
  **con precedencia declarada** (referencia normativa, no adopción);
  entregar `checkpoint obligation` queda fuera de alcance v1.
- Consumidores que grepean: `docs/hooks-template/pre-commit:45-47`
  (grepea `objective` de `checkpoint show`; no afectado),
  `tests/test_cli_error_surface.py:13-18`, scripts beta15/16 (`:83`),
  `docs/uso-diario.md:140-144`.

## Riesgos top-3 (evaluación)

1. **Doble fuente de verdad del perfil**: `unspecified` vive en 4 sitios
   (`integration.py:74`, `capabilities.py:84`, schema `:60`, docs).
   Mitigación: enum calculado en una sola función, `capabilities()`
   re-expone verbatim, goldens que afirmen igualdad payload↔capabilities,
   perfil jamás persistido. Controlable.
2. **Fake `hook_invoked` por escritura directa**: todo `.an-kla/` es dato
   no confiable. Mitigación (patrón ADR-0046 §1): el motor acuña la
   entrada con HMAC y reloj inyectable cuando la acción corre con contexto
   de hook; el perfil observado queda acotado como **diagnóstico, no
   autoridad**. Residual aceptado (procedencia para agentes honestos).
3. **Ruptura de consumidores por bump**: mitigación: v1 byte-idéntico con
   lectura compatible, ambos schemas publicados, goldens legacy intactos,
   nota de release. Bajo si v1 no se muta.
