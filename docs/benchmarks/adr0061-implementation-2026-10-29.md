# ADR-0061 — implementación y medición acotada (2026-10-29)

## Resultado y artefactos

Implementadas A (linaje consolidado) y B (proyección efímera para scan), sin
cambiar JSON públicos, bytes de manifiestos, CAS o autoridad. Las consultas
históricas de relación auditan la cadena completa para no ocultar corrupción;
el caso posicional current de un commit nuevo conserva su camino rápido.
La revisión fresca cerró fix-and-retry → proceed tras corregir ese hallazgo.
[Acta](../planning/adr0061-implementation-adversarial-2026-10-29.md).

Las tres corridas del código final completaron 500 revisiones bajo 90s. Las
tres del baseline no llegaron a 500 bajo ese límite. A igualdad de300,
mediana de40,708s a18,581s: mejora observada de2,19×. No es una garantía
estadística, productiva o de escala20k, ni aísla la ganancia marginal B frente
A: A tiene una sola muestra y hay variación de carga entre ejecuciones.

## Método y procedencia

- Intérprete explícito Python3.12.12, misma máquina macOS27.2 arm64.
- Baseline: código archivado desde Git14b69f5, verificación byte a byte de
  siete módulos críticos contra blobs Git. FaseA: base888504c + tres módulos
  cambiados; faseB final: base888504c + ocho módulos cambiados.
- Archivos/hash de cada fase en
  [evidence/adr0061-comparison-20261029/](evidence/adr0061-comparison-20261029/).
  Los ocho archivos de faseB se contrastaron con el árbol de trabajo después
  de medir: coincidieron. Los cambios de documentación no cambian esos bytes.
- Cada worker importa explícitamente su árbol de código en un proceso nuevo,
  verifica la ruta efectiva del paquete y usa un store efímero nuevo externo
  al checkout. AN_KLA_STORE_ROOT ausente, comprobado; no se abrió el canónico.
- Una revisión y un segmento por commit interno, sin FTS; payload/constructor
  iguales al diagnóstico. No se mide aquí la ruta CLI gobernada ni v3.
- Objetivo diagnóstico500, presupuesto90s por construcción con SIGALRM
  dentro del escenario, puntos100/200/300/400/500 y cinco snapshots por punto.
  Esto no cambia el objetivo oficial de20.000 revisiones ni sus umbrales.
- Secuencia: baseline1, A1, B1, baseline2, B2, baseline3, B3. No lancé CI ni
  otras pruebas de carga del agente deliberadamente concurrentes; el host no estuvo aislado
  de otros trabajos. Las diferencias entre repeticiones se conservan.

## Resultados completos, incluidos cortes

| Corrida | Revisiones confirmadas | Tiempo construcción s | Tiempo hasta300 s | Terminación |
|---|---:|---:|---:|---|
| Baseline1 | 386 | 90,030 | 57,129 | límite de pared |
| Baseline2 | 422 | 90,026 | 35,887 | límite de pared |
| Baseline3 | 410 | 90,028 | 40,708 | límite de pared |
| A1 | 500 | 43,759 | 13,678 | objetivo alcanzado |
| B1 | 500 | 37,647 | 12,941 | objetivo alcanzado |
| B2 | 500 | 51,324 | 18,581 | objetivo alcanzado |
| B3 | 500 | 55,701 | 19,604 | objetivo alcanzado |

Tamaño lógico posterior por stat: baseline7,70–8,98MB; A/B a500,
12.077.614 bytes y4019 archivos cada store. Se conserva el detalle en
`store-sizes.json`. No se crearon stores de20k ni se excedió2GiB por store
en estas mediciones; no describe el tamaño de todos los fixtures del CI.

No se adjudica tiempo a500 al baseline ni se eliminan sus corridas censuradas.
La comparación a300 usa los tres puntos completos de cada variante. La
muestra A1 no es evidencia suficiente para afirmar mejora marginal estable B/A.

El máximo de las muestras de snapshot en B fue0,040991s. No se observó el
disparador de #169 (0,5s sostenido) en este régimen sintético; no se evaluó
producción ni se extrapola la ausencia del disparador más allá de500 revisiones.

## Verificación posterior y límites

Los siete stores pasaron `verify` completo desde su respectivo código.
CURRENT coincidió con386/422/410 y500/500/500/500 respectivamente. Los tres
cortes pueden haber dejado objetos de intentos interrumpidos: verificar CURRENT
no prueba ausencia de huérfanos. No se ejecutó recover ni se reintentó ningún
commit interrumpido. Los resultados JSON de verificación se preservan.

Las pruebas de código comprueban una lectura por ancestro en el caso estable,
scan sin redecodificar proyecciones, fallback ante metadata no elegible,
rehash tras modificación/borrado/reemplazo, huérfanos ambiguos y contexto
nuevo por operación. No se usa una caché persistente ni inexistencia de journal
como prueba de ausencia de candidatos.

La cota de disco de20k sigue vigente: listas históricas actuales necesitan
al menos14.600.730.000 bytes sólo en referencias, frente al ceiling de2GiB.
[Cálculo y refutación](construction-manifest-bound-2026-10-29.md).
La aceptación integrada de20.000 revisiones queda pendiente de decisión de
recursos o constructor/formato; no se lanzó una corrida que excedería ese
presupuesto ni se sustituyó por lotes o compactación intermedia.

## Reproducción y gates

Se preservan workers/drivers originales como evidencia. Contienen rutas
absolutas temporales: al reproducir, usar árboles de fuente verificados y un
OUT nuevo; ajustar rutas y declarar el nuevo hash. No reejecutar sobre los
stores existentes, borrar evidencia ni inicializar memoria canónica.

El worker final incluye una guardia que exige AN_KLA_STORE_ROOT ausente;
las dos primeras corridas se ejecutaron antes de añadir esa aserción, con la
variable observada ausente. Esa adición sólo es preflight de seguridad y no
modifica el bucle cronometrado. Todos los workers verifican su paquete real.

Gates sizes/plans/adr_registry y pruebas dirigidas pasaron. El CI completo
final se registra en el PR antes de integración; esta nota no lo declara
verde anticipadamente. La entrega de A/B no equivale a release ni aceptación
de escala.


## Cierre del CI sobre A/B

`.venv/bin/python scripts/ci_local.py --simulate-ci` terminó con exit0 y
**ci_local: OK**: 1304 tests, 74 skips,1493,463s de discover (24,89min).
Importabilidad, unittest, selftest G-3, matriz y gates sizes/plans/adr_registry
OK. Filas anidadas activas; matriz adicional declaró3.9/3.13 no disponibles
por nombre en PATH, sin sustituir las piernas CLT explícitas de sellado.
[Log preservado](evidence/adr0061-comparison-20261029/implementation-ci.txt).

Después se ejecutaron context status, status y verify sobre el canónico,
sólo lectura: ok=true, sin diagnósticos de integración; revisión87 y mismo
CURRENT sha256:d241ef8ef105e209ef44a38b1efcd9cc7d6a06e599b106a7a1f62b064a86a9a2
observado antes del cambio. No se escribió checkpoint ni memoria.

El CI valida A/B bajo esos perfiles y condiciones; no sustituye la aceptación
integrada de escala20k pendiente. El paquete conserva su versión: no release.

## Decisión posterior del Operador — 2026-10-29

El Operador pospuso expresamente la prueba integrada de **20.000 revisiones**
por espacio. Sale del alcance activo; no bloquea el cierre de A/B ni equivale
a aceptación de esa escala. Se conserva el criterio de 20.000 revisiones,
sin sustituirlo por lotes de registros ni compactaciones intermedias.
Retomarla requiere una nueva orden y resolver el presupuesto de disco; no se
autoriza superar el ceiling vigente. La cota de 14.600.730.000 bytes sólo
para referencias permanece documentada arriba. Las menciones previas a
«pendiente» describen el estado al ejecutar el CI, antes de esta decisión.
