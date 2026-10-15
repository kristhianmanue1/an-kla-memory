# ADR-0056: Caché de segmentos materializados (lecturas) — PROPUESTA NO IMPLEMENTADA

- **Estado:** Propuesta
- **Implementación:** No iniciada
- **Fecha:** 2026-10-15
- **Decide sobre:** evitar re-leer y re-canonicalizar cada segmento en cada lectura (F2 del issue #149) mediante una caché derivada de filas materializadas.

## Contexto

`_read_segment` re-hashea el archivo y re-canonicaliza cada fila en cada
apertura (`store.py:589-600`): integridad total, coste total. El watermark
(ADR-0053) curó el recorrido de cadena (F1) pero no esto (F2). La batería
mide `snapshot` lineal en registros (0,126 s a 20k) — manejable hoy, dolor
creciente a escala.

## Decisión propuesta

Caché derivada por (revisión, stream): filas materializadas mantenida por
el escritor dentro del commit (base + pendientes, sin lecturas extra),
validada por forma + coincidencia de `segment_ids` con el manifiesto +
digest interno; auditoría completa (`verify`) siempre lee los segmentos
reales.

## El tradeoff que exige decisión del maintainer (razón de esta propuesta)

A diferencia del watermark — que sólo acortaba **profundidad de
validación** con la auditoría intacta — esta caché sirve **datos**: un
atacante de disco que reescriba la caché de forma autoconsistente (filas
alteradas + digest recalculado + ids correctos) hace que la lectura normal
sirva filas distintas de las ancladas por los segmentos content-addressed.
Eso **debilita tamper-evidence de las lecturas normales**, hoy una
propiedad central del store. No hay ancla local posible sin releer los
segmentos (lo que anularía la ganancia) ni firmas (decisión de producto
excluida del plan). `verify` seguiría detectándolo, pero la frontera
"tamper-evident en cada apertura" se perdería para el camino caliente.

Alternativas que no debilitan nada: fusión de segmentos **sólo para
escrituras nuevas por lote** (ya ocurre como efecto medido del ADR-0054:
12 segmentos grandes vs 601), y reconstrucción por compactación para
stores existentes. La ganancia residual de la caché sobre esas palancas,
a las escalas medidas por la batería, es pequeña (snapshot ≤ 0,13 s a
20k).

## Consecuencias (si se acepta)

- Positivas: `snapshot` deja de crecer con el número de segmentos.
- Negativas: tamper-evidence de lecturas normales pasa a ser
  "confianza-una-vez + auditoría explícita".
- Neutras: export/relocate tratarían la caché como derivada (skip-list).

## Test de regresión (si se acepta)

Equivalencia con/sin caché; caché corrupta NO autoconsistente degrada;
`verify` expone manipulación coherente de la caché; mantenimiento del
escritor sin lecturas extra.

## Referencias

Issue #149 (F2/P2c); ADR-0053 (watermark, contraste de propiedades);
ADR-0054 (lote, alivio ya medido de F2); batería P0. **Pendiente de
decisión explícita del maintainer; nada de esto autoriza implementación.**
