# Ronda adversarial G-VIEW-CAP — issue #60

- **Fecha:** 2026-08-12
- **Alcance:** descubrimiento `capabilities()["view"]` candidato de ADR-0034;
  revisión read-only con contexto fresco.
- **Decisión final:** `proceed`.

## Superficie atacada

- perfil, operación, superficies, schemas, proyecciones, defaults y límites;
- catálogos cerrados de warnings y errores;
- pureza L2 y efecto de coordinación `.reader-gate`;
- determinismo, estructuras no compartidas y descubrimiento sin leer memoria;
- no exposición de subjects, namespaces observados, kinds presentes o regex;
- límite de fase sin REL ni cambio de versión.

## Hallazgos y correcciones

| Intento | Hallazgo | Corrección |
|---|---|---|
| 1 | Catálogos duplicados podían derivar entre core, MCP y CAP | fuente única versionada en `context_view`; consumidores importan constantes |
| 1 | Guarda de privacidad superficial | recorrido recursivo de claves y valores del bloque `view` |
| 1 | Warning multi-namespace sin regresión semántica | prueba del universo filtrado antes de paginar |
| 2 | MCP aún repetía tool y warnings | consume `VIEW_SURFACES`, `VIEW_WARNING_CODES` y `VIEW_ERROR_CODES` |
| 2 | Warnings no se cotejaban contra schema | igualdad con enum de `context-view-v1`; errores con `view-error-v1` |
| 2 | Guarda admitía kinds como valores y faltaba `subject_filter` | rechazo de los once kinds y prueba de filtro exacto |

## Invariantes y evidencia

- ✓ Catálogos: warnings `2/2`, errores `10/10`, coinciden con schemas.
- ✓ CAP es determinista, no comparte estructuras y no crea `.an-kla`.
- ✓ No publica valores observados ni gramática completa de subject refs.
- ✓ Pureza L2 y side effect de coordinación quedan explícitos.
- ✓ No hay cambios en versión, notas de release ni tag.

Comandos de cierre:

```text
python3 -m unittest discover -s tests -p 'test_*.py'
→ Ran 509 tests; OK

python3 scripts/ci_local.py --simulate-ci
→ ci_local: OK

git diff --check
→ exit 0, sin salida
```

## Decisión

- [x] `proceed`
- [ ] `fix-and-retry`
- [ ] `escalate`
