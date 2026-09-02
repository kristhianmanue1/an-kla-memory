# ADR-0045: Adoptar Skevi como estándar de proceso del proyecto

- **Estado:** Aceptada
- **Implementación:** Implementada (rama `feat/adopcion-skevi`; vigente al
  mergear a `main`)
- **Fecha:** 2026-09-01
- **Decide sobre:** adopción formal del cuerpo normativo Skevi como estándar
  de proceso de an-kla-memory, incluido el reemplazo del gate de tamaños
  propio por el gate de Skevi sin modificación.

## Contexto

Una auditoría de cumplimiento (2026-09-01) comparó este repo contra el
estándar de `kristhianmanue1/skevi` @ `ee309bb` (alpha, Apache-2.0, misma
autoría que este proyecto). Resultado: alineación fuerte en principios
(evidencia, autoridad explícita, fail-closed, datos no confiables,
reversibilidad) y en arquitectura; dos brechas medibles:

1. §3.4 — el gate de tamaños propio (`scripts/check_sizes.py` previo) usa
   polaridad abierta: una allowlist de globs (`REGLAS`) que deja sin medir
   `README.md`, `AN-KLA.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `tests/**`.
   Skevi exige polaridad cerrada: todo archivo de texto se mide salvo
   exención explícita.
2. §4.1/§5.4 — commits directos a `main` recientes y `main` sin protección
   de rama.

Skevi ya anticipaba a este repo como adoptante: el propio
`check_sizes.py` de Skevi cita a `an-kla-memory` y su `docs/architecture/`
como ejemplo de estructura que declara `required` propio. Su guía 05
recomienda AN-KLA como memoria del agente. El maintainer ordenó la
adopción formal de manera explícita (2026-09-01).

## Decisión

Adoptar Skevi siguiendo su receta de adopción (README, «Cómo se usa»):

1. **Corpus copiado sin edición** desde `ee309bb`: estándar
   (`docs/estandar-diseno-software-github.md`), guía completa
   (`docs/ai-agent-guide/00`–`05`), plantillas (`templates/`,
   incl. `templates/skevi/`).
2. **Gate reemplazado**: `scripts/check_sizes.py` de Skevi reemplaza al
   gate propio (ADR-006 de Skevi: el script se copia sin modificación); se
   añade `scripts/check_plans.py`. La configuración del proyecto vive en
   `skevi-gate.json`:
   - `required` reemplaza el set de Skevi con los canónicos de este repo
     (estructura distinta: ADRs en `docs/architecture/`, contrato en
     `AN-KLA.md`, guía completa con `05`).
   - `limits` declarados por escrito (§3.4): `AGENTS.md` 120 (se conserva
     el límite de la casa); `README.md` 500; `0042-sealed-export-v1.md`
     700 mientras #95 siga abierto; techos para cinco tests grandes.
   - `skip_dirs`: `planning`, `releases`, `mejoras_ejemplo` (histórico, no
     evergreen — misma exención que declaraba el gate previo).
   - `root_markdown`: `AN-KLA.md`, `CHANGELOG.md`, `CODE_OF_CONDUCT.md`,
     `CONTRIBUTING.md`, `SECURITY.md` además de los tres por defecto.
   - `plans: docs/plans` — gate de planes activo; los planes nuevos de
     implementación viven en `docs/plans/` con estructura E1–E5.
   - `default_limit: 800` heredado y re-declarado.
3. **Registro de contexto** (§3.5): bloque `skevi:registry` en `AGENTS.md`
   más `.skevi/usage-guide.md` y `.skevi/architecture-overview.md`
   (puntero a ADRs, sin contenido nuevo).
4. **CI**: `test.yml` y `scripts/ci_local.py` ejecutan ambos gates.
5. **Flujo Git** (corrige la brecha §4.1): trabajo por rama corta + PR;
   `main` deja de recibir commits directos. La protección de rama queda
   como decisión separada del maintainer (configuración de GitHub, no de
   este repo).

Límites que se **relajan** por esta decisión, declarados aquí: ADRs
400 → 800 (por defecto), `scripts/*.py` 400 → 800, `docs/*.md` evergreen
600 → 800. El techo de 700 para ADR-0042 se conserva vía `limits` y #95
sigue abierto como deuda de partición: relajar el límite de categoría no
cierra la deuda puntual.

## Por qué no [alternativa]

- **Mantener el gate propio en paralelo**: dos implementaciones de la
  misma semántica (tamaños) son dos fuentes de verdad que divergen
  (prácticas §11.2). El gate previo se retira con esta ADR.
- **Adoptar el corpus sin el gate**: §3.4 lo excluye — un límite que no
  se comprueba con verificador no es un límite, y la adopción dejaría de
  ser formal.
- **Esperar a que Skevi sea estable**: el corpus es la referencia de
  proceso del mismo ecosistema; la copia queda pinneada a `ee309bb` y las
  actualizaciones se re-inspeccionan por diff (Skevi declara alpha en su
  README). El riesgo de drift normativo se acota con el pin.
- **Hooks pre-push locales en vez de CI**: ese arreglo responde a la
  cuenta de Skevi (sin minutos de Actions); este repo sí corre GitHub
  Actions (matriz 3 SO × 2 Python), así que el gate vive en CI.

## Consecuencias

- Positivas: polaridad cerrada real (todo texto medido salvo exención
  explícita); un solo gate; estructura y hogares canónicos verificados;
  gate de planes activo; compatibilidad de proceso con el ecosistema;
  `AGENTS.md`/`CLAUDE.md` como punteros verificados por el gate.
- Negativas: límites propios más estrictos relajados a 800 (ARQUITECTURA
  de ADRs y scripts pierden presión de tamaño; la disciplina queda en la
  revisión, no en el gate); `README.md` y cinco tests quedan con techos
  declarados y deuda de partición (issues de seguimiento); archivos
  nuevos de Skevi suman ~2.200 líneas de documentación normativa a
  mantener coherente.
- Neutras: `store.py` está en 818 líneas con el trabajo de #103/#104 en
  curso (por encima del default 800): al mergear, el gate lo marcará —
  la señal es deliberada; corresponde partir el archivo o declarar techo
  con issue en ese mismo PR. La rama se cortó desde `396f5fc` en
  worktree aislado para no interferir con esa sesión activa.
- El bloque gestionado de `AGENTS.md` no cambia; añadir contenido fuera
  del bloque producirá `target_drift.outside_managed_block: true` en el
  próximo `upgrade inspect` — absorción esperada y documentada.

## Test de regresión

- `python3 scripts/check_sizes.py` → `OK` en el worktree de adopción.
- `python3 scripts/check_plans.py` → `OK` (directorio sin planes aún).
- `python3 scripts/check_adr_registry.py` → `OK` con ADR-0045 registrada.
- `python3 -m unittest discover -s tests -p 'test_*.py'` → suite completa
  en verde (el gate reemplazado no tenía tests dedicados; los tests del
  producto no cambian).
- `python3 -m an_kla --project-root <canónico> context status` → sin
  diagnósticos.

## Referencias

- Skevi @ `ee309bb` — estándar §3.4, §3.5, §4.1; README «Cómo se usa»;
  ADR-006 (script sin edición) y ADR-014 (gate de planes) de Skevi.
- Auditoría de cumplimiento 2026-09-01 (esta sesión, con evidencia).
- `docs/history/` de Skevi: `drift-checkpoint-an-kla-2026-08-15.md`.
- #95 (partir ADR-0042), #103/#104 (trabajo en curso que infla
  `store.py`), issues de deuda de tamaños creados con esta adopción.

## Enmienda 1 (2026-09-02) — pin re-anclado a `v1.0.0`

Skevi publicó `v1.0.0`: promoción Alpha→Estable (PROP-005; criterio de
salida cumplido por el piloto infosalud, F0→F3 punta a punta con
evidencia, 2026-09-01). La inspección `diff ee309bb v1.0.0` muestra
**byte-idéntico** todo lo que esta ADR adopta (estándar, guía `00`–`05`,
plantillas, `check_sizes.py`, `check_plans.py`); los cambios de `v1.0.0`
son internos de Skevi — su propia adopción de AN-KLA Memory como memoria
del agente, su `skevi-gate.json`, README/manifiesto e historial.

Consecuencia: el pin vigente pasa a ser `v1.0.0` (`.skevi/usage-guide.md`
actualizado en el mismo commit). Las menciones a «alpha» en Contexto y
«Por qué no» quedan superadas por esta enmienda — el registro original no
se reescribe. El criterio de re-inspección por diff no cambia: una
actualización futura de Skevi se inspecciona y se adopta con enmienda o
ADR nueva, nunca en silencio.
