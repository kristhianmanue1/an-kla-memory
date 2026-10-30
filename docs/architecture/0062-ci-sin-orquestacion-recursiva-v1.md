# ADR-0062: Ejecutar CI mediante un plan sin orquestación recursiva

- **Estado:** Aceptada
- **Implementación:** No iniciada
- **Fecha:** 2026-10-29
- **Decide sobre:** eliminar ciclos de orquestación y ejecuciones redundantes del CI conservando sus obligaciones.

## Contexto

La [auditoría crítica](../benchmarks/ci-orchestration-audit-2026-10-29.md)
identifica el ciclo CI→discover→fila 15→CI→discover, limitado por una guarda,
re-runs de módulos ya descubiertos y helpers copiados. El último discover
de A/B tardó 1493,463 s; aún no se midió un CI optimizado. La política local
es comprobada por `tests/test_ci_metadata.py`; no existe CI remoto de PR.

El Operador indicó «adelante con propuesta» y pidió revisar críticamente
ciclos/funciones repetidos y optimizar. Esta ADR concreta esa propuesta;
El Operador aceptó la propuesta afinada y su implementación por fases con
«adelante con recomendaciones» (2026-10-29). La decisión se fusiona antes
del código, conforme a prácticas §3. La activación del gate nuevo se
presentará después de verificar la transición y sus resultados.

## Decisión

Separar planificación, ejecución de celda y agregación en un orquestador
exterior. La suite funcional no invoca CI ni descubre otra suite completa.
El grafo de ejecución de suites debe ser acíclico sin depender de una guarda
de entorno para terminar. Los CLI funcionales y fixtures aislados continúan
siendo procesos reales cuando lo requiera su propiedad evaluada.

### Plan único y deduplicación

- Resolver intérprete real, versión, capacidad/dependencias, plataforma,
  modo y opciones relevantes antes de construir la identidad de celda.
  Deduplicar sólo tareas equivalentes del mismo árbol y corrida; no cachear
  éxitos entre corridas ni equiparar alias por nombre o versión solamente.
- Una suite completa por celda acredita a la vez el paso unittest y sus
  filas funcionales. Reemplazar re-runs de `_ROW_MODULES` y fila 11 por un
  mapa normativo a casos efectivamente ejecutados, no por presencia/import.
  Conservar casos propios y negativos de esas clases; si cambian IDs,
  registrar explícitamente su correspondencia de migración.
- Compartir helpers de fixtures en un módulo de soporte sin prefijo test;
  no importar módulos de tests entre sí ni compartir stores mutables.
  Unificar ejecución/registro de subprocess del runner, sin centralizar
  reglas funcionales ajenas ni transformar CLI de producto en mocks.
- Conservar loops/reintentos intencionales de estrés, carrera y fault
  injection. La repetición necesaria debe tener una obligación identificada.

### Perfiles y obligaciones

| Perfil | Obligaciones | Puede sustituir gate previo a push |
|---|---|---|
| Desarrollo | Suite funcional una vez en intérprete soportado ≥3.12, tests unitarios del runner y gates estructurales | No |
| Auditoría | Suites completas sin/con extra, en modos normal/simulado; compatibilidad disponible 3.9/3.12/3.13; G-3 y gates estructurales aplicables | Sólo tras aceptación de la transición y equivalencia comprobada |

La base de auditoría comprende cuatro celdas (dos perfiles de dependencias
por dos modos), cada una une suite y CI sin relanzarlos. Las piernas de
compatibilidad conservan una suite directa por intérprete disponible distinto,
con sus dependencias y el entorno efectivo que recibía `paso_matriz`:
CI/GITHUB_ACTIONS capturados al entrar al runner, no el modo simulado que
`paso_tests` sólo inyecta en su hijo. Ese entorno queda explícito en el plan;
no se añaden ambos modos automáticamente a cada versión. Si el inventario
previo muestra una obligación distinta de modo ejecutada por los hijos
antiguos, debe tener sustituto trazable o quedar pendiente, nunca descartarse
como redundancia sin evidencia. Las ampliaciones deliberadas de cobertura
se separan y requieren decisión; no son optimizaciones de orquestación.
No se exige todo el producto cartesiano con todos los SO ni se
declara multiplataforma lo observado sólo aquí. No se cambia `requires-python`.
El desarrollo/gate principal sigue en Python ≥3.12 soportado; versiones
menores sólo se reportan como compatibilidad.

Seleccionar entornos existentes explícitamente, con sondeo de versión,
ejecutable y capacidad criptográfica real; no asumir CLT portable ni instalar
dependencias automáticamente. La base sin extra usa el principal ≥3.12
verificado (preferir `.venv` si cumple); si tiene criptografía, se requiere
otro entorno sin extra ≥3.12 real, no fingirlo bloqueando imports. La base
con extra usa un intérprete soportado explícitamente resuelto y sondeado:
CLT <3.12 puede cubrir cripto/compatibilidad en este host, nunca el gate
principal. Si falta un perfil requerido, la auditoría queda incompleta.
Normal limpia CI/GITHUB_ACTIONS heredados;
simulado los fija, con comprobación desde el hijo. Debe diferenciarse un
entorno sin extra real de bloquear imports sólo durante un test.

La matriz mínima de aplicación queda fijada así:

| Tarea exterior | Dimensiones | Compartir ejecución | Ausencia/skip |
|---|---|---|---|
| Suite y filas 1–16 | Cada celda base y de compatibilidad disponible | Sólo celda idéntica, con casos efectivos trazables | Perfil base ausente o caso requerido saltado: incompleto y rc no cero |
| Import del paquete | Cada entorno de intérprete/dependencias distinto | Una vez si sólo cambia el modo CI y se verifica igualdad de resolución | Import ausente/fallido: rc no cero |
| Tamaños, planes, registro | Árbol y configuración inmutables; intérprete principal ≥3.12 | Una ejecución por script y firma de entradas en la corrida | Script ausente, entradas cambiadas o evidencia inválida: rc no cero |
| G-3 selftest completo | Cada entorno de intérprete/dependencias realmente exigido por el inventario previo, mismo estado canónico | Una vez por entorno efectivo equivalente, no automáticamente por modo de suite | Requerido para aceptación aquí; ausencia inesperada: incompleto y rc no cero |
| Resolución de compatibilidad | 3.9/3.12/3.13, ejecutable real | Alias de la misma celda sólo tras sondeo | Intérprete no disponible: SKIP opcional explícito; no prueba esa versión |

G-3 conserva sondeo negativo del guard sobre la raíz canónica (rechazo
esperado), copia temporal, ataque sólo a la copia y verificación posterior.
Nunca atacar el store canónico. En un clon fresco sin store sigue siendo
legítimo diagnosticar el SKIP que permite el contrato vigente; no se crea ni
copia memoria para subsanarlo, y esa corrida no sustituye la aceptación
G-3 requerida aquí. No se usa el SHA de Git como prueba de inmutabilidad:
la firma de entradas incluye código de los gates, configuración, rutas,
existencias y bytes que inspeccionan, incluidos archivos no versionados.
Si cambian durante la corrida, invalidar su evidencia y salir con error;
no repetir en bucle hasta obtener verde. No reutilizar éxitos entre corridas.
Logs y temporales del runner deben vivir fuera de esas entradas (o en una
exclusión ya adoptada y declarada), para que el propio registro de evidencia
no altere el árbol evaluado. No inventar exclusiones para esconder cambios.

Justificación acotada de la consolidación estructural: los tres scripts
inspeccionados leen archivos/configuración y no consultan CI/GITHUB_ACTIONS
ni lanzan suites. La [sonda con control positivo](../benchmarks/evidence/ci-orchestration-20261029/gate-environment-probe.json)
obtuvo rc/stdout/stderr idénticos en ambos modos con Python 3.12.12, tras
comprobar desde hijos que las variables sí diferían. No demuestra igualdad
entre versiones/SO. La sonda es anterior a completar esta documentación:
sus conteos no describen el árbol final. La obligación consolidada del runner
es verificar el árbol de su corrida en el intérprete principal, no acreditar
portabilidad de los scripts. Si el mapa
previo identifica una obligación adicional de compatibilidad de gates, se
conserva separada hasta justificar su sustitución.

Para G-3 no basta esa sonda: su CLI depende del runtime y del entorno.
Registrar comando, intérprete, `sys.prefix`, dependencias, flags relevantes,
estado copiado y entorno efectivo; sólo fusionar tareas con iguales entradas
y propiedad probada. En primera implementación conservar sus variantes del
inventario previo cuando no haya evidencia de equivalencia. Lo mismo aplica
al import: sin prueba de igualdad por modo, se conserva esa variante.
Un binario resuelto al mismo realpath no identifica por sí solo un venv.
Los gates REL clean wheel y upgrade de ADR-0042 permanecen adicionales.

### Fallos y evidencia

Cada obligación debe enlazar a casos esperados, ejecutados, resultados y
skips. Un caso crítico saltado, suite vacía, timeout, hijo muerto o evidencia
incompleta no acredita esa obligación. Reportar dimensiones ausentes como
incompletas; un SKIP no se convierte en aceptación de cobertura requerida.
Conservar razones de skips legítimos de plataforma y su alcance.

Auditoría emite resumen por tarea: **rc cero si y sólo si todas las
obligaciones requeridas están acreditadas**. Ausencia requerida, skip crítico,
timeout, evidencia inválida o ejecución incompleta producen rc distinto de
cero, aunque no haya un test marcado FAIL. La tabla distingue disponibilidad
opcional de la que impide completar; los skips opcionales quedan visibles
como límites de alcance, no como cobertura efectiva.
Los escapes heredados no pueden convertir auditoría en desarrollo silencioso.

### Presupuesto temporal y cierre de procesos

Presupuestos iniciales **propuestos**, no tiempos esperados ni resultados:
sondeo/import 15 s, cada gate estructural 60 s, G-3 180 s, suite por celda
900 s y auditoría total 7200 s de pared. El margen de suite toma como
referencia hijos históricos de hasta 524,650 s, que aún incluían re-runs;
no es calibración del runner nuevo ni garantía de terminar en otros hosts.
Los límites se fijan y registran antes de empezar; nunca se amplían ni
reintenta automáticamente una tarea por timeout para lograr verde.

Usar reloj monotónico y deadline global, también durante sondeos y gates.
Para cada hijo el deadline efectivo es el menor entre su límite y el global;
reservar dentro de ellos 5 s de cierre (hasta 3 s TERM y 2 s KILL/recolección).
Al vencer, dejar de lanzar tareas y marcar las no iniciadas. La espera del
supervisor es acotada: un proceso que no pueda recolectarse no permite seguir
esperando ni declarar éxito; registrar `teardown_incomplete`, rc no cero.

Crear contención del árbol antes de lanzar el trabajo: sesión/grupo propio
en POSIX y mecanismo de árbol probado en Windows. Terminar descendientes,
no sólo el hijo directo; después recoger/recolectar y comprobar ausencia de
supervivientes del trabajo. No matar procesos externos a la contención.
La garantía cubre procesos cooperativos de pruebas, no código hostil que
escape deliberadamente del supervisor. Sin mecanismo probado no iniciar
auditoría pretendiendo garantizar cierre. Incluso con rc cero del hijo,
descendientes residuales o cierre incierto impiden éxito.

Volcar stdout/stderr incrementalmente a archivos, con cuota declarada y
marca de truncamiento, sin retener todo en RAM. Guardar plan y resultados
por tarea al completarse, más resumen al abortar: tiempos, rc/señal,
deadline, etapa del cierre y tareas no ejecutadas. Error de escritura o
pérdida de evidencia requerida impide aceptación. Conservar parciales;
no borrar artefactos para encubrir fallos ni escribir memoria canónica.

## Por qué no otras alternativas

- **Sólo paralelizar:** oculta repetición y añade contención; primero se
  elimina trabajo redundante y se mide secuencialmente.
- **Sólo saltar fila 15:** pierde obligaciones de perfiles/CI y deja re-runs.
- **Una única suite sin extra:** no verifica criptografía ni el otro modo.
- **Eliminar todo subprocess/helper repetido:** confunde aislamiento y
  pruebas de fallos con redundancia; compartir fixtures mutables introduce
  dependencia entre tests y falsos positivos.

## Consecuencias

Un solo dueño del plan evita ciclos; el mapa de casos permite auditar qué
prueba cada ejecución. Habrá nuevos tests de orquestación y coste de mantener
el mapa. Corregir cobertura omitida hoy puede añadir trabajo útil; no se
garantiza un porcentaje de aceleración. Actualizar documentación obsoleta
de CI remoto/tiempos en la transición, sin atribuir pruebas de otros SO.
No se cambia storage, release, memoria canónica ni escala 20.000 pospuesta.

## Test de regresión y transición

1. Capturar inventario efectivo del CI vigente y del nuevo sobre el mismo
   árbol funcional y entornos; registrar hashes, casos, duración y skips.
   Cada re-run retirado debe tener sustituto trazable de igual obligación.
2. Verificar plan sin celdas idénticas duplicadas y sin aristas de retorno;
   comprobar procesos reales además de tests unitarios con mocks.
3. Inyectar fallos en suite, cripto, ambos modos, matriz disponible, G-3 y
   gates; exigir rc no cero y diagnóstico del responsable. Cubrir suite
   vacía/todo-skips, timeout, muerte del hijo y entornos/escapes heredados.
   Incluir control positivo hijo+nieto con heartbeat que ignore TERM:
   detectar el heartbeat antes del corte, escalar a KILL y comprobar que
   cesa y no quedan procesos; heartbeat ausente desde el inicio no prueba
   limpieza. Probar deadline global, hijo salido con nieto vivo, cierre
   incompleto, disco/log truncado y conservación de resultados parciales.
4. Comparar tiempos sin corridas propias simultáneas, registrar repeticiones
   y límites del host; no sumar dos veces padres e hijos.
5. Fusionar ADR antes del código. Ejecutar CI vigente antes de publicar
   implementación, revisión adversarial fresca y aceptación explícita de la
   transición. Hasta entonces el gate anterior permanece vigente.

## Referencias

- [Diseño inicial de perfiles](../planning/ci-profiles-design-2026-10-29.md).
- [Coste observado](../benchmarks/test-suite-cost-2026-10-29.md).
- [ADR-0042 y matriz normativa](0042-sealed-export-v1.md).
- [Prácticas de ingeniería](../practicas-ingenieria.md), §1, §3 y §5.
- [Ronda adversarial](../planning/adr0062-adversarial-2026-10-29.md): fix-and-retry → proceed documental.
