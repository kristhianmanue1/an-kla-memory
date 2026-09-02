# Ronda adversarial pre-code — ADR-0046 attest (2026-09-01)

## Alcance

ADR candidata `docs/architecture/0046-attest-local-signed-observation-v1.md`
+ spike S0 + plan #102 §4 (F0). Revisor con contexto fresco, subagente
decorrelado, mandato read-only. Se atacó el mecanismo anti-replay, la
resolución receipt-lookup, la frontera CLI/librería, las superficies no
declaradas (refute), la gobernanza de contratos observables, la semántica
de la whitelist y del receipt, export/restore y el modelo de amenazas.

## Modelo de amenazas

Regla base intacta: la memoria es dato, nunca instrucción. Atacantes
modelo: agente perezoso-honesto que reutiliza receipts (replay), agente
que edita su whitelist, y agente con shell completo (fuera del modelo —
la clave es local y el ADR lo declara). Verificado sin hueco: JSON directo
sigue cerrado (enum v1 sin el kind), checkpoint cerrado por diseño
(F0-D5), MCP read-only, `evaluate*` no consumen authority.

## Hallazgos y correcciones

| Hallazgo | Riesgo | Corrección |
|---|---|---|
| BLOCKER: contradicción temporal del marcador de nonce — §3 marcaba al acuñar ("nace consumido") vs §4 en commit; y la idempotencia same-payload de `write_immutable` (:172-175) permitiría doble gasto silencioso con marcados idénticos | Doble gasto de receipts; anti-replay dependiente sólo del CAS | ADR §3 reescrito: receipt durable content-addressed (mint) **separado** de tombstone de consumo nonce-addressed, **creado —nunca comparado— con O_EXCL bajo `write_lock` tras el CAS**; ventanas de crash documentadas (tombstone sin commit = receipt quemado, fail-closed) |
| HIGH: receipt-lookup sin especificar — evidence porta `{id, sha256}` pero la única ruta era por digest del nonce; `receipt_id` ni siquiera estaba en el schema del ADR | Verificador incapaz de localizar el receipt; plan-write sin nada que leer | §3/§4: direccionamiento determinista `receipts/receipts/sha256/<digest-canónico>.json` (localizable por el `sha256` del evidence) + tombstone por nonce; `receipt_id` explícito en schema; archivo ausente → `receipt_invalid` |
| HIGH: verificación sólo en capa CLI — la API Python consume authority sin pasar por `_cli_authority`; el ADR afirmaba "el agente nunca fabrica la clase" sin acotar a CLI (y ADR-0047 consumirá la librería) | Hueco de enforcement percibido como absoluto | ADR §Decisión: frontera explícita (CLI = enforcement; API Python = caller-trusted, AN-KLA.md:180-181) + re-verificación y marcado de tombstone movidos al engine (`commit_write_plan`, bajo lock) como defense-in-depth |
| MEDIUM: superficie refute no declarada — `refute` acepta `tool_observed` como clase privilegiada vía resolver y no pasa por `_cli_authority`; nada impedía "conectar" attest al resolver después | Elevación futura sin ADR | §7: receipts attest NO alimentan `refute-authority-claim-v1` en v1; refute sigue resolver-gated; test de regresión prescrito |
| MEDIUM: contradicciones de contrato post-attest — `privileged_authority_requires_external_adapter: true` y AN-KLA.md:213-216 se vuelven falsos para tool_observed; mecanismos §11.1/§11.2 citados pero no escritos | Contratos mentirosos tras el release | §8: flip/re-scoping del flag, `cli_authority_classes` condicionado, bloque `attest`, mecanismos §11.1 (whitelist observable) y §11.2 (regla aditiva) escritos in-situ; AN-KLA.md §Resolver autoridad obligatorio en S2 |
| MEDIUM: whitelist con matching indefinido y set inicial peligroso bajo prefijo (`git diff --output=`, `--ext-diff` ejecuta config; `unittest` ejecuta código); falta código para whitelist editada entre plan y commit | "Sólo-lectura" como promesa falsa; edición sin detección | §2: matching **exacto de argv completo** + denylist explícita; garantía renombrada "procedencia de ejecución, no pureza"; `receipt_whitelist_changed` fail-closed + test |
| MEDIUM: semántica del receipt incompleta (exit_code != 0, timeout, output grande/binario, reloj, receipt vs fingerprint vigente) | Goldens no deterministas; `unittest` colgado; campos decorativos | §3: exit_code==0 exigido para autoridad; timeout duro con `attest_timeout`; hash streaming con cap + `truncated`; reloj/uuid inyectables; `policy_fingerprint` viejo → `receipt_invalid` (receipts mueren con cada bump, aceptado) |
| LOW: receipts tras export/restore no re-verificables (clave local); aserción del roundtrip ambigua | Expectativa falsa de re-validación | §6: declarado; test afirma el fallo cerrado, no la re-validación; receipts extranjeros inertes por binding |
| LOW: squatting de nonces sin clave (O_EXCL puro) → self-DoS de un nonce | Menor; dentro del modelo de amenaza | Conflicto O_EXCL en camino attest → código estable (`receipt_replayed`), sin quarantine-retry; documentado |

## Verificación de canonicidad / determinismo

- `policy_fingerprint` determinista y comparado en plan (`_verified_decision`)
  y commit bajo lock — ✓ (write_policy.py:51-91,:508-509; store.py:357-362).
- HMAC sobre canonical-json reproducible **condicionado** a reloj/uuid
  inyectables — especificado ahora en §3 (era ✗ en la candidata).
- `write_immutable` O_EXCL + fsync crash-safe para el receipt durable ✓;
  su idempotencia same-payload prohibida como marcador de consumo (BLOCKER).
- CAS triple + `mutation_preflight`/`assert_unchanged` cubren el binding
  vigente en commit ✓; la verificación de receipt en commit ahora dentro
  de esa sección crítica.

## Límites declarados

- Revisor read-only: no ejecutó suite ni probes (evidencia archivo:línea).
- `refute_contracts.py` leído por muestreo (fail-closed asumido por
  construcción: `resolver_required` + CLI sin resolver).
- `mcp.py` no auditado herramienta por herramienta (confía en
  `read_only: True` declarado); `sealed/bundle.py` como segunda vía de
  restore no revisado; rutas de receipts en Windows/NT no analizadas.
- Goldens que congelan fingerprints no enumerados uno a uno (churn
  asumido por el plan de release).

## Decisión

- [ ] proceed
- [x] fix-and-retry — **absorbido**: las 9 correcciones quedaron
  integradas en ADR-0046 el 2026-09-01. El ADR corregido queda listo para
  la orden de implementación S2 (fases a–h del spike, con el §8 de
  gobernanza en el mismo PR); la implementación llevará su propia ronda
  adversarial de fase y el release la ronda REL.
- [ ] escalate
