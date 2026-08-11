# Ronda adversarial documental de Fase 9 — continuidad obligatoria

## Alcance

Ataque preliminar a ADR-0030 y al plan de Fase 9. Se revisan autoridad,
privacidad, triggers, falsos positivos, loops, Git, backwards compatibility,
mutación silenciosa, host enforcement y relación con checkpoint-v2.

Esta pasada fue realizada por el mismo agente que redactó la propuesta. Sirve
para corregir inconsistencias internas, pero no sustituye la ronda fresca
requerida antes de aceptar el ADR o modificar el contrato gestionado.

## Modelo de amenazas

- agente que guarda secretos o texto excesivo al finalizar;
- memoria recuperada que intenta provocar su propia persistencia;
- JSON que fabrica `channel_confirmed` o `tool_observed`;
- hook que crea checkpoints infinitos por reloj o cambio de CURRENT;
- Git observer que filtra diff, remote, autor o rutas absolutas;
- checkpoint stale presentado como fresh cuando Git no está disponible;
- host no integrado presentado falsamente como enforcement completo;
- tarea trivial que crea revisiones en cada respuesta;
- carrera entre obligación, otro write y checkpoint commit.

## Hallazgos y correcciones incorporadas

| Severidad | Hallazgo | Riesgo | Corrección documental |
|---|---|---|---|
| BLOCKER | “guardar cuando sea conveniente” no tiene semántica verificable | agentes distintos guardan de forma arbitraria | triggers materiales y exenciones cerrados |
| BLOCKER | autoguardado silencioso podía persistir secretos o inferencias | memoria local contaminada sin revisión | evaluador read-only; mutación conserva plan/commit y minimización |
| BLOCKER | v2 no puede demostrar HEAD/branch/dirty | commit Git no es detectable | `git/v1` exige checkpoint/working-state v3 y observer real |
| HIGH | checkpoint CLI acepta `channel_confirmed` desde JSON | etiqueta privilegiada no resuelta | PR-B aplica frontera fail-closed; automático usa `model_derived` |
| HIGH | repo no controla final response del host | política documentada podía sobreafirmar enforcement | resultado/códigos AN-KLA + hook requerido; límite explícito sin host |
| HIGH | comparar `captured_at` causaría loop infinito | cada evaluación exige otro checkpoint | reloj y digest padre excluidos de diferencia material |
| HIGH | dirty worktree cambia durante cada edición | ruido y revisiones excesivas | dirty sólo obliga bajo trigger material/handoff |
| HIGH | observer ausente podía degradar a caller asserted | frescura Git inventada | estado `indeterminate`, nunca `fresh` |
| MEDIUM | todo commit, incluso mecánico, podía inflar revisiones | costo y ruido operacional | trigger más diferencia material; `checkpoint_unchanged` preservado |
| MEDIUM | template otorgaba autoridad demasiado amplia | checkpoint usado como puerta a facts/red/Git | autorización permanente limitada sólo a checkpoint local saneado |
| MEDIUM | obligación podía mutar mientras se evalúa | side effects inesperados | evaluator puro/read-only; commit separado con CAS y replan |

## Verificación de canonicidad y determinismo

La propuesta exige comparación por JSON canónico de seis campos materiales y
arrays ordenados por bytes. `captured_at`, revisión y digest padre no participan
en la decisión de diferencia. Todavía no existen schemas ni vectores golden; el
PR-A debe congelarlos antes de tocar store o template.

## Límites declarados

- No se modificó `AGENTS.md`, `AN-KLA.md`, `context_text.py`, CLI o schemas.
- No se implementó observer Git, hook del host o escritura automática.
- No se cambió el checkpoint recién guardado ni la revisión AN-KLA 20.
- No se creó issue, PR, commit, tag o release.
- No se afirma que un repositorio pueda bloquear por sí solo la respuesta de un
  agente externo.

## Decisión

- [ ] proceed
- [ ] fix-and-retry
- [x] escalate

`ESCALATE` permite conservar la formalización. Bloquea implementación y cambio
del contrato gestionado hasta una revisión fresca que resuelva especialmente:

1. que la autorización permanente ligada a instalar el template sea realmente
   limitada, revocable y no extensible a otros writes;
2. shape/canonicalización de `git/v1` y checkpoint-v3;
3. frontera de `channel_confirmed` para checkpoint;
4. API real del hook de finalización del host.

## Ronda fresca r2 — commit `277dea5`

- **Revisor:** agente con contexto fresco, modalidad estrictamente read-only.
- **Snapshot:** `277dea508fe3af961ea736ebe151793f338329d8`.
- **Decisión:** `ESCALATE`.
- **Mutaciones del revisor:** ninguna.

La ronda confirmó el diagnóstico base, pero determinó que la propuesta aún no
puede aceptarse ni iniciar F9.1. La severidad de que el template conceda por sí
solo autorización standing sube de MEDIUM a BLOCKER.

### Hallazgos r2

| Severidad | Hallazgo | Evidencia | Corrección requerida |
|---|---|---|---|
| BLOCKER | instalar el template no demuestra consentimiento permanente | ADR-0009 declara que el hash del bloque no es firma ni prueba de autoridad; el bloque puede llegar por clone, commit o update | template sólo obliga `evaluate + report`; commit automático exige opt-in `continuity-consent-v1` explícito, revocable y ligado a project/store/template/scope |
| BLOCKER | `fresh` puede certificar un candidato viejo copiado por el caller | candidato y `--trigger` son caller-provided; equivalencia no demuestra cobertura operacional | separar `candidate_equivalent` de frescura; sin observaciones verificables, máximo `indeterminate`; añadir basis/coverage/provenance/host status |
| BLOCKER | spoof de `channel_confirmed` es reproducible | `checkpoint plan` pasa JSON directo y policy acepta shape `channel_confirmed` | hotfix de frontera debe preceder al evaluador y proteger plan **y commit**; resolver privilegiado requiere handle activo |
| BLOCKER | `git/v1` no congela boundary plan/commit | ADR-0023 exige entries/status/mode/OID/rename/vectores y handle opaco activo en ambas fases | elegir API in-process con handle o attestation serializable verificable; definir drift, identidad, expiración y golden vectors |
| BLOCKER | rollout v3 pondría writer antes que readers | plan ubicaba v3 antes del PR de CLI/contrato; runtime actual sólo lee v1/v2 | dividir C1 readers-first y C2 writer opt-in; default v2 hasta cierre integral |
| BLOCKER | “continuidad saneada” no es regla ejecutable | working-state-v2 admite valores arbitrarios grandes; no hay sanitizer | definir `checkpoint-sanitization/v1`, allowlists/límites y `checkpoint_pending_human_review` para contenido libre |
| HIGH | branch legible puede contener PII | nombres de branch suelen incluir usuario/cliente/ticket | `branch_digest` por defecto; texto sólo con opt-in |
| HIGH | orden de decisions/blockers/evidence crea falsos cambios | v2 acepta igual conjunto en orden distinto y canonical JSON cambia | comparar como mapas por `id` o declarar orden semántico con reason propio |
| HIGH | obligación no tiene variantes cerradas por estado | `indeterminate` puede carecer de candidato/observer/store | schema `oneOf` por estado, reasons completos y precedencia exacta |
| HIGH | no existe API de finalización del host | búsqueda en código/tests no halló hook ni `checkpoint_pending` | capabilities separa `advisory` de `host-integrated`; sin hook no afirmar enforcement |
| MEDIUM | triggers externos carecen de procedencia | un enum CLI no prueba merge/release/handoff | `trigger-attestation-v1`: caller asserted para advisory, host observed sólo con adapter |
| MEDIUM | `NA` se mezcló con resultado de producto | schema sólo define fresh/required/indeterminate | `NA` existe sólo en reporte cuando evaluator no se invoca |

### Invariantes y evidencia r2

| Invariante | Comando | Resultado |
|---|---|---|
| snapshot exacto y limpio | `git rev-parse HEAD`; `git status --short` | `277dea5...`; vacío |
| commit sólo documental | `git show --stat --oneline 277dea5` | 5 docs, 576 líneas, sin código/schema/template |
| suite actual | `python3 -m unittest discover -s tests -p 'test_*.py'` | 396 tests OK |
| contratos dirigidos | `python3 -m unittest tests.test_checkpoints tests.test_context_package tests.test_agent_contracts` | 55 tests OK |
| gates docs | `git diff --check 277dea5^ 277dea5`; `python3 scripts/check_sizes.py` | exit 0; OK |
| obligation ausente | `python3 -m an_kla ... checkpoint obligation --help` | exit 2; sólo show/plan/commit |
| spoof canal | `validate_authority()` con JSON `channel_confirmed` | aceptado; hallazgo reproducido |
| source state cerrado | inspección policy/capabilities | sólo none/v1; adapter false |
| hook ausente | búsqueda finalization/session/post-commit/obligation | sin implementación |

### Decisiones pendientes tras r2

1. **Consentimiento:** recomendado que el template sólo fuerce evaluación y
   reporte; mutación automática requiere opt-in local explícito y ligado a
   identidad. No se recomienda que el template sea autoridad por sí solo.
2. **Observer:** API in-process con handle opaco durante plan/commit, o
   attestation serializable verificable ligada a repo/store/plan.
3. **Nivel de producto:** exponer `advisory` y `host-integrated`; nunca anunciar
   el segundo sin hook probado.

La propuesta queda a la espera del caso especial del maintainer antes de elegir
estas alternativas. Hasta entonces no se corrige el ADR de forma especulativa,
no se acepta y no comienza F9.1.

## Insumo posterior a la ronda: frontera de riesgo

El maintainer aportó el caso especial después del veredicto para preservar la
independencia de la ronda. El contraste entre `expertoGobernanza` y
`adrc-python` muestra que una sola escala `manual|balanced|strict` todavía
mezclaría continuidad con assurance.

La hipótesis posterior separa:

- frecuencia de continuidad: `manual|milestone|continuous`;
- fuerza de assurance: `standard|high|regulated`;
- aplicación por operación/stream/efecto, no rigidez universal del proyecto.

También deja abiertas tres formas de aceptación: activación local explícita,
capability opaca del host y aceptación firmada/externa. Este insumo no cambia el
veredicto r2 ni resuelve sus BLOCKER. ADR-0030 permanece `Propuesta`, la
implementación sigue detenida y se requiere decidir primero si integrar ahora,
experimentar opt-in o diferir. Detalle:
`fase-9-frontera-continuidad-assurance-2026-08-09.md`.
