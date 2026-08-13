# Prácticas de ingeniería de AN-KLA Memory

Prácticas establecidas para trabajo no trivial (especialmente lo que toca
`store.py`, `retrieval.py`, `index.py`, `write_policy.py` o el contrato
gestionado). Son **obligatorias antes de publicar** cualquier beta que toque
esas superficies; para cambios menores son referencia. Se actualizan con el
mismo proceso que describen (ADR + ronda adversarial al cerrar la edición).

El acceso rápido: `AGENTS.md` puntea aquí; `docs/adversarial-template.md` da la
plantilla de la ronda; `docs/agent-report-template.md` la del reporte.

## Índice por cuándo aplicar

| Práctica | Cuándo | Referencia |
|---|---|---|
| Ronda adversarial pre-code | antes de implementar/publicar cambios sensibles | §1 + `docs/adversarial-template.md` |
| Spike pre-implementación | antes de codear cambios de storage/concurrencia/formato poco conocidos | §2 |
| ADR antes que el código | cambios de arquitectura, política, contrato o formato | §3 + `docs/architecture/` |
| Secuenciación por fases | release que toca política + storage + contrato | §4 |
| CI local con `--simulate-ci` | antes de pushear; tests dependientes de entorno CI | §5 |
| Reporte RAG con evidencia | cierre de toda tarea no trivial | §6 + `docs/agent-report-template.md` |
| Gate de tamaños | siempre (CI + local) | §7 + `scripts/check_sizes.py` |
| Verificación de invariantes con evidencia | ronda adversarial y auditoría de release | §8 |
| Auditoría de release con evidencia | antes de comunicar/publicar | §9 |
| Señales en el punto de decisión | al diseñar errores, diagnósticos o resultados | §11.1 |
| Evolución aditiva/versionada | al cambiar contratos observables estables | §11.2 |

---

## §1 Ronda adversarial pre-code

Un revisor con **contexto fresco** (subagente, idealmente otro proveedor/modelo
para decorrelación real) ataca la implementación o el ADR candidata buscando
casos edge, invariantes rotos y regresiones silenciosas. **No rubber-stamp**: si
no halla nada, que lo diga explícito; si halla, prescribe la corrección.

- **Cuándo es obligatoria**: antes de publicar cualquier beta que toque
  `store.py`, `retrieval.py`, `index.py`, `write_policy.py` o el contrato
  gestionado. Recomendable también para ADRs de diseño antes de implementar.
- **Cómo**: lanzar subagente `explore` con (a) el diff o ADR, (b) los invariantes
  a verificar, (c) los casos edge a cubrir; exigir decisión
  `proceed | fix-and-retry | escalate` con evidencia comando→resultado.
- **Salida**: `docs/releases/<tag>-adversarial.md` (plantilla en
  `docs/adversarial-template.md`). Sin `proceed` no se publica el tag.
- **Ejemplos (beta.8)**: ADR-0019 v1 → `fix-and-retry` (2 BLOCKER); ADR-0020 v1 →
  `fix-and-retry` (1 BLOCKER de consistencia transaccional); PR-A → `fix-and-retry`
  (1 MEDIUM de regresión); PR-B → `proceed`. Todos absorbidos antes de publicar.

## §2 Spike pre-implementación

Investigación adversarial **sólo lectura** que verifica las suposiciones del
diseño contra el código real (`archivo:línea` + comandos) y devuelve un plan
validado, **antes de escribir una línea** de la implementación.

- **Cuándo**: cambios que tocan formato persistente, concurrencia o una
  superficie crítica mal conocida.
- **Cómo**: subagente `explore` con las preguntas concretas (¿dónde vive X?,
  ¿quién toma el lock?, ¿hay backwards-compat?) y exigencia de un plan con
  `archivo:línea` + top-3 riesgos + veredicto `proceed | refine | escalate`.
- **Ejemplo (beta.8)**: el spike de PR-B (supersede storage) detectó que
  `build_index` no filtra vigencia (regresión silenciosa de retrieval) y que el
  `supersedes_map` debe ser **acumulativo** (sino cadenas A→B→C reviven A). Dos
  HIGH evitados antes de codear.

## §3 ADR antes que el código

Los cambios arquitectónicos, de política, de contrato o de formato se discuten y
mergean como **ADR en `docs/architecture/` (PR docs/ separado) ANTES** de
implementar. La implementación lo referencia.

- Estructura: Contexto, Decisión, Por qué no [alternativa], Consecuencias, Test
  de regresión, Referencias (plantilla `docs/architecture/_TEMPLATE.md`).
- Cada ADR se abre con su propio PR docs/, se discute, se mergea; luego llega el
  PR de implementación que lo cierra.
- **Ejemplo**: ADR-0019 (supersede) y ADR-0020 (context_diagnostics) mergeados
  antes que sus respectivos PRs de código.

## §4 Secuenciación de releases por fases

Un release que toca política + storage + contrato a la vez se **parte en fases
coherentes** (p. ej. A política, B storage, C release/contrato). El tag **sólo se
crea cuando todas las fases están en `main`**, y se declara explícitamente que
`main` es **no etiquetable** entre fases.

- Cada fase = su PR + su ronda adversarial.
- El tag apunta al commit de la fase que cierra el release, no al HEAD.
- **Ejemplo**: beta.8 = PR-A (#34 política) + PR-B (#35 storage) + PR-C (#36
  release); `main` se declaró "no etiquetable" hasta C; el tag `v0.1.0-beta.8`
  apunta a `0362a63` (merge de C), no al HEAD posterior.

## §5 CI local con `--simulate-ci`

`scripts/ci_local.py` replica `.github/workflows/test.yml` sin gastar minutos de
GitHub Actions. La bandera `--simulate-ci` exporta `GITHUB_ACTIONS=true` y
`CI=true` antes de los tests para atrapar **no determinismos** que sólo aparecen
en el runner.

- Correr antes de pushear y siempre que un test dependa del entorno.
- No reemplaza el CI remoto (que valida 3 SO × 2 Python reales).
- **Ejemplo**: reveló y ayudó a fixar `test_skip_when_opt_out_env_set` (PR #25),
  que pasaba local pero fallaba en CI por `GITHUB_ACTIONS` inyectado.

## §6 Reporte RAG con evidencia

Cualquier tarea no trivial se cierra con estado `OK | PARCIAL | BLOQ` y
**evidencia** (comando ejecutado → resultado real), nunca afirmación.
`PARCIAL` lleva etiqueta `(espera-admin)` o `(incompleto)`. Plantilla en
`docs/agent-report-template.md`.

## §7 Gate de tamaños

`scripts/check_sizes.py` (CI + local) mantiene archivos aptos para contexto y
responsabilidad única. Límites por categoría; la deuda conocida se declara
explícita en `TECH_DEBT` con un issue de seguimiento (no se congela anónimamente).

## §8 Verificación de invariantes con evidencia

En cada ronda adversarial y en auditorías de release se listan los invariantes
(pureza de `evaluate_write`, `policy_fingerprint`, backwards-compat de lectura,
concurrencia/CAS, inmutabilidad CAS, no filtración) y se verifica **cada uno**
con `comando → resultado`, marcando ✓/✗. Sin evidencia no hay afirmación.

## §9 Auditoría de release con evidencia

Antes de comunicar/publicar, verificar con evidencia: instalador en venv limpio
(`pip install` → `--version` → `init` → `context plan install` → `context
install` → `status ok`), schemas embebidos en el wheel, migración desde la
versión anterior (plantilla reconocida en `_KNOWN_CONTEXT_TEMPLATES`),
README/contrato/coherencia tag↔VERSION, changelog (`docs/releases/`) y community
files (LICENSE, SECURITY, COC, CONTRIBUTING, CITATION, dependabot, templates).

## §10 Registro y vigencia de ADRs

La tabla de `docs/README.md` es el registro canónico del inventario y estado
decisional. Estado e implementación son ejes distintos: aceptar una decisión no
afirma que todas sus fases prospectivas estén implementadas. Cada cambio de
estado actualiza el ADR y el registro en el mismo commit.

`scripts/check_adr_registry.py` falla ante huecos, duplicados, rutas ausentes,
metadata no canónica o contradicciones de estado. Se ejecuta en CI local y
remoto. La evidencia de publicación se enlaza desde el registro a la nota de
release correspondiente; los documentos de `planning/` siguen siendo historia,
no una segunda fuente de estado.

## §11 Principios para contratos observables

### §11.1 Señalar en el punto de decisión

Un estado contractualmente relevante que el motor ya conoce, que puede cambiar
una decisión observable y que está autorizado para ese caller debe aparecer, de
forma estructurada y saneada, en el resultado o error de esa misma operación.
No se difiere a una recuperación posterior ni se obliga al agente a inferirlo
leyendo código fuente. La señal se emite después de las validaciones y controles
de autoridad aplicables, en la frontera más temprana que dispone de evidencia y
permiso suficientes; no autoriza acción, no eleva datos autodeclarados, no
fabrica verdad externa ni crea un oráculo de existencia o autorización.

Esto no exige duplicar todo diagnóstico en todas las superficies. El ADR de la
feature decide el punto exacto, el schema y la compatibilidad; tests cubren que
el código/reason/detail sea estable y no filtre payloads, rutas ni secretos.

### §11.2 Evolucionar de forma aditiva o versionada

Primero se identifica la unidad versionada: schema, payload, perfil, comando o
API. Sólo se añade dentro de la misma versión si el contrato vigente declara ese
punto extensible y los tests demuestran compatibilidad. Payloads dorados,
serialización canónica y schemas cerrados requieren una nueva versión o perfil.

Una superficie paralela debe derivar de una sola semántica y fuente canónica,
además de declarar precedencia, migración y, cuando corresponda, deprecación. Si
una reinterpretación o ruptura es inevitable, requiere ADR, versión nueva y
tests que demuestren el comportamiento legado y el nuevo; “aditivo” no justifica
ambigüedad, dos implementaciones divergentes ni dos fuentes de verdad.

## Cómo se mejora este documento

Como cualquier artefacto: cambios vía plan + ronda adversarial al cerrar la
edición como hito. El historial vive en git.
