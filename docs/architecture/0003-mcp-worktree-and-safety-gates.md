# ADR-0003: aislamiento de trabajo MCP y compuertas de seguridad

## Estado

Aceptada para planificación. No autoriza todavía implementar ni publicar un
servidor MCP.

## Contexto

`an-kla-memory` es la única fuente de verdad del producto. El repositorio
`memoria-agentica` conserva investigación histórica y no es un área de
integración ni un origen alterno de versiones publicables.

El adaptador MCP será un lector persistente de una memoria que hasta ahora se
consume principalmente mediante procesos CLI efímeros. Esto hace visibles, en
la frontera con un cliente externo, las garantías de presupuesto, privacidad,
procedencia y lectura consistente.

## Decisiones

### Área de trabajo

El desarrollo de MCP se realizará en un *worktree* del mismo repositorio,
asociado a una rama de característica, con esta ruta prevista:

```text
/Users/krisnova/www/an-kla-memory-mcp
```

La rama `main` de
`/Users/krisnova/www/an-kla-memory` permanece limpia y publicable. El cambio
se integra mediante commits y merge; nunca copiando archivos entre directorios.
No se creará un segundo repositorio de producto ni se trabajará MCP dentro de
`/Users/krisnova/www/memoria-agentica`.

### Alcance inicial del servidor

El primer servidor será local, por `stdio`, y de sólo lectura. No tendrá HTTP,
OAuth, sampling, red, secretos, ni ejecución de instrucciones procedentes de
la memoria. El cliente debe fijar una única raíz de proyecto al iniciar el
proceso; el servidor DEBE rechazar una raíz sin `.an-kla/` y DEBE rechazar un
workspace multi-raíz como función no soportada.

La alfa soporta exactamente la revisión MCP `2025-11-25`; rechaza una
inicialización con otra revisión en vez de negociar compatibilidad parcial.

Las primeras herramientas candidatas son `status`, `verify`, `doctor`
saneado, `retrieve`, `get_checkpoint` y `get_revision`. No se expondrán los
streams completos de facts, events o episodes como recursos MCP.

La escritura queda fuera de G2.5. Si se habilita en una fase posterior, vivirá
en un servidor independiente, opt-in, y toda mutación exigirá
`expected_current_hash`; el CAS del almacén sigue siendo la autoridad final.

### Contrato de presupuesto

El presupuesto de `retrieve` DEBE medir el bloque de contenido UTF-8 que el
host entrega al modelo (`content[0].text`), no sólo el texto de cada registro.
El sobre JSON-RPC de transporte queda explícitamente fuera: el cliente lo
desescapa antes de entregar el contenido al modelo. El adaptador debe medir
su envolvente raíz y cada registro mediante un renderizador canónico.
`used_bytes` debe representar exactamente ese bloque de contenido. La etiqueta
de datos no confiables se emitirá una vez en la raíz, no repetida por registro.
El resultado declara `host_framing_unmeasured: true`, porque el servidor no
puede medir marcadores o tokens adicionales que el host pudiera añadir.

La prueba de aceptación incluirá caracteres UTF-8 y verificará que el bloque
de contenido entregado al modelo no excede `budget_bytes`.

### Datos no confiables y escritura futura

Una etiqueta JSON como `untrusted_memory_data` informa, pero no obliga a un
cliente externo. Por ello el servidor no promete que un modelo obedecerá esa
etiqueta. La defensa real combina: interfaz de sólo lectura inicial, no
ejecución de contenido recuperado, y una operación de escritura futura que
requiera confirmación explícita y una procedencia distinguible de contenido
confirmado por una persona.

No se adopta como control suficiente un registro de hashes de n-gramas por
sesión: puede eludirse entre sesiones o mediante paráfrasis y puede bloquear
texto legítimo. Si se necesita detección de eco, será una señal diagnóstica
conservada como linaje (`derived_from_retrieval`), nunca una prueba de origen
humano ni el único mecanismo de autorización.

### Privacidad diagnóstica

Las herramientas MCP no devolverán rutas absolutas, nombres de usuario ni
mensajes de excepción sin sanear. Los errores se mapearán a códigos estables;
las rutas, cuando sean necesarias, serán relativas a la raíz fijada. Un modo
de detalle mayor requerirá una confirmación explícita del usuario y seguirá
sin exponer secretos.

### Explicabilidad de recuperación

Antes de implementar MCP se ampliará el resultado canónico de recuperación
con `excluded_summary`: conteos deterministas de exclusiones, al menos por
`zero_score`, `budget`, `inactive` y `invalid_record`. No incluirá el payload
de los elementos descartados. Esta función pertenece a `retrieval.py`, no a
una reconstrucción parcial en el adaptador MCP.

### Integración de VS Code

El integrador tratará `.vscode/mcp.json` como JSONC estructurado. AN-KLA será
propietario exclusivamente de las entradas `servers["an-kla-read"]` y,
cuando exista, `servers["an-kla-write"]`. Guardará el hash canónico de cada
subárbol que creó. Sólo actualizará o eliminará una entrada si el hash aún
coincide; ante divergencia reportará conflicto y no sobrescribirá nada. No se
usan marcadores de comentario como mecanismo de propiedad.

## Compuertas antes de G2.5

1. La recuperación cuenta la envolvente final y expone causas de exclusión.
2. La interfaz de lectura sanea diagnósticos y rechaza raíz ausente o ambigua.
3. Una prueba demuestra que `read_current()` abre y cierra `CURRENT` antes de
   cualquier lectura posterior; otra se ejecutará en Windows antes de declarar
   compatibilidad con ese sistema.
4. La documentación declara que aún no hay GC. Antes de introducir GC o
   compactación, se diseñan leases de lectores y pruebas de retención; no se
   afirma que el servidor MCP los resuelva anticipadamente.
5. Las pruebas existentes permanecen verdes y se añaden pruebas de contrato
   MCP antes de exponer el adaptador.

6. La alfa puede escanear el corpus completo. Antes de soportar ingesta masiva
   o G3, la recuperación MCP deberá usar un índice ligado a la revisión o una
   compuerta explícita de tamaño de corpus.

## Durabilidad por plataforma

`verify` y `doctor` declaran `durability_profile`. En POSIX se usa
`posix-fsync-dir/v1`; en Windows se declara `windows-no-dir-fsync/v1`, porque
la alfa no puede sincronizar el rename de directorio con la misma primitiva.
La integridad de contenido y el CAS siguen aplicando, pero no se afirma igual
garantía de persistencia ante caída súbita.

## Consecuencias

Se pospone el MCP escribible, deliberadamente. Un servidor de sólo lectura
permite validar formato, presupuesto y diagnósticos sin convertir contenido
recuperado en memoria persistente. El coste es que la consolidación desde un
IDE seguirá usando el CLI hasta una revisión explícita de la fase de escritura.
