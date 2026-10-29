# Tamaño y coste de la suite — 2026-10-29

## Qué se contó

Antes del fix de la sonda había **1285 casos** en el discover principal.
Después se añadieron cinco tests dirigidos de reintento/cleanup; no se
presentan como cobertura ejecutada en el resultado inicial de 1285.
Los skips y subtests tienen contabilidad propia de unittest: el contador no
representa casos únicos de negocio ni todas las aserciones ejecutadas.

`Row15SuiteBothProfilesTests`, en `tests/test_sealed_matrix_rows.py`, lanza:

1. CI local normal (incluye otro discover completo).
2. CI local --simulate-ci (incluye otro discover completo).
3. Discover completo con el intérprete principal.
4. Discover completo con CLT y las dependencias criptográficas disponibles.

En esas suites hijas la fila15 se salta mediante su protección contra
recursión; no es recursión infinita. Con los conteos previos, cinco niveles
principales/hijos suman aproximadamente `1285 + 4*1282 = 6413` casos
contabilizados por un discover de nivel superior, con repeticiones y skips.
No son 6413 tests distintos. Además `MatrixReRunTests` vuelve a ejecutar los
módulos fuente de las filas de sellado, y la fila11 vuelve a ejecutar export
restore y compactación en cada suite. El número efectivo de invocaciones de
casos puede ser mayor; no se midió exhaustivamente.

CI local también contiene una matriz adicional de intérpretes. En la corrida
fallida de esta sesión, python3.9 y python3.13 no estaban en PATH bajo esos
nombres; 3.12 quedó cubierta por el discover. Esto no impidió que fila15
localizara CLT por su ruta explícita.

## Tamaño del árbol de pruebas

Medición con Python3.12.12 sobre el árbol actual, incluido el nuevo módulo
`test_scale_probe_retries.py`: **106 módulos test_*.py**, **1.286.335 bytes**
de código de tests; **115 archivos / 1.344.236 bytes** en tests incluyendo
fixtures, excluyendo `__pycache__` y `.pyc`. Es tamaño lógico por `stat().st_size`.
No incluye stores temporales creados por las pruebas ni sus procesos hijos.
Reproducción: enumerar `Path("tests").rglob("test_*.py")` para módulos y todos
los archivos bajo tests excluyendo cachés, y sumar sus tamaños.

## Tamaño de la batería dentro de unittest

Son los overrides `SMOKE_OVERRIDES` en `benchmarks/scale/battery.py`, no una
corrida oficial all-v2 a escala:

| Familia | Smoke configurado |
|---|---|
| Ingesta gobernada | 6 registros por celda |
| Lote | 6 registros, lote2 |
| Lecturas diagnósticas | 50 registros, lote25 |
| Concurrencia v1/v2 | precarga40, 2 escritores y 2 lectores, 3s |
| Crash v1 | precarga10, 2 intentos |
| Compactación v1/v2 | 12 revisiones |
| Ingesta CLI | 4 registros |
| Término raro | 250 registros, lote125 |
| Crash mid-commit | precarga30, 2 intentos |

Estos tamaños no describen todos los fixtures de la suite. No se midió el
máximo de registros o bytes de TODOS los tests; los datos de esta tabla son
únicamente los smoke de la batería. No se corrieron 20k revisiones durante
este CI ni se creó el store hipotético de 14,60GB descrito en la otra nota.

## Tiempos reales y límites de interpretación

- Suite inicial invocada como `python3 -m unittest discover ...`: Python CLT
  3.9.6, **1285 OK**, cinco skips, **2611,457s = 43,52min**.
- CI local fallido sobre el cambio documental: principal Python 3.12.12,
  **1285 casos**, tres fallos de Row15 por cascada de la carrera CAS de la
  sonda de compactación, **1844,750s = 30,75min** para el discover.
- Hijos visibles en ese log: **317,917s**, **333,750s**, **524,650s**
  (5,30 / 5,56 / 8,74min); no sumar esas cifras de nuevo al total del padre.
- Smoke V2 dirigido tras el fix inicial: cinco familias, un test con
  subtests, **18,081s**, OK. No equivale a todo el CI.

Fuentes temporales: `/private/tmp/adr0061-baseline-tests.log`,
`/private/tmp/adr0061-docs-ci.log`, `/private/tmp/adr0061-smoke-fixed.log`.
Los tiempos corresponden a esas condiciones, no a un benchmark comparativo
entre Python3.9 y3.12. Las corridas principales iniciales se lanzaron en
paralelo: hubo trabajo redundante e interferencia potencial, sin aislamiento
para atribuir diferencias a la versión de Python.

La principal multiplicación demostrada es de orquestación. Cada suite además
ejecuta CLI en subprocesos, filesystem durable, export/restore, compactación,
crash y variantes criptográficas; no se perfiló cuánto aporta cada categoría
al total. La afirmación de que la demora procede de un corpus gigante no
está respaldada por estos smoke.

## Regla de trabajo y mejora futura

El Operador fijó Python **≥3.12** para desarrollo, sondas, gates y revisión;
resolver explícitamente `.venv/bin/python` u otro intérprete soportado ≥3.12.
La compatibilidad heredada se reporta por separado, sin confundirla con ese
gate. Se conserva el resultado de3.9; no se cambia el rango del paquete.

Una mejora posterior puede separar una suite rápida de la matriz de auditoría
y eliminar duplicados manteniendo la misma cobertura. Esta nota no autoriza
retirar filas ni saltar gates: durante ADR-0061 se mantienen las condiciones
adoptadas. Cualquier rediseño de CI deberá medir duración/cobertura y tener
su propio cambio revisado.


## Actualización tras ADR-0061

El CI final de implementación, con Python3.12.12, contó **1304 tests**,
74 skips y1493,463s (24,89min), con resultado ci_local: OK. Incluye las cinco
pruebas del harness y catorce de traversal/proyecciones; sus casos virtuales
20k no son una construcción de20k revisiones en disco. El código de pruebas
sigue siendo pequeño frente a la multiplicación de ejecuciones: los conteos
y tiempos anteriores son cortes históricos distintos, no pruebas de que la
versión de Python o este cambio expliquen por sí solos toda la diferencia.
El log final está en evidence/adr0061-comparison-20261029/implementation-ci.txt.
