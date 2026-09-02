# Arquitectura propuesta — puntero

> Este archivo nunca desarrolla arquitectura nueva aquí (norma:
> `../docs/estandar-diseno-software-github.md` §3.5 — ruta relativa a
> `.skevi/`). Es un índice hacia los ADRs del proyecto.

**Estado:** con ADRs — 45 decisiones registradas (ver ADR-0045).

## ADRs del proyecto

- Índice y estado canónico: [`docs/README.md`](../docs/README.md) — tabla
  verificada en CI por `scripts/check_adr_registry.py`.
- Textos: [`docs/architecture/`](../docs/architecture/).

Subsistemas nucleares (entrada rápida, no lista exhaustiva):

- `0001-revision-commit` — formato físico: revisiones content-addressed y `CURRENT`.
- `0007-write-policy-v1` — política de escritura gobernada (`plan-write` → `commit-write-plan`).
- `0022-store-project-identity-v1` — identidad lógica de store y proyecto.
- `0042-sealed-export-v1` — export sellado con adaptador externo de claves.
- `0043-store-threat-model-v1` — modelo de amenazas del store (A1–A4).
