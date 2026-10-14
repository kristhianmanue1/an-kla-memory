# Ronda adversarial — issue #152: `channel_confirmed` falla cerrado a nivel motor (2026-10-14)

Artefacto atacado: candidato de la rama
`claude/issue-152-channel-confirmed-motor` — gate en `an_kla/write_policy.py`
(`validate_write_authority` + `evaluate_write`, bandera
`channel_confirmed_adapter=false`), fingerprint del perfil
`2d13bb1d` → `21bc0dd3`, tests de rechazo en `tests/test_write_policy.py` y
`tests/test_write_commit.py`, y compactación posterior para volver al
presupuesto de `check_sizes`. Toca `write_policy.py`: ronda obligatoria según
`AGENTS.md`.

Intérprete: `.venv/bin/python` → Python 3.12.12 (regla del maintainer,
2026-10-13: nunca `python3` a secas ni el 3.9 del sistema).

## Alcance

1. Probe conductual end-to-end del hueco original (#152, acta
   `revision-critica-escalado-gobernanza-2026-10-14-adversarial.md` H3):
   `channel_confirmed` autodeclarado vía API Python en plan y commit.
2. Commit con authority intercambiada tras un plan válido, bajo lock, con
   verificación de efectos cero (CURRENT y journals).
3. Control negativo: el camino legítimo (`model_derived` + `summary`) sigue
   committeando.
4. Defense in depth de `evaluate_write` pura.
5. Determinismo del fingerprint del perfil.
6. Diagnóstico del rojo de Row15 (`test_ci_local_both_modes`) que bloqueaba la
   suite completa con el candidato.

## Modelo de amenazas

La frontera memoria-no-es-instrucción no cambia. El riesgo propio del cambio
es el inverso del habitual: que el gate **no cierre nada** (hueco intacto por
una vía lateral) o que **cierre de más** (rompa el camino legítimo de
escritura gobernada). Se ataca con autoridad autodeclarada bien formada —
issuer `channel`, scope correcto, evidencia vacía — exactamente la que el
probe pre-fix committeaba.

## Hallazgos y correcciones

| Hallazgo | Riesgo | Corrección |
|---|---|---|
| H1 — el candidato inicial excedía el presupuesto de `check_sizes` (`write_policy.py` 802 > 800; `test_write_policy.py` 801 > 800): causa raíz del rojo de Row15 (`ci_local` paso 5/7); las sospechas previas (fingerprint viejo `2d13bb1d`, `channel_confirmed` en `scripts/`) se descartaron por grep sin matches | suite completa en rojo con tests dirigidos en verde; diagnóstico abortado previo | compactación de comentarios del propio WIP (797/798 líneas, sin cambio semántico: el fingerprint hashea `_POLICY_CONFIGURATION`, no líneas de archivo); gates re-ejecutados en verde |
| H2 — la rama `skip` del gate interno de `evaluate_write` es inalcanzable por la vía pública: `validate_write_authority()` lanza antes | apariencia de segunda guarda sin cobertura ejecutable hoy | se conserva a propósito como defense-in-depth ante reordenaciones o trabajo futuro del adaptador (#140); declarado aquí, no silenciado |

## Verificación de canonicidad / determinismo

- Probes P1–P5 sobre store temporal desechable (Python 3.12.12):
  - P1 `plan_write` con `channel_confirmed` autodeclarado →
    `WritePolicyError: channel_confirmed_requires_adapter`;
  - P2 commit con authority intercambiada tras plan válido → mismo código,
    CURRENT estable y journals 1→1 (efectos cero);
  - P3 control negativo `model_derived`+`summary` → `committed=True`;
  - P4 `evaluate_write` pura → `raise channel_confirmed_requires_adapter`
    (validate precede al gate interno; ver H2);
  - P5 `policy_fingerprint()` determinista y con el bump (`21bc0dd3…`, no el
    `2d13bb1d…` previo).
- Tests dirigidos: 112 OK (test_write_policy, test_write_commit,
  test_supersede, test_f0_contracts, test_attest).
- Gates: `check_sizes` OK (498 archivos), `check_plans` OK (3 planes),
  `check_adr_registry` OK (51 ADRs) tras la Enmienda ADR-0007.
- Suite completa (discover con Row15 activa, que ejecuta `ci_local` en ambos
  modos): 1174 tests, OK (skipped=74) en 655.95 s con Python 3.12.12
  (`.venv/bin/python`), rc=0.

## Límites declarados

- El gate cierra la **autodeclaración en JSON** ante la API Python. Un caller
  con acceso al proceso puede mutar `_POLICY_CONFIGURATION` o usar
  `MemoryStore.commit()` interna: esa frontera es de integración/hosts, no de
  este cambio (igual que en checkpoint y refute).
- `channel_confirmed_adapter=false` es una constante de perfil, no un
  mecanismo de adaptador: el trabajo real del adaptador del host queda en
  #140.
- La rama skip interna de `evaluate_write` no tiene cobertura ejecutable hoy
  (H2); su prueba es de lectura de código, no conductual.
- La Enmienda ADR-0007 documenta la frontera; no introduce un ADR nuevo ni
  cambia el estado de aceptación.

## Decisión

- [x] proceed
- [ ] fix-and-retry
- [ ] escalate
