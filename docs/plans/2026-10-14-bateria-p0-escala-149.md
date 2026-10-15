# Plan — batería P0 de escala del store (issue #149, Fase 0)

**Estado:** ejecución autorizada por el maintainer el 2026-10-14 (decisiones
T1 dos columnas, T2 umbrales tal cual, T3 compactación con desviación
declarada). **Base:** `main@5f3c5ae` (merge PR #153). No toca
`an_kla/store.py`, `an_kla/retrieval.py`, `an_kla/index.py` ni
`an_kla/write_policy.py`: es infraestructura de medición, sin ronda
adversarial pre-code obligatoria (prácticas §1); se hará acta de cierre por
disciplina.

## Objetivo y método

Cubrir el criterio P0 del issue #149: matriz registros × revisiones ×
sujetos × ratio de supersedes por la vía gobernada pública, umbrales
escritos y commiteados antes de correr, resultados versionados, escenarios
de concurrencia (4 escritores/8 lectores), crash mid-commit, término raro
índice sí/no y compactación (escala alcanzable, desviación declarada). Dos
columnas: gobernada (acotada por umbral de aborto) y diagnóstica interna
(`MemoryStore.commit()`, etiquetada) para lecturas a gran escala.

- Umbrales: `benchmarks/scale/thresholds-v1.json` — commiteados en un commit
  previo a cualquier corrida; los resultados referencian su hash.
- Un resultado que empeore el baseline se reporta igual (criterio de
  aceptación del issue).
- Entorno registrado con huella completa (intérprete, máquina, FTS5);
  Python 3.12+ según regla del maintainer.

## Tareas

```text
TAREA P0-A plan y umbrales pre-corrida (Fase 0, #149)
Consumes: `docs/planning/revision-critica-escalado-gobernanza-2026-10-14.md`, `docs/plans/2026-10-10-g3-discovery-agent-roadmap.md`
Produce: este plan y `benchmarks/scale/thresholds-v1.json` commiteados antes de correr
Steps:
  - [x] Fijar umbrales v1 aprobados por el maintainer (latencia sostenida 2 s, celda 30 min, total 4 h, disco 2 GB/store) — verificación: commit del archivo de umbrales anterior en historia al commit de resultados; `scripts/check_plans.py` acepta este plan (reglas E1-E5).
  - [x] Declarar las dos columnas y sus etiquetas (gobernada vs interna diagnóstica) y la desviación de compactación (400 revisiones ahora, 20.000 post-P1) — verificación: el campo `deviation_declared` vive en el JSON de umbrales y se copia al informe de resultados.

TAREA P0-B implementación de la batería (Fase 0, #149)
Consumes: `an_kla/store.py`, `an_kla/retrieval.py`, `an_kla/context_view.py`, `an_kla/compaction.py`, `benchmarks/README.md`
Produce: se crean `benchmarks/scale/core.py`, `benchmarks/scale/scenarios_ingest.py`, `benchmarks/scale/scenarios_diagnostic.py`, `benchmarks/scale/scenarios_ops.py`, `benchmarks/scale/battery.py` y `tests/test_scale_battery_smoke.py`
Steps:
  - [x] Núcleo compartido: huella de entorno (intérprete, máquina, FTS5, revisión Git), carga de umbrales, escritura gobernada (plan_write + commit_write_plan vía model_derived+summary), construcción interna por lotes y medición con percentiles — verificación: smoke test del núcleo en verde con N diminuto.
  - [x] Columna gobernada: ingesta celda por celda (sujetos 1/200, supersede 0/10 %) con aborto por latencia sostenida o presupuesto, snapshot en puntos de lectura y lecturas finales (término común, raro, índice, context_view) — verificación: smoke test de ingesta con N=6 y aborto no disparado; resultado JSON con campo `internal_commit_diagnostic=false`.
  - [x] Columna diagnóstica interna: stores a 1k/5k/20k registros por lotes internos, mismas lecturas y tamaños de disco — verificación: smoke con punto 50 registros; resultado etiquetado `internal_commit_diagnostic=true`.
  - [x] Operaciones: concurrencia 4W/8R (LockBusyError y conflictos CAS contados), crash SIGKILL mid-commit con verify tras cada kill, y compactación gobernada completa (export create, proposal, compact plan, compact commit) cronometrada — verificación: smoke de cada escenario en escala diminuta; verify del CLI en ok tras cada kill.
  - [x] CLI de la batería con subcomandos, presupuesto total, copia de umbrales al resultado y modo --smoke — verificación: `python -m benchmarks.scale.battery --help` y corrida --smoke completa en verde.

TAREA P0-C corrida oficial y resultados versionados (Fase 0, #149)
Consumes: `benchmarks/scale/thresholds-v1.json`, `benchmarks/scale/battery.py`
Produce: se crea el directorio `benchmarks/scale/results/` con la corrida fechada, JSON por escenario e informe
Steps:
  - [x] Ejecutar la batería completa con los umbrales ya commiteados y presupuesto 4 h — verificación: log de corrida y JSON por escenario con huella de entorno; abortos registrados como resultados, no como fallos de la batería.
  - [x] Escribir informe comparando contra las sondas del issue #149 (forma de curva, no cifra absoluta) — verificación: informe versionado con caveats de máquina y desviaciones declaradas.
  - [x] Gates y suite: check_sizes, check_plans, check_adr_registry y suite completa con Row15 — verificación: comandos y salidas reales sobre el diff final; un fallo no se llama verde.

TAREA P0-D cierre (Fase 0, #149)
Consumes: `docs/adversarial-template.md`, `docs/planning/revision-critica-escalado-gobernanza-2026-10-14.md`
Produce: acta adversarial de la batería, PR referenciando #149 y comentario en el issue
Steps:
  - [x] Ronda adversarial de cierre sobre el artefacto final (código + resultados) con decisión proceed/fix-and-retry — verificación: acta con hallazgos y evidencia comando→resultado; sin proceed no se fusiona el PR.
  - [ ] Comentar el issue #149 con la ubicación de resultados y umbrales — verificación: URL del comentario registrada en el reporte de sesión.
```

## Límites declarados

- La columna gobernada no alcanzará 20.000 registros: el punto de aborto es
  el resultado falsable esperado (prerrequisito P1/P2 del propio issue).
- Compactación a 400 revisiones, no 20.000: desviación aprobada (T3).
- Crash mid-commit es probabilístico (SIGKILL con retardos sembrados);
  método declarado, no inyección determinista.
- Los números absolutos son de una máquina concreta; la forma de la curva es
  el hallazgo (frontera de confianza del informe origen).
