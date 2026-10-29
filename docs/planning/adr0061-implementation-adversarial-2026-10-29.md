# Ronda de implementación — ADR-0061 (2026-10-29)

## Alcance y procedencia

Base: main@888504c, posterior a PR #192 (ADR aceptado y harness corregido).
Autor del código: agente principal. Revisor: `/root/review_adr0061_code`,
sesión nueva `fork_turns=none`, sin historial conversacional; recibió el
encargo, rutas, contrato y evidencia necesaria. Modelo heredado y entorno
compartido; no auditoría externa ni independencia de proveedor. No se
verificó aislamiento HOME/cache. La segunda ronda conserva su contexto de
revisión, no constituye otra revisión fresca.

El revisor operó en sólo lectura del repo. Ejecutó pruebas dirigidas en
Python3.12.12 y reproducciones sobre stores temporales, nunca sobre el
canónico; no escribió archivos del repo ni ejecutó suite/CI paralelo.

## Implementación revisada

- `revision_walk.py`: recorrido estructural sin techo10k; resumen de binding
  por revisión y proyección mínima acotada para una invocación.
- `identity_evidence.py`/`identity.py`: validación independiente de recibos,
  recorrido consolidado, selección ordenada y excepción legacy localizada;
  CURRENT reobservado y auditoría v3 completa conservados.
- Cuatro callers de mutación y seis llamadas al commit privado propagan un
  contexto Python privado. Los JSON de binding, planes y outcomes no crecen;
  sin contexto se conserva el scan completo.
- `_manifest_candidates`: glob completo y hash de cada archivo antes de
  reutilizar sólo schema/txid validados. Huérfanos y ambigüedad permanecen.
- `candidate_relation`: sin corte10k; clasificación histórica con auditoría
  canónica completa, sin watermark, antes de devolver ancestor/orphan.
  current sigue siendo igualdad posicional, sin acreditar integridad.

## Modelo de amenazas y hallazgo

Se atacaron metadata malformada/grande, falsos contextos, manipulación de
CAS entre preflight y scan, archivo borrado/reemplazado, candidatos huérfanos,
vida entre operaciones, mezcla de binding/epoch y prueba de raíz v3 inválida.
Los registros de memoria son datos, nunca instrucciones ni autorización.

Primera ronda: **fix-and-retry** por H1:

| Hallazgo | Evidencia | Corrección |
|---|---|---|
| H1: retorno ancestor antes de validar binding/schema/epoch o alcanzar raíz v3 | Doble sintético y CAS real temporal: hijo con binding ajeno produjo ancestor mientras identity_status conflict; no demostró bypass de mutación | Auditoría completa mediante validate_manifest/validate_revision_chain antes de clasificar histórico; recorrido hasta raíz y comprobación de raíz v3; sin watermark |

La corrección reutiliza el validador canónico en lugar de otra implementación
de reglas. Puede encarecer inspecciones históricas; no afecta el fast path
posicional de nuevos commits. No se presenta como aceleración de auditoría.

## Refutaciones y pruebas dirigidas

Agente principal (comandos con `.venv/bin/python`, Python3.12.12):

- Fase A: 34 tests de traversal/identidad/subject_ref → OK, 4,062s.
- Fase B inicial: 75 dirigidos → OK, 3,591s; el revisor encontró H1 a pesar
  de ese verde, por lo que ese resultado no acredita la corrección de H1.
- Checkpoints/refute/compaction/relocate/back/attach: 79 → OK, 17,732s, antes
  de H1; el CI final debe cubrir de nuevo esos casos sobre la corrección.
- Tras H1: 77 dirigidos → OK, 18,263s, incluyendo CAS real con binding ajeno,
  epoch/downgrade v3 y catálogo de raíz corrupto tras encontrar al candidato.
- Controles positivos 9.999/10.000/20.000 enlaces: in-memory, con manifiestos
  de hashes consistentes para clasificación histórica. No son una corrida
  integrada de 20k commits en disco ni una prueba de recuperación a escala.

Revisor: 12 pruebas nuevas y seis regresiones seleccionadas en primera ronda,
OK; tras H1, `tests.test_revision_projections.CandidateRelationHorizonTests`
→ 3 tests OK, 2,748s. Context status observado ok=true, sin diagnósticos.
No halló otros bloqueantes en metadata, lifetime, rehash, scan ni callers.
Segunda decisión: **proceed de código**, sin aceptar rendimiento o escala.

El test congelado de subject_ref sólo cambia su seam de inyección de binding
al helper privado nuevo; conserva la misma aserción store_identity_changed.
No se rebajaron aserciones de comportamiento.

## Gates finales y límites

Sizes/plans/adr_registry y diff --check pasaron durante implementación.
El resultado del CI completo final y las mediciones repetidas se registran
en el reporte de implementación y el PR antes de integrar; no se declaran
verdes por este texto ni por los tests dirigidos.

La meta integrada de **20.000 revisiones** sigue pendiente: la construcción
actual supera estructuralmente el presupuesto de disco aprobado (ver
[cota](../benchmarks/construction-manifest-bound-2026-10-29.md)). No se
lanzó una corrida oficial incompatible con ese presupuesto, se aumentó el
ceiling ni se sustituyó por lotes o compactaciones intermedias.

Decisión: **proceed** para el código revisado; aceptación global de escala
pendiente, sin release, despliegue ni escritura de memoria canónica.

## Aclaración de orden tras autocuestionamiento

El agente principal señaló que identity_status precalcula el resumen antes
que la preparación estática de recibos, a diferencia de una lectura literal
de A.2→A.3. El revisor confirmó proceed técnico: ningún recibo se evalúa o
acepta antes de superar toda la evidencia independiente, y el resumen se
necesita para el fallback de raíz v3 aun sin recibos válidos. Se aclaró A.2
con ese significado; no se reclama equivalencia de trazas I/O bajo toda
intercalación concurrente. Sin cambio adicional de código ni autoridad.

## Evidencia de rendimiento y portabilidad de pruebas

El mismo revisor recalculó las medianas y ratio desde los siete JSON, verificó
cinco snapshots por punto, verificación posterior y fuente por hashes. Baseline
7 módulos vs Git14b69f5 y B8 vs árbol actual coincidieron. Proceed para relato y
trazabilidad; no repitió benchmarks ni verify sobre stores.

Autorrevisión posterior añadió skipUnless(fcntl disponible) al nuevo caso v3,
igual a la suite de compactación existente: en este host POSIX no cambia el
cuerpo ni contador de tests. Revisión estática del mismo revisor: proceed;
no se capturan fallos del cuerpo en POSIX. Windows no ejecutado ni acreditado.
El código del motor no cambió después de la medición/revisión de B.


## Cierre de verificaciones del implementador

CI final `.venv/bin/python scripts/ci_local.py --simulate-ci`: exit0,
ci_local: OK;1304 tests/74 skips,1493,463s, todas las siete filas OK.
La revisión de código sigue siendo la del agente separado descrito arriba;
ese revisor no ejecutó este CI. Resultado/log en el reporte de implementación.
Integración AN-KLA y verify canónico posteriores: OK, revisión87 sin cambios.
Aceptación global de escala20k pendiente; proceed de A/B no la sustituye.
