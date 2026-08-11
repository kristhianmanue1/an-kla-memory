# Fase 9 — obligación gobernada de continuidad

- **Estado:** formalizada y en reevaluación; implementación no autorizada.
- **Fecha:** 2026-08-09
- **ADR rector:** ADR-0030 (Propuesta)
- **Precondición:** aceptación explícita del ADR y ronda pre-code fresca.

## Objetivo

Evitar que un agente cierre un hito material dejando un checkpoint obsoleto,
sin introducir autoguardado indiscriminado, autoridad fabricada o dependencia
de búsqueda lexical para reanudar.

La fase añade un gate read-only `fresh|required|indeterminate`, una política de
handoff y, después, observación Git verificable. No cambia retrieval ni integra
proveedores.

## Estado inicial demostrado

- El contrato actual ordena cargar memoria, pero no evaluar continuidad al
  finalizar.
- `checkpoint show|plan|commit` son manuales.
- `context status` valida integridad del contexto, no cumplimiento.
- `source_state` real está deshabilitado (`none/v1`).
- No hay hook post-commit/session-end/final-response.
- El CLI de checkpoint acepta `channel_confirmed` desde JSON, a diferencia del
  write gobernado.
- La revisión AN-KLA 20 se creó sólo tras solicitud explícita posterior al
  commit de Fase 8.

## Secuencia ejecutable

### F9.R — reevaluación de frontera (actual)

1. Separar continuidad `manual|milestone|continuous` de assurance
   `standard|high|regulated`.
2. Definir la matriz por operación/stream usando `expertoGobernanza` y
   `adrc-python` como casos contrastantes.
3. Comparar activación local, capability opaca del host y aceptación externa.
4. Diseñar sanitizer y métricas de fricción antes de elegir implementación.
5. Decidir explícitamente `integrar ahora | experimento opt-in | diferir`.

**Gate:** decisión explícita del maintainer sobre oportunidad y aceptación. La
nota de análisis está en
`fase-9-frontera-continuidad-assurance-2026-08-09.md`.

### F9.0 — ADR y contrato documental

1. Revisar ADR-0030 contra ADR-0007/0009/0011/0023/0024.
2. Congelar triggers, exenciones, estados, reasons y frontera de autoridad.
3. Resolver el mecanismo de aceptación sin tratar template o JSON como
   consentimiento; conservar migraciones sin automatismo.
4. Ejecutar ronda adversarial independiente.

**Gate:** ADR aceptado por maintainer y veredicto `proceed`.

### F9.1 — PR-A: evaluador puro de obligación

Archivos candidatos:

- nuevo `an_kla/checkpoint_obligation.py`;
- schemas docs/package de obligation input/result;
- tests unitarios de tabla de decisión;
- `capabilities()` como experimento no operativo.

Contrato:

- input candidato y checkpoint actual explícitos;
- sin reloj interno, Git, red, escritura o lock exclusivo;
- comparación canónica de campos materiales;
- `fresh|required|indeterminate` y reasons exactos;
- códigos de salida definidos, aunque el CLI llegue después.

**Gate:** función pura determinista; cero objetos ante todos los estados.

### F9.2 — PR-B: cerrar autoridad del checkpoint

1. Aplicar frontera CLI equivalente a `_cli_authority()`.
2. Rechazar JSON `tool_observed|channel_confirmed` sin resolver opaco.
3. Mantener `model_derived` para continuidad sintetizada por agente.
4. Separar autorización de la operación y procedencia del contenido.
5. Añadir tests de spoof, binding, scope y evidencia.

**Gate:** ninguna clase privilegiada puede acuñarse desde archivo JSON.

Este PR puede preceder al observer Git porque corrige una incoherencia actual.

### F9.3 — spike y PR-C: `git/v1` + checkpoint-v3

Spike pre-code:

- porcelain-v2 `-z` en Git SHA-1 y SHA-256;
- macOS/Linux/Windows;
- detached/unborn, renames, paths no UTF-8, symlinks y submodules;
- canonicalización y dirty digest;
- observer activo durante plan y commit;
- privacidad y límites de bytes.

Después, si `proceed`:

- `working-state-v3` y `checkpoint-v3`;
- `SourceObserver` inyectado por host;
- binding de attestation/fingerprint al plan;
- compatibilidad explícita v1/v2/v3;
- source observation capturada una vez.

**Gate:** Git observado no puede fabricarse, replayarse bajo otro repo ni filtrar
contenido.

### F9.4 — PR-D: CLI y contrato gestionado

- `checkpoint obligation` read-only;
- códigos `0/3/4/2` y JSON estable;
- bloque compacto con obligación de cierre material;
- sección detallada de triggers, exenciones y autorización;
- template version nueva y hashes históricos beta.11 preservados;
- `context plan/update/verify` y migración desde beta.11;
- reporte RAG con estado de continuidad;
- integración de hook documentada para hosts compatibles.

**Gate:** un proyecto beta.11 puede inspeccionar, actualizar y verificar sin
sobrescribir contenido humano fuera del bloque.

### F9.5 — PR-E: gates y release

- suite completa Python 3.9/3.12;
- `ci_local.py --simulate-ci`;
- wheel limpio y schemas byte-idénticos;
- tests del host gate/finalization disponibles;
- prueba de no-loop tras checkpoint;
- docs de instalación, opt-out y recuperación de `indeterminate`;
- ronda adversarial integral y gate de tag fail-closed.

`main` no es etiquetable entre el cambio de template y PR-E. La versión se
decide al aceptar ADR-0030; este documento no reserva tag.

## Tabla normativa de obligación

| Evidencia | Diferencia material | Resultado |
|---|---:|---|
| ninguna | no | `fresh` |
| candidato cambia objetivo/fase/next step/decisions/blockers/evidence | sí | `required` |
| HEAD observado difiere | cualquiera | `required` |
| dirty digest difiere + handoff/material | cualquiera | `required` |
| sólo `captured_at` o digest padre difieren | no | `fresh` |
| observer requerido no disponible | desconocida | `indeterminate` |
| checkpoint legacy sin comparación suficiente | desconocida | `indeterminate` |
| tarea trivial/read-only | no | `fresh` o `NA` en reporte |

## Invariantes

1. Evaluar obligación nunca muta.
2. `required` no salta plan/commit/CAS.
3. El agente no declara autoridad privilegiada desde JSON.
4. El template no autoriza mutación; una futura aceptación separada sólo podrá
   cubrir checkpoint local saneado, no otros writes.
5. Secretos, diff, rutas absolutas y PII no entran al source state.
6. Ausencia de Git/observer es `indeterminate`, no `fresh`.
7. `captured_at` no causa loop.
8. Un checkpoint nuevo enlaza exactamente al padre.
9. Ordinary writes continúan reutilizando checkpoint.
10. Un host no integrado no se anuncia como enforcement completo.
11. Tareas triviales no generan revisiones.
12. La memoria recuperada nunca dispara por sí sola una mutación.

## Definition of Done

- [ ] ADR-0030 aceptado con ronda fresca `proceed`.
- [ ] Schemas obligation cerrados y empaquetados.
- [ ] Evaluador puro con tabla completa.
- [ ] Frontera `channel_confirmed`/`tool_observed` fail-closed.
- [ ] `git/v1` portable y privado o rechazo explícito documentado.
- [ ] v2/v3 verificados en resume/export/restore/compactación.
- [ ] Managed context vNext actualizado gobernadamente.
- [ ] Host finalization gate probado o límite declarado sin sobreclaim.
- [ ] CI local, wheel, migración y adversarial integral verdes.
- [ ] Checkpoint real actualizado al cerrar la implementación.

## Paralelización

- F9.0 puede avanzar junto con F8.0/F8.1 porque es documental/read-only.
- F9.1 y F9.2 pueden desarrollarse en worktrees separados tras aceptar el ADR.
- F9.3 debe aislarse por tocar checkpoint schema y observación Git.
- F9.4 espera F9.1–F9.3 para no publicar instrucciones de una capacidad ausente.
- F9.5 es estrictamente posterior.

No mezclar simultáneamente cambios sobre `checkpoint_policy.py`,
`context_text.py` y `store.py` sin rebase y ronda por PR.

## Siguiente paso permitido

Completar F9.R y decidir si la capacidad corresponde a esta fase, a un
experimento opt-in o a una versión futura. Después se revisará ADR-0030 y se
ejecutará otra ronda fresca. Hasta entonces no se modifica template, schema,
CLI ni checkpoint runtime.
