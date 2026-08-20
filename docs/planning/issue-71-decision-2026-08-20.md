# Decisión — #71: generadores de proposal/authority Nivel B (2026-08-20)

Punto 8 del plan `plan-backlog-2026-08-20.md`. Decisión documental; sin
código. Condición de salida del issue: `no-action | ADR-needed`.

## Condición de entrada (verificada contra disco)

El issue exige "medir primero #70 con al menos un flujo de consumidor
nuevo". #70 se cerró en beta.14 con ayuda ampliada de `plan-write`/
`commit-write-plan` y recorrido documentado de extremo a extremo
(`docs/releases/v0.1.0-beta.14.md`), pero **no existe medición posterior
de un flujo de consumidor nuevo** que use ese Nivel A: la evidencia de
beta.14 es de gates y auditoría propia, no de adopción externa (issues
cerrados post-beta.14: #76/#84, uso propio, no primer write de
consumidor). beta.15 (candidata sin tag en esta rama) no cambia la
superficie de escritura. La condición de entrada está, por tanto,
**incumplida en su cláusula de medición**, y eso ya bastaría para
no-action; el análisis siguiente evalúa el fondo de todos modos.

## Análisis de las cuatro opciones contra los seis criterios del issue

| Criterio | 1. plantillas documentales | 2. comandos generadores | 3. API Python | 4. no-action |
|---|---|---|---|---|
| `proposal_sha256` calculado y ligado | lo calcula el caller (igual que hoy) | el comando lo calcularía sobre un borrador aún sin decidir: acuñar hash antes de la decisión | ídem, más superficie importable | igual que hoy: lo calcula `plan-write` sobre objetos exactos |
| `configuration_fingerprint` | el caller lo define (correcto: es SU configuración) | riesgo de default silencioso: el comando rellenaría algo que significa "configuración del issuer verificada" | ídem | lo define el caller, como exige write-policy/v1 |
| impedir autoridad privilegiada desde JSON | intacto (documentos inertes) | un generador de authority produciría plantillas que parecen autoridad: fricción reducida al precio de banalizar el artefacto | igual, y `tool_observed` quedaría a un `patch` de distancia | intacto: `_cli_authority` sigue fallando cerrado |
| placeholders que fallen cerrado | los de un documento no ejecutan nada; quien copia y olvida, falla en validación | placeholders en artefactos ejecutables exigen un mecanismo nuevo de rechazo | ídem | n/a |
| compatibilidad `plan-write → commit-write-plan` | total (son los mismos objetos) | nueva superficie previa al flujo: más estados intermedios que revalidar | más modos de invocación que auditar | total |
| JSON canónico, errores estables, cero mutación | sí (documentos) | sí, pero con errores NUEVOS de generación que mantener | sí, con superficie API pública que congelar | sí (estado actual: 575 pruebas) |

El patrón es consistente, con una precisión: los argumentos duros de
las columnas 2-3 (acuñar `proposal_sha256` antes de decidir; producir
artefactos que "parecen autoridad") acusan al **authority-generator** y
a la API pública — `proposal_sha256`/`authority_class`/
`configuration_fingerprint` son campos de `write-authority-v1`, no del
proposal. Un `proposal-scaffold` puro que nunca toque authority sería
inofensivo y queda cubierto por la misma cláusula que la opción 1: la
reapertura condicionada. **Las columnas 2 y 3, donde están los
generadores de authority, reducen ceremonia automatizando exactamente
las decisiones (provenance, scope, fingerprint) que el flujo gobernado
existe para forzar.** La ceremonia no es costo accidental: es la
superficie donde el caller declara procedencia y asume scope. La
columna 1 (plantillas documentales) es inofensiva pero también
innecesaria: `plan-write --help` ya nombra los schemas exactos (los
campos, en `docs/write-policy-cli.md`, que ya trae el recorrido completo
— Nivel A, beta.14).

## Decisión

**`no-action`**, por dos razones independientes:

1. **Condición de entrada incumplida**: sin medición de Nivel A con un
   consumidor nuevo, decidir Nivel B ahora es optimizar ceremonia cuya
   fricción real no ha sido medida post-beta.14.
2. **Fondo**: generación ≠ ergonomía aquí. Los generadores (opciones
   2-3) convertirían decisiones de autoridad en defaults; la opción 1
   duplica lo que beta.14 ya publicó.

**Reapertura condicionada** (instrumento definido): un issue con los
`reason_codes`/errores exactos que el consumidor novo vio y el tramo del
recorrido de `docs/write-policy-cli.md` donde se atascó — eso distingue
"construcción de objetos" (candidato a ADR, empezando por opción 1 /
proposal-scaffold) de "desconocimiento del flujo" (mejorar docs). Sin
esa evidencia, no reabrir. El ADR, si algún día existe, empieza por la
opción 1; nunca por un comando que genere `authority`.

## Frontera de confianza

Nada aquí autoriza implementación ni reintroduce un comando `write`. La
regla de fondo: ningún artefacto generado puede acuñar autoridad;
`tool_observed`/`channel_confirmed` siguen requiriendo adaptador. El
precedente es `refute plan`: su `--authority-claim` es una aserción a
verificar (`skip` sin resolver privilegiado; `refute_policy.py:94-132`),
nunca authority atestiguada — cualquier generador futuro tendría que
satisfacer exactamente esa distinción claim/authority.
