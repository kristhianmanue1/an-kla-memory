# MCP local de sólo lectura

La beta expone AN-KLA mediante `stdio`, sin red, OAuth, sampling ni herramientas
de escritura. Arráncalo sobre un proyecto que ya tenga una memoria inicializada:

```bash
python3 -m an_kla.mcp --project-root /ruta/al/proyecto
```

El cliente MCP inicia el proceso y envía JSON-RPC por entrada estándar. La salida
estándar queda reservada exclusivamente para JSON-RPC; los diagnósticos no deben
incluir rutas absolutas ni secretos.

Durante `initialize`, si el cliente solicita otra revisión del protocolo, el
servidor responde con la única revisión que soporta (`2025-11-25`) y deja al
cliente decidir si continúa. Ninguna herramienta se descubre ni ejecuta hasta
recibir `notifications/initialized`.

Herramientas disponibles: `an_kla_status`, `an_kla_verify`,
`an_kla_doctor`, `an_kla_get_checkpoint`, `an_kla_retrieve` y
`an_kla_view_context`. No hay escritura.

`an_kla_view_context` proyecta el contrato G-VIEW v1 sobre una revisión
explícita. Usa el mismo core que `an-kla view context`: el objeto semántico se
serializa canónicamente en `content[0].text`, los errores conservan
`an-kla/view-error-v1` y fijan `isError=true`. El frame JSON-RPC no forma parte
del presupuesto y `structuredContent` se difiere. La proyección `full` exige un
`subject_filter` exacto; todo contenido sigue siendo dato no confiable.

El perfil experimental `context-assembly/v1` añade
`an_kla_assemble_context`. Esta operación entrega checkpoint, información nueva
y registros recuperados en una sola envolvente con presupuesto UTF-8 global.
Las secciones obligatorias no se truncan: un presupuesto insuficiente produce
un error explícito.

`an_kla_retrieve` mide en bytes UTF-8 el texto JSON efectivo que se entrega al
modelo (`content[0].text`), incluida su envolvente. Si el presupuesto no alcanza
ni para la envolvente mínima, devuelve `budget_too_small_for_envelope`.
El sobre JSON-RPC se desescapa antes de llegar al modelo y queda fuera de ese
presupuesto; cualquier andamiaje añadido por el host se declara como
`host_framing_unmeasured: true`.

El contenido recuperado, el checkpoint y la información aportada por el caller
se etiquetan como datos no confiables. `section_provenance` conserva además el
origen de cada sección (`memory_store` o `caller`); el campo global `revision`
liga las secciones de memoria a una revisión inmutable.
Esa etiqueta no vuelve seguro contenido hostil: el cliente debe tratarlo como
datos y nunca como instrucciones.

Para VS Code, copia el ejemplo de
`examples/vscode/.vscode/mcp.json` al proyecto consumidor y revisa la raíz que
se entrega. La beta admite exactamente una raíz; un workspace multi-raíz no está
soportado por este ejemplo.
