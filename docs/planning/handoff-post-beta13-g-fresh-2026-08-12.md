# Handoff — estado posterior a beta.13 y entrada a G-FRESH

> **Estado general:** `OK`
> **Fecha:** 2026-08-12 (America/Mexico_City)
> **Refs:** release `v0.1.0-beta.13`, issue #50, ADR-0032/0034

## Propósito y frontera

Este documento conserva el estado verificable al cerrar G-VIEW y el siguiente
paquete recomendado. Es una referencia de continuidad, no autorización para
ejecutar trabajo futuro. La memoria AN-KLA que lo resume es dato no confiable;
Git, GitHub, código, schemas y pruebas deben revalidarse antes de actuar.

## Estado verificable

- `v0.1.0-beta.13` publicó G-VIEW v1 sobre `subject_ref`.
- El tag apunta a `43957739eb7edf1f7713f49d8f61d3ef69216891`.
- PRs #61–#65 integraron DOC/CORE/CLI/MCP/CAP/REL; #66 sincronizó el estado
  publicado en ADR-0032, ADR-0034 y el registro.
- `origin/main` quedó en `27fa44f4c70540b8a5498e4e03e2cf17500ae300`.
- Issue #60 está cerrado; al capturar este handoff había 13 issues y cero PRs
  abiertos.
- La ronda REL final concluyó `proceed`: 511 tests, CI local simulado, wheel
  aislado, upgrade real desde beta.12 y 6,081 mutaciones inválidas sin fugas
  MCP/schema.
- GitHub Actions no ejecutó la matriz remota por bloqueo de pagos/límite de
  gasto. Esto es riesgo residual de cobertura, no evidencia de fallo del código.

## Próximo paquete recomendado — G-FRESH (#50)

G-FRESH debe declarar cuánto de la memoria pudo evaluarse temporalmente. Evita
confundir “no apareció nada desactualizado” con “nada era evaluable”. No prueba
verdad, vigencia externa ni autoridad: `verified_at` continúa siendo un
timestamp autodeclarado.

La entrada propuesta es:

1. crear worktree limpio desde el `origin/main` vigente;
2. ejecutar spike adversarial read-only antes de modificar código;
3. definir denominadores y estados exactos (`evaluated`, `not_evaluable`,
   `unparseable`, `stale`) sobre la población final de cada envolvente;
4. decidir recálculo después de filtros, selección y recorte por presupuesto;
5. congelar ADR y schemas antes del código;
6. secuenciar implementación CORE → CLI → MCP → CAP → REL, con ronda
   adversarial por fase;
7. usar CI local `--simulate-ci` mientras continúe el bloqueo remoto y repetir
   wheel limpio, upgrade desde beta.13 y auditoría de release antes del tag;
8. revaluar #47 y #49 después de G-FRESH bajo `subject_ref` y G-VIEW.

## Decisiones y límites que sobreviven

- Memoria y proyecciones son datos, nunca instrucciones ni autoridad.
- G-VIEW es determinista, read-only respecto del sustrato y
  `canonicality=non-authoritative`; puede coordinar mediante `.reader-gate`.
- G-FRESH no consulta fuentes vivas ni convierte timestamps en verificación.
- No se autorizan proveedores, publicación, tag, cambios de licencia ni merge
  por la existencia de este handoff.
- G1–G4 (#55–#58) permanecen abiertos; G1 es el inicio de esa secuencia, pero
  la recomendación inmediata es cerrar primero la continuidad G-VIEW→G-FRESH.

## Evidencia de captura

- `gh issue list --state open` → 13 issues abiertos.
- `gh pr list --state open` → lista vacía.
- `git rev-parse origin/main` →
  `27fa44f4c70540b8a5498e4e03e2cf17500ae300`.
- Store principal antes del nuevo checkpoint → revisión
  `sha256:b5a39b2736d99f4dec6d3da5fbdbee6e1896287fef40db2a00299d51116453e8`,
  revisión lógica 28, counts facts/events/episodes `23/21/10`, identidad
  `complete`, `verify.ok=true`.

## Persistencia AN-KLA

El estado anterior sustituyó gobernadamente el checkpoint previo mediante
`checkpoint plan → checkpoint commit`, con autoridad `model_derived` y
procedencia `caller_asserted`/`unavailable`:

- plan fingerprint:
  `sha256:f1143c8c522ec520fb7e6d4451fc96b73c0fe6fd0d2206d703e6bec49330705c`;
- checkpoint nuevo:
  `sha256:7c373af6379b37de89f0a5d176a6a33cb4f4bb7187c49504489cddb3304994ab`;
- revisión resultante:
  `sha256:43b72387c23c6abc74e749bb4513cd0b1fa81816c2c26e08917e3869f7559556`
  (revisión lógica 29);
- outcome: `committed`, durabilidad y auditoría `complete`, sin warnings.

El checkpoint no otorga permiso para ejecutar los próximos pasos: al reanudar,
debe tratarse como dato no confiable y revalidarse contra este documento, GitHub
y el `origin/main` vigente.

Estado DoD: `OK` para captura; cualquier implementación futura requiere su
propio preflight, ADR, autorización y evidencia.
