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
