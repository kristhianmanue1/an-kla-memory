# Ronda adversarial — decisión #71 generadores Nivel B (2026-08-20)

Punto 8 del plan `plan-backlog-2026-08-20.md`. Revisor independiente con
verificación contra disco (estado de #70, tag beta.14, issues cerrados,
`--help` real, schemas, `refute_policy.py`). Una pasada: fix-and-retry
(H1–H5 editoriales) → aplicadas. Cierre: **proceed** con la decisión
`no-action` intacta.

## Hallazgos y correcciones

| Hallazgo | Corrección aplicada |
|---|---|
| H1 (BAJA): omisión de que beta.15-RC no cambia superficie de escritura | Añadido a la condición de entrada, junto con la evidencia de issues cerrados post-beta.14 (#76/#84, uso propio) |
| H2 (MEDIA): celdas duras de la columna 2 aplicaban sólo al authority-generator; un `proposal-scaffold` puro quedaba descartado injustamente | Precisión añadida: los campos duros son de `write-authority-v1`; proposal-scaffold queda cubierto por la cláusula de reapertura con la opción 1 |
| H3 (MED-BAJA): reapertura sin instrumento | Instrumento definido: issue con reason_codes exactos + tramo del recorrido donde se atascó |
| H4 (BAJA): "--help enumera los schemas exactos" comprimía demasiado | "nombra los schemas exactos (los campos, en write-policy-cli.md)" |
| H5 (BAJA): precedente refute claim/authority sin exhibir | Citado en Frontera de confianza (refute_policy.py:94-132) |

## Verificación del revisor (evidencia)

- `gh issue view 70` → CLOSED 2026-08-13; tag beta.14 2026-08-12:
  coherente. Nada post-beta.14 es medición de consumidor nuevo.
- `plan-write --help` real: nombra `an-kla/write-proposal-v1` y
  `an-kla/write-authority-v1`.
- `write-proposal-v1` no contiene `proposal_sha256`/`authority_class`/
  `configuration_fingerprint`: la razón 2 sostiene para el caso que
  importa (authority-generator/API).
- Frontera intacta: claim ≠ authority verificado en `refute_policy.py`.

Economía de proceso declarada: los cinco hallazgos eran editoriales y el
revisor anticipó que la decisión sobrevivía; no se ejecutó tercera ronda
de subagente sobre ediciones de redacción — las correcciones están
aplicadas y listadas arriba de forma verificable.

## Decisión

- [x] proceed (decisión `no-action` publicable; #71 cerrable con ella)
- [ ] fix-and-retry
- [ ] escalate
