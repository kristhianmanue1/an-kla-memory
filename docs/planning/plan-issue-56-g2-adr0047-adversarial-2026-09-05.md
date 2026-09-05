# Ronda adversarial pre-code — ADR-0047 (2026-09-05)

Objeto: `docs/architecture/0047-host-hooks-governed-v1.md` (Propuesta).
Método: atacante de contexto fresco (subagente, sólo lectura), verificación
línea a línea de anclas, ataque por 6 ejes (contradicciones, huecos que
bloquearían F3, doctrina, consumidores, operativa, coherencia con el plan).

## Veredicto: `fix-and-retry` — absorbido

0 BLOCKER; 4 HIGH, 6 MEDIUM, 3 LOW, todos con corrección concreta. Según
el criterio de la ronda (idéntico al patrón de la ronda del plan,
2026-09-01): absorbidos verbatim en el texto enmendado, sin segunda ronda
completa, **condicionados a re-verificación puntual de H1–H4** antes de
firmar F3-A.

## Hallazgos y absorción

| ID | Sev | Hallazgo | Corrección absorbida |
|---|---|---|---|
| H1 | HIGH | `hook_invoked` fabricable sin clave: la lectura no verificaba HMAC/schema | §5 congela verificación en lectura por entrada (schema + canonicidad + HMAC + binding); entrada inválida jamás contribuye al perfil |
| H2 | HIGH | `pending_continuity` sin semántica computable (el motor no observa triggers) | §6 congela definición computable: no-vacío sólo con `required:true` + `material_close_or_handoff` sin run reciente de ese `hook_id`; `indeterminate` con evidencia degradada |
| H3 | HIGH | Umbral de "reciente" circular/sin congelar | §4/§5: `HOOK_RECENCY_HOURS = 24` constante congelada; `--now` inyectable añadido a `integration status` |
| H4 | HIGH | Contradicción: "contrato gestionado no cambia" vs plan F3-D que edita AN-KLA.md | Opción (a): F3-D re-alcanceado a guía de hosts + plantilla, sin tocar `AN-KLA.md` en v1 (Consecuencias/Neutras) |
| M5 | MED | Miscita §11.2 atribuida a ADR-0039/0046 (vive en practicas-ingenieria) | Citas corregidas a `docs/practicas-ingenieria.md` §11.2 |
| M6 | MED | `--on-behalf-of-hook` = canal nuevo sin reconciliar con F0-D3 | §4: canal único declarado, evidencia fuera de `memory/`, sin autoridad, huella `.an-kla/` documentada |
| M7 | MED | "Límites congelados" sin números | §1: ≤16 hooks; id 1–128 `[A-Za-z0-9._-]`; `budget_bytes` 1..1048576; fingerprint `^sha256:[0-9a-f]{64}$`; `required` sólo en `checkpoint` |
| M8 | MED | Mapeo checkpoint incompleto; presupuesto con dos fuentes; punto de acuñación indefinido | §2 argv completo con placeholders; `budget_bytes` de declaración = default, runtime manda; acuñación una vez por flujo, en `commit` |
| M9 | MED | hook-run sin binding de identidad (`project_uuid`/`store_identity`) | §4: campos firmados; lectura rechaza binding mismatch (precedente `attest.py:463-467`) |
| M10 | MED | Lectura degradada, orden/cap de runs, semántica de `run_id` | §5: códigos `hook_run_invalid`/`attest_not_initialized`/`hook_runs_unreadable`; orden por `observed_at` desc, cap 50; `run_id` por motor, reintento = no-op idempotente |
| L11 | LOW | Cita imprecisa de `leftovers == []` | Test de regresión cita `:79` (ausencia de memory) y `:147-152` (propiedad fuerte del CLI) |
| L12 | LOW | Comentario falso en `tests/test_adr_registry.py:27-29` | Test de regresión exige reescritura del comentario (0047 = #56/G2) junto al conteo 3→4 |
| L13 | LOW | `hook-run-v1` sin declaración de publicación; `status` ≠ `integration status` | §4: publicación paquete + espejo + `SCHEMA_FILES` + tupla dorada; §2 declara que la superficie del perfil no es enganchable |

## Re-verificación puntual H1–H4 sobre el texto enmendado (2026-09-05)

- **H1**: §5 "Verificación en lectura (congelado)" — perfil exige por
  entrada schema + JSON canónico + HMAC válido + binding vivo; inválida →
  `hook_run_invalid`, jamás contribuye. ✓
- **H2**: §6 semántica computable referenciada por el campo del payload
  (§5 bloque `host_hooks`). ✓
- **H3**: umbral `HOOK_RECENCY_HOURS = 24` + `--now` en
  `integration status` + ventana compartida por `pending_continuity`. ✓
- **H4**: Neutras re-alcancea F3-D; no queda frase que prometa edición de
  `AN-KLA.md` en esta fase. ✓

## Evidencia de contexto

- `python3 scripts/check_adr_registry.py` durante la ronda →
  `FAIL: 0047 ausente del registro` (esperado: ADR untracked, fila aún no
  creada; se resuelve en el commit de registro).
- Anclas verificadas correctas: `integration.py:74,77`; schema v1
  `:6,:60,:63`; `attest.py:226-228, 89-122, 345-362, 463-467, 485-505`;
  `cli_parser.py:35, 67-77, 119-121, 389-398`; goldens
  `test_integration_status.py:33-44, 79, 147-152`;
  `check_beta15/16_upgrade.py:83`; `test_adr_registry.py:24,30`.
