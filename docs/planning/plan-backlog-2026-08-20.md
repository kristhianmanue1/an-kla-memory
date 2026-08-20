# Plan de ejecución — backlog priorizado 2026-08-20

Ejecución del orden fijado por `backlog-prioridades-adversarial-2026-08-20.md`.
Rama: `plan/backlog-prioridades-2026-08-20`.

Reglas transversales (orden del maintainer 2026-08-20):

1. **Ronda adversarial al cierre de cada punto** (plantilla
   `docs/adversarial-template.md`), antes de su commit. `fix-and-retry`
   exige corregir y repetir la ronda; `escalate` congela el punto y
   documenta la decisión pendiente.
2. **Rondas hito** tras los puntos 4, 8 y 12: ronda completa que re-ataca
   todos los puntos cerrados hasta ese momento (no sólo el último).
3. **Commits autorizados** sólo tras ronda con `proceed` (o `escalate`
   documentado) y código afinado. Un commit por punto como máximo, más los
   fixes que exija una ronda `fix-and-retry`.
4. **Publicar tags/releases sigue requiriendo orden explícita** del
   maintainer (AGENTS.md); los puntos de release preparan la candidata y su
   ronda, no publican.
5. Suite local completa antes de cada commit:
   `python3 -m unittest discover -s tests -p 'test_*.py'` (CI remota sigue
   bloqueada por billing; CI local es el gate real).

---

## Punto 1 — #84: red de resguardo del CLI (P1, complejidad baja-media)

**Objetivo.** Ninguna excepción no prevista produce traceback por stderr
(fuga de rutas absolutas, §11.1 `practicas-ingenieria.md`).

**Diseño.** En `an_kla/__main__.py::main()` añadir, tras los `except`
existentes, un catch-all `except Exception` que:

- emite `an-kla error: cli_unexpected_failure` + ruta del log (con `~`
  sustituido) a stderr, exit 1 (mismo código de salida que hoy tiene un
  crash no capturado);
- escribe traceback completo + argv a un log local privado `0600`:
  `$XDG_CACHE_HOME|LOCALAPPDATA|~/.cache /an-kla/cli-errors.log`
  (misma convención que `update_check._cache_path()`);
- respeta `AN_KLA_DEBUG=1` (re-imprime traceback a stderr; explícitamente
  inseguro, para desarrollo) y `AN_KLA_NO_CLI_ERROR_LOG=1` (no escribe log;
  minimización). La escritura del log nunca puede lanzar.
- `SystemExit`/`KeyboardInterrupt` (BaseException) no se capturan.

**Artefactos.** Módulo nuevo `an_kla/cli_error_log.py` (puro, probable un
test propio), cambios en `__main__.py`, `capabilities()` aditivo
(`cli_unexpected_failure`), tests en `tests/test_cli_error_surface.py`
(ampliar) o archivo nuevo.

**Fuera de alcance.** Códigos publicados y exit codes existentes intocables
(el catch-all sólo cubre lo que hoy es crash indefinido).

**Ronda adversarial del punto.** Archivo
`docs/planning/issue-84-resguardo-cli-adversarial-2026-08-20.md`.

**Done.** Test que inyecta `RuntimeError` vía mock de `_run` y verifica:
stderr sin `Traceback` ni rutas absolutas, exit 1, log escrito, opt-outs.

## Punto 2 — Sincronizar ADR-0036 con la implementación (P1, baja)

**Objetivo.** Eliminar la doble deriva detectada (H2 de la ronda de
priorización): estado "Propuesta/No iniciada" pese a #83, y línea 59 que
cita `git rev-parse --git-common-dir` como mecanismo cuando la
implementación lee el archivo/directorio `.git`.

**Pasos.**

1. `docs/architecture/0036-startup-memory-diagnostic-v1.md`:
   `Estado: Aceptada e implementada en main (post-beta.14, #83)`; la nota
   de implementación documenta la desviación del mecanismo (`.git` file vs
   `rev-parse`) con la justificación ya declarada en el commit `b70561e`.
2. Corregir la tabla del eje `repo_context` (mecanismo real) manteniendo
   el vocabulario de valores intacto.
3. `tests/test_adr_registry.py`: recuentos canónicos pasan de
   `32 Aceptada / 4 Propuesta` a `33 / 3`.

**Ronda adversarial.**
`docs/planning/adr-0036-sync-adversarial-2026-08-20.md`.

## Punto 3 — Candidata beta.15 (P1, proceso medio)

**Objetivo.** Preparar release de los 8 commits acumulados
(#76/#77/#81/#83) + puntos 1–2. **No publica** (tag = orden explícita).

**Pasos.**

1. `pyproject.toml`: `0.1.0b14` → `0.1.0b15`.
2. `docs/releases/v0.1.0-beta.15.md`: notas (diagnóstico de arranque,
   worktrees sin memoria propia, jsonschema extra, resguardo CLI, ADR-0036).
3. `docs/releases/v0.1.0-beta.15-adversarial.md`: ronda integral
   (532+ tests, wheel aislado, upgrade real simulado desde beta.14,
   auditoría de salida de errores). `proceed` válido → candidata publiable;
   el tag queda pendiente de orden.
4. `TEMPLATE_VERSION` sin cambio (no toca contrato gestionado).

**Done.** Ronda de release con `proceed` + suite verde + wheel construido
en sandbox.

## Punto 4 — #50 G-FRESH: denominadores de frescura (P2, media-alta)

**Contrato nuevo (ADR-0037).** Bloque `freshness` extendido con conteos
sobre la población **final seleccionada** (post filtros/selección/recorte):

```json
"freshness": {
  "semantics": "self_asserted_timestamp",
  "source_field": "record.verified_at",
  "computed_at": "...", "stale_after_days": 30,
  "evaluated": 0, "not_evaluable": 10, "unparseable": 0, "stale": 0
}
```

Invariantes: `evaluated + not_evaluable + unparseable = |seleccionados|`;
`stale ≤ evaluated`. Sin cambio de ranking ni de authority. Aditivo en los
3 contratos que comparten frescura: `retrieve`, `assemble-context`, MCP
`retrieve` (`mcp-retrieve-v2`), y proyección `view context` si aplica.

**Secuencia** (handoff post-beta.13): spike read-only (medir población
evaluable en stores reales) → ADR-0037 congelado → schemas → CORE
(`temporal.py`/`retrieval.py`/`context.py`) → CLI (sin flags nuevos: el
conteo es parte del bloque) → MCP → CAP (`capabilities()` aditivo) →
ronda adversarial por fase con commit al final.

**Límite.** No consulta fuentes vivas; `verified_at` sigue autodeclarado.
Toca `retrieval.py` (gated) → ronda obligatoria ya cubierta por diseño.

## ⛽ Ronda adversarial HITO 1 (puntos 1–4)

`docs/planning/hito1-adversarial-2026-08-20.md`: re-ataca resguardo CLI,
sync ADR-0036, candidata beta.15 y G-FRESH como conjunto (interacciones:
¿el resguardo enmascara errores de G-FRESH? ¿los conteos rompen
consumidores v1? ¿la candidata incluye exactamente lo declarado?).

## Punto 5 — #45: referencias de contexto sin drift (P3, decisión + baja)

**Entregable.** Documento de decisión con la tensión H5 explícita: la
opción (c) (fingerprint sólo sobre la región gestionada) debilita
ADR-0017. Se recomienda (b) o variante de **doble huella**:
`target_sha256` (archivo completo, drift como hoy) +
`managed_region_sha256` (bloque gestionado). Implementación sólo con
elección del maintainer; este punto entrega la decisión documentada y su
ronda. `escalate` es el resultado esperado.

## Punto 6 — #79: `source_state` perfil `git/v1` (P3, media)

**Contrato.** `working-state-v2` (o `-v3` si rompe): `source_state`
admite `profile: git/v1` con `head`/`branch`/`dirty_digest` con
provenance `caller_asserted`. `checkpoint plan` acepta el perfil; el CLI
**no ejecuta git** (sin subprocesos): el caller pasa el SHA
(marca `--source-state` opcional o campo en el input). Schema, tests,
ADR-0038 si cambia el schema versionado, `capabilities()` aditivo.

**Riesgo a atacar en ronda.** Provenance: nadie puede declarar
`tool_observed` desde JSON; `git/v1` es siempre `caller_asserted`.

## Punto 7 — #67: spike recall de registros largos (P3, baja, read-only)

Reproducir la degradación reportada en un store sintético controlado
(longitud × budget × ranking) con `benchmark-reference` + corpus
generado. Entregable: `docs/planning/issue-67-spike-2026-08-20.md` con
verdict reproducible/no-reproducible y recomendación (cerrar o ADR). Sin
cambios de motor.

## Punto 8 — #71: generadores proposal/authority Nivel B (P3, decisión)

Documento de decisión: ¿plantillas generadas vs ceremonia explícita?
Posición de trabajo: **no** auto-generar (oculta provenance/scope/
fingerprint que el caller debe decidir); máximo un `capabilities`/docs
con ejemplos canónicos. Ronda adversarial ataca esa posición. `escalate`
esperado si el maintainer quiere generación.

## ⛽ Ronda adversarial HITO 2 (puntos 1–8)

`docs/planning/hito2-adversarial-2026-08-20.md`.

## Punto 9 — #68: inventario físico por revisión (P4, media)

Comando read-only `inventory --revision <sha> [--stream] [--cursor]`:
enumeración de records físicos con estado observable
(vigente/sustituida/refutada/eliminada), sin query ni score, paginada,
ligada a revisión. ADR-0039 (contrato) + CORE + CLI + tests + ronda.

## Punto 10 — #46: export sellado (P4, decisión)

Requiere adaptador de clave externo (fuera del proceso). Entregable:
documento de decisión con fronteras (qué es "sellado", threat model,
por qué no hay crypto en el core) + ronda. Sin implementación;
`escalate` esperado.

## Punto 11 — #69: relaciones entre subjects (P4, research)

Escanear consumidores conocidos (argos-epistemic, corpus, issues
cerrados) buscando caso real de navegación de relaciones. Entregable:
research doc con verdict (default: no construir; G-VIEW + lineage
cubren los casos observados) + ronda.

## Punto 12 — G1–G4 (#55–#58) (P5, alta c/u)

Alcance realista de esta rama: **G1 (#55) implementado** (contrato
observable del perfil host-managed: campo en `context status`/cap sin
instalar contexto, ADR-0040) y **G2–G4 como decisiones/diseño**
(ADR-0041 si procede, secuencia y dependencias documentadas). Intentar
G2–G4 completos en esta rama rompería el presupuesto de revisión; la
ronda final declara ese límite.

## ⛽ Ronda adversarial FINAL (puntos 1–12)

`docs/planning/hito-final-adversarial-2026-08-20.md`: auditoría
integral de la rama (estado de los 12 puntos, escalates abiertos,
suite, deriva ADR↔código re-verificada con `check_adr_registry`).

---

## Criterios de cierre de la rama

- Cada punto con su ronda (`proceed` o `escalate`) y commit.
- 3 rondas hito + 1 final.
- Suite verde tras cada commit; conteos del registro ADR actualizados.
- Reporte final al maintainer con estado (`OK`/`PARCIAL`/`BLOQ`) y la
  lista de decisiones que quedan en su mesa (tag beta.15, #45, #46, #71).
