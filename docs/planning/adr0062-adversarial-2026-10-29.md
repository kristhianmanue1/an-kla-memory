# ADR-0062 — revisión adversarial del rediseño CI

**Resultado:** `fix-and-retry` → `proceed documental` (2026-10-29).
**Alcance:** [ADR propuesta](../architecture/0062-ci-sin-orquestacion-recursiva-v1.md),
[auditoría crítica](../benchmarks/ci-orchestration-audit-2026-10-29.md) e inventario.
No se acredita un runner optimizado ni equivalencia ejecutada.

**Vigencia:** la ronda inicial siguiente es histórica. Tras el análisis
crítico del productor y la orden del Operador de afinar tres puntos, la
propuesta se modificó; la ronda de refinamiento al final acredita esa versión.

## Separación de revisión

Produjo `/root`; revisó `/root/review_ci_adr0062`, iniciado con
`fork_turns=none`, sin historial del productor, mediante encargo acotado y
lectura de archivos. Comparte entorno y configuración de modelo heredada;
no hay aislamiento de HOME/cachés ni independencia de proveedor verificada.
La separación es de contexto. No se afirma identidad de modelo verificada.

El revisor contrastó scripts, clases de matriz, apéndice ADR-0042 y selftest
G-3. No editó archivos, escribió memoria, hizo Git ni lanzó CI/suite completa.
Su consulta de issues/PRs falló por conectividad; el productor obtuvo por
consulta escalada cinco issues abiertos y ningún PR, antes de editar.

## Hallazgos, correcciones y confirmación

1. **M1, bloqueante documental:** «fallar ante FAIL» no bastaba. Un perfil
   requerido ausente podía dar PARCIAL con rc cero. Corrección: rc cero si y
   sólo si todas las obligaciones requeridas están acreditadas; ausencias,
   skips críticos, timeouts y evidencia incompleta dan rc no cero.
2. **M2, bloqueante documental:** faltaba fijar matriz de aplicación, en vez
   de diferir selección de intérpretes y alcance de gates a implementación.
   Corrección: cuatro celdas base, principal sin extra ≥3.12, cripto resuelto
   explícitamente, compatibilidad disponible en ambos modos y gates por celda
   sin compartir entre celdas durante esta transición. G-3 mantiene rechazo
   del guard canónico y ataque sólo a copia; ausencia de store en clon nuevo
   no acredita aceptación G-3 requerida en el checkout canónico.

El revisor releyó las correcciones en disco en una ronda de confirmación y
emitió `proceed documental`, sin bloqueantes residuales. El veredicto no
acepta la ADR ni autoriza implementación/publicación/cambio de gate.

## Evidencia y límites

Revisor:

- `.venv/bin/python --version` → Python 3.12.12.
- `context status` → ok=true, sin diagnósticos.
- `unittest tests.test_ci_local_matriz -v` → 6 tests OK (0,002 s), con mocks;
  no acreditan una pierna real de matriz.
- `runpy.run_path(inventory.py)['inventory']()` igual al JSON → True;
  14 entradas del mapa de filas, 8 módulos únicos, 5 grupos AST idénticos.

Productor, sobre el árbol documental local basado en
`888299251fe269652ee2c28292fb9c2b67bc4ebf`, Python 3.12.12:

| Comando | Resultado |
|---|---|
| `scripts/check_sizes.py` | OK |
| `scripts/check_plans.py` | OK, 4 planes |
| `scripts/check_adr_registry.py` | OK, 62 ADRs: 56 aceptadas, 6 propuestas |
| `-m unittest tests.test_adr_registry tests.test_ci_local_matriz tests.test_ci_metadata` | 10 tests OK, 0,008 s |
| Reproducción del inventario estático contra JSON | Igualdad exacta |
| `git diff --check` | Sin errores |

Los comandos Python anteriores usan `.venv/bin/python`. El único cambio a
tests es el pin de seis ADR propuestas en el registro; no modifica tests de
orquestación ni ejecución del CI. El inventario es evidencia estática
acotada, no perfilado dinámico. No hay porcentaje de aceleración medido.
No se repitió CI completo ni se publicó el cambio. La regla de CI vigente
antes de push/merge permanece aplicable. La ADR queda propuesta, pendiente
de decisión del Operador antes de implementarla. Escala 20.000 sigue pospuesta.

## Refinamiento de tres puntos y nueva revisión

El análisis posterior del productor devolvió `fix-and-retry`: la matriz
por celda podía añadir trabajo innecesario, compatibilidad replicaba modos
automáticamente y faltaba presupuesto temporal ejecutable. El Operador
autorizó afinar esos tres puntos, sin pedir cambio del runner.

Correcciones:

1. **Gates por entradas:** tamaños/planes/registro una vez por firma de
   entradas en el intérprete principal. Firma incluye archivos sin versionar
   y cambios invalidan evidencia; logs/temporales fuera de esas entradas o
   exclusión ya adoptada. Import/G-3 conservan diferencias de runtime y sólo
   se comparten con equivalencia demostrada, incluyendo `sys.prefix`.
2. **Compatibilidad:** conservar modo efectivo del paso directo previo,
   sin añadir dos modos por versión. Obligaciones distintas observadas en
   hijos anteriores requieren sustituto; ampliaciones quedan separadas.
3. **Tiempo y evidencia:** límites propuestos por tarea y global de pared,
   reloj monotónico, reserva de cierre dentro del deadline, contención y
   terminación de descendientes, teardown incierto como fallo y logs
   incrementales con conservación de resultados parciales. No son tiempos
   medidos del runner nuevo.

Revisor `/root/review_ci_three_refinements`, iniciado con `fork_turns=none`,
sin historial del productor: lectura de ADR, auditoría, sonda/script/JSON,
runner, matrices y gates. Mismo entorno/configuración de modelo heredada;
separación de contexto, sin independencia de proveedor ni aislamiento del
entorno. No editó ni ejecutó CI, suite completa, G-3 o memoria.

Verificó Python 3.12.12, context status ok, sizes OK (643 textos), planes OK
(4), registro OK (62), cinco issues abiertos y ningún PR. Emitió
`proceed documental`, sin bloqueantes. Tras releer las precisiones de
ubicación de logs y temporalidad de la sonda, confirmó el veredicto.

La sonda del productor ejecutó los tres gates en modos normal y simulado:
rc/stdout/stderr idénticos, seis rc cero; control positivo desde hijos
acreditó CI/GITHUB_ACTIONS distintos. JSON registra 642 textos de aquel
snapshot, no el conteo final. Sólo acredita mismo árbol/intérprete y esas
dos variables; no otros Python/SO ni equivalencia G-3.

Comprobaciones finales del productor con `.venv/bin/python`:
sizes OK (643), planes OK (4), registro OK (62: 56 aceptadas/6 propuestas),
10 tests dirigidos OK en 0,023 s, `git diff --check` sin errores y diff vacío
en runner y tests de orquestación. El pin de registro sigue siendo el único
cambio a tests. Los tiempos de las actas previas se conservan históricos.

**Cierre:** OK documental, `proceed`. ADR aún propuesta, runner intacto,
sin CI completo nuevo ni commit/push/merge de este trabajo documental.
No se afirma aceleración ni equivalencia implementada. Continúa pendiente
la decisión sobre esta ADR antes de la fase de código; 20.000 sigue pospuesta.

## Aceptación posterior y gate previo a integración

El Operador autorizó «adelante con recomendaciones» después de recomendar
aceptar/fusionar ADR-0062, implementar por fases y presentar resultados antes
de activar el nuevo gate. La ADR y el registro pasan a Aceptada; activación
no se infiere del merge documental.

`.venv/bin/python scripts/ci_local.py --simulate-ci` → exit 0, siete pasos OK;
discover principal: **1304 tests, 74 skips, 712,498 s**. G-3 OK;
3.12 cubierta, 3.9/3.13 no disponibles por nombre en PATH (SKIP); CLT sigue
ejecutándose desde fila 15. No se desactivaron filas selladas.
[Log](../benchmarks/evidence/ci-orchestration-20261029/docs-acceptance-ci.txt).
Este tiempo menor al histórico de 1493,463 s aún corresponde al runner viejo:
no acredita aceleración por optimización. Tras guardar log/acta se repiten
gates documentales; el código probado no cambia por incorporar esa evidencia.
