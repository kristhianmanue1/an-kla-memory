# ADR-0010: contratos públicos orientados a agentes

## Estado

Aceptada para `v0.1.0-beta.2`.

## Contexto

Los consumidores primarios de AN-KLA son agentes de IA que operan mediante CLI,
API Python o MCP. Estos consumidores interpretan con mayor confiabilidad
schemas, códigos estables, JSON canónico y ejemplos ejecutables que requisitos
dispersos en prosa. Los operadores humanos siguen necesitando documentación,
pero la prosa no debe ser la única representación de un contrato ejecutable.

La reevaluación de Argos mostró dos diferencias entre checkout y consumo:

1. los JSON Schema normativos existen, pero no viajan dentro del wheel;
2. un consumidor no puede descubrir de forma estructurada que recuperación v1
   busca sólo `facts`, que FTS es opcional o que el CLI no resuelve autoridad
   privilegiada.

Añadir esa información a envolventes v1 existentes no es neutral. Las respuestas
de recuperación y contexto están presupuestadas por sus bytes canónicos; un
campo aditivo cambia `used_bytes` y puede cambiar qué registros se seleccionan.

## Decisión

AN-KLA adoptará una superficie pública agent-first basada en cinco capas:

```text
schema versionado
  -> salida JSON canónica y códigos estables
      -> invariantes verificadas por pruebas
          -> fixtures y ejemplos ejecutables
              -> explicación humana
```

Una propiedad descrita sólo en prosa no se presentará como contrato ejecutable.
Una expresión matemática sólo será normativa cuando identifique variables,
unidad, perfil y procedimiento de verificación.

## Descubrimiento de capacidades

Se diseñará `an-kla/capabilities-v1`, accesible inicialmente mediante CLI y API
Python de sólo lectura. Debe declarar sin leer memoria local:

- versión del producto;
- schemas instalados y sus identificadores;
- perfiles de recuperación y perfil predeterminado;
- streams almacenables y streams buscados por perfil;
- unidades de presupuesto implementadas;
- operaciones gobernadas soportadas;
- clases de autoridad aceptadas por el CLI;
- herramientas MCP disponibles;
- límites funcionales relevantes.

La salida será determinista, JSON-canónica, sin rutas absolutas, secretos o
estado del proyecto. No se insertará dentro de `retrieval-result-v1`,
`context-assembly/v1` ni otra envolvente presupuestada existente.

La exposición por MCP requiere una revisión posterior de la lista de tools y su
contrato de protocolo. Añadir el comando CLI no autoriza escritura MCP.

## Distribución de schemas

Los cinco schemas normativos se distribuirán como recursos del paquete:

- `write-proposal-v1`;
- `write-authority-v1`;
- `write-decision-v1`;
- `write-plan-v1`;
- `cost-certificate-v1`.

`importlib.resources` será la frontera de lectura. El wheel, la API y los
comandos `schema list/show` deben exponer los mismos bytes e identificadores.
Si `docs/schemas/` permanece como espejo transitorio, CI exigirá igualdad exacta
con la fuente empaquetada.

## Compatibilidad

Los payloads presupuestados v1 quedan congelados byte a byte. Requieren un nuevo
schema o perfil los cambios que alteren:

- campos o serialización;
- ranking, orden o selección;
- causas de exclusión;
- unidad o semántica de presupuesto;
- streams candidatos;
- prioridad de secciones.

Nuevos comandos independientes pueden añadirse con schemas propios siempre que
no muten memoria, no reinterpreten una respuesta v1 y no se presenten como
autorización.

## Frontera de confianza

Schemas, manifests y resultados describen datos; no elevan autoridad. Helpers
CLI no fabricarán `tool_observed` ni `channel_confirmed`. La memoria recuperada,
los archivos de propuesta y sus metadatos continuarán tratándose como datos no
confiables.

## Criterios de aceptación

- un wheel aislado expone los cinco schemas sin red ni checkout;
- `schema list/show` y `capabilities` tienen salida versionada y determinista;
- un agente descubre el alcance facts-only de recuperación v1;
- los payloads dorados v1 permanecen idénticos;
- inspección y validación no crean `.an-kla` ni modifican memoria;
- errores usan códigos estables y no filtran rutas o contenido;
- Python 3.9 y 3.12 permanecen soportados.

## Consecuencias

El producto gana una frontera adecuada para automatización y reduce la necesidad
de que agentes lean código fuente. A cambio, toda nueva superficie legible por
máquina debe versionarse, probarse y mantenerse como contrato público.

Este ADR no decide recuperación multi-stream, explicabilidad por candidato,
tokenizers, escritura MCP ni cambios de formato físico.
