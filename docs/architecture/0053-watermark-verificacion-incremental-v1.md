# ADR-0053: Watermark de verificación incremental (P1 del escalado)

- **Estado:** Propuesta
- **Implementación:** No iniciada
- **Fecha:** 2026-10-14
- **Decide sobre:** cómo las lecturas normales dejan de revalidar la cadena completa de revisiones sin perder equivalencia de resultado ni tamper-evidence.

## Contexto

`validate_revision_chain` recorre desde la revisión pedida hasta la raíz
re-hasheando cada eslabón (`an_kla/revision_validation.py:195`), y
`_read_segment` re-hashea segmentos completos (`store.py:578`). La batería
P0 oficial (`results/20261014-182904`) midió las consecuencias: la vía
gobernada aborta por umbral (2 s sostenidos) entre las 403 y 478 escrituras
en las tres celdas, y `snapshot` crece con la historia. El issue #149 (P1)
propone un checkpoint derivado "verificado hasta la revisión R". El
precedente de caché derivada es el `CURRENT` del índice FTS: referencia de
caché, nunca autoridad de commit (`an_kla/index.py:102-105`).

## Decisión

Introducir un **watermark derivado** "verificado-hasta-R" con las reglas:

1. **Estructura**: archivo de caché junto a los índices con
   `{revision, chain_digest_at_R, manifest_digest_at_R, epoch_id}`. Lectura
   normal valida (a) el eslabón R contra el CURRENT del store y (b) sólo el
   sufijo R→revista-pedida. `verify --full` conserva el recorrido completo
   como auditoría explícita.
2. **Equivalencia o fallo cerrado**: un watermark corrupto, atrasado o
   manipulado **nunca produce un resultado distinto** del que daría la
   verificación completa; produce o (i) detección (digest de eslabón no
   coincide → descartar watermark y recorrer todo) o (ii) error cerrado.
   Este es el criterio de aceptación del issue y exige test dedicado.
3. **Reset por epoch de compactación**: el watermark liga `epoch_id`; tras
   una compactación el watermark previo se ignora y la verificación arranca
   en la raíz del epoch (el epoch manifest ya existe como frontera auditable).
4. **Punto de mantenimiento**: lo refresca el **escritor dentro de la
   transacción de commit existente** (mismo lock, mismo manifiesto), nunca
   el lector y nunca una segunda ronda de CAS. La batería midió 74 % de
   conflictos CAS con 4 escritores: añadir una escritura adicional por
   commit agravaría el cuello medido; ir dentro del manifiesto es amortizado.
5. **No-objetivo declarado (rollback)**: revertir el par
   (CURRENT, watermark) a un estado antiguo coherente produce un store que
   parece sano, exactamente igual que revertir sólo CURRENT hoy
   (tamper-evident ≠ tamper-proof, límite declarado en `store.py:1-4`).
   El watermark no empeora ni corrige ese vector; `verify --full` es la
   auditoría que lo expone.

## Por qué no [alternativa]

- **Cadena firmada**: identidad criptográfica es decisión de producto,
  fuera de alcance (plan origen: "qué NO hacer todavía").
- **Mantener verificación completa**: es el status quo que la batería midió
  y que el issue rechaza por coste O(historia).
- **Watermark como autoridad**: rompería el precedente de caché derivada
  (índice FTS) y crearía una segunda fuente de verdad, prohibido por §11.2.
- **Watermark mantenido por lectores**: carreras de escritura entre
  lectores y agravamiento del CAS medido (regla 4).

## Consecuencias

- Positivas: las lecturas normales crecen con el sufijo no verificado, no
  con la historia total; `verify --full` queda como auditoría barata de
  invocar a demanda.
- Negativas: más estado derivado que mantener; honestidad requerida en el
  alcance — el watermark mata el recorrido de cadena (F1) pero **no** el
  re-hash de segmentos (F2): el eje registros necesita fusión de segmentos
  (P2c) y no se promete aquí.
- Neutras: los criterios del issue se aplican por eje (revisiones primero);
  la re-corrida de la batería P0 contra `results/20261014-182904` es el
  criterio de cierre de la implementación.

## Test de regresión

- Watermark corrupto (digest alterado) → equivalencia (recorrido completo)
  o fallo cerrado; nunca estado aceptado distinto.
- Watermark atrasado → sufijo revalidado desde R; resultado igual al completo.
- Post-compactación → watermark de epoch anterior ignorado.
- Commit con watermark refrescado en el mismo manifiesto → sin escrituras
  extra visibles (journal único).
- Batería P0 re-corrida: techo de la celda gobernada supera las ~450
  escrituras de la línea base.

## Referencias

Issue #149 (P1 y criterios); batería P0 `benchmarks/scale/results/20261014-182904/INFORME.md`;
`an_kla/revision_validation.py`, `an_kla/index.py` (precedente CURRENT),
`an_kla/compaction.py` (epoch); ADR-0052 (mesa de diseño conjunta);
acta `docs/planning/mesa-diseno-140-149-adversarial-2026-10-14.md`.
