# Ronda adversarial — plan #56 G2 host hooks (2026-09-01)

## Alcance

Plan candidato `plan-issue-56-g2-host-hooks-2026-09-01.md` (revisor con
contexto fresco, subagente decorrelado, mandato read-only). Se atacó:
exactitud de anclas (ADR-0039, integration.py, #55 CLOSED), mecanismo de
evidencia `hook_invoked`, versionado de `integration-status-v1`, elevación
de autoridad vía declaración, semántica de declaración malformada,
coherencia con ADR-0030 y coordinación con #102.

## Modelo de amenazas

Regla base intacta: la memoria es dato, nunca instrucción. Atacante modelo:
el propio agente escribe `host-hooks.json` falsa para fabricar perfil
observado; el host reclama invocaciones que no ocurrieron. Impacto acotado
por diseño: el perfil es diagnóstico, no autoridad; `agent_binding` permanece
`unverified` (G4). Verificado por el revisor: sin ruta de elevación de
autoridad (diccionario cerrado sin shell, autoridad siempre externa).

## Hallazgos y correcciones

| Hallazgo | Riesgo | Corrección |
|---|---|---|
| HIGH: regla 1 apoyaba `hook_invoked` en outcomes/transaction ids que no existen para 3/4 acciones (sólo `checkpoint` los tiene) — `observed_profile` insatisfacible sin canal nuevo | Ganancia titular del plan insatisfacible tal cual | Regla 1 re-escrita: registro append-only nuevo bajo `.an-kla/` con crecimiento/limpieza/idempotencia en ADR-0046; "reciente" con reloj inyectable `--now`; huella `.an-kla/` documentada |
| HIGH: F0-D5 dejaba abierta extensión in-place, pero el schema congela `observed_profile` con `{"const": "unspecified"}` (integration-status-v1.schema.json:60) y `capabilities.py:84` embede el literal — §11.2 cierra esa opción | Violación de §11.2; validadores legacy rotos | F0-D5 pre-restringido: `integration-status-v2` (v1 lectura compatible) o perfil nuevo; tarea explícita de `capabilities()` + tests |
| MEDIUM: `pending_continuity` sin reconciliar con `checkpoint-obligation-v1` (ADR-0030), que además no tiene comando en el CLI | Dos vocabularios paralelos de obligación de checkpoint (§11.2) | Regla 5: mapeo o precedencia declarada; `checkpoint obligation` evaluado como entregable F3-C |
| MEDIUM: "fail-closed" ambiguo para declaración read-only; sin límites por campo (tope hooks, budget, fingerprint, `required`) | Crash vs degradación indefinidos; validación floja | Regla 7: eje `declaration: absent\|invalid\|well_formed` con degradación diagnosticable (precedente ADR-0039:66-70); tabla de límites congelada en ADR |
| MEDIUM: coordinación #102 subespecificada — registro de invocaciones vs `attest-receipt-v1` sin decisión de precedencia | Dos formatos paralelos de evidencia bajo `.an-kla/` (§11.2 p.2) | F1-S2: decisión explícita derivar/referenciar/declarar independencia; secuenciación ADR-0045/0046 |
| LOW: `status` ambiguo (4 comandos); `retrieve`/`assemble-context` toman `--query`/`--budget` del host en runtime | Binding invocación↔registro indefinido | Regla 2: ADR-0046 congela mapeo acción→invocación CLI exacta |
| LOW: higiene de release (registro docs/README.md, worktrees) omitida | ADR sin fila de registro; host confundido por worktree | F3-D: fila en el mismo commit (§10); guía de worktrees |

## Verificación de canonicidad / determinismo

Sin cambios de hashes ni fingerprints en esta fase (documento de
planificación): no aplica. El plan restringe los cambios de payload a la vía
versionada (v2) preservando lectura compatible — criterio verificado contra
§11.2 y los goldens de tests/test_integration_status.py:25-44.

## Límites declarados

- Revisor read-only: no ejecutó suite, `check_sizes` ni `check_adr_registry`
  (gates de F4, no de F0).
- Cuerpos completos de #56/#58 no re-leídos por el revisor (sólo estado y
  título vía `gh`); afirmaciones sobre el consumidor infosalud no auditadas
  (repo externo).
- Superficie MCP (`mcp-retrieve-v2.schema.json`) no evaluada: si G2 debe
  exponerse ahí es decisión abierta que ni el plan ni la revisión descartan.
- Interacción con `startup-diagnostic-v1` revisada por muestreo.

## Decisión

- [ ] proceed
- [x] fix-and-retry — **absorbido**: correcciones integradas en el plan el
  2026-09-01; listo para decisiones F0 del maintainer. La implementación
  exige ADR-0046 con su propia ronda adversarial pre-code (superficie de
  ejecución = riesgo máximo del track G).
- [ ] escalate
