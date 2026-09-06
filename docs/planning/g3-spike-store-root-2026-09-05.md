# Spike G3 — store_root externo (2026-09-05, read-only)

Insumo de ADR-0048 (issue #57). Ejecutado por subagente explore con
contexto fresco, sólo lectura + stores sintéticos en tmp, siguiendo los
criterios de #57 (matriz de fallos y migración). Veredictos:
**S1 refine · S2 proceed · S3 proceed · S4 refine**. Base: `817c489`.

## S1 — Mapa de acoplamiento → refine

El pivote único es `an_kla/store.py:100`
(`self.root = self.project_root / ".an-kla" / "memory"`): todo lo que
cuelga de `self.root` se re-ancla solo al parametrizar el constructor
(locks `store_locks.py:51,75`, reader gate `reader_gate.py:83,110`,
compaction `compaction.py:148,427,551`, indexes `index.py:55`).

17 módulos/plantillas, ~30 sitios concretos; **10 requieren cambio real**:

1. `store.py:100` — parametrizar constructor (`store_root` opcional).
2. `identity.py:60-70` — anchor de identidad: re-anclar al store_root.
   Crítico: raíces de rechazo de symlinks (`:143-144,158-160,222`) caminan
   hasta `project_root` — raíz equivocada con store externo.
3. `identity_evidence.py:21,112-122,172-221` — receipts de durabilidad con
   rutas relativas validadas contra project_root.
4. `attest.py:35-38,81-96,419,506` — key/whitelist/receipts/nonces viajan
   con el store (F0); 3 anclajes independientes a `store.project_root`;
   `__main__.py:484` pasa project_root crudo a `attest_run`.
5. `hook_runs.py:44,85,105-106,129,143` — ídem F0.
6. CLI `__main__.py:209` + `cli_parser.py:23,479,485` — añadir
   `--store-root` + resolución por defecto.
7. `export_restore.py:84,136,254-264` — publicación hacia store_root.
8. `sealed/bundle.py:551,758-789` — ídem.
9. `mcp.py:344-346,599-600`, `upgrade.py:211` — parametrizar.
10. `startup.py`/`integration.py` + schemas — versiones nuevas (S4).

**Carve-outs sin cambio** (del proyecto, no de la bóveda):
`context_package.py:460,581` + `context_text.py:19,545` (contexto
gestionado), `host_hooks.py:41` (declaración del host),
`docs/hooks-template/pre-commit`, y `indexes/`/`leases/`/`quarantine/`
(no migran). `capabilities.py:249` — 1 línea.

Grueso real: migración (fase dedicada), export/sealed, schemas + goldens
(92 referencias `.an-kla` en tests).

## S2 — Identidad y rutas → proceed (con experimento)

El binding liga **bytes, no rutas**: `read_binding` (`identity.py:139-171`)
valida par UUID/digest de los dos archivos vivos + identity inmutable
content-addressed; `assert_unchanged` (`:174-192`) exige igualdad byte a
byte bajo lock; `store_identity` = digest de los bytes del identity
(`:360`); `project_uuid` es uuid4 puro (`:275`) — sin ruta.

`canonical_project_root_at_init` (`:283`) es dato histórico congelado;
`root_relocated` (`:170`) es telemetría pura. Único gate real
ruta-como-autoridad: `adopt` (`:478-481`), sólo para stores legacy no
adoptados.

**Experimento** (store movido de ruta padre y nombre): `verify` ok con
`root_relocated: true`; `retrieve` ok (misma revisión); mutación vía
`MemoryStore.commit` exitosa (binding intacto); receipts post-move
firmados con binding vivo.

"Cadena nunca es autoridad" en código concreto:
1. Sustituir la igualdad de `adopt` por *relocation receipt* estilo
   `identity_evidence.py` (rutas relativas + fsync + encadenamiento).
2. Re-anclar raíces de `_reject_symlink_path` a la raíz de custodia.
3. `repo_context` queda clasificación, nunca condición de acceso.

## S3 — Migración plan→commit → proceed

**Se mueve** (custodia unificada, contra `_PATTERNS` de
`export_restore.py:27-40`): `memory/` completo (revisions, checkpoints,
segments, refs/CURRENT + ref-log, identities, authority-claims/
-attestations, refutations, compaction/, transactions/) + anchor de
identidad (project-identity.json, identity-intent.json, identity-intents/,
identity-receipts/) + F0: attest.key/whitelist/receipts/nonces + hook-runs/.

**No se mueve**: `indexes/` (derivable), `leases/` (sin referencias),
`quarantine/` (runtime), locks/gates, `context/` (del proyecto),
`host-hooks.json` (del proyecto).

**Maquinaria reutilizable** (sin inventar primitivas):
- restore como plantilla del movimiento seguro: staging + hash-check por
  archivo + `verify()` + `rename_noreplace` (`export_io.py:124-140`) +
  verify final (`export_restore.py:249-309`).
- epoch cut como plantilla del commit bajo locks + journal por etapas +
  receipts durables + reconciliación de replay (`compaction.py:509-675`,
  `:421-463`, `transactions.py:42-118`).
- Migración = copiar→verificar→rename_noreplace→cleanup del origen con
  delete-set + receipt; ventana de crash reducida a un `rename()` atómico.

## S4 — Worktrees y observabilidad → refine

`startup.py:36-44,64-88,91-121,142-143`: `external_memory_evaluated:
false` con comentario que ya anticipaba #57. Regla worktree es prosa
operativa (AGENTS.md), sin enforcement en código.

**Hallazgo duro de congelamiento**: `startup-diagnostic-v1.schema.json:26`
e `integration-status-v1/v2` (`:30`/`:31`) congelan
`external_memory_evaluated: {"const": false}` → G3 requiere
**startup-diagnostic-v2** e **integration-status-v3** (aditivos). Nota v3:
con F0, integration-status mezcla custodias (declaración host-hooks
project-local vs hook-runs store-externas) — v3 debe expresar ambas sin
ambigüedad.

## Riesgos top-5

1. **Migración a medias** — ALTO impacto, precedido: composición
   staging→rename_noreplace→journal→cleanup; crash entre receipt y
   cleanup cubierto por reconciliación probada.
2. **Ruta-como-autoridad residual** — MEDIO/BAJO: sólo `adopt` y el walk
   de symlinks; mitigación relocation receipt + re-anclaje.
3. **Consumers hardcodeados** — MEDIO: interno controlado; churn real =
   92 `.an-kla` en tests/goldens; externo documental.
4. **Custodia partida** (attest con project_root mientras store externo)
   — MEDIO: attest/hook_runs deben tomar el store y fail-closed si las
   raíces divergen.
5. **Contexto gestionado** — CONFIRMADO carve-out: `.an-kla/context/` y
   `host-hooks.json` quedan project-local por diseño.

## Estimación

7 fases: (1) ADR-0048 + adversarial pre-code; (2) núcleo
store/identity/identity_evidence + symlinks; (3) attest/hook-runs/
capabilities; (4) CLI/MCP/upgrade (`--store-root`); (5) `relocate`
plan→commit con tests de crash; (6) startup-diagnostic-v2 +
integration-status-v3 + export/sealed externo + rollback documentado;
(7) baseline completa + concurrencia + ronda adversarial final.
