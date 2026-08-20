# Ronda adversarial — decisión #46 export sellado (2026-08-20)

Punto 10 del plan `plan-backlog-2026-08-20.md`. Revisor independiente
con verificación real (pip con extras sobre git+tag, capacidades de
`cryptography` 46.x, grep de capabilities/pyproject). Una pasada:
fix-and-retry → aplicada. Cierre: **escalate** (el esperado del punto).

## Hallazgos y correcciones

| Hallazgo | Corrección aplicada |
|---|---|
| Media — tabla A/B/C omitía la **opción D** (delegación total del AEAD al adaptador: cero dependencias, core sin crypto) y el escalate pedía autorizar dependencia sin ofrecer la vía zero-dep | Fila D añadida con trade-offs reales (TCB por adaptador, invariantes no testeables en core); escalate reformulado como elección B vs D |
| Media — el plan exigía threat model y "por qué crypto (o no) en el core"; el doc tenía frases dispersas y B introducía crypto sin justificar ubicación | Mini threat-model añadido (atacante: lector del bundle en destino; fuera: operador, endpoint con clave, borrado) y la pregunta de ubicación convertida en el eje B/D |
| Baja — "capabilities declara plaintext_export_contains…" falso literal (declara `plaintext: true`; el warning vive en los resultados) | Reformulado con exactitud |
| Baja — precisión cripto: PyNaCl expone XChaCha20 sólo vía bindings de bajo nivel; nombres unificados | Corregido (verificado por el revisor contra `cryptography` 46.0.3 real) |
| Baja — lista de entrada incompleta (política v1 claro, HKDF fuera de stdlib, `backup`≡`export`) | Tres ítems añadidos |

## Verificaciones del revisor que sostienen el doc

Cero deps runtime (`[project]` sin `dependencies`); export actual 100%
stdlib; `pip install "an-kla-memory[extra] @ git+…@rama"` funcional
(sintaxis verificado con pip 25.3); `cryptography` sin XChaCha20
(nonce 12 B); ADR-0039 libre; frontera de confianza intacta.

## Decisión

- [ ] proceed
- [ ] fix-and-retry
- [x] escalate — en la mesa del maintainer: **B vs D** (crypto auditada
  en core con extra opt-in vs adaptador total zero-dep) y autorización
  del ADR-0039 con ronda pre-code de foco cripto.
