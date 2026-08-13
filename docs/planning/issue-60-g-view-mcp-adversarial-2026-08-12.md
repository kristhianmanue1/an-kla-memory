# Ronda adversarial G-VIEW-MCP — issue #60

- **Fecha:** 2026-08-12
- **Alcance:** adaptador MCP candidato de ADR-0034; revisión read-only con
  contexto fresco.
- **Decisión final:** `proceed`.

## Superficie atacada

- tool `an_kla_view_context`, input schema cerrado y validación runtime;
- paridad exacta con el core, JSON canónico en `content[0].text` e `isError`;
- saneamiento de retornos internos mal formados y argumentos hostiles;
- transporte stdio, ausencia de `structuredContent` y framing no medido;
- compatibilidad con las tools existentes y límite sin CAP/REL.

## Hallazgos y correcciones

| Intento | Hallazgo | Riesgo | Corrección |
|---|---|---|---|
| 1 | Retornos core mal formados podían reenviarse o marcarse success | fuga de campos privados y fail-open | frontera cerrada `_validate_view_result`; retorno saneado `internal_error` |
| 1 | Regex JSON Schema aceptaba newline final | divergencia schema/runtime | longitudes exactas y prohibición explícita de CR/LF |
| 2 | Contadores exigían siempre tres streams | falso rechazo de subsets válidos | validar contra los streams normalizados del payload |
| 2 | `content_differs_beyond_text` no estaba permitido | falso rechazo de conflicto textual válido | campo booleano opcional sólo en proyección `text` |
| 2 | Claves conocidas con valores hostiles podían pasar | fuga por constantes o detail inválido | validación de constantes, enums, digests, subject refs, estados y variantes |

Cada hallazgo tiene una prueba de regresión persistente en
`tests/test_mcp_view.py`.

## Invariantes y evidencia

- ✓ Streams parciales y `content_differs_beyond_text` válidos no se rechazan.
- ✓ Retornos mal formados y valores hostiles se sanean sin eco.
- ✓ Toda la unión `an-kla/view-error-v1` fija `isError=true`.
- ✓ Success conserva bytes canónicos exactos y `isError=false`.
- ✓ No hay `structuredContent`; `host_framing_unmeasured=true` permanece.
- ✓ MCP existente y stdio siguen compatibles; CAP/REL quedan fuera.

Comandos de la ronda final:

```text
python3 -m unittest tests.test_mcp_view tests.test_mcp tests.test_mcp_stdio tests.test_context_view
→ Ran 52 tests; OK

git diff --check
→ exit 0, sin salida
```

## Límites declarados

Esta ronda cierra el candidato G-VIEW-MCP. No autoriza merge, capabilities,
nota de release ni tag.

## Decisión

- [x] `proceed`
- [ ] `fix-and-retry`
- [ ] `escalate`
