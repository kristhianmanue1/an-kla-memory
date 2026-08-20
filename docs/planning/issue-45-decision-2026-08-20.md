# Decisión — #45: referencias de proyecto en el contexto gestionado (2026-08-20)

Punto 5 del plan `plan-backlog-2026-08-20.md`. Documento de decisión
(v2, tras ronda adversarial `fix-and-retry`). **No implementa nada**; el
issue queda en `escalate`.

## El problema (verificado en este repo)

`AGENTS.md` de este checkout lleva contenido propio fuera del bloque
gestionado. Efectos medidos (2026-08-20, comandos reales):

- `context status` → `ok: true` + warning
  `context_target_changed_outside_managed_block` permanente;
- `upgrade inspect --target v0.1.0-beta.15` →
  `target_drift.outside_managed_block: true`,
  `will_be_absorbed_by_apply: true`: todo apply exige
  `--confirm-target-drift`.

Un proyecto que sólo quiera **referenciar** `CONTRIBUTING.md` o sus ADRs
hereda esa fricción, y los agentes que sólo leen `AGENTS.md` no
descubren esos documentos.

## Requisito mecánico común (lo que la v1 de este doc omitía)

Cualquier solución que simultáneamente (i) no advierta sobre el contenido
intencional del proyecto y (ii) siga advirtiendo sobre otra mutación del
archivo **exige hashing por regiones**: el digest único del archivo
completo no puede distinguirlas. La "doble huella" no es una opción más:
es el mecanismo subyacente de (a) y de cualquier variante seria de (c).
Discutir opciones es discutir **dónde vive la región project y quién la
gobierna**, no si se hashea por región.

## Análisis de opciones

### (c) Fingerprint sólo sobre la región gestionada — RECHAZADA

Deja el resto del archivo sin cobertura: instrucciones fuera-del-bloque
mutan en silencio en el punto de entrada que todo agente lee. ADR-0017
hace del digest completo la garantía de transparencia; ADR-0035
§"Por qué no hashear sólo el bloque gestionado" lo descarta por lo
mismo. La variante con doble huella completa (archivo + gestionada) sin
región project nombrada no resuelve nada nuevo: el texto del proyecto
sigue siendo "texto libre" sin identidad propia.

### (a) Segundo bloque "project" con huella propia — DIFERIDA (objeciones reales sin refutar)

ADR-0035 §"Por qué no un segundo bloque 'project'" lo rechaza hoy:
marcadores adicionales, reglas de nesting, ownership ambiguo y repetir
la clase de colisión de #44 (documentar marcadores dentro del archivo
que los define). Esta decisión **no refuta** esas objeciones; las
acepta como costo real. Además la semántica exige: hashing por regiones,
adopción por edición del bloque (ceremonia comparable a la que se quiere
eliminar, sólo que acotada al bloque), reglas de interacción con el
bloque gestionado y con `uninstall` (el bloque project debería
sobrevivir), y enmienda explícita de esa sección de ADR-0035. Matriz de
interacción resultante:

| Evento | (a) bloque project | (a) texto libre | (d) adopción completa |
|---|---|---|---|
| Editar referencias del proyecto | warning/adopción del bloque project | warning archivo + confirm | adopción completa nueva |
| Editar otro texto libre | warning archivo + confirm (si (a) mantiene el digest completo; si no, hueco de (c)) | warning archivo + confirm | adopción completa nueva |
| Upgrade de versión | bloque preservado; drift sólo si cambió | igual que hoy | igual que hoy |

(a) gana sólo en la fila 2 y sólo si el proyecto disciplina su texto
libre. El costo: parser nuevo (riesgo #44), schema v2, gobernanza de
versión del bloque.

### (b) Placeholder en el template — RECHAZADA

Rompe la comparabilidad del template entre proyectos
(`_KNOWN_CONTEXT_TEMPLATES`, `managed_content_sha256` como comparador,
`context_package.py:70-78,221-234`) y da al contenido del proyecto la
semántica de versión/upgrade del template global, que no le corresponde.

### (d) Adopción explícita de baseline (ADR-0035, ya Propuesta) — RECOMENDADA como paso 1

Una sola operación gobernada absorbe el estado intencional del archivo
(referencias incluidas) como baseline. Para referencias estables —el
caso de #45— la ceremonia es **una vez**; no reaparece por upgrade si el
texto no cambió. No añade parser ni marcadores: no hereda el riesgo de
#44. Su límite es la fila 2: cualquier edición posterior de texto libre
re-arma el warning (con `--confirm-target-drift` como remedio de un
flag). ADR-0035 ya pasó su propia ronda adversarial y espera
implementación: recomendarla no crea documento nuevo.

## Recomendación

1. **Paso 1 (autorizable ya): implementar ADR-0035** (adopción explícita
   de baseline). Resuelve el dolor medido de este checkout con una
   ceremonia única.
2. **Paso 2 (diferido con criterio explícito):** re-evaluar (a) sólo si
   el uso real muestra fricción recurrente de re-adopción en este u otro
   proyecto (criterio del segundo adoptante, como ADR-009 de Skevi).
   Requeriría ADR nuevo que enmiende la sección de ADR-0035 y resuelva
   nesting/ownership/#44/uninstall antes de código.

## Riesgos y actores nombrados

- Migración: adoptar baseline cambia `manifest.target_sha256`; operación
  gobernada, auditada por `upgrade inspect`. Conlleva el versionado de
  upgrade-plan que ADR-0035 §4-5 exige (rename
  `manifest_target_sha256_at_install` → `..._at_baseline`, planes v2
  fallan CAS post-adopción).
- `uninstall` del contexto gestionado no toca texto libre ni baseline.
- Conflicto bloque gestionado ↔ contenido del proyecto: la jerarquía la
  decide el host (AN-KLA no redefine jerarquía del agente); ADR-0035
  deja la autoridad interpretativa al host, este doc no la presume.
- Hosts que no son este repo: (d) es agnóstica del contenido.

## Frontera de confianza

El contenido fuera del bloque gestionado es texto del proyecto (mismo
plano que `AGENTS.md`), nunca contenido recuperado de memoria: dato vs
instrucción se decide por procedencia, y esta decisión no fabrica
autoridad. Nada aquí autoriza implementación sin orden del maintainer.
