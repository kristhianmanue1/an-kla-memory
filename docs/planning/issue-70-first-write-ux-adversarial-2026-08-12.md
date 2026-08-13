# Ronda adversarial local — issue #70, primer write Nivel A

> **Estado:** `proceed`
> **Fecha:** 2026-08-12
> **Alcance:** ayuda CLI, detalles saneados de errores y guía de escritura;
> sin cambios de schema, policy, storage ni contrato gestionado

## Invariantes atacados

- `plan-write → commit-write-plan` y la separación de autoridad no cambian.
- Los códigos `input_json_*` y `write_plan_base_changed` permanecen estables.
- Los details humanos no filtran rutas, payloads, secretos ni contenido JSON.
- Un JSON no puede acuñar `tool_observed` ni `channel_confirmed`.
- La guía no recomienda hashes falsos ni presenta marcadores como valores.
- Cada commit mueve `CURRENT`; un plan obsoleto no se fuerza ni reutiliza.
- `--help` no lee memoria, red, reloj ni archivos de usuario.

## Intento 1 — `fix-and-retry`

1. **MEDIUM:** `argparse` partía los identificadores
   `an-kla/write-{proposal,authority}-v1` por el guion. Se aplicó formatter que
   conserva el texto exacto.
2. **HIGH:** ayuda y guía llamaban `current_revision` al campo de `status`; el
   payload real usa `revision`. `current_revision` pertenece al planning result.
   Se corrigieron ambos textos y se añadió aserción focal.
3. **LOW:** faltaba cubrir el rol `planning_result` cuando su archivo no puede
   leerse. Se añadió prueba de exit 2 sin path.

## Intento 2 — `proceed`

Sin hallazgos restantes:

- roles expuestos: constantes `proposal|authority|planning_result`;
- JSON inválido no expone payload y JSON ilegible no expone path;
- `write_plan_base_changed` conserva el código y añade únicamente
  `refresh_status_and_replan` en la presentación CLI;
- los demás callers de `_json()` no reciben role y conservan su stderr previo;
- el ejemplo calcula `digest_json` sobre objetos parseados y describe el
  fingerprint como binding autodeclarado, nunca prueba de autoridad;
- no se modificaron `write_policy.py`, `store.py`, schemas ni fingerprints.

## Evidencia

- baseline focal: `python3 -m unittest tests.test_write_commit` → 28 tests,
  `OK`.
- candidato final focal: mismo comando → 32 tests, `OK`.
- `python3 -m an_kla plan-write --help` → schemas y origen de revisión visibles.
- `python3 -m an_kla commit-write-plan --help` → planning result exacto y
  secuencialidad visibles.
- `git diff --check` → sin salida.
- `python3 scripts/check_sizes.py` → `check_sizes: OK`.

Esta ronda fue realizada por el agente implementador; no se presenta como
revisión independiente. El CI local completo sigue siendo gate previo al push.
