# Ronda de #181 — status/nu cadena vacía (2026-10-28)

## Objeto y diff

PR #184 (`fix/181-status-vacio-inventario` @ `4752ced`, base `main@c19d207`):
`is_canonical_vigency` deja de tratar la cadena vacía como canónica (opción 1
del issue), de modo que `inventory` cuenta el caso en `no_canonica`,
`verify`/`doctor` lo informan como `noncanonical_vigency` sin perder `ok`, y
refute/supersede/retrieve lo excluyen como ya lo hacían. La política de
escritura v1 no cambia. Cuatro archivos; cero diff en `store.py`,
`retrieval.py`, `index.py`, `write_policy.py` → ronda no obligatoria por el
contrato, ejecutada por prudencia al tocar un predicado compartido con
`verify`.

## Ejecución del revisor (no propio, solo lectura)

- Diff: 4 archivos (vigency.py +8/−4; inventory.py solo comentario; fixture
  #179; test nuevo de #181, 158 líneas).
- Tests objetivo del PR: 31, OK. Suite completa: 1265, OK (skipped=74).
- Experimento con store real fuera del repo: matriz de 10 casos de vigencia
  (`status ""`, `nu ""`, `status None`, campo ausente, `nu "vigente"`,
  `status "vigente"` + `nu ""`, `status ""` + `nu "vigente"`, no escalares),
  invariante `total = suma de buckets`, validación del bucket en
  `inventory-v1`, CLI exit 0, `project_snapshot` tumba el record `""` como
  inactive, store limpio sin claves nuevas.
- Grep de consumidores del predicado: sólo `_physical_status` (inventory) y
  `verify` (store). `context_view` usa lógica propia que ya excluía `""`;
  `doctor`/MCP derivan de `verify`; `export`/`upgrade` tratan el campo como
  informativo.

## Hallazgos y resolución

| id | severidad | hallazgo | resolución |
|----|-----------|----------|------------|
| F1 | media | Enmienda 1 de ADR-0041 y «Diagnóstico de arranque» de uso-diario describen el bucket como «no es cadena ni `null`»; tras el fix la cadena vacía (que sí es cadena) también cae ahí. Precedente #182: enmienda en el mismo PR. | Enmendados ambos documentos en el commit de ronda. |
| F2 | baja | El issue narra la retirada por compactación pero el test nuevo no tenía aserto de tombstone. | `test_compaction_projection_tombstones_empty_vigency` añadido. |
| F3 | baja | `retrieve` sólo ejercitaba `f-empty-status`; sin caso CLI de inventory. | Loop por ambos ids + `test_cli_inventory_reports_noncanonical_bucket`. |

## Veredicto

`proceed` — código correcto, mínimo y coherente con `is_active` en toda la
matriz; suite completa en verde; tests sólidos (revertir el fix los mata). El
hallazgo medio era documental y se resuelve en el mismo PR.

## Gates sobre el commit revisado (`4752ced`)

- Suite `.venv/bin/python` (3.12): 1265 tests, OK (skipped=74).
- `scripts/ci_local.py --simulate-ci`: OK (7/7 pasos; unittest 1265 OK).
- `check_sizes.py` OK; `check_plans.py` OK.
