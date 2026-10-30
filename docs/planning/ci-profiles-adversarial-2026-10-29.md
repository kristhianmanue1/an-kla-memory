# Revisión adversarial — propuesta de perfiles CI

**Resultado:** `proceed documental`, 2026-10-29.
**Artefacto:** [mapa y diseño](ci-profiles-design-2026-10-29.md), propuesta no adoptada.

## Producción y separación

Productor: agente principal `/root`. Revisor: subagente
`/root/review_ci_design`, iniciado con `fork_turns=none`: recibió rutas,
invariantes y alcance, sin historial del productor. Comparte entorno y
configuración de modelo heredada; no hay independencia de proveedor ni
aislamiento de HOME/cachés. No se verificó identidad del modelo por una
fuente externa. La separación acreditada es de contexto de conversación.

El revisor inspeccionó el diseño, el diff de postergación, `ci_local.py`,
las clases de matriz sellada, los tests de resolución de intérpretes y
ADR-0042 con su apéndice. Trabajó sólo en lectura, sin suite completa,
CI costoso ni escritura de memoria. Confirmó Python 3.12.12.

## Hallazgos y refutación

- **Precisión del conteo:** 1304 es el contador principal; no suma casos de
  los hijos, aunque el tiempo del padre los incluye. El productor corrigió
  el texto y el revisor releyó la corrección antes de su veredicto.
- **Cobertura normativa:** fila 15 exige CI sin/con extra, pero los dos CI
  hijos usan el intérprete actual. Se explicitó que discover CLT no prueba
  CI con extra. Clean wheel y upgrade REL permanecen obligaciones separadas.
- **Contraejemplos exigidos antes del código:** skips criptográficos
  parciales, intérprete ausente, entorno «normal» contaminado por CI heredado,
  discover vacío, todo-skips, timeout, hijo muerto y escapes heredados.
  El documento exige controles y no afirma equivalencia ya ejecutada.
- **Escala:** el criterio de 20.000 revisiones permanece sin validar;
  la postergación por espacio sale del alcance activo y no rebaja ese criterio.

Tras releer las correcciones, el revisor informó «sin hallazgos bloqueantes
restantes» y `proceed documental`. La ronda no adopta política ni activa CI.

## Comprobaciones del productor

Sobre el árbol documental local basado en
`888299251fe269652ee2c28292fb9c2b67bc4ebf`, con Python 3.12.12:

| Comando | Resultado observado |
|---|---|
| `.venv/bin/python scripts/check_sizes.py` | OK |
| `.venv/bin/python scripts/check_plans.py` | OK, 4 planes |
| `.venv/bin/python scripts/check_adr_registry.py` | OK, 61 ADRs: 56 aceptadas, 5 propuestas |
| `.venv/bin/python -m unittest tests.test_ci_local_matriz tests.test_adr_registry` | 9 tests, OK, 0,016 s |
| `git diff --check` | Sin errores |
| `context status` con `.venv/bin/python -m an_kla` | ok=true, sin diagnósticos |
| `gh issue list --state open`, `gh pr list --state open` | 5 issues; ningún PR abierto |

La consulta inicial a GitHub falló por conectividad del sandbox; el reintento
escalado devolvió las listas. Estos tests dirigidos validan resolución de
matriz y registro; no prueban perfiles nuevos ni sustituyen el CI completo.
No se ejecutó el CI completo de nuevo ni se hizo push/merge de este diseño.
La regla vigente de CI antes de push se conserva. Cambios sólo documentales;
la continuación es presentar el diseño, antes de adoptar ADR e implementar.
