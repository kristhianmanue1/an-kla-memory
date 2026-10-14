# Ronda adversarial — revisión crítica de escalado y gobernanza (2026-10-14)

Artefacto atacado: `revision-critica-escalado-gobernanza-2026-10-14.md` (v1,
sin versionar) + párrafo post-beta.30 de `README.md`. Ronda de refinamiento
pre-decisión, no pre-release: no toca `store.py`, `retrieval.py`, `index.py`
ni `write_policy.py`; aplica la plantilla de ronda como disciplina.

## Alcance

1. Integridad referencial: las 27 citas `file:line` del informe contra el
   código en `main@5b073ec`.
2. Probe conductual del hallazgo central (`channel_confirmed` a nivel motor):
   demostración end-to-end vía API Python, no sólo lectura de código.
3. Reproducibilidad de cifras: spot-check de un punto por eje.
4. Consistencia interna del documento y fidelidad del README.

Intérprete: `.venv/bin/python` → Python 3.12.12 (regla del maintainer,
2026-10-13: nunca `python3` a secas ni el 3.9 del sistema).

## Modelo de amenazas

La frontera memoria-no-es-instrucción no cambia: el informe es datos y
propuesta, no autorización. El riesgo propio de esta ronda era el inverso —
que el documento *afirme* más de lo que verificó (hallazgo no demostrado,
referencia rota, cifra irreproducible) y que el README heredara ese exceso.

## Hallazgos y correcciones

| Hallazgo | Riesgo | Corrección |
|---|---|---|
| H1 — errata "Issues en.Scope:" en la cabecera | ruido, credibilidad | "Issues en alcance" |
| H2 — "los 8 invariantes listados en la sección 7 del informe fuente": referencia interna inexistente (los invariantes ya estaban listados inline) | lector persigue una sección que no existe; traza rota | frase corregida a "Conservar los invariantes de continuidad:" |
| H3 — el hallazgo central se apoyaba sólo en lectura de código | afirmación fuerte sin demostración conductual | probe end-to-end ejecutado: `channel_confirmed` autodeclarado vía `store.commit_write_plan` → `committed=True` con registro `payload` completo; `tool_observed` sin receipt → skip `unresolved_authority` (y con evidencia fabricada → `invalid_write_authority`); `model_derived`+`full` → skip por techo. Evidencia empírica incorporada a §4.1 |
| H4 — cifras sin spot-check de reproducibilidad | número suelto, no falsable | spot-check: `context_view` 10k = 1,46 s vs 1,518 informado (±4 %), añadido a §2 |
| H5 — caveats metodológicos incompletos: sonda con subject único vs 200 sujetos del issue #149 | comparabilidad con la evidencia del issue | matiz declarado en §2 (el coste domina la proyección por registro previa a paginación por sujeto) |

Sin hallazgos que refuten afirmaciones del informe: las 27 referencias
resolvieron al contenido citado y el probe confirmó el hallazgo central.

## Verificación de canonicidad / determinismo

No aplica a hashes del producto (ronda documental). Los probes usaron stores
temporales borrados; ningún store real fue abierto; el árbol de trabajo sólo
contiene los dos artefactos de la sesión.

## Límites declarados

- El probe de `tool_observed` con evidencia fabricada se detuvo en la
  validación de forma (`invalid_write_authority`); no llegó a
  `enforce_for_commit` (receipt HMAC). El diseño en capas queda descrito por
  lectura de código, no demostrado capa a capa.
- La reproducibilidad se comprobó en la misma máquina e intérprete del
  informe original; no cubre variabilidad entre máquinas.
- Esta ronda no valida el plan §5 (propuesta pendiente de decisión del
  maintainer), sólo la calidad de su evidencia.

## Decisión

- [x] proceed
- [ ] fix-and-retry
- [ ] escalate

Correcciones H1–H5 aplicadas en la iteración de productor posterior al
congelado de la ronda; gates `check_sizes`/`check_plans` re-ejecutados en
verde tras corregir.
