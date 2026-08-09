# Fase 8 — recuperación semántica derivada

- **Estado:** formalizada; investigación autorizada, implementación pendiente.
- **Fecha:** 2026-08-09
- **ADR rector:** ADR-0029 (Propuesta)
- **Precondición vigente:** evidencia externa del consumidor en issue #10.

## Objetivo

Añadir recuperación por significado y, después, evaluar memoria semántica
generada, preservando el CAS de AN-KLA como única autoridad. La fase no integra
un proveedor, no cambia el ranking productivo y no descarga modelos por sí sola.

## No confundir los tracks

| Track | Pregunta | Primera entrega |
|---|---|---|
| Retrieval semántico | ¿Cómo encontrar un registro existente por significado? | Índice vectorial derivado y perfil opt-in |
| Memoria semántica | ¿Cómo proponer hechos/escenarios a partir de evidencia? | Contrato posterior de propuestas no confiables |
| Atestación de perfil (F8-E) | ¿Cómo verificar qué modelo/configuración fue observado? | Snapshot firmado opcional, nunca backend |

El track de retrieval puede completarse sin permitir que un LLM escriba
memoria. El track de generación no comienza con la autorización de este
documento: necesita ADR y orden explícita para cualquier adaptador de proveedor.
F8-E puede investigarse en paralelo, pero no bloquea el perfil genérico y no
autoriza integrar Escrubery.

## Secuencia ejecutable

### F8.0 — cerrar evidencia de entrada

1. Ejecutar la validación de Argos del issue #10 contra beta.11.
2. Registrar queries fallidas y exitosas, preservando privacidad.
3. Clasificar fallos: tokenización, paráfrasis, presupuesto, stream, lifecycle,
   índice o UX.
4. No atribuir a semántica un fallo que sea de streams o presupuesto.

**Gate:** reporte externo reproducible y corpus saneado. Sin él no se elige
modelo, extensión ni algoritmo.

### F8.1 — spike de portabilidad y threat model

Spike read-only, sin tocar `store.py`, `retrieval.py` o `index.py`:

1. Comparar brute-force exacto, `sqlite-vec` y al menos una alternativa sólo
   como control; ChromaDB no es candidato autoritativo.
2. Probar Python 3.9/3.12, SQLite efectivo, macOS/Linux/Windows, wheel limpio y
   operación offline.
3. Medir build/query, RAM, disco y rebuild desde el fixture.
4. Evaluar callback host, proceso local y biblioteca local para embeddings.
5. Identificar licencias, descarga de pesos, telemetría, red, persistencia de
   modelos y exposición de datos.
6. Proponer binding y códigos de degradación exactos.

**Salida:** `docs/planning/spike-semantic-index-v1.md` con archivo:línea,
comandos, top riesgos y veredicto `proceed | refine | escalate`.

### F8.2 — benchmark semántico v3

Crear ADR de evaluación o enmienda explícita sin reinterpretar ADR-0025:

- queries exactas y semánticas emparejadas;
- paráfrasis sin overlap, sinónimos, negaciones y distractores cercanos;
- multistream y lifecycle completo;
- presupuestos 256/512/1024/4096;
- estados absent/fresh/corrupt/stale/model-mismatch;
- métricas de ranking, budget, latencia, build y tamaño;
- corpus externo saneado con review humana ligada al digest.

Comparar overlap, BM25, vector y lexical+vector. El benchmark es read-only y
ningún resultado autoriza por sí solo un ranking productivo.

### F8.3 — aceptar o rechazar ADR-0029

Actualizar ADR-0029 con la evidencia del spike y benchmark:

- extensión/backend elegidos o rechazo explícito;
- perfil/fingerprint de embeddings;
- layout y manifest exactos;
- schema de resultado y degradaciones;
- compatibilidad, migración y política de fallback;
- decisión sobre ANN vs exacto y RRF;
- amenaza de privacidad y consentimiento.

Ejecutar ronda adversarial pre-code fresca. Sólo `proceed` más aceptación
explícita del maintainer permite código.

### F8-E — atestación opcional mediante Escrubery

Track paralelo detallado en
`docs/planning/fase-8-escrubery-attestation-2026-08-09.md`:

1. **E0:** hacer reproducible la fuente remota, CI, tests y licencia.
2. **E1:** append Evidentia inmutable/serializado, checkpoint real y keyring
   verificable.
3. **E2:** endurecer F3 con artefactos fijados, aislamiento y cero mutación ante
   fallo.
4. **E3:** congelar `embedding-profile-attestation-v1` y políticas de datos.
5. **E4:** export/verificación offline sin base o MCP vivos.
6. **E5:** spike de adapter contra fixtures, con drift/expiry/revocación.

Escrubery sólo observa y atestigua. AN-KLA verifica un snapshot con clave fijada
por el host y liga su digest al manifest; no consulta PostgreSQL/MCP en el hot
path. El track queda `FIX-AND-RETRY` para integración runtime por los bloqueos
documentados en `kristhianmanue1/escrubery#1`. Un adapter requiere orden
explícita independiente incluso si E0–E5 pasan.

### F8.4 — PR-A: núcleo de índice derivado

Superficie prevista, sujeta al ADR aceptado:

- nuevo módulo de perfil/validación de embeddings;
- build y resolución content-addressed por revisión/configuración;
- manifest de cobertura y digests;
- rebuild manual y best-effort post-commit;
- doctor/verify-index sin autoridad de commit;
- schemas normativos y empaquetados.

No modificar ranking productivo en este PR. Fallar embeddings no puede revertir
ni degradar un commit ya durable.

### F8.5 — PR-B: retrieval vectorial opt-in

- perfil vectorial explícito;
- query embedding con timeout y shape cerrada;
- candidatos revalidados contra snapshot;
- lifecycle/streams/texto uniformes;
- over-fetch, threshold y desempate versionados;
- budget después de ranking;
- degradación visible y payload `untrusted_memory_data`.

Los perfiles v1 conservan bytes y comportamiento para los mismos inputs.

### F8.6 — PR-C: híbrido experimental

- fusión RRF o alternativa aceptada;
- lexical y vector conservan diagnósticos separados;
- no sumar scores heterogéneos sin normalización;
- benchmark v3 y reportes versionados;
- `capabilities()` sólo anuncia perfiles implementados, no experimentos
  internos.

El perfil híbrido sigue opt-in. Cambiar el default requiere otra decisión
explícita posterior.

### F8.7 — track separado de memoria semántica

Sólo después del retrieval:

1. ADR para propuestas derivadas LLM y procedencia por evidencia.
2. Definir si persona/escenario son vistas, episodes o nuevos artefactos; no
   crear un cuarto stream por accidente.
3. Toda síntesis sale como propuesta no confiable.
4. Persistencia únicamente por `plan-write -> commit-write-plan` y autoridad
   separada; `model_derived` conserva su techo.
5. Probar refute/supersede, drift, prompt injection y reconstrucción desde
   evidencia.

Integrar un modelo o proveedor no está autorizado por la Fase 8 documental.

### F8.8 — cierre de release

- rondas adversariales por PR y una pasada fresca integral;
- suite completa y `ci_local --simulate-ci`;
- wheel limpio y matriz de plataformas disponible;
- schemas docs/package byte-idénticos;
- migración beta.11 y rebuild de índices;
- docs de instalación, privacidad, operación offline y degradaciones;
- benchmark humano aprobado y gate de tag fail-closed.

`main` no es etiquetable entre PR-A y el cierre de PR-C/release. El número de
release se decide al aceptar ADR-0029; este plan no reserva ni publica tag.

## Invariantes no negociables

1. CAS y revisiones siguen siendo la fuente de verdad.
2. El índice es descartable y reconstruible.
3. Los filtros epistémicos son idénticos en todos los perfiles.
4. Ningún dato recuperado configura modelos, endpoints o comandos.
5. Ninguna red, descarga o telemetría es implícita.
6. El default lexical no cambia durante la fase experimental.
7. `working_state` no entra a búsqueda por similitud.
8. Resultado vectorial no concede autoridad de escritura.
9. Fallback y límites siempre son observables.
10. No hay dual write autoritativo.
11. Una atestación externa no elige perfil, no autoriza red y no eleva
    autoridad; su ausencia no rompe scan/FTS.

## Criterio de terminación

La Fase 8 termina sólo cuando existe una de estas decisiones verificables:

- **adoptar:** perfil semántico opt-in implementado, benchmarkeado, documentado
  y publicado con gates completos;
- **rechazar:** evidencia demuestra que coste, portabilidad, privacidad o
  calidad no justifican la función y ADR-0029 queda `Rechazado` con resultados;
- **diferir:** bloqueo externo explícito y estado durable, sin presentar el
  prototipo como capacidad del producto.

## Dependencias y referencias

- ADR-0029: frontera de índice derivado.
- ADR-0004/0014/0016: índice FTS5 derivado y degradación.
- ADR-0005/0025: evaluación y prohibición de promover por métricas aisladas.
- ADR-0008: presupuesto y costos separados.
- ADR-0021/0026: frescura y lifecycle.
- Issue #10: validación externa pendiente.
- Issue #41: análisis ADRC/CMF y ChromaDB.
- Escrubery #1: análisis adversarial, hardening y propuesta F8-E.
- Plan F8-E: `fase-8-escrubery-attestation-2026-08-09.md`.
