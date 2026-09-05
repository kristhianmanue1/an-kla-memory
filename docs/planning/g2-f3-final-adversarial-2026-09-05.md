# Ronda adversarial final — G2 F3 (2026-09-05)

Objeto: implementación G2 completa, commits `85214b8..HEAD` (F3-A/B/C/D).
Criterio de aceptación de #56: ronda final con evidencia antes de cerrar.
Método: atacante de contexto fresco (sólo lectura); lectura del diff
completo, 6 scripts de ataque con stores tmp y CLI real, validación
jsonschema de los 3 schemas, concurrencia con 8 procesos, escala (3.003
entradas + entrada de 120 MB), permisos 000, replay de la guía.

## Veredicto: `fix-and-retry` — absorbido y re-verificado

3 HIGH, 2 MEDIUM, 4 LOW. Sin defectos de doctrina: el rango no toca
`store.py`/`write_policy.py`/`checkpoint_policy.py`/`retrieval.py`/
`index.py`; ningún camino de hook fabrica autoridad; invocación plana
deja CERO archivos; stdout jamás contaminado; sin recursión; O_EXCL
intacto bajo concurrencia.

## Hallazgos y absorción

| ID | Sev | Hallazgo | Absorción |
|---|---|---|---|
| H1 | HIGH | Run reciente de hook desconocido inflaba `observed_profile` (viola §5) | Filtro `recent_ids ∩ declared_ids`; test de regresión |
| H2 | HIGH | `indeterminate` con lectura limpia y evidencia vieja (viola §6) | `indeterminate` sólo con `degraded` no vacío; test de regresión |
| H3 | HIGH | OSError al acuñar crasheaba el comando ya exitoso y filtraba ruta | `except OSError` con código estable `hook_run_unwritable` sin rutas; test de regresión |
| M1 | MED | `hook_runs_unreadable` inalcanzable (glob tragaba PermissionError) | `os.scandir` con captura explícita; directorio inexistente = lectura limpia |
| M2 | MED | Lectura sin tope (escaneo total + `read_text` sin límite) | Cap 64 KiB por entrada (`hook_run_invalid`) + cap 2000 entradas (`hook_runs_truncated`) |
| L1 | LOW | Flag fantasma `--on-behalf-of-hook` en `integration status` (se acepta y se ignora) | Flag retirado de ese parser (la superficie no es enganchable, §2) |
| L2 | LOW | Oración falsa de idempotencia en la guía | Redacción corregida: cada flujo = `run_id` nuevo; mismo `run_id` = no-op |
| L3 | LOW | Lectura no validaba `observed_at`/`exit_code` contra el schema | Validación en lectura: fecha parseable + exit_code 0..255, si no `hook_run_invalid` |
| L4 | LOW | `.reader-gate` creado por `status` (pre-existente, fuera del rango) | Sin cambio; anotado como hallazgo histórico, no regresión F3 |

## Re-verificación post-parche

- Tests de regresión H1/H2/H3 añadidos a `tests/test_hook_runs.py`
  (16 pruebas del módulo, 30 con superficie v2): todos en verde.
- Corrección adicional destapada por el parche: `scandir` sobre
  directorio inexistente = sin runs con lectura limpia (no degradación).
- Suite canónica: **976 tests OK** (510s, 5 skips).
- `check_sizes`/`check_plans`/`check_adr_registry` OK.
