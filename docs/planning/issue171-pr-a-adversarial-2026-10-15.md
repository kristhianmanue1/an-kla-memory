# Ronda adversarial de #171 PR A (DX del consumidor, sin plantilla)

Rama `fix/171-dx-errores-consumidor`. Dos rondas con revisor de contexto
fresco (subagente `Explore`, sólo lectura, experimentos en `/private/tmp`).
Suites con Python 3.12.12 explícito en venv con extras `test` y `sealed`.

## Alcance

`resume.py` (mínimo en `budget_too_small_for_resume_snapshot`),
`__main__.py`/`identity.py`/`transaction_attempts.py`/`cli_parser.py`
(`invalid_transaction_id`), `update_check.py` (aviso), `status` (`runtime`).
No toca `store.py`, `retrieval.py`, `index.py`, `write_policy.py` ni el
contrato gestionado: `TEMPLATE_VERSION` intacto.

## Modelo de amenazas

Los mensajes de error y `runtime` no repiten entradas del caller ni rutas
(§11.1). `minimum_budget_bytes` es metadato de tamaño, no contenido.

## Ronda 1, pre-code: `fix-and-retry`

| Hallazgo | Riesgo | Corrección |
|---|---|---|
| BLOCKER P4: versión mayor declarada en AGENTS.md silenciaría `managed_contract_modified` | Ocultar ediciones del contrato | Diferido a PR B: diagnóstico `unverifiable`, `ok:false` |
| MAJOR P1: mínimo medido a otro budget no es el mínimo (ancho decimal, `retrieve(budget)`) | El reintento falla | Proyección completa por candidato, bandas como ADR-0034 |
| MAJOR P2: `init` emite el código vía `IdentityError` con exit 1 y sin pista | DX inconsistente | Rama común, exit 2, predicado `is_canonical_uuid` compartido |
| P3: imponer `uv tool` contradice README:20-22 e inventario (31 venvs pip) | Regresión para venvs | Aviso con ambas formas; invocación de la plantilla sin cambios |
| P1(b) toca `DETAILED_CONTRACT` | Falso `managed_contract_modified` | Movido a PR B |

## Ronda 2, sobre `8d5f3c9`: `fix-and-retry`

| Hallazgo | Riesgo | Corrección |
|---|---|---|
| MAJOR: sin salida temprana, el error de `resume` probaba todos los candidatos (20k: 0,15 s → 15 s) | Error lento en stores grandes | Salida temprana si root/snapshot no caben; 20k: 4,5 s con budget 4096 (≈ resume exitoso en N), 9 s con 15000 (dos proyecciones completas, ver ronda 3) |
| MINOR: tests `--query` sin registros | Evidence no ejercida | Store con 12 facts que casan; guarda de coste sobre llamadas a `retrieve` |
| MINOR: test de bandas no discriminante | Falsa cobertura | Casos con salto de banda y no monótono |
| MINOR: `entrypoint` por `argv[0]` | Etiqueta errónea en `-c`/embebido | `__main__.__spec__`; tercer valor `embedded`; tests de los tres |
| MINOR: Enmienda 1 imprecisa sobre lo que revela N | Documentación | Redacción corregida |

Salida exitosa de `resume` byte a byte igual a la base en 2040
combinaciones (legacy v1/v2, 0/5/60 facts, con/sin query, perfil index).

## Ronda 3, re-verificación de `625cd89`: `fix-and-retry` sólo en tests

| Hallazgo | Estado | Corrección |
|---|---|---|
| Salida temprana | Resuelto: 2040 combinaciones byte a byte iguales a la base; ningún budget en `[N-150, N)` cabe | — |
| Guarda de coste no mata al mutante sin salida temprana | Corregido | Cuenta `_size_at_fixed_point` con 200 facts: corregido 406, mutante 606 > cota 407 (`AssertionError: 606 not less than or equal to 407`) |
| Dos proyecciones completas cuando el contador `excluded_summary.budget` gana un dígito (15000 → 9 s) | Declarado | Consecuencia de la reserva del peor diagnóstico no implementada; N sigue siendo mínimo |
| Bandas sin caso que las exija | Aceptado | Defensa, misma regla que ADR-0034 |
| `entrypoint`, Enmienda 1 | Resueltos | — |

Suite completa `.venv/bin/python` 3.12.12: 1220 tests OK (skipped=5);
`ci_local --simulate-ci` OK.

## Límites declarados

- `relocate` conserva `relocate_transaction_invalid` (exit 1, sin pista):
  contrato propio v4; sólo cambia el help.
- Un intent de identidad corrupto en disco (`identity.py`, lectura) también
  muestra la pista y exit 2; improbable (digest), no se separa aquí.
- `runtime` aún no está documentado en el contrato: PR B.
- La reserva del peor diagnóstico de ADR-0023 sigue sin implementar
  (declarada en la Enmienda 1); cuesta una segunda proyección completa en el
  error. Saltar el `deepcopy` de candidatos que no caben queda como mejora
  opcional, no aplicada sin verificar que la evidence añade ≥ `cost_bytes`.
- El mínimo es exacto si el tamaño crece con el budget; si no, es un budget
  verificado que cabe (misma regla que ADR-0034).

## Decisión

- [x] proceed: el revisor condicionó el `proceed` a que la guarda de coste
  matara al mutante; verificado arriba.
- [ ] fix-and-retry
- [ ] escalate
