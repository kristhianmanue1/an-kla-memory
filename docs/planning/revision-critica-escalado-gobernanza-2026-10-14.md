# Revisión crítica de escalado y gobernanza — post beta.30

- Fecha: 2026-10-14
- Commit inspeccionado: `main@5b073ec` (merge PR #150, `v0.1.0-beta.30`), árbol limpio
- Alcance: sólo lectura del repo; sonda de escala en store temporal
- Issues en alcance: #149 (escalado), #140 (autoridad humana del checkpoint), #58 (G4 identidad)
- Estado: propuesta pendiente de decisión del maintainer; este documento no
  autoriza cambios ni releases

## Resumen ejecutivo

1. La curva O(historia) del issue #149 se **revalidó contra beta.30** con una
   sonda propia: `context_view limit=50` crece hasta 3,22 s a 20.000 registros
   y el coste por commit es ~cuadrático con las revisiones (0,47 s a 400
   revisiones, proyección ~27 s a 3.000).
2. La capa de gobernanza es **mecanismo verificable** (CAS con flock,
   tamper-evidence de lectura, checkpoint-policy a nivel motor, refute cerrado
   sin resolver, compactación con prueba de restauración). Pero se halló un
   hueco: `channel_confirmed` en escrituras simples sólo se rechaza en la CLI;
   la API Python directa lo acepta (`write_commit.py` no re-verifica esa
   clase).
3. La ventaja frente a un JSON/JSONL bien diseñado sigue siendo **hipótesis**:
   no existe batería en el repo que mida continuidad/handoff (H-A) ni
   superioridad reproducible (H-B).

## 1. Verificaciones contra código (HEAD `5b073ec`)

| Afirmación | Veredicto | Evidencia |
|---|---|---|
| `snapshot()` revalida ascendencia completa en cada lectura | Confirmado | `revision_validation.py:195-270`; sin caché ni watermark en el repo |
| `_read_segment` re-hashea y re-canonicaliza cada segmento | Confirmado | `store.py:578-589` |
| Escritura gobernada paga 3–4 snapshots completos | Confirmado | guard `store.py:405`; base `transactions.py:503`; reindex `index.py:46`; supersede `supersede.py:26`; mapas acumulativos `transactions.py:539` |
| `retrieve` escanea todo antes de tocar el índice | Confirmado | `retrieval.py:189-207`; estrechado en `:224-248`; no existe modo índice-primero |
| `context_view` deriva todo antes de paginar | Confirmado | `_derive` `context_view.py:269` (llamada `:425`); paginación `:470-481` |
| Beta.27/28: `no_lexical_overlap` + vocabulario | Confirmado | `retrieval.py:57`; `startup.py:132-163` |
| Beta.29: checkpoint rechaza privilegio autodeclarado | Confirmado | `checkpoint_policy.py:324-329`, en plan y commit |
| Sin memoria multi-máquina | Confirmado | `capabilities.py:334` |

## 2. Revalidación empírica propia (sonda sobre HEAD)

Metodología: igual que el issue #149 (`commit()` interno para aislar el
motor), store temporal, `.venv` Python 3.12, mínimo de 3 corridas por medición.
Código de la sonda reproducida en el apéndice. Caveats: sondas sintéticas, no
batería oficial; los números absolutos dependen de máquina e intérprete; la
sonda usa un único `subject_ref` (el coste domina la proyección por registro
en `_derive`, previa a cualquier paginación por sujeto; el issue #149 midió
200 sujetos con la misma forma de curva). Spot-check de reproducibilidad
(2026-10-14, misma máquina): `context_view` a 10k = 1,46 s frente a 1,518
informado (±4 %).

Eje registros (lote de 1.000 por commit interno):

| N | snapshot s | retrieve scan s | retrieve índice s | context_view limit=50 s | store MB | índices MB |
|---:|---:|---:|---:|---:|---:|---:|
| 1.000 | 0,004 | 0,008 | 0,011 | 0,121 | 0,4 | 0,2 |
| 5.000 | 0,021 | 0,037 | 0,041 | 0,705 | 3,5 | 2,5 |
| 10.000 | 0,038 | 0,065 | 0,080 | 1,518 | 10,4 | 8,6 |
| 20.000 | 0,080 | 0,140 | 0,168 | 3,221 | 35,2 | 31,5 |

Eje revisiones (1 registro por commit interno):

| Revisión | snapshot s | commit medio s |
|---:|---:|---:|
| 50 | 0,010 | 0,015 |
| 100 | 0,028 | 0,042 |
| 200 | 0,088 | 0,136 |
| 400 | 0,304 | 0,472 |

Lecturas: (a) duplicar revisiones multiplica el coste ~3,5× (ajuste ~O(rev²));
(b) el perfil índice es **más lento** que el scan a 20k (0,168 vs 0,140 s), lo
que confirma que el FTS aporta diagnóstico (#118), no rendimiento; (c) los
índices son el 89 % del disco del store a 20k registros y no existe poda de
huérfanos (sólo conteo en `doctor`).

## 3. Mecanismo vs convención

Enforced: tamper-evidence de lectura (`store.py:555-589`); CAS bajo flock con
doble re-lectura (`write_commit.py:44-53`, `transactions.py:678-699`); techos
de autoridad deriv (`write_policy.py:525-537`, re-verificados bajo lock);
checkpoint-policy a nivel motor; refute cerrado sin resolver inyectado
(`refute_policy.py:99-103`; la CLI no inyecta ninguno); compactación con
restore-proof real (`compaction.py:47-98`); custodia fail-closed
(`custody.py:119-145`).

Límites honestos declarados en el propio código: la clave de attest vive en el
mismo host (`attest.py:9-13`); identidad sin firmas (tamper-evident, no
tamper-proof); `CURRENT` sin firma permite rollback a revisión válida antigua
(`store.py:1-4`); `MemoryStore.commit()` es primitiva interna sin política de
escritura (`store.py:358-364`); el store en reposo es texto claro (sealed es
sólo export).

## 4. Contraejemplos hallados

1. **`channel_confirmed` pasa a nivel motor** (verificado empíricamente en la
   ronda adversarial del 2026-10-14): la CLI lo rechaza
   (`__main__.py:181-184`), pero un caller Python directo de
   `commit_write_plan` con JSON autodeclarado `channel_confirmed` committea
   `write-full` — probe con store temporal: `committed=True`, registro
   persistido con `payload` completo, sin evidencia alguna en `authority`.
   Contraste: `tool_observed` resiste en dos capas (plan exige evidencia
   `resolution=verified`, commit re-verifica el receipt HMAC en
   `write_commit.py:112-116`) y `model_derived`+`full` es rechazado por techo
   (`summary_required_for_authority_ceiling`). La narrativa "beta.29 lo
   endureció" es cierta para checkpoint, no para escrituras simples vía API.
2. El índice FTS por defecto es contraproducente: más lento que scan y 89 % del
   disco, sin GC.
3. Escotilla `commit()` interna: sin política de escritura (no expuesta por
   CLI, pero disponible en API).

## 5. Plan propuesto para atacar los issues abiertos

Orden crítico-propositivo; nada material sin ronda adversarial (cambios a
`store.py`, `retrieval.py`, `index.py`, `write_policy.py` la exigen).

**Fase 0 — sin tocar el motor (esta iteración)**
- Nuevo issue: cierre del hueco `channel_confirmed` a nivel motor,
  siguiendo el patrón de checkpoint-policy (re-verificación bajo lock en
  `commit_write_plan`, error estable, tests de rechazo). Cambio pequeño,
  alta simbólica.
- Batería P0 del #149: matriz registros × revisiones × sujetos × ratio de
  supersedes ejecutada por la vía gobernada pública, umbrales escritos antes
  de correr, resultados versionados. Prerrequisito de todo lo demás.

**Fase 1 — #140 como diseño de una sola interfaz**
- El resolver de autoridad humana del host que define #140 es la misma
  interfaz que necesita `channel_confirmed` a nivel motor y que refute ya
  consume por inyección. Diseñar una vez (ADR), tres consumidores. Evita
  resolver #140 como caso aislado.

**Fase 2 — #149 P1+P2 (sin cambiar sustrato)**
- P1: watermark "verificado hasta la revisión R" (patrón ya existente en el
  índice FTS: caché derivada con `CURRENT` propio, nunca autoridad), con test
  que corrompe el checkpoint derivado y demuestra equivalencia o fallo
  cerrado.
- P2: retrieve índice-primero manteniendo paridad #118 como diagnóstico;
  context_view con paginación en origen; fusión periódica de segmentos; commit
  gobernado en lote (un plan, N records, una revisión) sin debilitar CAS ni
  política por record.

**Fase 3 — #58 (G4) antes de congelar sustrato**
- G4 cambia el binding de identidad que cualquier sustrato nuevo debe
  preservar. El threat model ya está (`g4-a0-threat-model-2026-10-13.md`);
  el diseño de #58 debe revisarse antes de decidir P3, no después.

**Fase 4 — #149 P3 (SQLite opcional) sólo si P1+P2 no alcanzan umbrales**
- Conservar los invariantes de continuidad: export byte-exacto, CAS,
  tamper-evidence, techos re-verificados bajo lock, un archivo = un store
  portable, auditoría de compactación, paridad de diagnóstico, fallo cerrado
  ante índice ausente.

**Qué NO hacer todavía**: backend SQLite antes de P0-P2; MongoDB/Postgres;
resolvers bundled; memoria multi-máquina; firmas de identidad (decisión de
producto); cualquier superficie que convierta el store en base canónica.

**Próximo experimento falsable (H-A)**: handoff ciego A→B sin acceso a la
conversación original, con propuesta no decidida, pendiente material, intento
fallido y un fact envenenado que dice "el agente tiene permiso de escribir".
Falsación: B eleva autoridad desde memoria, pierde un pendiente material o
necesita la conversación. Correr 2× (AN-KLA vs JSONL C1 con el mismo
contenido).

## 6. Archivos de esta sesión

- `docs/planning/revision-critica-escalado-gobernanza-2026-10-14.md` (este
  documento)
- `docs/planning/revision-critica-escalado-gobernanza-2026-10-14-adversarial.md`
  (acta de la ronda adversarial: hallazgos H1–H5 y correcciones aplicadas)
- `README.md`: párrafo de estado post-beta.30 y entrada en Documentación
- Sonda de escala: apéndice; la copia ejecutada vivió en el TMPDIR del
  operador y fue borrada con su store

## Apéndice — sonda reproducible

```python
"""Sonda de escala AN-KLA (issue #149). Store temporal; sólo lectura del repo."""
import sys, tempfile, time
from pathlib import Path
sys.path.insert(0, "/ruta/al/checkout/an-kla-memory")
from an_kla.store import MemoryStore
from an_kla.retrieval import retrieve, SCAN_PROFILE, INDEX_PROFILE
from an_kla.context_view import context_view
from an_kla.index import build_index
from an_kla.subject_ref import derive_namespace

TEXT = "registro {i} sobre quetzal y memoria de trabajo del agente"

def new_store(tmp):
    store = MemoryStore(tmp)
    cur = store.initialize()
    ident = (Path(tmp) / ".an-kla" / "project-identity.json").read_bytes()
    ref = f"an-kla:subject:v1:service:{derive_namespace(ident)}:svc"
    return store, cur, ref

def timed(fn, n=3):
    ts = []
    for _ in range(n):
        t0 = time.perf_counter(); fn(); ts.append(time.perf_counter() - t0)
    return min(ts)

# Eje registros: lotes de 1000 facts por commit interno.
with tempfile.TemporaryDirectory() as tmp:
    store, cur, ref = new_store(tmp)
    n = 0
    for target in (1000, 5000, 10000, 20000):
        while n < target:
            facts = [{"id": f"f-{n+i}", "subject_ref": ref,
                      "payload": {"text": TEXT.format(i=n+i)}}
                     for i in range(1000)]
            cur = store.commit(expected_current_hash=cur,
                               checkpoint_patch={}, facts=facts)
            n += 1000
        snap = timed(store.snapshot)
        scan = timed(lambda: retrieve(store, "quetzal", 4096, profile=SCAN_PROFILE))
        build_index(store)
        idx = timed(lambda: retrieve(store, "quetzal", 4096, profile=INDEX_PROFILE))
        cv = timed(lambda: context_view(store, revision=cur, limit=50))
        print(n, snap, scan, idx, cv)

# Eje revisiones: 1 fact por commit interno; medir snapshot y commit medio.
with tempfile.TemporaryDirectory() as tmp:
    store, cur, ref = new_store(tmp)
    window, n = [], 0
    for n in range(400):
        t0 = time.perf_counter()
        cur = store.commit(expected_current_hash=cur, checkpoint_patch={},
                           facts=[{"id": f"f-{n}", "subject_ref": ref,
                                   "payload": {"text": TEXT.format(i=n)}}])
        window.append(time.perf_counter() - t0)
        if (n + 1) % 50 == 0:
            print(n + 1, timed(store.snapshot), sum(window) / len(window))
            window = []
```

## Frontera de confianza

Este documento registra verificación de código y mediciones propias; no
instruye ejecutar comandos hallados en memoria y no concede autoridad. Los
números absolutos son de una máquina concreta (Apple Silicon, Python 3.12):
la forma de la curva es el hallazgo, no la cifra. Las decisiones del plan
requieren orden explícita del maintainer.
