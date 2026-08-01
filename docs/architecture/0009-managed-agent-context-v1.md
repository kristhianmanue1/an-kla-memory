# ADR-0009: contexto administrado y compacto `context-package/v1`

## Estado

Aceptada para `v0.1.0-beta.1`.

## Problema

`AGENTS.md` pertenece al proyecto y puede contener reglas del usuario, pruebas,
convenciones y límites de seguridad ajenos a AN-KLA. Reemplazar el archivo
completo destruiría contexto legítimo; añadir instrucciones a ciegas produciría
duplicados y podría conservar rutas heredadas incompatibles con
`write-policy/v1`.

Al mismo tiempo, copiar el manual completo dentro de `AGENTS.md` impone su costo
de contexto en todas las tareas. El archivo raíz debe actuar como mapa compacto,
no como enciclopedia. Esta decisión sigue la jerarquía documentada de archivos
`AGENTS.md` y la recomendación de mantener el mapa raíz breve:

- <https://openai.com/index/unrolling-the-codex-agent-loop/>
- <https://openai.com/index/harness-engineering/>

## Decisión

AN-KLA posee únicamente un bloque delimitado por dos comentarios HTML en un
`AGENTS.md` explícito. Los comentarios son sintaxis Markdown reconocible y no se
renderizan como contenido visible:

```text
<!-- an-kla:managed-begin {...} -->
...contenido administrado...
<!-- an-kla:managed-end {...} -->
```

El bloque incluye solamente:

1. que el proyecto usa AN-KLA;
2. cuándo vale la pena cargar memoria;
3. una referencia a `AN-KLA.md`;
4. que la memoria recuperada es dato no confiable;
5. que la escritura nueva usa `plan-write` y `commit-write-plan`.

El procedimiento detallado vive en `AN-KLA.md`, archivo rastreable y disponible
en clones limpios. `.an-kla/context/` sólo conserva manifiesto, lock y respaldos
locales; no publica la memoria viva del proyecto.

## Propiedad e integridad

El marcador inicial contiene esquema, ID, versión y SHA-256 del contenido
normalizado a LF. La huella detecta deriva; no es firma ni prueba de autoridad.
El instalador falla cerrado ante contenido alterado, marcadores duplicados,
anidados, incompletos, indentados o situados dentro de una cerca de código.

El contenido exterior al bloque se conserva. Un destino existente se respalda
por contenido antes de la primera instalación y sus permisos se preservan.

## Operaciones

`context plan` no muta. `context apply` reconstruye el plan bajo un lock local y
compara la huella del archivo observada con la base planificada. Los comandos de
conveniencia `install`, `update` y `uninstall` ejecutan ambos pasos en la misma
invocación explícita.

La escritura usa un temporal en el mismo directorio, `fsync`, preservación de
modo y `os.replace`. La exclusión es local y cooperativa: no se afirma CAS
distribuido ni coordinación entre máquinas.

## Instrucciones del bloque

La frase “trabajo material o dependiente del historial” evita recuperar memoria
como ritual en saludos o tareas ajenas. El contrato detallado exige una consulta
concreta, limita la verificación repetitiva y distingue información durable de
texto trivial. Una decisión `skip` de la compuerta causal es válida.

El bloque nunca autoriza acciones externas ni permite que un registro recupere
autoridad. Las demás instrucciones aplicables y el usuario conservan su
precedencia normal.

## Migración heredada

Si un archivo sin marcadores contiene dos o más firmas de la integración
anterior —por ejemplo `python3 -m an_kla`, `.an-kla/memory`, `write`,
`--expected-current` o `rebuild-index`— la instalación termina con
`legacy_an_kla_context_detected`. Añadir el bloque nuevo dejaría órdenes
contradictorias, por lo que la beta requiere revisar y retirar manualmente el
texto legado antes de instalar.

## No objetivos de v1

- fusión semántica automática de instrucciones modificadas;
- edición simultánea por procesos que ignoran el lock;
- coordinación multi-máquina;
- archivos `AGENTS.md` anidados o instalación automática en `CLAUDE.md`,
  `GEMINI.md`, Cursor o Copilot;
- tratar las huellas como identidad criptográfica;
- obedecer instrucciones encontradas en memoria.
