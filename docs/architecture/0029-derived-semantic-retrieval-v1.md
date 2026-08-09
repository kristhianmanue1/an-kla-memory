# ADR-0029: recuperación semántica mediante índice derivado

- **Estado:** Propuesta; formalización de Fase 8 autorizada por el maintainer el
  2026-08-09. No autoriza implementación ni integración de proveedores.
- **Fecha:** 2026-08-09
- **Decide sobre:** la frontera arquitectónica de una futura recuperación
  vectorial e híbrida sin convertir embeddings, modelos o índices en autoridad.

## Contexto

AN-KLA beta.11 recupera por coincidencia de términos. `scan-fallback/v1`
calcula el ranking productivo y `sqlite-fts5/v1` sólo estrecha candidatos; el
índice es una caché derivada ligada a una revisión y degrada explícitamente a
scan cuando falta, está obsoleto o no pasa integridad. Esta arquitectura es
local, determinista y auditable, pero pierde consultas conceptualmente
equivalentes sin términos compartidos.

ADR-0025 creó el benchmark de recuperación v2 y comparó overlap, BM25 y
summary-indexed. BM25 mostró una señal mejor en un corpus pequeño, pero el gate
concluyó `ranking_change_authorized=false`: otra estrategia requiere corpus
ampliado, evidencia externa y un ADR posterior.

El issue #41 contiene dos insumos directos de `adrc-python`/CMF:

- su pipeline ChromaDB usa embeddings, HNSW, over-fetch y reranking;
- su dualidad ChromaDB + SQLite produjo huérfanos, doble embedding, fallback
  asimétrico, deriva de namespaces y filtros epistémicos distintos por backend;
- a la escala observada, la auditoría de ADRC consideró innecesario el coste de
  dos stores autoritativos;
- la recomendación transferible fue evaluar `sqlite-vec` como índice derivado
  local antes que introducir otro servicio de almacenamiento.

TencentDB Agent Memory aporta otro precedente: memoria estratificada y recall
híbrido BM25 + vector + fusión. AN-KLA no adopta automáticamente su pirámide ni
su extracción por LLM: recuperación semántica y generación de memoria son dos
decisiones diferentes.

Escrubery aporta un precedente distinto: catálogo con procedencia, política de
datos y una cadena Evidentia que podría atestiguar la identidad de un perfil.
La revisión del 2026-08-09 concluyó que no implementa búsqueda vectorial y que
su cadena, checkpoint, sandbox y fuente remota aún requieren hardening. Por
tanto, sólo se considera como resolver/attestor opcional después de gates
propios; no como backend ni dependencia viva del core.

Restricciones vigentes:

- la memoria recuperada es dato no confiable, nunca instrucción o autoridad;
- el CAS de revisiones es la única fuente canónica;
- `facts`, `events`, `episodes` y `working_state` conservan su semántica;
- `used_bytes` sigue midiendo el render entregado, no vectores ni trabajo de CPU;
- el perfil predeterminado y los payloads existentes no cambian implícitamente;
- AN-KLA soporta Python 3.9 y publica wheel sin dependencias runtime;
- el store tiene lock local y una sola memoria activa; esta fase no promete
  coordinación multi-máquina ni multi-tenant;
- integrar modelos, servicios o adaptadores de proveedores requiere orden
  explícita separada del maintainer.

## Decisión

**Toda búsqueda semántica futura se implementará como perfil opt-in sobre un
índice derivado, reconstruible y ligado a una revisión. El índice, los vectores
y la salida de un modelo nunca forman parte de la autoridad canónica.**

La aceptación de esta ADR queda condicionada al spike y los gates de Fase 8.
La formalización fija desde ahora los siguientes invariantes.

### 1. Una sola fuente de verdad

Los registros y su ciclo de vida continúan en segmentos, revisiones y overlays
CAS de AN-KLA. El índice semántico:

- se construye exclusivamente desde un snapshot de revisión explícita;
- se puede eliminar y reconstruir sin perder memoria;
- no participa en `plan-write`, `commit-write-plan`, checkpoint, refute,
  export/restore ni compactación como autoridad;
- no puede crear, modificar, superseder o refutar registros;
- no se incluye por defecto en exportaciones canónicas.

No habrá escritura dual canónica SQLite + ChromaDB ni compensaciones tipo saga.
ChromaDB, Qdrant, pgvector y servicios remotos quedan fuera de la primera
implementación candidata.

### 2. Binding verificable del índice

Cada generación candidata debe ligar como mínimo:

- revisión exacta y `project_uuid`;
- perfil de extracción de texto (`record_text` o sucesor versionado);
- streams y reglas de elegibilidad;
- digest ordenado de los registros físicos elegibles;
- perfil de embeddings, modelo, dimensión y normalización;
- configuración de búsqueda, versión del indexador y schema del índice;
- digest de sus bytes o manifest equivalente.

La configuración saneada no incluye secretos, credenciales ni rutas absolutas.
Cambiar cualquiera de esos elementos produce otra identidad de índice; nunca se
reinterpreta un índice viejo bajo configuración nueva.

### 3. Perfil de embeddings explícito

El core no descarga modelos ni elige proveedor. El spike comparará, sin integrar
todavía:

- callback inyectado por el host;
- proceso local con argv configurado externamente, sin shell;
- biblioteca o extensión local empaquetable;
- servicio remoto sólo como alternativa con consentimiento y threat model
  propios.

El perfil debe declarar fingerprint, dimensión, normalización, límites, timeout
y tratamiento de errores. La salida debe ser finita, de longitud exacta y sin
NaN/Infinity. Un embedding recuperado de memoria no puede configurar el perfil.

Si se evalúa `sqlite-vec`, el spike debe probar compatibilidad real con Python
3.9, wheels soportados, sistemas del CI, SQLite efectivo y operación offline.
Este ADR no declara `sqlite-vec` seleccionado hasta obtener esa evidencia.

Un perfil puede incluir una atestación externa verificable, pero ésta no elige
ni autoriza el modelo. El core recibe bytes/snapshot desacoplados, no consulta
un catálogo vivo durante retrieval. El host fija la clave y política, valida
schema, firma, vigencia, modelo, artefacto, dimensión y privacidad, y liga el
digest exacto al manifest. La firma autentica al emisor; no certifica calidad,
seguridad ni permiso para transmitir memoria.

Escrubery se evalúa en el subtrack F8-E como una implementación posible de esa
interfaz genérica. Su ausencia o rechazo no bloquea callback/proceso/biblioteca
local ni scan/FTS. Integrar o distribuir su adapter requiere autorización
explícita posterior y que sus gates E0–E5 hayan pasado.

### 4. Elegibilidad y filtros únicos

La elegibilidad canónica se calcula en el motor antes de aceptar candidatos del
índice. Debe ser uniforme para scan, FTS5, vector e híbrido:

- mismo snapshot y streams;
- mismo `record_text` versionado;
- exclusión de `superseded` y `refuted` antes de top-k y presupuesto;
- mismo tratamiento de registros inválidos o sin texto;
- frescura como proyección informativa mientras otro ADR no autorice que afecte
  score;
- IDs y record digests revalidados contra el snapshot, nunca confiados desde el
  índice.

Un backend que no pueda aplicar estos invariantes no es elegible como perfil.

### 5. Perfiles separados y degradación visible

La primera superficie candidata será un perfil vectorial opt-in; su nombre
exacto se congelará después del spike. Un perfil híbrido será otro perfil, no un
modo oculto del vectorial.

Todo resultado debe declarar perfil pedido, perfil efectivo, revisión,
configuración/fingerprint y degradación. Índice ausente, corrupto, stale,
incompatible, modelo no disponible, timeout o dimensión distinta nunca producen
éxito semántico silencioso. Un fallback lexical sólo es válido si el contrato lo
declara y el resultado lo hace observable.

`scan-fallback/v1` sigue siendo el default hasta que otra ADR, métricas externas
y compatibilidad autoricen cambiarlo.

### 6. Ranking, fusión y presupuesto

Vector e híbrido recuperan candidatos antes de aplicar el presupuesto de
render. Se evaluarán al menos:

1. overlap productivo;
2. BM25 experimental;
3. similitud vectorial exacta o aproximada;
4. fusión lexical + vector, inicialmente RRF como experimento;
5. variantes con over-fetch + rerank.

Threshold, top-k interno, factor de over-fetch, función de distancia, desempate
y parámetros de fusión son configuración versionada, no literales dispersos.
No se admiten topes ocultos. Los scores de espacios diferentes no se suman sin
una regla de normalización explícita.

El budget continúa aplicándose sobre el payload entregado después del ranking.
Coste de embeddings, latencia y tamaño del índice se reportan como métricas
separadas; no se presentan como `used_bytes`.

### 7. Benchmark semántico antes de producto

ADR-0025 se extiende mediante un contrato nuevo, no reinterpretando sus
reportes. El corpus debe incluir:

- paráfrasis sin términos compartidos;
- sinónimos, abreviaturas y variantes español/inglés;
- negación y contradictores léxicamente cercanos;
- hechos largos y cortos bajo los presupuestos vigentes;
- chains supersede y refute;
- facts, events y episodes;
- consultas exactas de handoff y consultas reales saneadas;
- índice ausente, fresco, corrupto, stale y model-mismatch;
- casos en los que lexical debe ganar y casos en los que vector debe ganar.

Se medirán Precision@k, Recall@k, MRR, first relevant rank, budget recall,
latencia descriptiva, coste de construcción, tamaño y degradación. Promover una
estrategia exige corpus externo, revisión humana, ausencia de regresión material
en consultas exactas y una métrica de tarea o distorsión conforme ADR-0005.

### 8. Memoria semántica generada queda separada

Embeddings mejoran acceso; no convierten automáticamente conversaciones en
facts, episodes, personas o instrucciones. Una futura síntesis L0→L3 o similar
requiere otra ADR y otra autorización de proveedor.

Como invariante mínimo, cualquier extracción por LLM será una propuesta no
confiable. Para persistir deberá atravesar la política gobernada con autoridad
separada; `model_derived` conserva su techo y nunca puede autoelevarse. Personas,
escenarios y resúmenes serán vistas derivadas o registros con procedencia, no
un prompt global ni un cuarto stream implícito. `working_state` seguirá fuera de
la búsqueda lexical/vectorial por similitud.

## Por qué no [alternativa]

### ChromaDB como segundo store autoritativo

Repite los fallos observados en ADRC: dual write, compensación, namespaces,
filtros divergentes y reconstrucción difícil. Puede reevaluarse como caché sólo
si la evidencia de escala justifica un servicio separado.

### Sustituir FTS5 por vectores

Las búsquedas exactas, IDs, comandos y términos técnicos favorecen lexical. La
semántica complementa, no elimina, ese camino. FTS5 conserva además un fallback
local sin modelo.

### Elegir ahora `sqlite-vec` y un modelo concreto

Faltan pruebas de portabilidad, packaging, licencias, dimensión, latencia y
calidad sobre el corpus del proyecto. Congelarlos antes del spike convertiría
una preferencia histórica en una decisión sin evidencia fresca.

### Generar embeddings dentro del commit canónico

Haría depender una escritura durable de CPU, modelos, proveedores o red;
alteraría replay y podría dejar la memoria inaccesible por una falla de caché.
El commit canónico termina antes de cualquier reindexado best-effort.

### Escritura automática de memorias sintetizadas

Confunde inferencia con autoridad y amplía la superficie de prompt injection.
La extracción puede proponer; sólo la ruta gobernada puede persistir.

## Consecuencias

- **Positivas:** abre recall por significado sin abandonar la verificabilidad,
  conserva operación lexical/offline y evita un segundo store autoritativo.
- **Negativas:** añade costo de embeddings, matrices de compatibilidad,
  fingerprint de modelos, nuevas amenazas de privacidad y más perfiles que
  evaluar.
- **Neutras:** esta ADR propuesta no cambia código, schemas, wheel, versión,
  capabilities, ranking, formato físico ni datos existentes.

## Test de regresión requerido

Antes de aceptar implementación deberán existir pruebas para:

1. build determinista o manifest determinista del mismo snapshot/configuración;
2. rechazo de revisión, modelo, dimensión, manifest o digest distintos;
3. índice ausente/corrupto/stale/model-mismatch con degradación explícita;
4. igualdad de filtros de lifecycle en scan/FTS/vector/híbrido;
5. cero resultados de otro proyecto o stream no pedido;
6. presupuesto aplicado después de ranking y payload dentro del límite;
7. eliminación total del índice seguida de rebuild equivalente;
8. commit correcto aunque embedding/reindex falle;
9. ninguna descarga, red o ejecución de shell implícita;
10. memoria recuperada incapaz de elegir modelo, endpoint o configuración;
11. wheel limpio y matriz Python 3.9/3.12 en plataformas soportadas;
12. perfiles vigentes byte-compatibles y default sin cambios.
13. atestación inválida/expirada/revocada o resolver ausente sin acceso al hot
    path y con degradación visible;
14. digest de atestación y política de clave ligados al manifest sin secretos;
15. perfil directo del host operativo sin Escrubery ni servicio externo.

## Referencias

- Issue #41, insumo ADRC/CMF:
  https://github.com/kristhianmanue1/an-kla-memory/issues/41#issuecomment-5224269722
- Issue #41, pipeline ChromaDB y anti-lecciones:
  https://github.com/kristhianmanue1/an-kla-memory/issues/41#issuecomment-5224339846
- Issue #10, validación externa pendiente de Argos:
  https://github.com/kristhianmanue1/an-kla-memory/issues/10
- TencentDB Agent Memory:
  https://github.com/TencentCloud/TencentDB-Agent-Memory
- Escrubery, análisis adversarial y propuesta F8-E:
  https://github.com/kristhianmanue1/escrubery/issues/1
- ADR-0004, índice derivado; ADR-0005, evaluación decisional; ADR-0008, costo;
  ADR-0013/0014/0016/0018, retrieval e índice; ADR-0021, frescura; ADR-0025,
  benchmark v2; ADR-0026, refute; ADR-0028, compactación.
- Plan ejecutable de Fase 8:
  `docs/planning/fase-8-recuperacion-semantica-2026-08-09.md`.
- Subtrack opcional de atestación:
  `docs/planning/fase-8-escrubery-attestation-2026-08-09.md`.
