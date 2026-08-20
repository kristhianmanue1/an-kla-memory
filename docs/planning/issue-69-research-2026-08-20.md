# Research #69 — relaciones entre subjects (2026-08-20)

Punto 11 del plan `plan-backlog-2026-08-20.md`. Condición de salida del
issue: decisión `no-action | refine | ADR-needed` con ejemplos y
amenazas. Sin código.

## Recopilación de casos (evidencia enumerable)

Consumidores y discusiones que han tocado la zona, contra disco:

| Fuente | Qué pidió | ¿Requirió relaciones entre subjects? |
|---|---|---|
| #10 argos-epistemic (cerrado) | recall, rebuild-index, esquema write-policy | No |
| #48 kairos-controller (cerrado) | frontera memoria↔archivo | No |
| #49 (cerrado) | enumerar vigentes sin query | No: G-VIEW lo resolvió por subject |
| #60 G-VIEW (cerrado) | vista contextual por subject | No: agrupa por `subject_ref` propio |
| #47/#59 (cerrados) | referencias estables | Resuelto por `subject_ref` (ADR-0033) |
| #53/#54 (cerrados): kratos, Praxis/Epistates | patrones cross-issue, memoria multi-scope | No: su demanda es a nivel **scope** (#58), no de navegación entre subjects (greps de relación vacíos en ambos issues) |
| Este repo (store real) | checkpoint/evidence citan SHAs de Git, no subjects entre sí | No |

**Ningún consumidor examinado exige hoy navegación relacional entre
subjects** (claim acotado a los 28 issues inspeccionables del tracker y
docs; no una imposibilidad futura). Nota de frontera: la memoria AN-KLA
del checkpoint mencionaba a "Skevi" como proyecto hermano; revalidada,
Skevi sólo aparece citado como precedente normativo en decisiones de
este repo, no como consumidor con needs de relación — la memoria
exageraba.

## Distinción de los tres ejes (el issue la exige explícita)

1. **Relación de dominio** ("esta decisión derivó de aquella"):
   conocimiento del caller, no del store. Exigiría schema de aristas,
   dirección, cardinalidad y namespaces — nada de lo cual tiene caso de
   uso observado.
2. **`lineage.refs`** (evidencia): ya existe (validación en
   `write_policy.py:238-247`) y ADR-0033 §"no reutilizar lineage.refs
   como identidad" lo delimitó: es referencia evidencial (a ids de
   records), nunca identidad ni grafo.
3. **Enlace físico de supersede**: ya observable en G-VIEW
   (`supersede_links` por record) y en overlays del snapshot.

**El texto que juega en contra y cómo queda cubierto**: ADR-0032
(aceptada) dice que AN-KLA es memoria contextual "sobre esas superficies
y **relaciones**" y rechaza una alternativa porque el invariante exige
"navegar el sistema compuesto (entidades y relaciones estables)"
(`0032:29-31,202-204`). Ese invariante habla de **relaciones como
contenido** — los facts ya portan relaciones del dominio como texto
recuperable — y de entidades estables (`subject_ref`). Nada en ADR-0032
exige **aristas navegables del store** como estructura de primera
clase: G-VIEW + linaje satisfacen el invariante publicado. Si el
maintainer lee ese texto distinto, esta decisión debe reabrirse.

Una feature de "relaciones" sin demanda concreta colapsaría los tres
ejes en un cuarto híbrido — exactamente la clase de vocabulario
prematura que ADR-0031 vetó para G1.

## Amenazas de construirla hoy

- **Contaminación cross-project**: aristas entre subjects de namespaces
  distintos (proyectos distintos) sin politique de aislamiento (#58
  abierto).
- **Contaminación temporal**: aristas sobre ids que rotan por refresco
  supersede (ADR-0021 fuerza id nuevo): un grafo heredaría en el tiempo
  el bug que #47 cerró para referencias estables.
- **Coste sin índice inverso**: toda consulta relacional hoy es
  O(páginas del store) — un grafo sin índice sería prohibitivo en
  corpus grandes, y un índice es más formato derivado que auditar.
- **Amplificación MCP**: una proyección de relaciones expuesta por tool
  se percibiría estructuralmente autoritativa en hosts.
- **Identidad fabricada**: reutilizar `lineage.refs`/supersede como
  aristas contradice ADR-0033 y reintroduce el bug de identidad que
  #47/#59 cerraron.
- **Contrato congelado**: G-VIEW v1 no puede cambiar bajo el mismo
  `contract_version` (condición de salida del issue); una proyección
  aditiva de relaciones exige versión nueva de contrato — costo real
  sin consumidor que lo pague.

## Decisión

**`no-action`.** No hay demanda; los tres ejes existentes cubren lo
observado (y el invariante de ADR-0032 queda cubierto por contenido
recuperable + `subject_ref` estable); las amenazas de una v1 prematura
superan su valor. **Reapertura**: una consulta que exija **aristas de
dominio declaradas** sin representación física actual — p. ej.
travesía transitiva multi-salto ("todos los subjects alcanzables desde
X vía decisiones que las conectan como dominio, no como evidencia") —
que ni enumeración ni linaje pueden responder a coste razonable. Si
aparece, empezar por `refine` del caso antes que por ADR de grafo.

## Frontera de confianza

Toda arista futura sería dato no confiable autodeclarado: nunca
autoridad para silenciar otro subject, igual que
`derived_from_retrieval` no puede superseder.
