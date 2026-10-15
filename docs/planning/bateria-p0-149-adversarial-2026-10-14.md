# Ronda adversarial de cierre — batería P0 de escala (issue #149, 2026-10-14)

Artefacto atacado: `benchmarks/scale/` completo (core, tres módulos de
escenarios, CLI, umbrales) + corrida oficial `results/20261014-182904` +
INFORME.md, sobre `claude/bateria-p0-escala-149@6646669`. No toca
`store.py`/`retrieval.py`/`index.py`/`write_policy.py`: ronda disciplinaria
de cierre, no obligatoria (prácticas §1), ejecutada por el propio agente
con probes conductuales.

Intérprete: `.venv/bin/python` → Python 3.12.12 (regla del maintainer,
2026-10-13).

## Alcance

1. Validez de los resultados oficiales: umbrales commiteados antes de
   correr; abortos como resultados, no fallos.
2. Frontera de seguridad: la batería no muta stores reales; todo vive en
   workspaces efímeros.
3. Reproducibilidad y honestidad de las cifras frente a las sondas del
   issue #149.
4. Robustez de la instrumentación tras tres corridas.

## Modelo de amenazas

La batería es infraestructura de medición: su riesgo propio es **afirmar
más de lo que midió** (medida de un régimen equivocado presentada como
otra, cifras no reproducibles, resultados inventados tras una corrida
muerta). La memoria del store canónico no se toca; ningún comando lee la
bóveda del proyecto.

## Hallazgos y correcciones

| Hallazgo | Riesgo | Corrección |
|---|---|---|
| H1 — la primera corrida medía `context_view` sólo en el régimen 200-sujetos y sin registrar el código de resultado; la cifra 0,28 s a 20k contradecía aparentemente la sonda origen (3,2 s) | medida de régimen equivocado leída como regresión/mejora del producto | probe de discriminación (1 vs 200 sujetos): el caso origen cae en `view_subject_exceeds_budget` tras derivar el sujeto gigante — dos regímenes legítimos del eje sujetos; la batería mide ambos y registra el outcome |
| H2 — supersede elegía targets ya sustituidos (`plan_supersede_target_not_vigente`) | celda muerta a mitad; resultados de la celda perdidos | pool de ids vigentes + captura por celda |
| H3 — `compact commit` sin `--bundle` fallaba cerrado; y el archivo de plan re-serializado llevaba una clave `ok` inyectada por el helper CLI (`compaction_planning_result_invalid`) | ceremonia incompleta leída como incapacidad del producto | `--bundle` añadido; la clave inyectada se excluye al re-alimentar al CLI; verificado con ceremonia completa (export→plan→commit→verify ok, revisión 401) |
| H4 — el padre de la segunda corrida murió sin traza (sin traceback ni `finally`) y los resultados vivían sólo en memoria | pérdida total de una corrida de ~1 h | persistencia inmediata por escenario (`f6d2eac`); fusión de re-corridas parciales sin fragmentar la oficial; causa de la muerte no atribuible con la evidencia disponible — declarado, no especulado |
| H5 — `p50=None` de un escritor sin commits rompía los totals | smoke roto por agregado | lista de p50 existentes |

## Verificación de canonicidad / determinismo

- Umbrales pre-corrida: commit `54efb65` anterior a todo resultado; copia
  `thresholds-used.json` dentro de la corrida oficial.
- Stores de la batería: todos bajo `tempfile.mkdtemp` (workspaces efímeros
  eliminados en corrida oficial exitosa); `git status` sin cambios de store
  real en ningún punto.
- Cifras contrastadas contra el issue: snapshot 20k 0,126 s vs 0,080 s de
  la sonda (misma forma, revs mayores); commit gobernado a ~450 revs
  consistente con la proyección cuadrática; índice sin aceleración
  confirmado; compactación con snapshot 5,2× más rápido post-epoch.
- Suite y gates: ver línea final de evidencia.

## Límites declarados

- La columna gobernada no alcanza 20k registros (aborta ~400–480 revs):
  es el resultado falsable esperado, no un defecto de la batería.
- Compactación a 400 revs (desviación aprobada T3); 20k queda post-P1.
- Crash es probabilístico (SIGKILL con retardos sembrados): 10 muestras,
  no inyección determinista.
- La muerte dura del padre de la corrida 2 quedó sin causa atribuible; se
  mitigó el efecto (persistencia por escenario), no la causa.
- `store_bytes` de la diagnóstica es pre-índice (diferencia de método con
  la sonda origen, declarada en el INFORME).

## Decisión

- [x] proceed
- [ ] fix-and-retry
- [ ] escalate

Correcciones H1–H5 aplicadas antes de la corrida oficial válida; gates y
suite verificados tras el artefacto final (línea de evidencia del INFORME
y del reporte de sesión).
