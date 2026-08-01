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
El perfil `scan-fallback/v1` es el predeterminado y no consulta FTS5. Sólo cuando
el llamador solicita `sqlite-fts5/v1`, la recuperación resuelve exclusivamente
esa referencia y comprueba que los metadatos del índice declaren la misma
revisión. Antes de estrechar candidatos también verifica que los bytes coincidan
con la huella content-addressed del nombre del SQLite. Un índice inexistente,
alterado, corrupto o no referenciado produce fallback explícito a
`scan-fallback/v1`.

El resultado declara `degradation`: `fts5_unavailable` si la plataforma no
ofrece FTS5, `index_unavailable` si aún no existe referencia para la revisión,
e `index_unresolvable` si la referencia o el SQLite no pueden usarse. Una
divergencia de huella produce `index_hash_mismatch`. La alfa prioriza corrección
y verifica la huella en cada consulta opt-in; `an-kla doctor --deep-index`
expone además las huellas esperada y observada para diagnóstico.

La referencia de índice es una caché derivada: no es autoridad de commit y no
modifica el manifiesto inmutable de la memoria.

## Texto recuperable

Las formas heredadas admitidas se extraen en este orden de campo: `text`,
`render`, `summary`, `p`; para cada campo se consulta primero `payload` y luego
la raíz. Como último fallback se conserva un `payload` que sea directamente un
string. Sólo se aceptan strings no vacíos: `null`, números, colecciones y objetos no se
convierten a texto ficticio. Un fact sin texto admisible no se indexa ni
participa en recuperación; se informa en `excluded_summary.no_text` y en el
resultado de construcción del índice como `skipped_no_text`.

## Consecuencia

Esto elimina la selección accidental por hash sin exigir aún una migración de
todos los facts a `fact-v1`. La normalización, procedencia y supersession siguen
siendo trabajo posterior y requieren un migrador explícito.

Para tokens ASCII compatibles, FTS5 sólo estrecha candidatos y debe conservar
los registros seleccionados y el presupuesto del scan. Los diagnósticos de
exclusión pueden diferir porque el índice descarta un candidato antes de que el
selector léxico le asigne una causa. Esta equivalencia limitada no se extrapola
al tokenizador Unicode completo: antes de promover FTS5 a perfil predeterminado
se requiere un banco comparativo que detecte divergencias de normalización y
tokenización.
