# Plan iterativo para custodia, descubrimiento y evaluación de AN-KLA

**Estado:** propuesta de ejecución, 2026-10-10. **Dueño de decisiones:** maintainer.
**Base observada:** `main` y `origin/main` en `0f874e97601858d788a19182a0829be1761c3898`, árbol limpio; issues abiertos #57, #134 y #58; ningún PR abierto. Esta base se vuelve histórica al cambiar GitHub o el checkout. Crear este plan no autoriza implementar, escribir AN-KLA, hacer commit, push, release ni publicar.

## Resultado buscado y orden

AN-KLA debe poder conservar una sola bóveda por proyecto fuera del checkout sin crear otra silenciosamente; el operador debe poder descubrir las bóvedas locales sin convertir el índice en autoridad; la identidad de agente y multi-scope se estudian con una frontera separada. Los métodos de Muse son candidatos de evaluación, no dependencias de producto.

| Orden | Corte | Issue | Estado inicial | Criterio para avanzar |
| --- | --- | --- | --- | --- |
| P0 | R0: reconciliar contrato y medir baseline | #57 | pending | ADR-0048 y nombres de schemas coherentes; suite y gates basales registrados |
| P1 | R1: resolver raíces, identidad, consumidores y observabilidad sin migrar | #57 | pending | Store externo nuevo y project-local legado verifican por todas las entradas cubiertas; las demás fallan cerradas hasta R1c |
| P1 paralelo | D0: diseño de descubrimiento, sin registro operativo | #134 | pending | Problema actual medido, alternativas y autoridad del índice decididas en ADR propio |
| P2 | R2: `relocate` gobernado y recuperación | #57 | pending | Plan exacto, crash, concurrencia y roundtrip demostrados en stores de prueba |
| P2 | R3: consumidores, compatibilidad y auditoría final | #57 | pending | Export, worktrees, contratos y ronda adversarial sobre artefacto final |
| P3 condicionado | D1: registro local orientativo | #134 | pending | Sólo tras ADR y prueba de no reasignación ni divulgación inadvertida |
| P3 exploratorio | A0: threat model de identidad y multi-scope | #58 | pending | Sin implementar G4 ni prometer privacidad |
| P4 condicionado | M0: método Muse en pruebas propias | ninguno | pending | Sólo si un consumidor y una mutación muestran una brecha no cubierta |

R1 y D0 pueden avanzar en paralelo porque comparten conceptos, pero D0 no bloquea R1. R2 depende de R1a-R1c verificados. R1a y R1b son cortes parciales: no acreditan por sí solos que la custodia externa funcione en todas las entradas. D1 debe consumir la semántica de custodia vigente al ejecutarse. A0 puede iniciar en lectura antes, aunque una decisión G4 debe incorporar lo observado en G3. Ningún corte convierte un SHA, un índice o una traza en aprobación humana.

**Cobertura del spike G3:** sus F1-F7 eran una estimación histórica, no los nombres ni el orden normativo de este plan. F1 (ADR y revisión pre-code) se reconcilia en R0; F2 (núcleo, identidad y symlinks) en R1a; F3 (attest, hook-runs y capabilities) y F4 (CLI, MCP y upgrade) en R1c, con capabilities también en R1b; F5 (relocate) en R2a-R2b; F6 (diagnósticos, integration-status, export sellado y rollback) en R1b, R2b y R3; F7 (baseline, concurrencia y revisión final) en R0, R2a y R3. Esta distribución exige comprobar las invariantes de cada fase, no declarar una fase histórica completa por coincidencia de nombre. R1b adelanta contratos observables respecto de la estimación F6; R3 valida su coherencia tras relocate.

## Registro de seguimiento para agentes

Los issues de GitHub conservan el estado del backlog; `docs/README.md` conserva el estado de ADR. Este archivo conserva orden, criterios y enlaces de evidencia, sin reemplazarlos. Al retomar una tarea, el agente registra en su reporte: `task_id`, estado `pending|active|blocked|verified|superseded`, fecha de observación, rama/SHA/árbol, issue/PR, artefacto probado, comandos con resultado, hallazgos adversariales, siguiente acción y autoridad vigente. Si conoce sólo el modelo configurado, declara `model_effective=unknown`; distingue ejecutor y revisor. El reporte sigue `docs/agent-report-template.md` y se enlaza desde el issue o PR correspondiente cuando esa escritura esté autorizada.

Antes de cada corte: releer `AGENTS.md` y `AN-KLA.md`, consultar issues/PR, `git status`, SHA local y remoto, `context status` y `verify`; comparar contra la base observada aquí. No inicializar `.an-kla/` en un worktree. Ante timeout de una operación persistente, inspeccionar su transacción antes de repetirla. Una casilla se marca `verified` sólo con evidencia sobre el artefacto final de ese corte; una modificación posterior obliga a determinar qué comprobaciones siguen aplicando.

**Punto de control:** al iniciar y cerrar cada sesión material, actualizar el reporte y la fila pertinente del issue; si el trabajo sigue abierto, revisar el backlog al menos una vez por semana de actividad, sin convertir esa cadencia en una automatización ya programada. Al iniciar otro corte, verificar si el anterior fue absorbido, quedó parcial o fue supersedido. La tabla anterior es un corte inicial; el estado vigente se contrasta con issue, PR, ADR y Git, no se infiere de la tabla. No escribir checkpoint AN-KLA por la sola existencia de este plan. Una ronda de release examina el diff final, no sólo este plan.

## Tareas ejecutables

```text
TAREA R0 contrato y baseline de G3 (P0, #57)
Consumes: `docs/architecture/0048-store-root-externo-v1.md`, `docs/releases/v0.1.0-beta.28-adversarial.md`, `tests/test_export_restore.py`
Produce: ADR-0048 reconciliado, reporte basal fechado y matriz de compatibilidad para R1-R3
Steps:
  - [x] Contrastar nombres publicados: `startup-diagnostic-v2` ya significa vocabulario y ADR-0048 lo reserva para custodia; proponer nombre nuevo y revisar consumidores antes de editar — verificación: búsqueda en schemas, capabilities, tests y ADR sin dos significados para el mismo id; decisión normativa del maintainer registrada y cambio documental integrado antes de código G3.
  - [x] Corregir referencias históricas del fallo #119 sin borrar su procedencia ni reabrirlo por prosa antigua — verificación: `gh issue view 119` y test de export host-managed contrastados con el ADR final.
  - [x] Delimitar con ADR-0048 §Por qué no la semántica vigente de `restore`: publicación project-local y uso de `relocate` para cambiar custodia continua; si se desea restauración directa a store externo, someter ese contrato a decisión separada antes de implementarlo — verificación: matriz de operaciones y destinos sin ampliar `restore` por inferencia del plan.
  - [x] Ejecutar baseline antes de cualquier cambio en almacenamiento o concurrencia: python3 -m unittest discover -s tests -p 'test_*.py', python3 scripts/check_sizes.py, python3 scripts/check_plans.py y python3 scripts/check_adr_registry.py — verificación: guardar comandos, intérprete, SHA, conteos y salidas reales; un fallo no se llama verde.
  - [x] Delimitar las variantes: project-local legado, store externo fresco, worktree sin resolución y con resolución, macOS/Linux v1, Windows diferido — verificación: matriz con resultado esperado y criterio de falsación para cada variante.

TAREA R1a resolución de raíces e identidad sin migración (P1, #57)
Consumes: `docs/architecture/0048-store-root-externo-v1.md`, `an_kla/store.py`, `an_kla/identity.py`, `an_kla/identity_evidence.py`
Produce: núcleo de store externo fresco opt-in, compatibilidad project-local y pruebas focales; entradas aún no cubiertas identificadas y cerradas ante divergencia
Steps:
  - [x] Implementar resolución flag > env > puntero > project-local según ADR, con puntero y binding de custodia fail-closed — verificación: tests de precedencia y divergencia; `init` no crea una bóveda gemela si hay puntero incompatible.
  - [x] Reanclar todos los recorridos de identidad y symlink a la raíz de custodia; sustituir en `adopt` la igualdad de ruta por el relocation receipt exigido por ADR-0048 — verificación: init externo fresco, store legacy y proyecto de prueba movido a otra ruta; receipt válido permite adopción y receipt ausente, inválido o divergente falla cerrado, también ante symlink hostil.
  - [x] Inventariar entradas todavía no adaptadas y evitar que acuñen evidencia o abran una bóveda distinta mientras R1c esté pendiente — verificación: caso negativo por entrada afectada y límites explícitos en el reporte de R1a; no declarar el store externo utilizable de extremo a extremo.
  - [x] Repetir suite completa por tocar store y concurrencia, más gates de tamaños y planes — verificación: resultados sobre el SHA y diff de R1a, sin atribuir tests de R0 al código nuevo.

TAREA R1b observabilidad versionada (P1, #57)
Consumes: `docs/architecture/0048-store-root-externo-v1.md`, `docs/releases/v0.1.0-beta.28.md`, `an_kla/schemas/startup-diagnostic-v2.schema.json`, `an_kla/startup.py`, `an_kla/integration.py`, `an_kla/capabilities.py`
Produce: diagnósticos de custodia con schemas versionados y eje `doctor`, sin filtrar rutas
Steps:
  - [x] Publicar el identificador de startup reconciliado en R0 y `integration-status-v3` con bloque `store`; mantener congelados los schemas anteriores y preservar el bloque `vocabulary` emitido por la ruta beta.28 al definir la nueva versión de startup — verificación: goldens con y sin vocabulario, lectores de versiones viejas y nuevas, capabilities coherentes y fallo ante payload ambiguo o una extensión incompatible de v2.
  - [x] Añadir `doctor.custody_divergence` con códigos estables para puntero local, custodia resuelta y raíz canónica histórica; distinguir store ausente, project-local, externo resuelto y divergencia sin inferir agente verificado ni privacidad — verificación: pruebas de diagnóstico en esos estados, custodia separada de host-hooks y hook-runs, y revisión de salida sin rutas sensibles.
  - [x] Ejecutar suite y gates tras el cambio observable — verificación: comandos y resultados sobre el diff final de R1b.

TAREA R1c entradas de custodia y consumidores directos (P1, #57)
Consumes: R1a y R1b verificados, `docs/architecture/0048-store-root-externo-v1.md`, `docs/planning/g3-spike-store-root-2026-09-05.md`, `an_kla/attest.py`, `an_kla/hook_runs.py`, `an_kla/__main__.py`, `an_kla/cli_parser.py`, `an_kla/mcp.py`, `an_kla/upgrade.py`, `docs/hooks-template/pre-commit`
Produce: resolución de custodia coherente para atestación, hooks, CLI, MCP y upgrade; capabilities alineadas con R1b
Steps:
  - [x] Hacer que attest, hook-runs e identity-evidence reciban el store resuelto y verifiquen el mismo binding antes de acuñar — verificación: pruebas con raíces divergentes fallan cerradas sin crear receipts, nonces ni hook-runs en el lugar equivocado.
  - [x] Propagar `--store-root` y la resolución del puntero por CLI, MCP y upgrade, conservando las operaciones project-local que ADR-0048 excluye del movimiento — verificación: cada entrada abre la misma identidad/revisión con custodia externa; sin resolución o con puntero incompatible produce diagnóstico estable y no crea un store gemelo. MCP se comprueba como superficie de lectura.
  - [x] Contrastar capabilities y diagnósticos de R1b con todas estas entradas, incluido el hook Git ejecutado desde checkout principal y worktree enlazado; repetir suite completa y gates — verificación: matriz entrada × estado de custodia sobre el diff final de R1c, con comportamiento explícito si el worktree carece de resolución; sólo entonces se considera utilizable el store externo nuevo, sin afirmar que relocate o export sellado estén completos.

TAREA D0 diseño independiente de descubrimiento (P1 paralelo, #134)
Consumes: `an_kla/startup.py`, `an_kla/identity.py`, `docs/architecture/0048-store-root-externo-v1.md`
Produce: censo nuevo y propuesta de ADR para registro o descubrimiento acotado
Steps:
  - [ ] Repetir el censo de stores en alcance local autorizado, sin abrir secretos ni borrar datos; separar activos, movidos, copias y huérfanos inciertos — verificación: método, fecha, denominador y límites del censo, sin tratar los 25/4 históricos como estado actual. Mantener rutas crudas sólo en un artefacto efímero privado no rastreado; el reporte compartible contiene agregados y referencias saneadas.
  - [x] Comparar índice local orientativo, escaneo explícito y ausencia de índice frente a privacidad, rutas obsoletas, clones, relocación y recuperación — verificación: threat model con casos en que un registro falso jamás habilita `init`, lectura, borrado ni reasignación.
  - [x] Presentar decisión de contrato al maintainer antes de schema/código — verificación: ADR propuesto y criterios de aceptación enlazados a #134; ningún registro operativo creado por este corte.

TAREA R2a traslado gobernado (P2, #57)
Consumes: R1a-R1c verificados, `docs/architecture/0048-store-root-externo-v1.md`, `an_kla/export_restore.py`, `an_kla/transactions.py`
Produce: `relocate` plan y commit, con receipts y reconciliación
Steps:
  - [x] Construir plan exacto sobre revisión e identidad observadas, staging hermano y publicación sin reemplazo — verificación: destino ocupado, cambio de CURRENT y contenido alterado fallan cerrados sin borrar origen.
  - [x] Probar crash antes/después de publicación y cleanup con transaction inspect/reconciliación; probar concurrencia con lectores y escritores — verificación: cada punto de fallo deja un estado identificable y una ruta de recuperación, sin duplicar commit por timeout.
  - [x] Repetir suite completa y gates tras cambiar almacenamiento/concurrencia — verificación: resultados fechados sobre el diff de R2a.

TAREA R2b regreso y recuperación de custodia (P2, #57)
Consumes: R2a verificado, `docs/architecture/0048-store-root-externo-v1.md`, `an_kla/export_restore.py`
Produce: relocate-back por subárbol y procedimiento de rollback probado
Steps:
  - [x] Ejecutar roundtrip externo > project-local en stores de prueba, incluida falla entre subárboles — verificación: bytes, identidad, CURRENT, receipts y contenido excluido cotejados antes/después; no prometer un único rename en el regreso.
  - [x] Probar recuperación tras borrar/recrear sólo el checkout de prueba, conservando la bóveda externa — verificación: resolver identidad y revisión originales sin crear store nuevo; prueba negativa de puntero divergente.
  - [x] Cerrar con suite completa y gates — verificación: salidas sobre el artefacto final de R2b.

TAREA R3 consumidores y cierre técnico de G3 (P2, #57)
Consumes: R1-R2 verificados, `an_kla/export_restore.py`, `an_kla/sealed/bundle.py`, `tests/test_export_restore.py`, `docs/adversarial-template.md`, `docs/agent-report-template.md`
Produce: compatibilidad de export/restore, worktrees y ronda adversarial final
Steps:
  - [x] Adaptar los anchors de export claro/sellado a la custodia resuelta, conservando los carve-outs project-local y las exclusiones de claves; probar export desde store externo y restore al destino project-local que admite el contrato vigente. Un destino de restore externo requiere la decisión contractual separada de R0 — verificación: roundtrip export externo > restore project-local, destino ocupado, bundle que intenta escribir fuera del destino permitido y demás controles negativos; no publicar bundles ni claves.
  - [x] Probar worktree nuevo sin resolución y con `store_root` resuelto — verificación: primero diagnóstico de ausencia sin init; después misma identidad/revisión, sin declarar aislamiento de autoridad.
  - [x] Actualizar y verificar la regla transitoria de worktrees en la sección manual de `AGENTS.md` cuando #57 la sustituya, para que las instrucciones correspondan al comportamiento probado. Si el bloque gestionado o `AN-KLA.md` también requieren cambios, tratarlos por su flujo versionado separado — verificación: lectura de ambas instrucciones finales y prueba de los ejemplos operativos, sin inicializar otra bóveda.
  - [x] Revisar diff final con revisor de contexto fresco y suite/gates completos — verificación: acta con hallazgos, correcciones, riesgos residuales y `proceed|fix-and-retry|escalate`; sólo `proceed` permite proponer cierre/release al maintainer.

TAREA D1 registro orientativo condicionado (P3, #134)
Consumes: D0 con ADR aceptado, semántica de custodia de R1-R2 vigente, `an_kla/identity.py`
Produce: descubrimiento local gobernado por contrato propio, sólo si el maintainer lo autoriza
Steps:
  - [ ] Implementar mínimo acordado sin usar el índice como autoridad de acceso — verificación: entradas falsas, viejas, duplicadas, clones y store movido no autorizan mutación ni eligen bóveda silenciosamente.
  - [ ] Probar inventario y olvido de entrada sin borrar store, más filtración de rutas en salida — verificación: identidad y `verify` determinan estado observado; no hay eliminación física implícita.
  - [ ] Ejecutar suite y gates pertinentes sobre el diff, con ronda adversarial si toca store o contrato gestionado — verificación: reporte por issue #134 y decisión humana separada para release.

TAREA A0 threat model G4 en lectura (P3 exploratorio, #58)
Consumes: `docs/architecture/0031-agent-owned-memory-host-managed-v1.md`, evidencia G3 disponible al retomar, issue #58
Produce: matriz de amenazas y preguntas de decisión para un ADR G4 futuro
Steps:
  - [x] Modelar contaminación cross-project, divulgación, suplantación, confused deputy y falsa privacidad — verificación: contraejemplo por amenaza y fuente del control actual; `agent_binding=unverified` permanece explícito.
  - [x] Separar identidad de routing, acceso al filesystem y autoridad de escritura — verificación: ningún namespace o worktree se presenta como enforcement sin prueba.
  - [x] Proponer gates de pilotos y migración sin fijar schema ni implementar G4 — verificación: maintainer recibe opciones y riesgos, no una promoción automática.

TAREA M0 ensayo opcional de método Muse (P4 condicionado)
Consumes: `tests/test_context_view.py`, `an_kla/retrieval.py`, `docs/adversarial-template.md`
Produce: decisión de no transferir o fixture propio de falsación, sin dependencia Muse
Steps:
  - [x] Identificar un consumidor que confunda una proyección o recuperación parcial con completa y demostrar que tests actuales no detectan el fallo — verificación: caso reproducible y control positivo; si no existe, cerrar M0 como no transferir.
  - [ ] Si hay brecha, congelar input/revisión/vista esperada y mutación que produzca diff; distinguir proyección de reinferencia y autenticidad — verificación: original pasa, mutación falla, sin copiar fixtures ni protocolo MSP.
  - [ ] Comparar utilidad y mantenimiento frente a la prueba local mínima — verificación: reporte del consumidor; la adopción requiere decisión separada del maintainer.
```

## Estado de ejecución (2026-10-13)

Ejecutado por el agente bajo la autorización y delegación del maintainer
(commits, push y merge; sin tag, release ni escritura en un AN-KLA vivo).
Registros: `docs/planning/g3-*-2026-10-13.md` y `docs/planning/g4-a0-threat-model-2026-10-13.md`.

| Corte | Estado | Evidencia |
| --- | --- | --- |
| R0–R1c | hecho | PRs #141 y #142 |
| R2a, R2b | hecho | PRs #143 y #144 |
| R3 | hecho, con ronda adversarial `fix-and-retry` → `proceed` tras correcciones | PR #145; acta `g3-r3-ronda-adversarial-2026-10-13.md` |
| D0 | parcial: ADR-0050 propuesto; censo no ejecutado (requiere autorización y raíces del maintainer) | `g3-d0-descubrimiento-2026-10-13.md` |
| D1 | no iniciado: condicionado a ADR-0050 aceptado y autorización | — |
| A0 | hecho (lectura) | `g4-a0-threat-model-2026-10-13.md` |
| M0 | cerrado como «no transferir» | `g3-m0-metodo-muse-2026-10-13.md` |

Pendiente del maintainer: decisión sobre ADR-0050 y el censo; decisión de
ADR-0048 Enmienda 4 §3 (ligar una bóveda creada en otra raíz); cierre de #57
y cualquier release.

## Condiciones de parada y cierre

Detener sólo la operación afectada ante cambio de autoridad, identidad ambigua, store inesperado, discrepancia de base, fuga de secreto, prueba de control inconclusa o mutación no autorizada. Continuar tareas independientes en lectura. El estado `verified` de una tarea no equivale a aceptación de ADR, merge, release, instalación ni utilidad para consumidores. Para publicar una beta que toque store o contrato gestionado rigen la ronda adversarial y los gates del repositorio; tag, push y publicación requieren orden explícita del maintainer.
