# ADR-0006: contrato inicial de `context-assembly/v1`

## Estado

En implementación experimental. No forma parte de una versión etiquetada.

## Decisión

`context-assembly/v1` ensambla una única envolvente JSON canónica a partir del
checkpoint de una revisión —que contiene objetivo y estado de trabajo—,
información nueva suministrada por el cliente y registros recuperados para una
consulta. El checkpoint y la sección de información nueva son indivisibles y
obligatorios en la envolvente; el valor de información nueva puede ser nulo
cuando el cliente no lo suministra. Los registros recuperados llenan el
presupuesto restante en el orden determinista del recuperador.

La operación primero fija la revisión devuelta por recuperación y después lee
el checkpoint de esa misma revisión inmutable. Por tanto, una actualización
concurrente de `CURRENT` no mezcla estado de dos revisiones.

El presupuesto mide exactamente los bytes UTF-8 de la envolvente canónica
completa, incluido `used_bytes`, metadatos, checkpoint, información nueva y
registros. Si la envolvente y sus secciones obligatorias no caben, la operación
falla con `budget_too_small_for_required_context`: no trunca ni resume estado
silenciosamente. El framing añadido por un host permanece fuera de la medición
y se declara mediante `host_framing_unmeasured: true`.

## Alcance y límites

- Es una operación local de lectura y no modifica la memoria.
- Su unidad exacta es el byte UTF-8, no el token de un proveedor.
- La etiqueta de datos no confiables no autoriza ejecutar contenido.
- El orden léxico heredado no demuestra calidad decisional.
- La política de prioridad inicial es checkpoint, información nueva y, por
  último, recuperación. Cambiarla exige un perfil distinto o versionar este
  contrato; no se ajustará de manera implícita.

## Aceptación inicial

Las pruebas deben demostrar presupuesto sobre la envolvente completa con texto
multibyte, fallo cerrado cuando no caben las secciones obligatorias, coherencia
de revisión y exposición por la frontera MCP de sólo lectura.
