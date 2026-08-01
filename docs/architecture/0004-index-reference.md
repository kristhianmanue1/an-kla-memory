# ADR-0004: referencia explícita de índice derivado

## Estado

Aceptada para la alfa posterior a `v0.1.0-alpha.2`.

## Problema

Un índice FTS5 es una caché derivada de una revisión inmutable, pero distintas
generaciones del indexador pueden producir más de un archivo SQLite para la
misma revisión. Elegir un archivo por orden lexicográfico de su hash no expresa
recencia ni compatibilidad; además, un temporal abandonado no debe interpretarse
como referencia.

## Decisión

Cada perfil de índice usa:

```text
.an-kla/memory/indexes/<revision>/sqlite-fts5-v1/CURRENT
```

El archivo contiene el identificador SHA-256 del único SQLite activo. Se
actualiza atómicamente sólo después de escribir y hashear el objeto inmutable.
La recuperación resuelve exclusivamente esa referencia, verifica el hash del
archivo y comprueba que los metadatos del índice declaren la misma revisión.
Un índice inexistente, corrupto o no referenciado produce fallback explícito a
`scan-fallback/v1`.

La referencia de índice es una caché derivada: no es autoridad de commit y no
modifica el manifiesto inmutable de la memoria.

## Texto recuperable

Las formas heredadas admitidas se extraen en este orden: `text`, `render`,
`summary`, `p`. Un fact sin texto en esos campos no se indexa ni participa en
recuperación; se informa en `excluded_summary.no_text` y en el resultado de
construcción del índice como `skipped_no_text`.

## Consecuencia

Esto elimina la selección accidental por hash sin exigir aún una migración de
todos los facts a `fact-v1`. La normalización, procedencia y supersession siguen
siendo trabajo posterior y requieren un migrador explícito.
