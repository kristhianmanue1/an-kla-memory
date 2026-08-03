# Plan técnico posterior a la reevaluación de Argos

Fecha: 2026-08-03

Base evaluada: `67f6ee486a4235e43ca16d8f701eb8722aaad68a` (`v0.1.0-beta.1`)

Estado: ejecución iniciada en `v0.1.0-beta.2`

## 1. Objetivo

Preparar la siguiente beta de AN-KLA reduciendo la distancia entre sus contratos
normativos y la experiencia de consumo, sin modificar el formato físico ni
debilitar revisiones inmutables, CAS, canonicalización, presupuesto UTF-8 o
escritura gobernada.

El ciclo prioriza:

1. distribuir los contratos normativos dentro del wheel;
2. declarar explícitamente que recuperación v1 busca sólo `facts`;
3. permitir validar entradas gobernadas sin reimplementar canonicalización;
4. diseñar explicabilidad como una interfaz separada;
5. estudiar recuperación v2 antes de mezclar streams o cambiar ranking.

### Usuario primario: agentes de IA

La interfaz se diseña primero para agentes que consumen estructuras y
protocolos, aunque debe seguir siendo comprensible para operadores humanos. El
orden de autoridad documental será:

```text
schema versionado
  -> salida canónica y códigos estables
      -> invariantes y pruebas ejecutables
          -> ejemplo completo
              -> explicación humana
```

Una afirmación que exista sólo en prosa no cuenta como contrato implementado.
La notación matemática se usará cuando defina una magnitud comprobable —costo,
presupuesto, orden o fingerprint— y siempre tendrá una prueba asociada.

Principios agent-first:

- descubrimiento de capacidades sin inspeccionar código fuente;
- JSON canónico para toda salida destinada a automatización;
- schemas y perfiles identificados por nombre y versión;
- códigos estables en lugar de depender de mensajes humanos;
- determinismo, idempotencia y ausencia de efectos laterales en inspección;
- procedencia y frontera de confianza explícitas;
- ejemplos ejecutables y fixtures antes que snippets ilustrativos;
- Markdown como mapa compacto para humanos y agentes, no como única API;
- memoria recuperada siempre marcada como datos no confiables;
- ninguna elevación de autoridad por campos autodeclarados.

## 2. Evidencia de partida

Hallazgos confirmados directamente:

- los cinco JSON Schema existen en fuente, pero no se incluyen en el wheel;
- `retrieve`, FTS5 y `assemble-context` sólo seleccionan `facts`;
- un fact largo puede rankear primero y quedar excluido por el presupuesto de la
  envolvente completa;
- `excluded_summary` informa conteos, pero no identifica el candidato excluido;
- FTS no se reconstruye durante commit, pero la lectura no queda obsoleta:
  degrada a `scan-fallback/v1` sobre la revisión vigente;
- la ayuda CLI no basta para construir con facilidad una propuesta y autoridad;
- la suite de `67f6ee4` pasa 124 pruebas y CI cubre Python 3.9/3.12 en Linux,
  macOS y Windows.

No se encontró evidencia de corrupción, pérdida de atomicidad, fallo de CAS,
mutación MCP o reutilización silenciosa de un índice de otra revisión.

## 3. Restricciones y no objetivos

Este plan no autoriza:

- cambiar `.an-kla/memory` ni el formato físico de ADR-0001;
- añadir FTS al camino autoritativo de commit;
- cambiar de forma incompatible `scan-fallback/v1`, `retrieval-result-v1` o
  `context-assembly/v1`;
- recuperar `events` o `episodes` bajo un perfil v1 existente;
- generar resúmenes automáticamente y presentarlos como fieles;
- fabricar `tool_observed` o `channel_confirmed` desde el CLI;
- habilitar escritura MCP;
- publicar, crear tags o integrar proveedores.

Las respuestas presupuestadas v1 quedan congeladas. Añadir campos como
`streams_searched` cambia bytes, `used_bytes` y selección, así que requiere un
schema o perfil versionado nuevo.

## 4. Preparación y baseline

El checkout local puede no coincidir con la beta evaluada. Antes de implementar:

- [x] Crear la rama `codex/agent-first-beta2` desde `origin/main` verificado.
- [x] Confirmar que `v0.1.0-beta.1^{}` resuelve a `67f6ee4`.
- [ ] No borrar ni incorporar archivos no rastreados del checkout actual.
- [x] Ejecutar la suite antes de cambios de recuperación, almacenamiento o
      concurrencia.
- [x] Registrar Python, plataforma y hash base en el reporte de la rama.
- [ ] Mantener cada cambio en un PR con una sola frontera contractual.

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Gate: 124/124 pruebas correctas y worktree limpio salvo artefactos de build
previstos e ignorados.

Baseline ejecutado el 2026-08-03: 124/124 pruebas correctas con Python 3.9.6 en
macOS, usando `/private/tmp` porque el sandbox ordinario era de sólo lectura.
El preflight resultó sano con la advertencia no bloqueante
`context_manifest_missing`.

## 5. Dependencias

```text
T0 baseline
  -> A0 contrato agent-first y capacidades
      -> T1 schemas empaquetados
          -> T2 documentación y ejemplos
              -> T3 validación/hash CLI

T0 baseline
  -> D1 ADR de explicabilidad
      -> T4 explain-retrieval/v1
          -> D2 ADR y benchmark de recuperación v2
```

`T1`–`T3` forman el alcance recomendado de la próxima beta. `T4` sólo entra si
conserva intactas las salidas v1. Recuperación v2 queda para otra entrega.

## 5.1 A0 — Descubrimiento para agentes

Los agentes no deben inferir capacidades leyendo `--help`, README o módulos. Se
diseñará una salida canónica de sólo lectura:

```text
an_kla capabilities
```

La respuesta `an-kla/capabilities-v1` describirá como mínimo:

- versión de producto y protocolo MCP;
- perfiles de recuperación y perfil predeterminado;
- streams almacenables y streams buscados por perfil;
- unidad de presupuesto disponible;
- schemas instalados y sus `$id`;
- operaciones gobernadas soportadas;
- clases de autoridad aceptables por CLI;
- herramientas MCP de lectura disponibles;
- límites declarados: sin escritura MCP, GC, multi-máquina o tokens exactos.

### Tareas

- [x] Crear ADR-0010 sobre contratos agent-first y compatibilidad.
- [ ] Revisar y aceptar ADR-0010.
- [x] Definir `capabilities-v1` sin leer memoria ni rutas locales.
- [x] Garantizar salida determinista y canonicalizable.
- [x] Entregar primero CLI/API y posponer la exposición MCP.
- [x] No insertar capacidades dentro de payloads v1 existentes.

### Aceptación

Un agente recién instalado descubre qué puede hacer AN-KLA, qué no puede hacer
y qué schemas debe usar sin leer código ni depender de prosa.

## 6. T0 — Contrato de compatibilidad

### Tareas

- [ ] Enumerar comandos, módulos exportados, schemas, perfiles y códigos de error
      de `v0.1.0-beta.1`.
- [ ] Capturar payloads dorados de `retrieve`, `assemble-context`, MCP retrieve y
      planificación de escritura.
- [ ] Registrar hashes SHA-256 de los fixtures canónicos.
- [ ] Documentar que alterar bytes, selección, orden, exclusiones o campos de una
      envolvente presupuestada exige una nueva versión.
- [ ] Definir reglas para campos aditivos fuera de envolventes presupuestadas.
- [ ] Declarar que comandos diagnósticos no cambian la garantía del recuperador.

### Aceptación

- existe una matriz de compatibilidad revisable;
- los fixtures v1 se comparan byte a byte;
- ninguna tarea posterior reinterpreta v1 implícitamente.

## 7. T1 — Distribución de schemas normativos

### Diseño

Usar `an_kla/schemas/` como ubicación empaquetable mediante
`importlib.resources`. Durante la transición, `docs/schemas/` puede conservarse
como espejo, pero CI debe exigir igualdad exacta o generarlo desde la fuente
canónica.

### Tareas

- [x] Crear `an_kla/schemas/` como paquete de recursos.
- [x] Incorporar exactamente:
  - `write-proposal-v1.schema.json`;
  - `write-authority-v1.schema.json`;
  - `write-decision-v1.schema.json`;
  - `write-plan-v1.schema.json`;
  - `cost-certificate-v1.schema.json`.
- [x] Declarar package data sin dependencias nuevas.
- [x] Implementar API interna para enumerar nombres y leer bytes.
- [x] Añadir `an_kla schema list` con envolvente JSON versionada y canónica.
- [x] Añadir `an_kla schema show <nombre>`.
- [x] Rechazar nombres desconocidos con código estable y sin rutas locales.
- [x] Preservar `$id`, versión y contenido normativo.
- [ ] Actualizar enlaces documentales a la fuente canónica.
- [x] Hacer que `capabilities-v1` enumere los mismos nombres de schema.

### Pruebas

- [x] Acceso a los cinco recursos desde checkout.
- [x] Construcción del wheel sin red.
- [x] Inspección ZIP de presencia y hashes.
- [x] Instalación del wheel en entorno temporal sin checkout.
- [x] Ejecución de `schema list/show` en ese entorno.
- [x] Igualdad entre fuente, espejo y wheel.
- [ ] Compatibilidad Python 3.9 y 3.12 (3.9 local correcto; 3.12 pendiente de CI).

### Aceptación

Una instalación aislada enumera y lee los cinco contratos exactos sin red ni
repositorio. No cambia ningún payload de memoria o recuperación.

## 8. T2 — Documentación y ejemplos ejecutables

### Alcance de recuperación

- [ ] Declarar en README que `scan-fallback/v1` busca sólo `facts`.
- [ ] Declararlo en `retrieve --help` y `assemble-context --help`.
- [ ] Declararlo en documentación MCP, ADR-0004 y ADR-0006.
- [ ] Explicar que `events` y `episodes` se almacenan, pero no son candidatos v1.
- [ ] Explicar que `assemble-context --budget` cubre la envolvente completa.
- [ ] Explicar que `index_unavailable` degrada aceleración, no corrección.

No añadir `streams_searched` a respuestas v1 en esta tarea.

### Escritura gobernada

- [ ] Añadir `proposal.json` y `authority.json` completos para `model_derived`.
- [ ] Añadir el caso equivalente para `derived_from_retrieval`.
- [ ] Mostrar una decisión aceptada y una `skip`.
- [ ] Explicar `issuer.kind`, `configuration_fingerprint`, `scope`, `evidence` y
      `lineage`.
- [ ] Explicar por qué autoridad derivada no permite `full` en policy/v1.
- [ ] Repetir que JSON no resuelve autoridad privilegiada.
- [ ] No versionar un planning result estático ligado a una revisión real.
- [ ] Acompañar cada ejemplo con schema, precondiciones, decisión esperada y
      códigos de razón esperados en forma parseable.

### Pruebas

- [ ] Ejecutar los ejemplos sobre memoria temporal.
- [ ] Verificar fingerprint y decisión esperados.
- [ ] Verificar que `skip` no crea journal, evento ni revisión.
- [ ] Verificar que documentación y `--help` coinciden.

### Aceptación

Un consumidor comprende qué se busca, por qué un fact puede no caber y cómo
construir una entrada derivada válida sin leer `write_policy.py`.

## 9. T3 — Hash y validación de entradas gobernadas

### Superficie mínima

```text
an_kla proposal-hash --proposal proposal.json
an_kla validate-write-input --proposal proposal.json --authority authority.json
```

### Tareas

- [ ] Reutilizar `canonical_json`, `digest_json`, validadores y
      `evaluate_write`; no duplicar política.
- [ ] Hacer ambos comandos estrictamente de lectura.
- [ ] Emitir resultado versionado con hashes, decisión y razones.
- [ ] No presentar validación como autorización o commit.
- [ ] Rechazar `tool_observed` y `channel_confirmed` desde CLI.
- [ ] Sanear errores: sin rutas, payloads ni secretos.
- [ ] Enlazar estos comandos desde `plan-write --help`.
- [ ] Emitir JSON canónico por stdout y reservar stderr para el código terminal
      saneado.
- [ ] Incluir `untrusted_input_data: true` cuando la salida reproduzca metadatos
      derivados de archivos del candidato.

No implementar aún `build-authority`: primero debe definirse quién construye
`issuer.configuration_fingerprint` y cómo se evita elevar autoridad.

### Pruebas

- [ ] Hash idéntico al usado por `evaluate_write`.
- [ ] Reordenar claves conserva el hash canónico.
- [ ] NaN, tipos inválidos y campos extra fallan cerrado.
- [ ] Objetos no ligados producen la decisión/código esperado.
- [ ] Autoridad privilegiada autodeclarada se rechaza.
- [ ] No se crea `.an-kla`, journal, segmento ni revisión.
- [ ] Errores no contienen rutas ni contenido.

### Aceptación

El consumidor calcula hashes y valida entradas con la implementación oficial,
sin mutar memoria ni fabricar autoridad.

## 10. D1 — ADR de explicabilidad

Antes de cambiar recuperación, decidir:

- schema `an-kla/retrieval-explain-v1`;
- frontera CLI/API y exclusión inicial de MCP;
- sensibilidad de IDs;
- presupuesto del diagnóstico;
- máximo de candidatos y bytes;
- `text_bytes` frente al incremento real de envolvente;
- razones `selected`, `inactive`, `invalid_record`, `no_text`, `zero_score` y
  `budget`;
- declaración de streams buscados/no buscados;
- coherencia de revisión bajo concurrencia;
- relación con scan y FTS5.

El ADR debe prohibir copiar contenido excluido y declarar que explicar no muta.

### Aceptación

Schema, amenaza de privacidad, presupuesto y reglas deterministas están
aceptados antes de implementar.

## 11. T4 — `explain-retrieval/v1`

### Superficie propuesta

```text
an_kla explain-retrieval --query QUERY --budget BYTES \
  --diagnostic-budget BYTES
```

### Tareas

- [ ] Reutilizar tokenización, render y ranking existentes.
- [ ] Fijar una revisión al inicio.
- [ ] Declarar `streams_searched: ["facts"]` sólo en el schema diagnóstico.
- [ ] Exponer por candidato sólo ID, score, costos, selección y motivo.
- [ ] Limitar candidatos y tamaño total.
- [ ] Marcar IDs y memoria como datos no confiables.
- [ ] Conservar `retrieve` y `assemble-context` byte a byte.
- [ ] No exponer inicialmente por MCP.
- [ ] Incluir magnitudes comprobables: bytes de texto, incremento de envolvente
      y presupuesto restante antes/después de cada decisión.

### Pruebas

- [ ] Fact largo relevante frente a fact corto.
- [ ] UTF-8 multibyte y checkpoint grande.
- [ ] Inactivos, inválidos y sin texto.
- [ ] Orden determinista en empates.
- [ ] Índice ausente, corrupto e incompleto.
- [ ] Equivalencia explicativa scan/FTS.
- [ ] Movimiento concurrente de `CURRENT` sin mezclar revisiones.
- [ ] Presupuesto del propio diagnóstico.
- [ ] Payloads v1 idénticos a T0.

### Aceptación

El caso largo/corto se diagnostica sin exponer texto, alterar selección normal o
exceder el presupuesto diagnóstico.

## 12. D2 — Recuperación v2 y proyecciones

Esta fase es diseño y benchmark antes de implementación.

### Preguntas obligatorias

- ¿Episodio completo, proyección o fact que lo referencia?
- ¿Los eventos son recuperables o sólo cronología?
- ¿Cómo se comparan scores entre streams?
- ¿Cómo se reparte presupuesto por procedencia?
- ¿Qué autoridad y linaje respaldan una proyección?
- ¿Dónde vive y cómo se content-addressa?
- ¿Cómo se sustituye o invalida?
- ¿First-fit por relevancia o utilidad por byte?
- ¿Cómo se evita usar tamaño como señal semántica implícita?

### Recomendación inicial

- conservar facts-only en v1;
- preferir un fact resumen gobernado que referencie un episodio;
- hacer toda proyección explícita, versionada y ligada al contenido;
- no generar resúmenes silenciosamente;
- no cambiar ranking sin perfil nuevo.

### Benchmark mínimo

- [ ] Facts cortos/largos con relevancia anotada.
- [ ] Unicode y normalización diversa.
- [ ] Mezcla de facts, events y episodes.
- [ ] Presupuestos amplios y cercanos al límite.
- [ ] Candidato más relevante que no cabe.
- [ ] First-fit, utilidad/costo y alternativas deterministas.
- [ ] Equivalencia/degradación FTS y scan.
- [ ] Calidad separada de costo y latencia.

Gate: no implementar v2 hasta elegir un objetivo medible y demostrar mejora sin
reinterpretar v1.

## 13. UX del índice

- [ ] Documentar FTS como caché derivada por revisión.
- [ ] Mostrar `requested_profile`, `profile` y `degradation` en ejemplos.
- [ ] Explicar cuándo `rebuild-index` recupera aceleración.
- [ ] No ejecutar rebuild durante commit.
- [ ] Mantener pruebas de índice ausente, corrupto, rehasheado e incompleto.

## 14. Estrategia de PRs

1. **PR 1 — Contratos empaquetados:** T1 y pruebas de wheel.
2. **PR 2 — Documentación:** T2 y ejemplos ejecutables.
3. **PR 3 — Validación CLI:** T3 sobre el núcleo puro.
4. **PR 4 — ADR de explicabilidad:** D1, sin implementación productiva.
5. **PR 5 — Diagnóstico:** T4, sólo después de aceptar D1.
6. **Trabajo posterior:** D2 y cualquier recuperación v2.

## 15. Gates de no regresión

Cada PR debe comprobar, según corresponda:

- suite completa y `git diff --check`;
- Python 3.9/3.12 y matriz Linux/macOS/Windows;
- igualdad byte a byte de payloads v1;
- ausencia de mutaciones para inspección/validación;
- errores saneados;
- wheel instalable sin checkout;
- ninguna dependencia nueva sin decisión explícita;
- ningún cambio de formato físico, CAS, lock o `CURRENT`.

## 16. Alcance de próxima beta

Mínimo recomendado:

- T0, T1, T2 y T3 completos;
- documentación del índice consolidada;
- todos los gates verdes.

T4 es deseable, pero no bloquea los contratos empaquetados si su ADR sigue en
revisión. Recuperación v2 queda fuera. Tag y publicación requieren autorización
explícita separada.

## 17. Coordinación con consumidores

- [ ] Compartir la clasificación corregida del issue #10.
- [ ] Avisar antes de modificar schemas, perfiles o firmas públicas.
- [ ] Proporcionar fixtures de compatibilidad a Argos.
- [ ] Solicitar manifiestos de Argos con backend, modelo, versiones, umbrales,
      configuración y fingerprints.
- [ ] No convertir métricas heurísticas de Argos en gates de release.
- [ ] Usar Argos para seleccionar zonas de inspección directa.

## 18. Definición de terminado

El ciclo termina cuando:

- el wheel expone los cinco schemas exactos;
- facts-only es inequívoco sin alterar payloads v1;
- los ejemplos gobernados son pruebas ejecutables;
- hashes y entradas se validan sin mutar memoria;
- v1 permanece byte a byte compatible;
- CAS, journals, canonicalización y fallback conservan garantías;
- existe decisión explícita sobre incluir T4;
- todo trabajo multi-stream permanece bajo perfil versionado.
