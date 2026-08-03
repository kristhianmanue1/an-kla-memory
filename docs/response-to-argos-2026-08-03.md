# Respuesta técnica al equipo de Argos

Fecha: 2026-08-03

Asunto: retroalimentación sobre la reevaluación de `an-kla-memory@67f6ee4`

Equipo de Argos:

Gracias por la reevaluación técnica y, especialmente, por separar el carril de
análisis de Argos de las comprobaciones directas sobre código, tests, wheel y
comportamiento observable. Esa separación mejora materialmente la utilidad del
reporte y corrige interpretaciones que aparecieron en el issue #10.

Nuestra revisión coincide con sus conclusiones principales:

- no encontramos evidencia de corrupción, lectura obsoleta, fallo de CAS,
  pérdida de atomicidad o mutación desde MCP;
- el fact largo sí es encontrado y rankeado; queda fuera porque no cabe en la
  envolvente global de `assemble-context`;
- AN-KLA no usa BM25 para ordenar resultados;
- recuperación v1 sólo considera `facts`;
- el índice no se actualiza durante commit, pero tampoco se reutiliza
  silenciosamente: la revisión nueva degrada a scan y permanece correcta;
- los JSON Schema existen en el checkout, pero no se distribuyen en el wheel;
- la escritura gobernada conserva buenas propiedades, aunque su integración CLI
  requiere demasiada construcción manual.

Valoramos también que el nuevo reporte retire sospechas no sustentadas sobre CAS
o atomicidad y que trate `coverage`, `residual_risk` y `complete` como señales
heurísticas, no como certificados del producto.

## Comentarios críticos sobre la metodología

La extracción estructural de Argos es útil para localizar superficies de alto
impacto. Pudimos reproducir los 56 artefactos, el grafo 260/499, los impactos de
`main` y `commit_write_plan`, y los conteos de comportamiento. Sin embargo, esas
métricas deben continuar acompañadas por sus límites:

- el grafo AST y la resolución por nombre corto aproximan alcanzabilidad, no
  frecuencia real, criticidad de negocio o corrección;
- los conteos de funciones con `raise` incluyen producción y tests;
- una separación nominal entre `ValueError` y errores de dominio no implica
  familias independientes; `ContextPackageError` hereda de `ValueError`;
- una puntuación alta de impacto no demuestra por sí misma que una frontera esté
  correctamente encapsulada.

La comparación lexical/densa es particularmente valiosa. Una cobertura de
`0.0` frente a `0.8667` sobre el mismo objetivo demuestra que el backend no es
un detalle: forma parte de la identidad del experimento.

Recomendamos que cada reporte incluya un manifiesto legible por máquina con, al
menos:

```json
{
  "schema": "argos/run-manifest-v1",
  "target_revision": "...",
  "evaluator_revision": "...",
  "linker_profile": "...",
  "model": "...",
  "model_revision": "...",
  "configuration_fingerprint": "sha256:...",
  "thresholds": {},
  "dependency_versions": {},
  "artifact_set_fingerprint": "sha256:..."
}
```

El Markdown debería generarse desde ese manifiesto para evitar que frases fijas
declaren un linker distinto del ejecutado.

## Sobre los conflictos sintéticos

Coincidimos en no atribuir a AN-KLA los cinco conflictos producidos por la
corrida densa. Los pares señalados no contienen contradicciones textuales
verificadas; son incompatibilidades inferidas entre proposiciones sintéticas.

Sería útil distinguir explícitamente:

- `textual_contradiction`;
- `behavioral_contradiction`;
- `schema_incompatibility`;
- `synthetic_tension`;
- `unadjudicated_similarity`.

Mientras no exista adjudicación, sugerimos evitar la etiqueta simple `conflict`
en el resumen ejecutivo. `synthetic_tension` o `candidate_conflict` comunica
mejor el nivel de evidencia.

Un conflicto verificable debería incluir:

- dos claims normalizados y visibles;
- polaridad opuesta explícita;
- alcance común;
- evidencia primaria de ambos lados;
- explicación del criterio de incompatibilidad;
- estado de adjudicación.

## Sobre independencia

Agradecemos que el reporte reconozca la dependencia operativa entre ambos
proyectos. Proponemos sustituir “validación independiente” por:

> Evaluación cruzada entre repositorios con dependencia operativa declarada y
> verificación directa separada.

Esto conserva el valor de que analizador y código analizado sean repositorios
distintos sin sobreafirmar independencia organizacional o epistemológica.

## Acciones que AN-KLA incorpora

A partir de sus hallazgos y nuestras reproducciones, proponemos:

1. empaquetar los cinco schemas normativos como recursos instalables;
2. probar construcción, inspección e instalación aislada del wheel;
3. documentar que recuperación v1 busca exclusivamente `facts`;
4. añadir ejemplos completos y ejecutables de propuesta y autoridad derivada;
5. ofrecer hash canónico y validación no mutante desde CLI;
6. diseñar una interfaz separada y presupuestada para explicar exclusiones;
7. estudiar proyecciones y multi-stream sólo bajo un perfil nuevo.

No planeamos actualizar FTS dentro del commit. Tampoco añadiremos episodios a un
perfil v1 ni generaremos resúmenes automáticamente.

Existe una cautela de compatibilidad: añadir
`streams_searched: ["facts"]` o diagnósticos por candidato a respuestas v1
cambiaría bytes, `used_bytes` y qué registros caben. Documentaremos
inmediatamente el alcance actual, pero cualquier campo nuevo en una respuesta
presupuestada deberá entrar mediante schema o perfil versionado. La
explicabilidad se diseñará inicialmente como operación separada.

## Propuesta de coordinación

Nos gustaría coordinar mediante contratos y fixtures, no mediante acoplamiento a
detalles internos:

- AN-KLA puede proporcionar payloads dorados y fixtures de compatibilidad para
  recuperación, ensamblado y escritura gobernada;
- Argos puede ejecutarlos como consumidor downstream;
- cambios futuros de schema, perfil o firma pública deben anunciarse antes de
  integrarse;
- los manifiestos de corrida de Argos pueden conservar trazabilidad;
- los resultados semánticos se usarán para priorizar inspección, mientras que
  las afirmaciones del producto seguirán apoyándose en código, pruebas y
  artefactos distribuibles.

Como caso compartido de regresión proponemos conservar:

```text
fact largo, mayor score, no cabe
fact corto, menor score, sí cabe
episode relevante, fuera del stream v1
índice ausente para revisión nueva, fallback correcto
```

Argos puede observar explicabilidad y experiencia downstream; AN-KLA puede
mantener el fixture normativo y las garantías de presupuesto.

## Cierre

La reevaluación actual es considerablemente más útil que el diagnóstico inicial
porque distingue síntomas, mecanismos y límites del evaluador. Recibimos como
válidos los hallazgos de distribución, visibilidad facts-only, explicabilidad y
ergonomía.

Nuestra principal petición para futuras evaluaciones es conservar una identidad
reproducible del experimento y separar conflicto sintético de contradicción
verificada. Con esas mejoras, Argos puede aportar una señal externa valiosa sin
convertir sus métricas semánticas en afirmaciones más fuertes que la evidencia.

Gracias por la revisión y por corregir las hipótesis de BM25, lectura stale y
ausencia total de schemas.
