# Ronda adversarial documental de Fase 8 — recuperación semántica

## Alcance

Ataque preliminar a ADR-0029 y al plan de Fase 8 antes de cualquier código. Se
revisan autoridad, dual stores, lifecycle, privacidad, portabilidad, ranking,
presupuesto, degradación, compatibilidad y generación automática de memoria.
La pasada se amplió con evidencia directa de Escrubery como posible attestor;
no se asumió que su firma, sandbox o checkpoint fueran garantías cerradas.

Esta pasada fue realizada por el mismo agente que redactó la propuesta; detecta
inconsistencias internas, pero no sustituye la ronda fresca requerida para
aceptar el ADR o iniciar implementación.

## Modelo de amenazas

Memoria, corpus, queries, embeddings, metadata de índices y salida de modelos
son datos no confiables. Amenazas principales:

- prompt injection que intenta configurar el embedder o autorizar escritura;
- exfiltración de memoria a un endpoint remoto;
- índice alterado que introduce IDs ajenos o revive registros inactivos;
- model drift o dimensión distinta interpretados bajo el mismo perfil;
- fallback silencioso presentado como búsqueda semántica;
- resultados aproximados que evaden filtros canónicos;
- síntesis LLM persistida como verdad sin autoridad;
- dependencia o modelo incompatible con wheels/plataformas declaradas.
- catálogo externo comprometido, stale o no reconstruible que selecciona un
  modelo o introduce un endpoint;
- firma válida interpretada erróneamente como calidad, privacidad o autoridad;
- consulta de PostgreSQL/MCP externo en el hot path que elimina operación
  offline o produce drift no ligado al manifest.

## Hallazgos y correcciones incorporadas

| Severidad | Hallazgo | Riesgo | Corrección documental |
|---|---|---|---|
| BLOCKER | “adoptar memoria semántica” mezclaba retrieval y escritura LLM | inferencia automática podía adquirir autoridad | tracks separados; generación requiere otra ADR y flujo gobernado |
| BLOCKER | preferir `sqlite-vec` podía leerse como selección ya tomada | integrar una dependencia sin portabilidad/licencia demostradas | elección condicionada a spike Python/SQLite/wheel/OS |
| BLOCKER | un índice íntegro podía contener IDs fuera del snapshot | contaminación cross-revision/proyecto | revalidar IDs/digests y elegibilidad contra snapshot canónico |
| HIGH | degradar siempre a lexical ocultaría que no hubo semántica | consumidor atribuiría calidad al perfil incorrecto | perfil efectivo, fingerprint y razón de degradación obligatorios |
| HIGH | embeddings remotos no tenían frontera de privacidad | transmisión no autorizada de memoria | alternativa remota separada, consentimiento y threat model propios |
| HIGH | top-k/threshold/over-fetch podían quedar como magic numbers | resultados irreproducibles y drift silencioso | configuración versionada y fingerprint |
| HIGH | score vectorial y BM25 podían sumarse directamente | ranking sin interpretación estable | fusión explícita; RRF sólo experimental al inicio |
| HIGH | filtros post-top-k revivirían superseded/refuted | memorias inválidas desplazan candidatas activas | elegibilidad antes de selección y revalidación canónica |
| MEDIUM | costo vectorial podía confundirse con `used_bytes` | contrato de presupuesto falso | CPU/latencia/index size como métricas separadas |
| MEDIUM | exportar índices por defecto aumentaría superficie sensible | embeddings innecesarios en backup | índice fuera del export canónico por defecto |
| MEDIUM | elegir una versión de release ahora acoplaba el roadmap | tag prematuro o main falsamente etiquetable | release se decide tras aceptar ADR-0029 |
| BLOCKER | tratar Escrubery como motor vectorial o dependencia lista | no implementa retrieval semántico y su remoto no reconstruye el HEAD evaluado | rol limitado a attestor opcional; E0 exige fuente reproducible |
| BLOCKER | confiar en Evidentia/checkpoint como garantía cerrada | append concurrente puede bifurcar; replay muta campos hasheados; checkpoint observado es nulo | E1 exige inmutabilidad, serialización, checkpoint real y verifier offline |
| HIGH | introspección F3 podía elevar evidencia fallida a perfil | sandbox insuficiente y captura vacía persistida | E2 fija allowlist/digests, aislamiento, resultado tipado y cero mutación ante fallo |
| HIGH | firma de catálogo podía confundirse con autorización | autenticidad del emisor no prueba aptitud ni consentimiento de red | host fija clave/política y selecciona perfil; atestación sigue siendo dato no confiable |
| HIGH | adapter vivo en retrieval acoplaría disponibilidad/estado externo | no determinismo, fuga y pérdida de modo offline | snapshot firmado/exportado y digest ligado al manifest; sin consulta viva |

## Verificación de canonicidad y determinismo

La propuesta preserva el CAS como autoridad y exige binding de revisión,
project, records, extractor, modelo, dimensión, normalización, algoritmo y
bytes/manifest. Aún no hay schema exacto ni implementación para verificar; el
spike debe producir las preimágenes concretas antes de aceptación.

## Límites declarados

- No se modificó código, schema, versión, capabilities ni memoria local.
- No se eligió `sqlite-vec`, modelo, proveedor, dimensión o algoritmo final.
- Se creó únicamente el issue documental
  `https://github.com/kristhianmanue1/escrubery/issues/1`; no se modificó su
  código, ramas, tags o PRs.
- No se creó PR, commit, tag ni release.
- No se descargaron dependencias o pesos ni se transmitieron datos.
- No existe todavía corpus semántico externo ni evidencia cross-platform.
- No se implementó ni autorizó adapter de Escrubery; F8-E no bloquea el perfil
  genérico de embeddings.

## Decisión

- [ ] proceed
- [ ] fix-and-retry
- [x] escalate

`ESCALATE` no bloquea conservar la formalización documental. Bloquea aceptar
ADR-0029 o iniciar código hasta completar F8.0/F8.1 y obtener una ronda fresca
independiente con evidencia. El siguiente gate permitido es la validación de
Argos y el spike read-only; no la implementación. Para Escrubery, sólo E0–E4
pueden preparar evidencia y contratos; E5 requiere autorización explícita antes
de producir un adapter candidato.
