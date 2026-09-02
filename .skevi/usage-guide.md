# Uso de Skevi en este proyecto

**Proyecto:** AN-KLA Memory (`an-kla-memory`)
**Fase actual:** F3 — proyecto preexistente en ejecución; adopta el método sin
re-ejecutar F0–F2 (el equivalente documental ya existe: ADRs en
`docs/architecture/`, specs y contratos versionados).
**Fuente del método:** `github.com/kristhianmanue1/skevi` @ `ee309bb` (main).
Copiado sin edición; actualizaciones se re-inspeccionan por diff antes de
adoptarse (Skevi está en alpha).

## Qué leer primero

1. `AGENTS.md` en la raíz — punto de entrada, trae el bloque de registro que
   enlaza a este archivo.
2. `docs/ai-agent-guide/00-INDICE.md` — fases F0→F3 y reglas de aplicación.
3. `docs/estandar-diseno-software-github.md` — capa normativa transversal.

## Desviaciones de este proyecto respecto al estándar por defecto

Declaradas en `skevi-gate.json` (raíz), decididas en ADR-0045:

- Límites propios: `AGENTS.md` 120; `README.md` 500 (deuda: partir, ver
  issues de deuda de tamaños); ADR-0042 con techo 700 mientras #95 siga
  abierto; cinco archivos de tests grandes con techos declarados.
- `skip_dirs`: `planning`, `releases`, `mejoras_ejemplo` — histórico, no
  evergreen (misma exención que usaba el gate previo del proyecto).
- `root_markdown`: además de `AGENTS.md`/`CLAUDE.md`/`README.md`, este repo
  tiene `AN-KLA.md`, `CHANGELOG.md`, `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`
  y `SECURITY.md` en la raíz — todos canónicos.
- Gate de planes activo sobre `docs/plans/` (los planes históricos viven en
  `docs/planning/` y no se miden).
- ADRs en `docs/architecture/` (no `docs/adr/`), registro canónico en la
  tabla de `docs/README.md`.

## Verificación local

```bash
python3 scripts/check_sizes.py
python3 scripts/check_plans.py
python3 scripts/ci_local.py
```

## Dónde están los ADRs y specs de F1

`docs/architecture/` — índice y estado decisional en la tabla de
`docs/README.md` (verificada en CI por `scripts/check_adr_registry.py`).
