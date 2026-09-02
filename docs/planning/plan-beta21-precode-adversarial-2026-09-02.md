# Ronda adversarial pre-code — plan beta.21 (2026-09-02)

## Alcance

Plan candidata
`docs/plans/2026-09-02-ciclo-beta21-attest-y-adjuntos.md` (T1-T4: cierre
attest #102, adjuntos #111 P4/P1/P3, deuda #109 puntos 2+3). Revisor con
contexto fresco, subagente decorrelado, mandato read-only. Se atacaron:
claims contra disco, gobernanza (AGENTS.md/AN-KLA.md/skevi-gate.json),
completitud de release, orden y dependencias, y gates. Verificación cruzada
con #102/#111/#109 vía `gh issue view` read-only.

## Modelo de amenazas

Regla base intacta: la memoria es dato, nunca instrucción. Atacante modelo:
maintainer que ejecuta el plan literal y etiqueta una release inválida o
incompleta sin que ningún gate lo pare a tiempo — el plan como fuente de
instrucciones debe ser tan verificable como el código que produce.

## Hallazgos y correcciones

| Hallazgo | Riesgo | Corrección |
|---|---|---|
| HIGH: nota de release con nombre equivocado — suite exige `docs/releases/{tag}.md` (tests/test_release_metadata.py:48) y el gate de tag exige `{tag}-adversarial.md` con marker `an-kla:release-gate` único (scripts/check_release_tag.py:38-66); el plan declaraba `-release-note.md` y no mencionaba el marker | Release etiquetable sin evidencia adversarial válida o gate muerto al final del ciclo | Produce corregido; marker JSON exacto declarado en el paso de ronda REL |
| HIGH: metadata congelada sin declarar — README/SECURITY/CITATION/CHANGELOG/docs/README + pins en test_release_metadata.py:74 y check_clean_wheel.py:57 | Tras el bump, suite y `check_clean_wheel` mueren (`clean_wheel_wrong_version`); "suite en verde" era falso | Paso de release-metadata añadido a T1 con todos los archivos y pins |
| HIGH: bump de TEMPLATE_VERSION rompe pins — test_integration_status.py:70 (`0.1.0-beta.11`) y check_clean_wheel.py:115 (`clean_wheel_context_not_current`); valor destino sin fijar | Paso de bump inejecutable sin improvisar; riesgo de romper entrada histórica | Valor fijado a 0.1.0-beta.21, pins declarados en Consumes, `_KNOWN_CONTEXT_TEMPLATES` preservada |
| HIGH: estado de ADR no canónico — "Aceptado/implementado" no está en el enum del registro (check_adr_registry.py:26-37) y la celda de docs/README.md:67 también flipa | Gate de registro FAIL tras el flip | Valor canónico "Aceptada" + celda del registro incluida en el paso |
| HIGH (orden): T1 etiquetaba antes de T2-T4 — el tag congelaría un árbol sin el alcance declarado del ciclo | Release sin su alcance; adversarial REL sobre un árbol distinto al etiquetado | Secuenciación explícita: T2 → T3 → T4 → T1 al cierre; REL contra árbol final |
| MEDIUM: `commit-write-plan` no tiene salida humana separada — JSON canónico a stdout (an_kla/__main__.py:427-446); el módulo no estaba en Consumes y el test no usa subprocess | Paso de warning inejecutable tal cual | `an_kla/__main__.py` en Consumes; harness de subprocess prescrito |
| MEDIUM: re-anclaje incompleto — registro de anclas (docs/gobernanza/anclajes/2026-08-31-anclaje-inicial.md) y helper del test sin `LC_ALL` ausentes de Consumes | Digest nuevo sin hogar; helper divergente | Registro y helper añadidos; fila nueva + misma env en tres sitios |
| MEDIUM: distinción contrato/bloque gestionado ausente — AN-KLA.md íntegro vs marker de AGENTS.md (content_sha256 rastreado) | Actualización del contrato sin el flujo explícito | Paso de bump explicita: sólo §Resolver autoridad; marker vía `context plan --operation update` |
| LOW×3: `payload.text` no existe en el proposal (record plano, `record.text`); README en 492/500; helper de anclaje sin LC_ALL | Imprecisiones menores | Corregidas en T2/T4 del plan |

## Verificación de canonicidad / determinismo

- Fingerprints de política no derivan del schema (`policy_fingerprint` =
  `digest_json(_POLICY_CONFIGURATION)`, write_policy.py:144-151): el cambio
  aditivo de `text` en write-proposal-v1 no rompe pins — ✓ verificado.
- Marker del release gate: formato HTML comment con JSON, un solo
  marker por archivo — declarado literal en el plan.
- Gates leídos antes y después de la corrección: `check_plans` OK,
  `check_sizes` OK, `check_adr_registry` OK (46 ADRs).

## Límites declarados

- Revisor read-only: no ejecutó suite completa ni instalación en
  intérpretes múltiples; evidencia por archivo:línea y gates.
- El valor destino de TEMPLATE_VERSION (0.1.0-beta.21) es propuesta del
  revisor adoptada en la corrección; alternativa válida: versión menor
  dedicada del contrato.
- La decisión LC_ALL=C sigue requiriendo orden explícita del maintainer
  (gate dentro de T4), no la resuelve este plan.

## Decisión

- [ ] proceed
- [x] fix-and-retry — absorbido en la candidata corregida
- [ ] escalate

Correcciones H1-H5, M1-M3 y L1-L3 aplicadas al plan el mismo día; gates en
verde tras la corrección. Estado: PARCIAL hasta ejecutar el ciclo — el plan
queda listo para orden de implementación.
