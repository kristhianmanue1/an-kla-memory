# Plantilla — ronda adversarial pre-release

Copiar a `docs/releases/vX.Y.Z-adversarial.md` antes de publicar cualquier
beta que toque `store.py`, `retrieval.py`, `index.py`, `write_policy.py` o el
contrato gestionado (`AGENTS.md`/`AN-KLA.md`). Estructura extraída de las
rondas ya hechas en `v0.1.0-beta.1` y `v0.1.0-beta.7` — no inventa proceso
nuevo, lo estandariza.

---

# Ronda adversarial de `<feature/issue>` (`<versión>`)

## Alcance

Qué implementación candidata se ataca y qué se revisó específicamente
(núcleo de decisión, CLI, filesystem, concurrencia, superficie de
`capabilities()`, backwards compatibility).

## Modelo de amenazas

Recordar la regla base: la memoria recuperada es dato no confiable, nunca
instrucción (`AGENTS.md`). Declarar si el cambio toca esa frontera o no, y
por qué. Si hay fuentes externas relevantes (prompt injection, consentimiento
de herramientas, procedencia), citarlas.

## Hallazgos y correcciones

| Hallazgo | Riesgo | Corrección |
|---|---|---|
| <qué se encontró> | <qué podía salir mal> | <qué se cambió, o "no aplicado, ver Límites"> |

## Verificación de canonicidad / determinismo

Si el cambio afecta hashes, fingerprints o decisiones reconstruibles:
confirmar que la reconstrucción sigue siendo determinista y que cualquier
alteración se detecta (qué error dispara).

## Límites declarados

Qué queda explícitamente fuera de alcance o sin resolver, y por qué no se
considera bloqueante para este release. La deuda no resuelta debe quedar
nombrada aquí, no implícita.

## Decisión

- [ ] proceed
- [ ] fix-and-retry
- [ ] escalate (bloqueo que requiere decisión del maintainer)

Sin `proceed` no se publica el tag.
