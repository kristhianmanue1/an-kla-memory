# Ronda adversarial G-VIEW-CLI — issue #60

- **Fecha:** 2026-08-12
- **Alcance:** adaptador CLI candidato de ADR-0034; revisión read-only con
  contexto fresco.
- **Decisión:** `proceed`.

## Superficie atacada

- comando `view context` y forwarding de todos sus inputs al core;
- discriminación de la unión success/error;
- JSON canónico, stderr saneado y exits `0/2/3/1`;
- defaults compartidos con el core y coherencia del registro ADR;
- límite de fase: sin MCP, capabilities ni release.

## Hallazgos y correcciones

Antes de la ronda final, una prueba de integración real detectó que el success
schema no contiene `ok=true`. El adaptador clasificaba el resultado mediante
ese campo y devolvía exit 3 ante un success válido. Se cambió el discriminante
al schema cerrado `an-kla/view-error-v1` y se conservó la prueba de regresión.

La ronda final no encontró hallazgos `BLOCKER`, `HIGH`, `MED` ni `LOW`.

## Invariantes y evidencia

- ✓ Todos los inputs llegan al mismo core; los defaults `text`, `50`, `65536`
  y streams `None` se comparten o verifican por prueba.
- ✓ Success: JSON canónico stdout y exit 0.
- ✓ `view_invalid_inputs`: stdout vacío, stderr saneado y exit 2.
- ✓ Error operacional catalogado: JSON canónico stdout y exit 3.
- ✓ `view_internal_error`: stdout vacío, stderr saneado y exit 1.
- ✓ CORE+CLI constan como candidatos; MCP/CAP siguen pendientes.

Comandos de la ronda final:

```text
git diff --check
→ exit 0, sin salida

python3 -m unittest tests.test_context_view_cli tests.test_context_view
→ Ran 28 tests; OK
```

## Límites declarados

Esta ronda no autoriza commit, PR, merge, MCP, capabilities, nota de release ni
tag. Es evidencia de cierre del candidato G-VIEW-CLI solamente.

## Decisión

- [x] `proceed`
- [ ] `fix-and-retry`
- [ ] `escalate`
