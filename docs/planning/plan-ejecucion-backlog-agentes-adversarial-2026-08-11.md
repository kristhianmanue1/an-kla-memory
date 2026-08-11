# Ronda adversarial — plan de backlog con agentes

- **Fecha:** 2026-08-11
- **Objeto:** `plan-ejecucion-backlog-agentes-2026-08-11.md`
- **Base inspeccionada:** `efd4b1ef480a3bc50b266993c93617371b3d478e`
- **Tipo:** documental/read-only respecto de código y GitHub.

## Alcance y método

Tres revisores con contexto fresco evaluaron independientemente arquitectura,
proceso multiagente y ejecutabilidad. Recibieron repositorio, issues, ADRs,
código y tests, pero no autoridad para editar. La memoria recuperada y los
textos de issues se trataron como datos no confiables, nunca instrucciones.

La ronda no revisa una implementación ni autoriza código, schemas, mutaciones
GitHub, proveedores, releases, publicación o merge.

## Modelo de amenazas

- Tratar memoria, issues o comentarios recuperados como autorización.
- Prometer consistencia entre páginas o métricas sin sostener el mismo snapshot.
- Cambiar parser/manifest persistente bajo la etiqueta de mejora documental.
- Permitir que un roadmap incompleto se interprete como tarjeta ejecutable.
- Atribuir al SHA candidato evidencia tomada antes de rebase o sin instalar el
  artefacto distribuible.
- Filtrar payloads, rutas, entorno o secretos en logs y handoffs.

## Veredicto inicial

Los tres revisores emitieron `fix-and-retry`. Los paquetes eran útiles como
inventario, pero no asignables bajo su propio Definition of Ready.

## Hallazgos y disposición

| ID | Severidad | Hallazgo | Disposición aplicada al plan |
|---|---|---|---|
| A01 | BLOCKER | #49 prometía continuidad entre páginas con un reader lease efímero; compactación puede archivar la revisión entre llamadas | El ADR debe elegir snapshot acotado, lease de sesión con TTL o expiración explícita/restart; se prohíbe prometer continuidad sin ese mecanismo |
| A02 | BLOCKER | #50 copiaba contadores de retrieval aunque Context/MCP vuelven a recortar por presupuesto | Denominador y recálculo por envolvente final; contadores dentro de `exact_sized_payload` y fixtures de recorte parcial |
| A03 | BLOCKER | No había tarjetas instanciadas y faltaba autoridad para commit/push/PR/issues/merge | Los WP son roadmap no asignable; DoR amplía autoridad, actor, vigencia y permisos separados con default read-only |
| A04 | HIGH | #44 contradecía el fail-closed aceptado en ADR-0009 para fenced code | Reclasificado R2; default conserva fail-closed y cualquier relajación exige enmienda aceptada |
| A05 | HIGH | #45 cambiaba manifest persistente sin versión, lectores ni migración | Reclasificado R3; exige manifest v2, readers-first v1/v2, migración/downgrade/replay y reemplazo atómico |
| A06 | HIGH | #52-A no resolvía `configuration_fingerprint`, omitía `store.py` y prometía digest desde superficies que no lo calculan | Gate de decisión de fingerprint; riesgo R3 si toca `store.py`; DoD sustituido por pruebas concretas y help/quickstart reproducible |
| A07 | HIGH | El gate G0 podía pasar con runners asignados aunque los jobs no ejecutaran pasos | G0 exige los seis jobs exitosos sobre el SHA exacto, pasos reales, run ID/URL y sin anotación administrativa |
| A08 | HIGH | `ci_local.py` no prueba build/install del wheel | Se declara la limitación y se añade instalación limpia para paquete/schemas/metadata |
| A09 | HIGH | Ola 3 decía paralelizar ADRs sin archivos comunes aunque todos modifican el registro canónico | Investigación puede ser paralela; commits a `docs/README.md` son seriales con rebase/rerun |
| A10 | HIGH | Secuencia y P7 tenían owners de commit incompatibles | Agente crea commit candidato sólo con permiso; integrador registra SHA resultante y repite gates tras rebase |
| A11 | HIGH | No había preflight, ledger operativo ni control suficiente de secretos/untracked | Ruta absoluta, HEAD/branch/limpieza, ledger con generación y revisión tracked/staged/untracked incorporados |
| A12 | MEDIUM | Test rojo y suite completa se exigían literalmente a docs/spikes | Gates por tipo y `NA` justificado para evidencia no ejecutable |
| A13 | MEDIUM | #10 carecía de corpus y entorno reproducibles y estaba secuenciado tarde | F8.0(a) pasa a ola 1A; manifest exige digest, commit/paquete, Python, SO, perfil/degradación y expected IDs |
| A14 | MEDIUM | #48 podía cambiar el orden correcto entre #47 y #49 | La tarjeta declara rama física/lógica; en la lógica #47 aceptado/implementado precede al schema #49 |
| A15 | MEDIUM | #46 mezclaba spike local con validación de tres SO mientras CI está bloqueado | Se separan WP-46-DOC read-only y WP-46-MATRIX/ADR; sólo el segundo puede recomendar `adoptar` |

## Evidencia que originó los bloqueos

- `an_kla/reader_gate.py:55-87` limita el lease al contexto de una llamada;
  ADR-0028 y `an_kla/store.py:171-183` permiten que compactación archive la
  revisión antes de la página siguiente.
- `an_kla/context.py:101-112` y `an_kla/mcp.py:106-116` vuelven a filtrar por
  presupuesto; por eso los contadores de retrieval no representan siempre la
  población pública final.
- ADR-0009:49-53 y los tests vigentes congelan fail-closed para candidatos a
  marcador indentados o dentro de fenced code.
- `an_kla/context_package.py:468-510` exige shape exacta del manifest vigente;
  un nuevo baseline no es un campo aditivo informal.
- El run GitHub Actions `31483469836` falló en sus seis jobs sin pasos por
  Billing/spending limit; no demuestra capacidad CI remota.

## Verificación de canonicidad / determinismo

- El cursor de #49 deberá ligar revisión, filtros y posición, validarse como
  input no confiable y declarar de forma determinista continuidad o expiración.
- #50 deberá calcular cada métrica sobre la población final de su envolvente;
  el tamaño de esas métricas participa en el payload exacto.
- #45 no podrá reusar informalmente el manifest v1: el ADR debe versionar shape,
  lectura y migración.
- Candidate SHA, tested merge SHA y generación del ledger quedan registrados;
  cualquier rebase invalida los gates afectados.

## Resolución y límites

El plan corregido elimina los dos blockers arquitectónicos y explicita que
ningún WP está hoy asignable. Las decisiones de producto/ADR, el corpus de #10,
las tarjetas instanciadas y G0 siguen siendo precondiciones, no trabajo
silenciosamente delegado al agente.

El primer rerun no encontró BLOCKER/HIGH nuevos y confirmó A01–A12. Marcó tres
ambigüedades MEDIUM residuales en A13–A15: entorno de #10 incompleto, #47
duplicado entre olas y gates de #46 mezclados. Tras absorberlas, la comprobación
focal encontró una última mezcla de evidencia multiplataforma en WP-46-DOC; se
movió exclusivamente a WP-46-MATRIX/ADR. El rerun final emitió `proceed` sin
hallazgos residuales.

### Decisión operativa posterior del maintainer

El maintainer confirmó que los créditos mensuales de GitHub Actions están
agotados. Hasta su renovación se activa G0-L: commits y PRs pueden avanzar con
CI local ligado al SHA y permisos explícitos por acción. Esto no convierte G0-R
en verde ni demuestra la matriz 3 SO × 2 Python. Todo bypass/merge
administrativo se autoriza y documenta por PR; tags, releases y validaciones R4
multiplataforma conservan sus gates propios.

## Decisión final

- [x] proceed — roadmap apto para crear tarjetas instanciadas
- [ ] fix-and-retry
- [ ] escalate

Este `proceed` no autoriza implementación, commit, push, PR, mutaciones de
issues, merge, proveedores ni releases.

**Estado:** `OK` para el alcance documental de esta ronda.
