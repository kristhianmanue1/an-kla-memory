# ADR-0057: Lectura de segmentos sin re-canonicalización

- **Estado:** Aceptada
- **Implementación:** Implementada (`store.py::_read_segment`)
- **Fecha:** 2026-10-15
- **Decide sobre:** eliminar la re-serialización canónica de cada fila en cada lectura de segmento, conservando íntegra la detección de manipulación.

## Contexto

`_read_segment` verificaba cada lectura en dos capas: (1) hash de los
bytes contra el identificador content-addressed; (2) re-serialización
canónica de cada fila para comparar byte a byte. La capa (2) re-deriva una
propiedad que la capa (1) ya ancla: si el hash cuadra, los bytes son
exactamente los escritos, y el escritor construye los bytes canónicos por
definición (`_write_segment` concatena `canonical_json`). El spike de
perfilado (2026-10-15, stores temporales 1k–50k) midió que la capa (2)
cuesta el **64,7 %** de la lectura de segmentos, constante en escala, y
que omitirla acelera `snapshot` **~56 %** (50k registros: 0,165 → 0,074 s)
— mientras el ancla de integridad (hash + framing) cuesta ~2 %.

## Decisión

La lectura de segmentos verifica hash de bytes y framing (`\n` final) y
sirve las filas parseadas; **no re-deriva la forma canónica**. La
invariant "los segmentos almacenados son canónicos" sigue garantizada por
construcción en la escritura, que es donde se verifica barato. El código
de error `segment_not_canonical` deja de emitirse en lectura (la
manipulación real sigue detectándose por `segment_hash_or_framing_invalid`).

## Por qué no [alternativa]

- **Caché de segmentos (ADR-0056)**: debilita tamper-evidence del camino
  caliente; innecesaria cuando el 65 % del coste era trabajo redundante.
- **Mantener la doble verificación**: es defense-in-depth contra un fallo
  del propio escritor (bytes no canónicos con digest correcto), fallo que
  no afecta integridad ni a los digests derivados (que se computan sobre
  el valor parseado, no sobre los bytes), a cambio de la mitad del coste
  de toda lectura.

## Consecuencias

- Positivas: toda lectura (`snapshot`, `retrieve`, `context_view`,
  plan/commit) ~2× más rápida en su parte de segmentos; cero pérdida de
  propiedad de integridad.
- Negativas: un hipotético bytes-no-canónico escrito por un escritor
  defectuoso ya no se detectaría al leer (se detectaría comparando
  escritura/lectura en auditorías de writer).
- Neutras: el código de error retirado no tenía consumidores ni pins.

## Test de regresión

- Manipular un byte de un segmento → `segment_hash_or_framing_invalid`
  (el ancla sigue viva).
- Lectura normal sirve filas idénticas a las escritas.
- Batería: la columna diagnóstica muestra `snapshot` ~mitad.

## Referencias

Spike de perfilado 2026-10-15 (apéndice en el acta adversaria de esta
ADR); ADR-0056 (caché rechazada en favor de esta ruta); issue #149 (F2);
batería P0/P1 (`results/20261014-182904`, `20261014-213523`).
