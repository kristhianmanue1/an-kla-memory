# Ronda adversarial — requisito previo: sonda de compactación (2026-10-29)

## Hallazgo observado

Antes de implementar ADR-0061, el CI local sobre el commit documental
06e25ea falló: 1285 tests, tres fallos de Row15 por cascada del smoke
`compaction-large`. Los JSON originales contienen
`WritePolicyError: write_plan_base_changed`. La sonda capturaba el CAS al
planificar pero no al commitear. La carrera depende del scheduling; una
suite sin esa intercalación puede pasar. No es un defecto nuevo del motor
ni evidencia de corrupción del store. Log: /private/tmp/adr0061-docs-ci.log.

## Corrección acotada

En `benchmarks/scale/scenarios_durability.py`, reintentar sólo el CAS
`write_plan_base_changed` y LockBusyError en ambas fases. Otros errores de
política siguen propagándose. Un resultado de commit no confirmado detiene
la sonda: no se cuenta como CAS ni se repite un efecto incierto.

Ante excepción de sonda o recolección, terminar/recolectar el subproceso de
compactación propio; si vence el timeout de terminación, kill y recolección.
No se relajan umbrales, tamaño del store, gates ni criterio de 20k revisiones.

## Revisión y evidencia

Autor: agente principal. Revisor `/root/review_probe_prerequisite`, sesión
nueva `fork_turns=none`, sin historial conversacional; recibió las rutas,
explicación del fallo y actualizaciones del diff. Entorno/modelo compartidos,
sin independencia de proveedor ni auditoría externa. La relectura posterior
usa el mismo contexto de revisión, no un segundo revisor independiente.

El revisor contrastó rechazos CAS antes de efectos en store/write_commit,
el JSON original y el flujo de cleanup. Primera decisión proceed con una
observación de cobertura: timeout de communicate tras sonda exitosa. Se
incorporó ese caso y la detención ante resultado incierto; relectura final:
**proceed**, sin hallazgos bloqueantes residuales. El revisor ejecutó los
cinco tests dirigidos, sin ejecutar stores ni sondas.

Comprobaciones del agente principal:

- `.venv/bin/python -m unittest tests.test_scale_probe_retries -v` → 5 OK.
- Smoke compaction-large real → commit_ok y verify OK; evidencia en
  /private/tmp/adr0061-probe-smoke-fixed (antes de endurecer resultado incierto)
  y /private/tmp/adr0061-probe-smoke-final (árbol final de la corrección).
- `tests.test_scale_battery_smoke.ScaleBatteryV2SmokeTests.test_smoke_v2_scenarios`
  → cinco familias, 1 test OK, 18,081 s (antes de endurecer resultado incierto).
- Gates sizes/plans/adr_registry y diff --check → OK; repetir en cierre.
- CI completo de la corrección: su resultado se registra en el PR antes de
  integrar; no se declara verde a partir de los tests dirigidos.

## Límites

El presupuesto de la sonda sigue siendo blando entre intentos: una llamada
individual puede sobrepasarlo. La recolección depende del SO y puede fallar
ante otra interrupción o errores de terminate/kill. No se afirma una garantía
absoluta de cleanup. El smoke no sustituye la corrida oficial a 20k.

Decisión: **proceed** para el requisito previo del harness. No implementa
ADR-0061, publica release ni cambia contratos públicos del motor.

## Documentación solicitada durante la verificación

El Operador pidió conservar el resultado previo de compatibilidad y documentar
Python≥3.12 como intérprete de trabajo. Se añadió la regla en §5 de prácticas
de ingeniería y la nota `docs/benchmarks/test-suite-cost-2026-10-29.md` con
conteos, smoke y tiempos observados. También se añadió la cota de disco en
`docs/benchmarks/construction-manifest-bound-2026-10-29.md` con su control
preservado. El mismo revisor contrastó ambas notas y la regla contra código y
logs: proceed documental, sin rebajar gates ni rango soportado. Es continuación
de su contexto de revisión, no una revisión fresca adicional. No verificó el
store de rev566 ni aisló comparativas de velocidad entre intérpretes.
