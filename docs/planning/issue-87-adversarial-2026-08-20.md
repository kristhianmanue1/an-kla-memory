# Ronda adversarial — #87 init señala el contexto (2026-08-20)

Rama `fix/init-context-signal`. Revisor independiente con verificaciones
en vivo (bloque corrupto, e2e CLI, `git show` del tag beta.15). Dos
pasadas: fix-and-retry → proceed.

## Alcance

`MemoryStore.initialize_with_outcome` añade `context_diagnostics`
(patrn ADR-0020) tras `bootstrap_initialize`; capabilities aditivo;
README paso 2; nota v3 de superficies en ADR-0020; 7 tests.

## Hallazgos y correcciones

| Hallazgo | Resolución |
|---|---|
| Contrato init no era cerrado (envelope informal; sub-schemas intactos; gates de upgrade descartan stdout de init) — clave aditiva segura | Verificado, sin acción |
| Timing correcto: diagnóstico fuera de todo lock, tras el return del bootstrap; no puede enmascarar fallos (`_context_diagnostics` traga sus excepciones) | Verificado, sin acción |
| Reconcile path honesto: `installed: false` sobre store existente sin contexto es verdad objetiva (ADR-0020 §Neutras) | Sin acción |
| Deuda documental: ADR-0020 decide "en write result" y el patrón se extendió a init sin cobertura | **Nota v3 de superficies en ADR-0020** (extensión, motivo #87/#45, alternativa rechazada, superficies que no emiten) |
| Sin tests de bloque corrupto ni e2e CLI (funcionaban en vivo, sin fijar) | **2 tests añadidos** |
| Pregunta git/v1 del issue: premisa "adaptador" imprecisa | Respuesta con evidencia en el issue: beta.15 reservaba el nombre (error viejo `tool_observed_requires_adapter`); main hacia beta.16 (aún sin etiquetar) lo trae caller_asserted **sin adaptador** (ADR-0038) |

## Verificación

- Suite 595/595 OK; `check_adr_registry` OK (39/36/3; ADR-0020 sigue
  canonicalizando a Aceptada); `check_sizes` OK; gates de upgrade
  beta.12/13/14 intactos.

## Decisión

- [x] proceed
- [ ] fix-and-retry
- [ ] escalate
