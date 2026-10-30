# Propuesta: separar desarrollo y auditoría del CI local

**Estado:** propuesta documental, no adoptada ni implementada.
**Fecha:** 2026-10-29. **Base inspeccionada:** `888299251fe269652ee2c28292fb9c2b67bc4ebf`.
El Operador autorizó registrar la postergación de escala y preparar este
mapa/diseño. No se cambian scripts, tests, dependencias ni gates actuales.
Cambiar la política requerirá ADR aceptada y fusionada antes del código.
**Revisión:** [acta adversarial](ci-profiles-adversarial-2026-10-29.md),
`proceed documental`; no implica aceptación ni activación de estos perfiles.

## Refinamiento pedido por el Operador

Tras presentar este diseño, el Operador pidió revisar críticamente ciclos y
funciones repetidos y optimizar el CI. La
[auditoría crítica](../benchmarks/ci-orchestration-audit-2026-10-29.md) concreta
prioridades y distingue repeticiones necesarias de redundancia. La
[ADR-0062 propuesta](../architecture/0062-ci-sin-orquestacion-recursiva-v1.md)
formaliza plan único, celdas deduplicadas y evidencia efectiva de cobertura.
La ronda inicial enlazada arriba sólo acredita el diseño inicial; la ADR y
este refinamiento tienen su [propia ronda](adr0062-adversarial-2026-10-29.md),
fix-and-retry → proceed documental. No se ha cambiado el runner.

Una revisión crítica posterior pidió afinar tres puntos: consolidación de
gates según sus entradas, compatibilidad sin ampliar modos automáticamente
y presupuestos con cierre de descendientes/evidencia parcial. La ADR-0062
incorpora ese refinamiento; las actas anteriores describen sus versiones
históricas y no acreditan por sí solas la propuesta modificada.

## Diagnóstico y fuentes

El [informe de coste](../benchmarks/test-suite-cost-2026-10-29.md) explica la
multiplicación de suites. El último CI de A/B contó 1304 tests principales,
74 skips y 1493,463 s para el discover principal. El tiempo incluye hijos;
el contador principal no suma sus casos ni acredita 1304 casos efectivos
sin skips. Los módulos hijos repiten casos ya descubiertos por el padre.
No se perfiló el coste por familia ni se promete una reducción determinada.

| Obligación | Ejecución vigente y fuente | Repetición / límite |
|---|---|---|
| Importabilidad, suite principal | `scripts/ci_local.py:paso_import`, `paso_tests` | Un discover principal; `--simulate-ci` inyecta CI/GITHUB_ACTIONS en él |
| Fila 15, suite sin/con extra | `tests/test_sealed_matrix_rows.py:Row15SuiteBothProfilesTests` | Dos discovers: intérprete actual y CLT por ruta explícita; guarda `ANKLA_MATRIX_ROW15_ACTIVE` evita recursión de esta clase |
| Fila 15, CI normal y simulado | `Row15SuiteBothProfilesTests.test_ci_local_both_modes` | Dos CI hijos, cada uno con otro discover; matriz de intérpretes desactivada sólo en esos hijos |
| Filas de sellado con fuente declarada | `tests/test_sealed_matrix.py:_ROW_MODULES`, `MatrixReRunTests` | Deduplica módulos dentro de cada llamada; los repite en cada suite padre/hija y también con CLT |
| Fila 11, legado v1 sin extra | `tests/test_sealed_matrix_rows.py:Row11V1BundlesUnchangedTests` | Repite export/restore y compactación; además tiene roundtrip y control negativo de imports, que deben conservarse |
| Compatibilidad de intérpretes | `scripts/ci_local.py:paso_matriz` | 3.9/3.12/3.13; disponible distinto del principal ejecuta discover completo, incluida su propia fila 15; ausente declara SKIP |
| Resolución/escape de matriz | `tests/test_ci_local_matriz.py` | Tests con mocks; no acreditan la ejecución real de una pierna |
| G-3 | `scripts/ci_local.py:paso_redteam_selftest` | En CI exterior y dos CI hijos; copia desechable, requiere store canónico; ausencia declara SKIP |
| Tamaños, planes y registro ADR | `scripts/ci_local.py:paso_sizes`, `paso_plans`, `paso_adrs` | Exterior y dos CI hijos; conservar fallos como bloqueantes |

Las repeticiones son candidatas a consolidación, no pruebas intercambiables
ya demostradas. El conjunto exacto depende de intérpretes, dependencias,
entorno heredado, plataforma y skips. El número aproximado de cinco suites
del informe no incluye toda pierna adicional disponible en PATH.

La [fila 15 normativa](../architecture/refs/sealed-export-v1-appendix.md)
exige suite completa y CI local sin/con extra. El código lanza los dos CI
con `sys.executable`; el discover CLT separado no demuestra por sí solo CI
con extra. El diseño debe resolver esa diferencia, no usar el comportamiento
vigente como definición suficiente de la obligación. Los gates REL de clean
wheel y upgrade de ADR-0042 son adicionales: estos perfiles locales no los
sustituyen ni se consideran evidencia de release.

El checkout no contiene `.github/workflows/`; no acredita CI remoto
multiplataforma. El encabezado de `ci_local.py` y §5 de prácticas aún hablan
de un workflow remoto y tiempos antiguos: corregir esas descripciones en
el futuro cambio, sin presentar una simulación local como tres SO probados.

## Perfiles propuestos

**Desarrollo:** suite directa una vez en Python soportado ≥3.12, controles
de orquestación sin lanzar suites completas y gates de estructura. Debe
conservar todos los casos funcionales que correspondan a ese entorno,
incluidos los controles negativos de ausencia de extra. Reporta explícitamente
las dimensiones no ejecutadas. No habilita push/merge ni sustituye auditoría.

**Auditoría:** orquestador exterior que ejecuta las obligaciones completas
por intérprete/perfil/modo exigido, agrega fallos y emite inventario de casos,
skips, entorno y duración. La suite funcional no vuelve a invocar el CI.
Las filas 1–16 conservan trazabilidad a casos efectivos; se reemplaza su
re-ejecución redundante sólo cuando el inventario acredita su cobertura.
G-3 y gates estructurales siguen siendo obligatorios conforme al contrato
vigente; no se reemplazan por un mock ni se ejecutan ataques en el canónico.

Normal y simulado son modos de entorno independientes: el orquestador debe
retirar CI/GITHUB_ACTIONS heredados en el normal y fijarlos en el simulado,
con sondas que comprueben lo observado por cada hijo. Actualmente los hijos
normales heredan esas variables si el CI exterior corre con `--simulate-ci`;
por ello el nombre «normal» no demuestra hoy un entorno sin CI.

No confundir versión con dependencias: `.venv` 3.12.12 se observó sin
cryptography; CLT es una pierna heredada separada. Se mantendrán ambos perfiles
sin/con extra, con capacidad criptográfica comprobada antes de tests. No se
instala nada en este encargo. La selección portable del intérprete con extra
y la provisión de entornos se resolverán en ADR; no se supondrá que CLT existe
en Windows/Linux. El intérprete principal de desarrollo/gates seguirá ≥3.12
dentro de `requires-python`; no se retira compatibilidad 3.9/3.13 ni se
reinterpreta el rango de soporte del paquete como sólo esas tres versiones.

## Criterios antes de retirar una ejecución

1. Inventariar ambos planes en el mismo árbol, registrando por caso:
   identificador completo, hash del árbol probado, intérprete real y versión,
   dependencias/capacidad criptográfica, modo y entorno relevante, plataforma,
   resultado y razón de skip. Conservar logs crudos y duración por proceso;
   no sumar de nuevo el tiempo de los hijos al tiempo del padre.
2. Comparar obligaciones, no sólo conteos ni nombres de módulos. Cada fila
   criptográfica requerida debe mostrar sus casos esperados ejecutados; un
   `OK` con todos o algunos casos críticos saltados no prueba la fila.
   Para cada ejecución retirada, enlazar la que la cubre en las mismas
   dimensiones o declarar una diferencia que exige decisión del Operador.
3. No exigir inicialmente todo el producto cartesiano de versiones × extras
   × modos × SO: preservar el conjunto realmente exigido por ADR-0042 y
   contratos, explicitar sus huecos y no convertirlos en cobertura observada.
   Una dependencia/intérprete ausente conserva su SKIP visible; no acredita
   esa pierna ni una auditoría completa donde sea obligatoria.
4. Inyectar fallo en caso funcional, fila criptográfica, CI normal/simulado,
   G-3, matriz disponible y cada gate: auditoría debe salir distinto de cero
   y señalar la obligación. Verificar discover vacío, todo-skips, fallo de
   import, timeout y proceso hijo muerto: ninguno puede producir éxito falso.
5. Separar tests unitarios del orquestador (mocks) de al menos una integración
   real del camino de auditoría. Impedir recursión por estructura; ninguna
   variable heredada puede rebajar silenciosamente el gate de publicación.
6. Comparar duraciones secuencialmente, sin otras corridas propias simultáneas,
   con condiciones y repeticiones declaradas. No fijar un porcentaje de mejora
   antes de medir; la conservación de obligaciones prima sobre la rapidez.

## Secuencia y límite de autorización

1. Completar revisión adversarial de este mapa/diseño, corrigiendo bloqueantes.
2. Presentar al Operador la propuesta concreta; aún no activa perfiles nuevos.
3. Si acepta el cambio de política, redactar/aceptar/fusionar ADR antes del
   código, incluyendo matriz normativa y tratamiento de dimensiones ausentes.
4. Implementar en fase separada, medir equivalencia y tiempos, revisar con
   contexto fresco y ejecutar el CI vigente antes de publicar la transición.
   El nuevo gate sólo sustituye al anterior tras aceptación explícita.

La prueba real de 20.000 revisiones está **pospuesta por espacio**, fuera del
alcance activo por decisión del Operador. Se conserva sin validar ese criterio;
no se introduce en desarrollo/auditoría, ni se sustituye por lotes. #169 sigue
condicionada a `snapshot() > 0,5 s` sostenido; la lentitud total del CI no lo
demuestra. SQLite, G4 y cambios del formato persistente quedan fuera del diseño.
