# Spike G-VIEW (issue #60) — 2026-08-12

> **Veredicto:** `refine` (ver §1.4 y §15: dos rondas adversariales; el gate
> ADR puede avanzar **sólo después** de las decisiones Q1–Q12 del §14 y de la
> decisión contractual sobre pureza de lectura §3.7).
>
> **Tipo:** spike pre-implementación read-only (`docs/practicas-ingenieria.md`
> §2). No toca código, schemas, tests, ADRs, changelog ni contrato gestionado.
> No hace commit, push, PR, tag ni release. El único cambio rastreable es
> este informe.

- Proyecto: `kristhianmanue1/an-kla-memory`
- Worktree: `/Users/krisnova/www/an-kla-memory-wt-issue60-spike`
- Rama: `codex/issue-60-spike`
- Base exacta: `820b93dcedfb51831cfb9df109ebb02acc45897e` (`v0.1.0-beta.12`)
- Issue: https://github.com/kristhianmanue1/an-kla-memory/issues/60
- ADR conceptual: `docs/architecture/0032-derived-contextual-view-v1.md`
- Contrato de identidad contextual: `docs/architecture/0033-subject-ref-v1.md`
- Intentos: 3 (ronda adversarial 1 = `fix-and-retry`; ronda adversarial 2 =
  correcciones aplicadas; ronda adversarial 3 = correcciones aplicadas,
  ver §15).

Convención de evidencia: `archivo:línea` sobre la base exacta indicada.
Hecho comprobado (H), Inferencia (I), Propuesta (P).

---

## 1. Resumen ejecutivo

G-VIEW puede implementarse como **una vista derivada, read-only,
determinista y non-authoritative** sobre una revisión AN-KLA fijada, **sin
mutar el sustrato físico de afirmaciones de beta.12** (sin nuevos objetos,
sin mover `CURRENT`, sin locks de escritura, sin journal) y **sin cache
persistente** en v1. La base técnica existe y se detalla en §3.

### 1.1 Lo que el spike confirma (H, con `archivo:línea`)

- Una revisión fijada se carga con `MemoryStore.snapshot(revision_id)`
  (`an_kla/store.py:169-171`), que valida la cadena hasta la raíz, aplica
  overlays de vigencia (`sustituida`/`refutada`) (`an_kla/store.py:215-244`)
  y devuelve registros inmutable-verificados. El `revision_id` es
  content-addressed; los segmentos y manifest son bytes inmutables.
- `subject_ref` tiene contrato congelado (ADR-0033, implementado en
  beta.12) y se persiste verbatim en el segmento
  (`an_kla/write_policy.py:222-226`, `an_kla/subject_ref.py:21-26`).
- `canonical_json` (`an_kla/canonical.py:10-17`) es determinista y
  self-contained; `exact_sized_payload` (`an_kla/canonical.py:20-37`)
  prueba que el codebase ya sabe medir sobres auto-referenciales.

### 1.2 Lo que el spike corrige (vs. intento 1)

El intento 1 contenía cuatro defectos técnicos serios detectados por la
ronda adversarial del intento 2 (§15.2):

1. **Afirmación falsa "cero escrituras".** `snapshot()` entra en
   `shared_reader_gate`, que abre `.reader-gate` con `O_RDWR | O_CREAT` y
   ejecuta `fchmod` (`an_kla/reader_gate.py:38-49, 77-80`);
   `tests/test_reader_gate.py:43` confirma que la primera lectura **crea**
   el archivo `.an-kla/memory/.reader-gate`. La afirmación literal "cero
   escrituras" es falsa. §3.7 distingue tres capas (mutación del sustrato,
   efecto de coordinación, lock de escritura vs lock compartido) y propone
   el veredicto `refine`.
2. **Cursor y presupuesto no garantizaban progreso.** El cursor apuntaba a
   la "última alternativa emitida", así que una página sin elementos no
   podía avanzar; `budget=0` devolvía un sobre de tamaño positivo. §5 se
   reescribe: cursor apunta al **siguiente subject a considerar**;
   `budget ≥ 1` cubre el sobre completo; primer subject que no cabe →
   `view_subject_exceeds_budget` (fail-closed estable).
3. **Sin contenido de la afirmación.** El sobre sólo proyectaba metadata;
   el consumidor no podía observar las alternativas. §7 añade una
   proyección canónica `record_raw` + `record_text` (legacy-compatible)
   para cada alternativa e historia.
4. **Cadena supersede ≠ mismo subject.** `resolve_supersede_targets` sólo
   exige mismo stream/id vigente (`an_kla/supersede.py:25-59`); no compara
   `subject_ref`. §3.2/§6.1 corrigen: cada registro se agrupa por su
   **propio** `subject_ref` exacto; el link supersede es metadata, no
   agrupamiento.

Y tres MED:
5. Sobreafirmación "no puede llegar al store" para namespaces históricos
   (T1): un mismo pin puede contener registros con namespaces distintos
   tras reemplazo de anchor (ADR-0033 §12). La vista no mezcla.
6. `shared_reader_gate` excluye **sólo compactación** (mismo archivo
   `.reader-gate` con `LOCK_EX` en `exclusive_reader_gate`,
   `reader_gate.py:90-117`), **no** al writer ordinario (que usa
   `.write.lock` distinto, `store.py:569-625`). T7 y §8 corregidos.
7. El digest SHA-256 **no keyed** del cursor detecta corrupción accidental,
   no manipulación maliciosa (caller puede recalcularlo). T5 corregido: la
   protección real es semántica (la posición debe existir en la secuencia
   recomputada).

### 1.2.bis Correcciones de la ronda 3 (intento 3)

La ronda adversarial 3 (§15.3, contexto fresco, verificación independiente
de las 25 citas técnicas centrales) no reintrodujo los defectos del
intento 1/2 y añadió: **H1** — la garantía "bytes medidos ≤ presupuesto"
era afirmación, no teorema (el `budget_used_bytes` final puede tener más
dígitos que el valor tentativo del paso 3b); §5.3 se reescribió para medir
con cota superior `budget_bytes` y añadió la cadena demostrable. Cuatro
MED: **M1** L1/L2 es platform-dependiente (non-fcntl no crea `.reader-gate`);
**M2** conteo `subjects_without_subject_ref` congelado (todos, no sólo
vigentes); **M3** `inputs.streams` se normaliza al enum antes de digerir;
**M4** `view_subject_exceeds_budget` terminal sin diagnóstico → Q12. Cinco
LOW de claridad (forma simétrica de `supersede_link`, citas de export
excluyente, `bare_digest`, endurecimiento `O_NOFOLLOW`/`st_nlink`,
intra-stream). Todas aplicadas.

### 1.3 Riesgos centrales (top-3 en §13)

(a) Vista mayoritariamente vacía hasta que los consumidores escriban con
`subject_ref` (la revisión 28 probe no los tiene). (b) Fragmentación por
kind (ADR-0033 §4): un ADR como `doc` y como `decision` son dos subjects
sin navegación entre ellos en v1. (c) La frontera "conflicto de datos vs.
ambigüedad de regla" es fina; cualquier caso nuevo detectado al codear
debe volver al ADR, no al código.

### 1.4 Veredicto

**`refine`** al gate G-VIEW-DOC. El gate ADR puede abrirse **sólo después**
de: (i) la decisión contractual del maintainer sobre pureza de lectura (§3.7,
Q11, dependiente de la plataforma) — aceptar `.reader-gate` como fuera del invariante
"cero escrituras" o requerir un nuevo primitiva de lock read-only sin
`O_CREAT`; (ii) la decisión Q12 sobre diagnóstico de budget; y (iii) las
decisiones Q1–Q10 del §14. **No proceder** a implementación hasta que el
ADR congele los contratos de cursor/presupuesto (§5, garantía H1
demostrable), proyección de contenido (§7), agrupamiento cross-subject
(§6.1) y la frontera de pureza (§3.7).

---

## 2. Preflight (comando → resultado real)

Ejecutado desde el worktree aislado; `python3` = `python3` del sistema en
este host. Integración/memoria se verifica en la raíz principal
`/Users/krisnova/www/an-kla-memory`.

| Comando | Resultado |
|---|---|
| `git status --short` | limpio antes del primer intento; tras intento 2 sólo `?? docs/planning/issue-60-g-view-spike-2026-08-12.md` |
| `git rev-parse HEAD` | `820b93dcedfb51831cfb9df109ebb02acc45897e` |
| `git rev-parse origin/main` | `820b93dcedfb51831cfb9df109ebb02acc45897e` (HEAD == origin/main) |
| `gh issue list --state open` | 13 issues abiertos; #60 `[G-VIEW]` presente |
| `gh pr list --state open` | sin PRs abiertos |
| `python3 -m an_kla --no-update-check --project-root /Users/krisnova/www/an-kla-memory context status` | `ok=true`, `installed=true`, `template_version=0.1.0-beta.11`, `diagnostics=[]`, `warnings=[]` |
| `python3 -m an_kla --no-update-check --project-root /Users/krisnova/www/an-kla-memory verify` | `ok=true`, `revision=sha256:b5a39b27...16453e8`, `revision_number=28`, `identity_status=complete`, `counts={facts:23, events:21, episodes:10}` |
| `python3 -m unittest discover -s tests -p 'test_*.py'` (intentos 1 y 2) | 1ª corrida intento 1: `Ran 468 tests in 488.6s`, `FAILED (errors=3)` por `subprocess.TimeoutExpired` (30 s) en `test_bm25_rows_are_stable_across_hash_seeds` y hermanos. 2ª corrida intento 1: `Ran 468 tests in 103.6s`, `OK`. Intento 2 (post-correcciones al informe, sin tocar código): vuelve a pasar `OK` (el informe no importa tests). Flake de subprocess bajo carga, no fallo de código. |

La ausencia de `.an-kla` en el worktree aislado es intencional. No se
inicializó, copió ni enlazó memoria en el worktree.

---

## 3. Mapa actual con referencias `archivo:línea`

### 3.1 Carga de una revisión fijada

- `MemoryStore.snapshot(revision_id)` — `an_kla/store.py:169-171`. Punto de
  entrada público; adquiere `shared_reader_gate` antes de cualquier I/O.
- `_snapshot_under_gate` — `an_kla/store.py:173-245`. Resuelve `revision_id`
  explícito o cae a `read_current()`; nunca relee `CURRENT` después del pin
  inicial dentro de la misma llamada.
- Resolución de revisión inexistente / archivada: si `_read_json_object`
  falla, intenta `archived_revision_link_under_gate`
  (`an_kla/store.py:177-186`, `an_kla/compaction.py:721-737`) y lanza
  `IntegrityError("revision_archived_by_compaction")`. Si el objeto falta
  sin estar archivado: `IntegrityError("object_missing:revisions")`
  (`an_kla/store.py:655-660`).
- Validación de la cadena: `validate_revision_chain`
  (`an_kla/revision_validation.py:195-270`) recorre padres hasta la raíz,
  verifica hashes, transiciones, acumulatividad de `supersedes_map`
  (`an_kla/revision_validation.py:221-224`) y refutations_map aditivas.
- `verify_revision` (`an_kla/compaction.py:678-718`) expone disponibilidad
  `present | archived_by_compaction | unknown`. **No es un pre-check
  barato:** cuando la revisión está `present` llama internamente a
  `store._snapshot_under_gate(revision)` (`an_kla/compaction.py:705-712`),
  duplicando la validación completa. La vía principal para la vista es
  llamar `snapshot(revision_id)` y mapear cualquier `IntegrityError`
  (incluida `revision_archived_by_compaction` y `object_missing:revisions`)
  a `view_revision_not_available` (§6.2).

### 3.2 Vigencia, overlays y supersede cross-subject

- `supersedes_map` es **acumulativo** (heredado del padre) y se aplica como
  overlay `status="sustituida"` sin reescribir bytes
  (`an_kla/store.py:210-230`). `validate_lifecycle`
  (`an_kla/revision_validation.py:273-308`) rechaza cadenas circulares y
  superposiciones refute×supersede.
- `refutations_map` se aplica como overlay `status="refutada"` usando el
  digest JSON del registro crudo (`an_kla/store.py:231-244`).
- `raw_records` (pre-overlay) se conserva en el `Snapshot` para que la vista
  pueda distinguir "afirmación física" de "estado de vigencia".
- Filtrado actual por vigencia en `retrieve`: el código evalúa
  `record.get("status", record.get("nu", "vigente"))` y acepta
  `{"vigente", "active", None}` (`an_kla/retrieval.py:161`). **Ojo:** el
  predicado **literal** incluye el fallback legacy `nu`. **Decisión
  propuesta (P, D6):** la vista adopta el predicado **exacto** de
  `retrieve` (`status if present else nu if present else "vigente"`),
  incluido el fallback `nu`, para no divergir del sustrato en stores
  legacy.
- **Supersede no garantiza mismo `subject_ref` (H, hallazgo HIGH intento
  2).** `resolve_supersede_targets` (`an_kla/supersede.py:25-59`) sólo
  exige mismo `stream`, `target_id` y target vigente; **no compara
  `subject_ref`**. `validate_lifecycle` (`an_kla/revision_validation.py:
  273-308`) tampoco. **Decisión (D6/D17):** la vista agrupa cada registro
  por su **propio** `subject_ref` exacto. Si target y sucesor comparten
  `subject_ref`, el target aparece en `history` del sucesor. Si tienen
  subjects distintos (o uno no tiene), cada uno va a su grupo y la
  relación física se expone como **metadata de link** (`supersedes` /
  `superseded_by`) en el registro correspondiente, **no** como
  agrupamiento forzado. Sin subject_ref en ambos → `history` queda vacío
  y los registros se cuentan en `subjects_without_subject_ref`.

### 3.3 Identidad contextual (`subject_ref`)

- Gramática normativa única: `SUBJECT_REF_PATTERN`
  (`an_kla/subject_ref.py:21-25`), duplicada byte-idénticamente en
  `write-proposal-v1.schema.json` en `docs/schemas/` y `an_kla/schemas/`
  (`tests/test_subject_ref.py:135-154` valida la igualdad).
- `parse_subject_ref` (`an_kla/subject_ref.py:43-54`) produce
  `{kind, namespace, id}` en una sola pasada `fullmatch`. Sin I/O, sin
  escritura; **apto para uso en una vista read-only.**
- Namespace = digest de `project-identity-v1`
  (`an_kla/subject_ref.py:57-65`); la validación de binding vive sólo en
  `commit_write_plan` (`an_kla/store.py:377`, `an_kla/subject_binding.py`)
  y **no** se invoca desde lecturas.
- Enum cerrado de 11 kinds con precedencia semántica no ejecutable
  (ADR-0033 §Decisión 4).
- **Namespaces históricos múltiples en un mismo pin (H, MED intento 2).**
  ADR-0033 §Decisión 12 establece que si el anchor de identidad se
  reemplaza, los registros históricos **retienen sus bytes y su namespace
  anterior**. Por tanto una revisión válida puede contener registros con
  namespaces distintos. La vista **no sobreafirma** "no puede llegar al
  store": los agrupa por `subject_ref` exacto (namespace incluido en el
  string), no mezcla, y expone un `warnings` entry
  `multiple_namespaces_observed` cuando se detecta más de un namespace en
  el universo escaneado (datos, no error).

### 3.4 Recuperación determinsta y presupuestos

- `canonical_json` (`an_kla/canonical.py:10-17`): `sort_keys=True`,
  `separators=(",",":")`, `ensure_ascii=False`, `allow_nan=False`.
- `digest_bytes` / `digest_json` (`an_kla/canonical.py:40-45`).
- `exact_sized_payload` (`an_kla/canonical.py:20-37`) itera hasta
  convergencia; **prueba que el codebase sabe medir sobres
  auto-referenciales.** G-VIEW reutiliza el patrón.
- `record_text` (`an_kla/record_text.py:15-32`) define el orden de campos
  para extraer texto indexable: `indexable_text > text > render > summary >
  p`, con fallback al string `payload`. **G-VIEW lo reutiliza para la
  proyección `record_text` (§7), garantizando paridad con `retrieve` y con
  el motor FTS5.**
- `retrieve` ordena por `(-score, identifier)` (`an_kla/retrieval.py:178`):
  **no** define un orden total puro por bytes; G-VIEW define el suyo (§5).
- Códigos estables de error en `_safe_error` (`an_kla/mcp.py:24-49`):
  enum cerrado, fail-closed a `internal_error`.
- Exit codes CLI: `0` éxito, `2` uso, `3` outcome-no-committed /
  namespace-unavailable / disponibles (análogo a `subject namespace` exit 3
  en `__main__.py:533-538`), `1` fatal vía handler general.
- `capabilities()` determinista y dorada por `tests/test_agent_contracts.py`.

### 3.5 Frontera de confianza

- Toda superficie MCP proyecta `untrusted_memory_data=true` y
  `host_framing_unmeasured=true` (`an_kla/mcp.py:97-104`). `verified_at`
  conforme a ADR-0021 como `self_asserted_timestamp`
  (`an_kla/temporal.py:11-13`).
- `AGENTS.md`, `AN-KLA.md:133-145` y ADR-0032 §Modelo de amenazas exigen
  `canonicality=non-authoritative` (ADR-0031) y que la vista no prometa
  frescura que el sustrato no puede demostrar.

### 3.6 Estado del sustrato real (probe)

En la raíz principal con `python3 -m an_kla ... verify`:
- Revisión 28, schema `an-kla/revision-v1` (legacy; sin `subject_ref`
  todavía en ningún registro).
- `supersedes_map` longitud 1; `refutations_map` longitud 0. 1 registro
  marcado `sustituida`.
- Registros usan campos abiertos: `id`, `payload`, opcionalmente
  `verified_at`, `schema`, `status`, `provenance` (legacy), `type`,
  `topic`. **No se observó `lineage` en la muestra** — soporte legado
  abierto, debe tolerarse en v1.

**Inferencia (I):** hasta que los consumidores escriban con `subject_ref`,
la vista será mayoritariamente vacía en este store. Esperado.

### 3.7 Pureza de lectura — el hallazgo BLOCKER del intento 2

El intento 1 afirmó "cero escrituras, revisiones nuevas o locks de
escritura" basándose en que la vista no invoca `commit*` ni `_replace_current`.
Eso es **verdadero para el sustrato de afirmaciones**, pero **falso
literalmente** porque la cadena de llamadas de `snapshot()` entra en
`shared_reader_gate` (`an_kla/store.py:170`), y `_open_gate` abre
`.an-kla/memory/.reader-gate` con `os.O_RDWR | os.O_CREAT` y ejecuta
`os.fchmod(descriptor, 0o600)` (`an_kla/reader_gate.py:38-49`). El test
`tests/test_reader_gate.py:38-43` prueba que la primera llamada a
`snapshot()` **crea** el archivo `.reader-gate` en disco.

Tres capas que el informe distingue con precisión:

1. **Mutación del sustrato de afirmaciones / revisión (H: cero).** La vista
   no crea objetos bajo `revisions/`, `checkpoints/`, `segments/`,
   `transactions/`, `refutations/`, ni mueve `CURRENT`, ni escribe journal,
   ni adquiere `.write.lock`. Confirmado en `an_kla/store.py:169-245`
   (`snapshot` sólo llama `_read_*`) y en `an_kla/reader_gate.py:55-88`
   (el gate no toca `CURRENT` ni objects).
2. **Efecto observable de coordinación en `.reader-gate` (H: sí, posible).**
   Si `.reader-gate` no existe, la primera lectura lo crea; `fchmod` lo
   normaliza a `0o600` aunque ya existiera. Esto es un efecto secundario
   **fuera del sustrato**, en un archivo de coordinación usado para
   excluir compactación concurrente. No afecta a `CURRENT`, a objetos ni a
   la inmutabilidad de la revisión pinneada; pero **es una escritura
   observable en el filesystem** bajo `.an-kla/memory/`. **Defensa en
   profundidad sobre el artifact (`reader_gate.py:39-47`):** `_open_gate`
   exige `O_NOFOLLOW` (alza `reader_gate_platform_unsafe` si el flag no
   existe) y rechaza symlinks y hardlinks (`stat.S_ISREG` +
   `st_nlink != 1`) antes de `fchmod`; el test
   `tests/test_reader_gate.py:38` (`test_snapshot_creates_permanent_gate_ignored_by_export`)
   confirma además que `.reader-gate` **se excluye de los export bundles**,
   reforzando su naturaleza de coordination artifact fuera del sustrato.
3. **Locks.** `shared_reader_gate` adquiere `fcntl.flock(LOCK_SH)` sobre
   `.reader-gate` (`reader_gate.py:78`). `exclusive_reader_gate` (usado por
   compactación) adquiere `LOCK_EX` sobre el **mismo** archivo
   (`reader_gate.py:106`): compactación espera al reader. El writer
   ordinario adquiere `fcntl.flock(LOCK_EX)` sobre **`.write.lock`**
   (`store.py:569-625`), archivo **distinto**: **el writer NO espera al
   reader**, y viceversa. Esto es intencional (la snapshot es
   content-addressed y consistente consigo misma sin necesidad de
   coordinar con writers), pero refuta la afirmación del intento 1 de que
   "la vista excluye writers".

**No se propone** llamar `_snapshot_under_gate` sin `shared_reader_gate`:
eliminaría la protección contra compactación concurrente y rompería el
contrato de `compaction/v1`. La pregunta es contractual, no de implementación.

**Decisión para el gate ADR (Q11):** el invariante #4 del issue #60 dice
"cero escrituras, revisiones nuevas o locks de escritura". Tres lecturas:

- **L1 (estricta):** "cero escrituras" incluye cualquier byte tocado bajo
  `.an-kla/`. Bajo L1, `shared_reader_gate` no cumple; se requiere una
  **nueva primitiva** de lock read-only que abra `.reader-gate` con
  `O_RDWR` pero **sólo si ya existe**, fallando cerrado con
  `reader_gate_unavailable` si no existe (análogo a cómo `subject namespace`
  falla con `namespace_unavailable` sin crear `.an-kla/`). Esta primitiva
  es un cambio de contrato que requiere su propio ADR + ronda adversarial.
- **L2 (intermedia):** "cero escrituras" se refiere al **sustrato de
  afirmaciones** (objetos, `CURRENT`, journal, segmentos). Bajo L2, el
  archivo `.reader-gate` es **coordination artifact fuera del sustrato** y
  se declara explícitamente en `capabilities()` (bloque `view`) como
  `read_coordination_side_effect = ".reader-gate (may be created/locked,
  no substrate mutation)"`. La vista cumple el invariante.
- **L3 (permisiva):** el invariante se reduce a "no muta `CURRENT` ni
  crea objetos", ignorando locks y coordination artifacts. **Rechazada**:
  deja ambigua la frontera y abre la puerta a futuras escrituras
  silentes.

**Recomendación del spike al maintainer: L2**, con la salvedad de que
requiere una nota ADR vinculante que defina el invariante #4 como L2 y
declara `.reader-gate` como coordination artifact. Si el maintainer exige
L1, el gate G-VIEW-DOC debe ampliarse con un sub-ADR de primitiva read-only
(`read_gate/v2`) antes de cualquier implementación.

**Impacto en el veredicto:** `refine`, no `proceed`, porque la frontera de
pureza es contractual y debe cerrarse en el ADR antes de codear.

**Plataforma-conditionalidad (M1, ronda 3):** el comportamiento de
`.reader-gate` depende de la disponibilidad de `fcntl`:
- En plataformas POSIX con `fcntl` (Linux, macOS): `shared_reader_gate`
  entra en `_open_gate` y crea/chmod `.reader-gate` (`reader_gate.py:77-80`).
  L1 es **falsa** (hay escritura observable); L2 aplica.
- En plataformas **sin** `fcntl` (p. ej. Windows, donde `shared_reader_gate`
  hace `yield` sin abrir el gate, `reader_gate.py:72-76`): `.reader-gate`
  **no se crea** en lectura; la compactación también está deshabilitada
  (`exclusive_reader_gate` alza `compaction_platform_unsupported`,
  `reader_gate.py:99-100`). Aquí L1 es **trivialmente cierta** (cero bytes
  tocados bajo `.an-kla/` por la lectura).

Por tanto **L1/L2 no es una decisión global**: la respuesta es
dependiente de la plataforma. Q11 (§14) debe pedir al maintainer una decisión que
**o** (a) fija L2 globalmente y declara `.reader-gate` como coordination
artifact en ADR (con nota explícita de que en plataformas non-fcntl el
artifact simplemente no se materializa), **o** (b) fija L1 globalmente y
exige `read_gate/v2` en POSIX (donde hoy se crea el archivo) pero lo
permite en non-fcntl (donde no se crea). La matriz de tests §10 "Pureza de
lectura" debe parameterizarse por plataforma.

---

## 4. Decisiones propuestas y alternativas descartadas

### 4.1 Decisiones propuestas (P — requieren congelarse en ADR G-VIEW-DOC)

| # | Decisión | Justificación |
|---|---|---|
| D1 | **Comando CLI:** `view context`. Forma: `an-kla --project-root <root> view context --revision <sha256:...> [--subject <subject_ref>] [--streams facts,events,episodes] [--limit N] [--budget N] [--cursor <token>] [--now <iso8601>] [--stale-after-days N]`. `--revision` obligatorio. Salida JSON canónica a stdout. | Paridad con `retrieve`/`assemble-context`. |
| D2 | **Fuente:** `MemoryStore.snapshot(revision_id)` con `revision_id` obligatorio explícito. | Evita lectura accidental de `CURRENT` a mitad de cálculo. |
| D3 | **Universo v1:** `facts`, `events`, `episodes`. Default: los tres. `--streams` opt-in. Los conteos de `subjects_without_subject_ref` se refieren sólo a los streams solicitados. | Un subject puede tener fact + event + episode. |
| D4 | **Agrupación:** por `subject_ref` exacto (string completo byte-exacto, sin normalizar). | ADR-0033 §3 prohíbe NFC/casefold. |
| D5 | **Registros sin `subject_ref`:** sección `subjects_without_subject_ref: {facts:N, events:N, episodes:N}` (sólo conteo). No se agrupan, no se derivan. **`N` cuenta TODOS los registros sin `subject_ref` del stream solicitado, independientemente de su vigencia** (vigente, sustituida o refutada): el propósito del contador es señalar cuánta del store es pre-`subject_ref`/no agrupable, no sólo la vigente. (M2, ronda 3.) | Prohibido agruparlos (ADR-0032 §"Corrección al spike previo"). |
| D6 | **Vigencia por subject:** alternativas = registros cuyo predicado `status if present else nu if present else "vigente"` evalúa a `{vigente, active, None}` (idéntico a `retrieve`, incluyendo fallback `nu`). `sustituida`/`refutada` van a `history`. Valor fuera de `{vigente, active, None, sustituida, refutada}` → `view_rule_ambiguous`. | Alinea con `retrieve` (`retrieval.py:161`). |
| D7 | **Conflicto de datos → éxito explícito:** dos o más alternativas vigentes con el mismo `subject_ref` se devuelven todas, ordenadas por §5.1, con `data_conflict=true`. | ADR-0032 §Decisión 7. |
| D8 | **Ambigüedad de regla → fail-closed** con código `view_rule_ambiguous`. Trigger principal y alcanzable: registro cuyo predicado de vigencia evalúa a un valor fuera del enum conocido. Trigger de defensa: cualquier otro caso donde la regla contractual sea insuficiente (p. ej. drift estructural). | ADR-0032 §Decisión 7. |
| D9 | **Sin cache persistente en v1.** | Determinismo y simplicidad. |
| D10 | **Sin reloj, red, Git ni APIs durante el cálculo.** `verified_at` se proyecta verbatim; `days_since_verified`/`stale`/`freshness_error` se rellenan **sólo si el caller pasa `--now`**. **Diferencia intencional respecto de `retrieve`:** `retrieve` usa `datetime.now(timezone.utc)` cuando `now` es `None` (`an_kla/retrieval.py:124-126`); la vista **NO** copia ese fallback (rompería ADR-0032 §4). | ADR-0032 §4; ADR-0021. |
| D11 | **Salida:** schema nuevo `an-kla/context-view-v1`, cerrado (`additionalProperties:false`), con `canonicality="non-authoritative"`, `untrusted_memory_data=true`, `revision`, `contract_version="g-view/v1"`, `inputs`, `freshness`, `subjects_without_subject_ref`, `subjects`, `pagination`, `warnings`. La forma del sobre **no** cambia entre los modos con/sin `--now`; sólo los valores. | Paridad con `mcp-retrieve-v2`. |
| D12 | **`verified_at` se proyecta como `self_asserted_timestamp`** conforme a ADR-0021. | ADR-0021 §3; ADR-0032 §5. |
| D13 | **MCP tool `an_kla_view_context`** read-only, paridad con CLI; mismo schema. | ADR-0032 no prohíbe MCP. |
| D14 | **Cursor determinista versionado** por `(contract_version, revision, inputs_digest, next_subject_ref, digest_canónico)`. El cursor apunta al **siguiente subject a considerar** (no a la última alternativa emitida), para garantizar progreso incluso en páginas sin elementos. Validación fail-closed (§5.2). | §5. |
| D15 | **`capabilities()`** se extiende aditivamente con un bloque `view` (perfil, `contract_version`, operaciones, códigos terminales, `read_coordination_side_effect`). **No** expone kinds/namespaces/pattern (`tests/test_agent_contracts.py:324-340`). | ADR-0010. |
| D16 | **Proyección de contenido (D11-high-2):** cada alternativa e historia proyecta `record_raw` (objeto verbatim del snapshot pre-overlay, forma abierta pero sin mutar; el schema del sobre lo admite como `object` sin `additionalProperties:false` **sólo en este campo**) y `record_text` (derivado por `record_text()`, `an_kla/record_text.py:15-32`). Ambos son `untrusted_memory_data`. | El consumidor debe poder observar las alternativas; el conflicto no es inspeccionable sin contenido. |
| D17 | **Supersede cross-subject (D11-high-3):** cada registro se agrupa por su propio `subject_ref` exacto. Si target y sucesor comparten subject_ref, el target va a `history` del sucesor. Si no, cada uno va a su grupo y la relación se expone como `supersede_link` en el registro correspondiente. Si el sucesor carece de subject_ref, se cuenta en `subjects_without_subject_ref`; el target aparece en su propio grupo (o se cuenta si tampoco tiene). **El link supersede es siempre intra-stream (L5, ronda 3):** `validate_lifecycle` (`revision_validation.py:285`) exige que `target_id` y `sustituida_por` estén ambos en `by_id[stream]`; el campo `stream` de `supersede_link` es por tanto compartido por ambos extremos. | `supersede.py:25-59` no compara `subject_ref`; el agrupamiento forzado inventaría relación. |
| D18 | **Pureza de lectura (§3.7):** la vista **no** muta el sustrato. La declaración contractual del invariante #4 ("cero escrituras") debe precisarse en el ADR como L2 (`.reader-gate` es coordination artifact fuera del sustrato) o, si el maintainer exige L1, debe añadirse un sub-ADR de primitiva read-only (`read_gate/v2`) antes de implementar. | Hallazgo BLOCKER intento 2. |

### 4.2 Alternativas descartadas (con razón)

- **Cache persistente (SQLite/JSON).** ADR-0032 §4; añadiría superficie de
  invalidación y drift. Sin cache en v1.
- **Catálogo canónico con ganador por subject.** ADR-0032 §8.
- **Vista que consulta fuentes vivas.** ADR-0032 §4/§5.
- **Reutilizar `lineage.refs` como identidad.** ADR-0032 §"Corrección al
  spike previo".
- **Agrupar registros sin `subject_ref` por heurística.** Sin contrato, es
  invención. Se exponen sólo conteos (D5).
- **Cursor por índice posicional absoluto.** Frágil ante cambios de
  contrato; cursor por `(subject_ref, stream, record_sha256)` + digest es
  más robusto.
- **Cursor "última alternativa emitida" (intento 1).** Descartado por la
  ronda adversarial 2: una página sin elementos no puede avanzar. Cursor =
  "siguiente subject a considerar" (D14).
- **`budget=0` devuelve sobre vacío sin error (intento 1).** Descartado:
  el sobre vacío tiene tamaño positivo, violando "bytes medidos ≤
  presupuesto". `budget ≥ 1` requerido (§5.3).
- **Proyectar `verified_at` con `now = datetime.now()`.** Prohibido por
  ADR-0032 §4; la vista exige `now` explícito (D10).
- **Extender schemas v2 existentes.** ADR-0033 §8.
- **Replay sobre `CURRENT` sin pin.** No-determinismo.
- **Forzar toda cadena supersede al subject del sucesor (intento 1).**
  Descartado: `supersede.py:25-59` no valida `subject_ref`; forzarlo
  inventaría agrupamiento (D17).
- **`_snapshot_under_gate` sin `shared_reader_gate`.** Descartado:
  rompería `compaction/v1` (T8).
- **Cursor descrito como protección criptográfica contra manipulación
  (intento 1, T5).** Descartado: el digest SHA-256 no keyed detecta
  corrupción accidental, no manipulación; la protección real es semántica
  (la posición debe existir en la secuencia recomputada).
- **L3 (invariante #4 reducido a "no mutar CURRENT/objetos").** Deja
  ambigua la frontera de pureza; rechazada.

---

## 5. Ordering, cursor, paginación y presupuesto

### 5.1 Orden total

Para una misma `(revision_id, inputs)` la vista produce una secuencia
totalmente ordenada de **subjects** (cada subject es atómico para la
paginación). Reglas (en orden de precedencia):

1. **Por `subject_ref`** ascendentemente por comparación por code point del
   string completo (equivalente a `sorted()` de Python sobre strings UTF-8;
   locale-independiente y estable).
2. **Dentro de un subject, por alternativa vigente** ascendentemente por
   tupla canónica `(stream, record_sha256)` donde `stream` se ordena por el
   enum cerrado `("facts","events","episodes")` y `record_sha256 =
   digest_json(raw_record)`. Esta tupla es **única** dentro de un subject
   (la unicidad de `id` es por stream, `store.py:198-205`; los
   `record_sha256` son content-addressed).
3. **Dentro de la historia por alternativa** (no vigente): orden
   descendente por `verified_at` **textual** cuando existe (comparación por
   code point, no cronología interpretada); en ausencia o empate, desempate
   ascendente por `(stream, record_sha256)`. Determinista y sin reloj.

Esta secuencia es reproducible sin reloj, sin red, sin estado.

### 5.2 Cursor (D14)

El cursor es un string opaco que el caller devuelve intacto para pedir la
siguiente página. **Semántica:** apunta al **siguiente subject a considerar**
(no a la última alternativa emitida). Esta unidad atómica coincide con la
unidad de paginación, garantizando progreso incluso en páginas vacías.

Forma interna (canonical JSON, opaque al caller — p. ej. hex del JSON
canónico):

```json
{
  "v": "g-view/v1",
  "r": "sha256:<revision>",
  "ih": "sha256:<digest del canonical_json(inputs)>",
  "n": "<subject_ref del siguiente subject a considerar, o null si complete>",
  "d": "sha256:<digest de los campos anteriores>"
}
```

`d` = `digest_json({v,r,ih,n})`. **El digest es detección de corrupción
accidental, no protección criptográfica:** un caller puede recalcularlo.
La protección real es **semántica**: al reanudar, la vista recomputa la
secuencia determinista y busca el subject `n` en ella; si no existe (por
drift contractual, revisión distinta, inputs distintos, o subject eliminado
— p. ej., por reemplazo de anchor que movió al subject fuera del universo
visible) → `view_cursor_invalid`. No hay secretos; la seguridad es
integridad de contrato, no confidencialidad.

**`ih` (digest de inputs) — forma canónica (M3, ronda 3):** `inputs` se
construye como un dict cerrado `{streams, subject_filter, limit,
budget_bytes, now, stale_after_days}` donde **`streams` se normaliza al
orden canónico del enum `("facts","events","episodes")` con dedup** antes
de digerir y antes de computar, sin importar el orden pasado por el
caller. Esto hace el cursor robusto a `--streams events,facts` en página 1
y `--streams facts,events` en página 2 (ambos producen el mismo `ih` y la
misma secuencia). Si el caller pasa un stream fuera del enum, el error se
reporta en la página 1 como `view_invalid_inputs` (detail `streams`), antes
de emitir cursor alguno.

**Validación de revisiones y digests (L3, ronda 3):** el campo `r` del
cursor y cada `record_sha256` son identificadores `sha256:<64hex>`;
reutilizar `bare_digest` (`an_kla/canonical.py:48-54`) para validar su
forma antes de cualquier lookup, evitando re-implementar la guarda.

Validación fail-closed ante: digest inconsistente, `v` ≠ contract actual,
`r` ≠ revisión solicitada, `ih` ≠ digest de inputs actuales, `n` no
encontrado en la secuencia recomputada. Cualquier fallo →
`view_cursor_invalid` (§6.2).

### 5.3 Paginación y presupuesto — semántica coherente y fail-closed

**Definición de presupuesto.** `--budget N` (entero ≥ 1) cubre el sobre
**completo**: `len(canonical_json(view_payload).encode("utf-8"))`,
incluyendo cabeceras, `subjects` (con `record_raw` y `record_text`),
`freshness`, `pagination` (incluyendo el propio `next_cursor` cuando más
subjects queden) y `warnings`. `budget < 1` → `view_invalid_inputs` con
detail `budget`.

**Algoritmo (convergente, mide el sobre final; corrección H1 ronda 3):**

1. **Secuencia ordenada** (§5.1): determinista, independiente de `budget`
   y de `budget_used_bytes`.
2. **Punto de partida** determinado por el cursor: si hay cursor, empezar
   en el subject `n`; si no, en el primer subject de la secuencia.
3. **Selección greedy subject a subject.** Para cada subject candidato
   (en orden):
   a. Construir el sobre tentativo = sobre actual + este subject + (si
      quedan más subjects, un `next_cursor` placeholder). El campo
      `pagination.budget_used_bytes` se fija en **cota superior
      `budget_bytes`** (el valor máximo declarado, no el total corriente).
   b. Calcular `len(canonical_json(sobre_tentativo))` con esa cota.
   c. Si `len(sobre_tentativo) ≤ budget_bytes`: emitir el subject; avanzar
      cursor al siguiente subject. Continuar.
   d. Si excede: **detenerse**. Si al menos un subject fue emitido en esta
      página, devolverla con `next_cursor = n` apuntando al subject que no
      cupo (`complete=false`, `truncated_subjects = total − served`). Si
      **ningún** subject fue emitido aún (primer subject no cabe ni solo),
      lanzar `view_subject_exceeds_budget` (código terminal, exit 3).
4. **Fin natural:** si todos los subjects se sirven sin exceder,
   `complete=true`, `next_cursor=null`.
5. **Fijación final de `budget_used_bytes`.** Tras el paso 3/4, los
   subjects servidos y la presencia/ausencia de `next_cursor` están
   fijos. Iterar `exact_sized_payload`-style (`canonical.py:20-37`)
   **sólo sobre el campo `budget_used_bytes`**, con los demás campos ya
   determinados. Converge porque el único valor variable es el propio
   `budget_used_bytes`. Si no converge en ≤ 16 iteraciones →
   `view_internal_error` (paridad `canonical.py:33-34`).

**Por qué la cota superior `budget_bytes` en el paso 3a es obligatoria
(H1):** el valor final de `budget_used_bytes` (tras el paso 5) puede
tener **más dígitos** que el total corriente en el momento de la decisión
(p. ej., el total corriente cabe en 3 dígitos pero el sobre final crece a
4). Si el paso 3b midiera con el total corriente, la decisión de emitir
se basaría en un sobre más pequeño que el final, y el sobre final podría
exceder `budget_bytes` por el delta de dígitos. Midiendo con la cota
superior `budget_bytes` (que tiene el máximo número de dígitos posible),
todo `budget_used_bytes` final ≤ `budget_bytes` produce un sobre
menor-o-igual al medido en 3b. Como además `canonical_json` ordena claves
y `budget_used_bytes` es el único campo variable entre 3b y 5, la
siguiente cadena es **demostrable**:

`len(canonical_json(sobre_final))` ≤ `len(canonical_json(sobre_medido_en_3b))`
≤ `budget_bytes`.

El paso 3a debe usar `budget_bytes` literalmente (no una cota menor tipo
`10^ceil(log10(budget))`); la implementación puede cachear ese valor por
llamada. Alternativa equivalente válida: reservar el ancho fijo máximo de
`budget_used_bytes` (p. ej., siempre 10 dígitos rellenados con ceros
izq.), pero rompe la lectura humana y el patrón `exact_sized_payload`; se
descarta por complejidad sin ganancia.

**Propiedades que esta semántica garantiza:**

- **Bytes medidos ≤ presupuesto declarado** (demostrable: paso 3a mide con
  cota superior `budget_bytes`; paso 5 reduce `budget_used_bytes` a su
  valor final ≤ cota; ver prueba H1 arriba).
- **Progreso o error estable cuando el primer subject no cabe:** paso 3d
  fail-closed con `view_subject_exceeds_budget`. No hay página vacía con
  cursor opaco que oculte subjects para siempre.
- **Cursor en la misma unidad atómica que la paginación (subject):** el
  cursor apunta al "siguiente subject", no a una alternativa suelta.
- **Ninguna alternativa/conflicto oculto por salto:** un subject se emite
  completo (todas sus alternativas vigentes + su historia) o se omite
  completo; nunca se sirve parcial.
- **Algoritmo convergente que mide el envelope final:** paso 5.

**Casos especiales:**

- `--limit N`: número máximo de subjects en la página (además del
  presupuesto). `limit ≤ 0` → `view_invalid_inputs` con detail `limit`.
- `--subject <subject_ref>`: sirve sólo ese subject (un subject). Sigue
  aplicando la semántica de presupuesto; si no cabe →
  `view_subject_exceeds_budget`.
- Página con `complete=false`: siempre lleva `next_cursor` no nulo.
- Página con `complete=true`: `next_cursor=null`.

`pagination` siempre presente: `{complete: bool, next_cursor: str|null,
served_subjects: int, total_subjects: int, truncated_subjects: int,
budget_used_bytes: int, budget_bytes: int, limit: int}`.

### 5.4 Compatibilidad con orden adversarial

Test de byte-estabilidad: dada una misma `(revision_id, inputs)`, dos
llamadas (incluso desde procesos distintos) deben producir el mismo
`canonical_json(view_payload)` byte a byte. Pruebas con orden físico
adversarial de segmentos deben confirmar que la vista no depende del orden
físico, sólo del ordenamiento §5.1.

---

## 6. Taxonomía de conflictos y códigos de error

### 6.1 Taxonomía de conflicto de datos (resultado exitoso explícito)

Estos casos **no son error**; producen `subjects[i].alternatives` con ≥ 2
entradas y `subjects[i].data_conflict = true`. **Cada alternativa proyecta
su `record_raw` y `record_text` completos (D16)** para que el consumidor
pueda inspeccionar el conflicto:

| Caso | Comportamiento |
|---|---|
| Dos registros vigentes, mismo `subject_ref`, streams distintos | Alternativas separadas (una por stream), ambas vigentes, ordenadas por §5.1.2, cada una con su `record_raw` + `record_text`. `data_conflict=true`. |
| Cadena de supersede con mismo `subject_ref` en target y sucesor | Alternativa vigente = sucesor; el target va a `history` del sucesor con `status="sustituida"` y `supersede_link={stream,target_id,sustituida_por}`. |
| **Cadena supersede con subjects distintos (o uno sin subject_ref)** | Cada registro se agrupa por su propio `subject_ref` exacto. El sucesor aparece como alternativa vigente de su subject; el target aparece como alternativa vigente o en `history` de su propio subject (según su estado overlay). La relación física se expone vía `supersede_link` en cada registro afectado. **No se fuerza agrupamiento.** |
| Refutación posterior al `verified_at` de un registro | El refutado aparece en `history` con `status="refutada"`; no se elimina. |
| Dos registros vigentes con `record_sha256` idéntico, mismo stream, mismo `subject_ref` | Imposible en snapshot válida (dedup `store.py:198-205`, validación commit `store.py:734-741`). Por drift → `view_rule_ambiguous`. |
| Dos registros vigentes con `record_sha256` idéntico, streams distintos | Ordenable por `(stream, record_sha256)` (§5.1.2); se sirve como `data_conflict=true`, **no** como error. |
| Registros con namespaces distintos en un mismo pin (anchor reemplazado) | Agrupados por `subject_ref` exacto (namespace incluido en el string); no se mezclan. `warnings` lleva `multiple_namespaces_observed` (datos, no error). |

### 6.2 Taxonomía de ambigüedad contractual y errores (fail-closed)

| Código | Condición | Exit |
|---|---|---|
| `view_rule_ambiguous` | Registro cuyo predicado de vigencia evalúa a un valor fuera de `{vigente, active, None, sustituida, refutada}`, o drift estructural donde la regla contractual es insuficiente. | 3 |
| `view_cursor_invalid` | Cursor opaco mal formado, digest inconsistente, `contract_version`/`revision`/`inputs_digest` no coinciden, o `n` (siguiente subject) no existe en la secuencia recomputada. | 3 |
| `view_revision_not_available` | `snapshot(revision_id)` lanza `IntegrityError` (`revision_archived_by_compaction`, `object_missing:revisions`, etc.). | 3 |
| `view_subject_exceeds_budget` | El primer subject a considerar (incluyendo su `record_raw` + `record_text` + overhead de sobre y `next_cursor`) no cabe en `budget_bytes`. Garantiza progreso o error estable (§5.3 paso 3d). | 3 |
| `view_invalid_inputs` | `limit ≤ 0`, `budget < 1`, `--subject` no cumple `SUBJECT_REF_PATTERN`, `--streams` con valor fuera del enum, `--now` sin formato ISO-8601 cerrado, combinatoria prohibida. Detail evolutivo nombra el campo. | 2 (CLI usage) |
| `view_internal_error` | Cualquier otro fallo no catalogado (fall-closed genérico, análogo a `_safe_error → internal_error` en `mcp.py:48-49`); p. ej. no convergencia de `budget_used_bytes` (§5.3 paso 5). | 1 |

### 6.3 Códigos terminales canónicos (a congelar en ADR)

Lista estable: `view_rule_ambiguous`, `view_cursor_invalid`,
`view_revision_not_available`, `view_subject_exceeds_budget`,
`view_invalid_inputs`, `view_internal_error`. Convención de exit codes
idéntica al CLI vigente (`0` éxito, `2` uso, `3` outcomes no-committed /
namespace-unavailable / análogos, `1` fatal vía handler general).

---

## 7. Envelope/schema de salida — borrador y ejemplo mínimo

Schema propuesto: **`an-kla/context-view-v1`** (a publicar en
`docs/schemas/context-view-v1.schema.json` y gemelo byte-idéntico en
`an_kla/schemas/`). Forma cerrada (`additionalProperties:false`) **salvo**
el campo `record_raw`, que es un `object` abierto (proyección verbatim del
registro crudo, compatible con schemas legacy abiertos). Todos los campos
de records llevan marca heredada `untrusted_memory_data` (declarada al
nivel del sobre).

```json
{
  "schema": "an-kla/context-view-v1",
  "canonicality": "non-authoritative",
  "untrusted_memory_data": true,
  "canonicalization": "canonical-json/v1",
  "contract_version": "g-view/v1",
  "revision": "sha256:<revision_pin>",
  "inputs": {
    "streams": ["facts","events","episodes"],
    "subject_filter": null,
    "limit": 50,
    "budget_bytes": 65536,
    "now": null,
    "stale_after_days": null
  },
  "freshness": null,
  "subjects_without_subject_ref": {"facts": 0, "events": 0, "episodes": 0},
  "subjects": [
    {
      "subject_ref": "an-kla:subject:v1:service:p-00…00:billing-svc",
      "data_conflict": false,
      "alternatives": [
        {
          "stream": "facts",
          "id": "f-billing-001",
          "record_sha256": "sha256:<digest_json(raw_record)>",
          "status": "vigente",
          "verified_at": "2026-08-11T10:20:51.000000Z",
          "self_asserted_timestamp": true,
          "days_since_verified": null,
          "stale": null,
          "freshness_error": null,
          "record_text": "billing-svc opera en us-east-1 con SLO 99.9%",
          "record_raw": {
            "id": "f-billing-001",
            "schema": "an-kla/fact-v1",
            "subject_ref": "an-kla:subject:v1:service:p-00…00:billing-svc",
            "verified_at": "2026-08-11T10:20:51.000000Z",
            "payload": {"text": "billing-svc opera en us-east-1 con SLO 99.9%"},
            "lineage": {"derived_from_retrieval": false, "refs": [{"kind":"external","id":"https://example/adr"}]}
          },
          "supersede_link": null,
          "lineage_refs": [{"kind": "external", "id": "https://example/adr"}]
        }
      ],
      "history": [
        {
          "stream": "facts",
          "id": "f-billing-000",
          "record_sha256": "sha256:…",
          "status": "sustituida",
          "verified_at": "2026-07-01T00:00:00Z",
          "self_asserted_timestamp": true,
          "days_since_verified": null,
          "stale": null,
          "freshness_error": null,
          "record_text": "billing-svc opera en us-east-1 (SLO sin definir)",
          "record_raw": {"id":"f-billing-000","schema":"an-kla/fact-v1","subject_ref":"an-kla:subject:v1:service:p-00…00:billing-svc","verified_at":"2026-07-01T00:00:00Z","payload":{"text":"billing-svc opera en us-east-1 (SLO sin definir)"}},
          "supersede_link": {"stream":"facts","target_id":"f-billing-000","sustituida_por":"f-billing-001"},
          "lineage_refs": []
        }
      ]
    }
  ],
  "pagination": {
    "complete": true,
    "next_cursor": null,
    "served_subjects": 1,
    "total_subjects": 1,
    "truncated_subjects": 0,
    "budget_used_bytes": 812,
    "budget_bytes": 65536,
    "limit": 50
  },
  "warnings": []
}
```

### 7.1 Proyección de contenido (D16) — detalles

- **`record_raw`**: objeto verbatim del snapshot pre-overlay
  (`Snapshot.raw_records`, `store.py:77, 208, 231-244`). Forma abierta
  (legacy-compatible); el schema del sobre lo admite como
  `{"type":"object"}` **sin** `additionalProperties:false` en este campo,
  documentando que su forma depende del schema de records vigente al
  commit (p. ej. `an-kla/fact-v1` es abierto, `an-kla/write-proposal-v1`
  añade `subject_ref`). **No se filtra ni reordena**; se proyecta tal cual.
- **`record_text`**: string derivado por `record_text(record_raw)`
  (`an_kla/record_text.py:15-32`), idéntico orden de campos que usa
  `retrieve` y el FTS5. Garantiza paridad con la búsqueda textual y da al
  consumidor un texto limpio sin necesidad de interpretar `record_raw`.
- **Presupuesto.** Cada byte de `record_raw` + `record_text` entra en
  `budget_used_bytes` (§5.3). Un subject con records grandes puede
  provocar `view_subject_exceeds_budget` si no cabe ni solo.
- **`record_sha256`** = `digest_json(raw_record)` (pre-overlay); estable y
  reproducible.
- **Datos no confiables.** Todo el sobre lleva `untrusted_memory_data:
  true`; los campos `record_raw` y `record_text` se documentan como dato
  potencialmente contaminado (prompt injection, contenido atacante). La
  vista no interpreta ni ejecuta nada de `record_raw`.
- **`supersede_link`**: `{stream, target_id, sustituida_por}` o `null`.
  Presente cuando el registro participa en una cadena supersede (como
  target o como sucesor). No agrupa; sólo expone la relación física para
  que el consumidor pueda reconstruir el grafo si lo desea. **Forma
  simétrica (L1, ronda 3):** el mismo objeto `{stream, target_id,
  sustituida_por}` se proyecta en AMBOS extremos del link — en el target
  (status `sustituida`) y en el sucesor (status `vigente`). En el sucesor,
  `sustituida_por` referencia su propio `id` (redundante pero uniforme y
  sin campo adicional que mantener); en el target, referencia el `id`
  del sucesor. Alternativa de campo distinto (`succeeds`) se descarta por
  multiplicar superficie contractual sin ganancia semántica. `stream` es
  único y compartido (L5).
- **`lineage_refs`**: array (vacío si el registro no tiene `lineage`, p.
  ej. legados sin ese campo). Sólo procedencia/evidencia (ADR-0032
  §"Corrección al spike previo").
- **`self_asserted_timestamp: true`**: siempre presente en alternativas e
  history cuando existe `verified_at`; declara explícitamente no-autoridad
  (ADR-0021 §3).
- **Forma con/sin `--now`:** el sobre **no** cambia de forma. Cuando
  `inputs.now == null`, `freshness` vale `null` y los campos
  `days_since_verified`/`stale`/`freshness_error` de cada alternativa/history
  valen `null`. Cuando el caller pasa `--now`, `freshness` es un objeto
  cerrado `{semantics, source_field, computed_at, stale_after_days}`
  (idéntico a `retrieval-result-v2.schema.json:71-90`) y por
  alternativa/history se rellenan los tres campos (`days_since_verified`
  siempre; `stale` sólo si `--stale-after-days`; `freshness_error` sólo si
  `verified_at` está pero no es parseable).

---

## 8. Cache, recomputabilidad y concurrencia

| Alternativa | Recomendación v1 | Razón |
|---|---|---|
| **Sin cache** | **Recomendada** | Determinismo absoluto, sin invalidación, sin drift. La snapshot es O(n) y el store es local. |
| Cache efímera en proceso (memo dentro de la llamada) | Tolerable como optimización interna no observable | No cambia bytes de salida. No expuesta en contrato. |
| Cache persistente | **Descartada para v1** | Añade superficie de invalidación, drift, locks. Requeriría su propio ADR con threat model. |

**Invalidación (caso efímero):** la cache vive lo que dura la llamada; no
sobrevive entre invocaciones.

**Aislamiento y concurrencia (corregido vs. intento 1):**

- La vista corre dentro de `shared_reader_gate`
  (`an_kla/reader_gate.py:55-88`), que adquiere `fcntl.flock(LOCK_SH)` sobre
  `.reader-gate`.
- **`shared_reader_gate` excluye compactación** local, no al writer
  ordinario. Compactación usa `exclusive_reader_gate`
  (`reader_gate.py:90-117`) sobre el **mismo** `.reader-gate` con `LOCK_EX`;
  por tanto espera a que todos los readers liberen. Un writer ordinario
  usa `.write.lock` (`store.py:569-625`), archivo **distinto**:
  **el writer NO espera al reader, y viceversa**.
- **Implicación para la vista:** mientras se computa, un writer puede
  commitir una nueva revisión y mover `CURRENT`. **No afecta** a la
  corrección de la vista porque el `revision_id` pinneado es
  content-addressed: sus segmentos y manifest son bytes inmutables que
  seguirán existiendo (no se borran por un commit ordinario; sólo la
  compactación archiva, y ésta sí está excluida por el gate).
- **Implicación para la pureza de filesystem:** la primera lectura puede
  crear `.reader-gate` y `fchmod`arlo (§3.7). El writer no crea ni lee
  `.reader-gate`; no hay interferencia en ese sentido.

**Recomputabilidad:** dada `(revision_id, inputs, contract_version)` la
salida es byte-idéntica entre corridas, procesos y máquinas, porque (a) el
`revision_id` es inmutable y content-addressed; (b) los inputs entran al
digest del cursor y al sobre; (c) el orden es byte-exacto (§5.1); (d) no
se consultan reloj ni red (D10); (e) el algoritmo de selección y
convergencia (§5.3) no depende de estado externo.

---

## 9. Threat model y mitigaciones

| # | Amenaza | Mitigación |
|---|---|---|
| T1 | **Namespaces históricos múltiples en un pin.** Reemplazo de anchor deja registros con namespace anterior (ADR-0033 §12). | La vista agrupa por `subject_ref` exacto (namespace incluido en el string); **no mezcla**. `warnings` lleva `multiple_namespaces_observed` cuando se observa más de un namespace. No sobreafirmar "no puede llegar al store": el binding al commit usa el namespace vigente en ese momento, pero la cadena puede tener varias eras. |
| T2 | **`subject_ref` controlado por dato no confiable** (prompt injection en `record_raw`). | `subject_ref` es dato, no autoridad (ADR-0033 §7; `write_policy.py:36-46`). La vista lo trata como string opaco. `record_raw` y `record_text` se exponen como `untrusted_memory_data`; la vista no interpreta ni ejecuta nada. |
| T3 | **Falsa actualidad / autoridad.** | `canonicality="non-authoritative"`, `untrusted_memory_data=true`, `self_asserted_timestamp=true` obligatorios en el sobre. |
| T4 | **Conflicto oculto por ordering/budget/paginación.** | `pagination.truncated_subjects` lo declara explícito; `data_conflict=true` se eleva por subject sin consumir presupuesto extra; el cursor permite reanudar; §5.3 garantiza progreso o error estable. |
| T5 | **Cursor replay o binding incompleto.** | Cursor ligado a `(contract_version, revision, inputs_digest, next_subject_ref)` más `d` (digest de corrupción accidental, **no** protección criptográfica: el caller puede recalcularlo). La protección real es **semántica**: la reanudación busca `next_subject_ref` en la secuencia recomputada; si no existe → `view_cursor_invalid`. No hay secretos; integridad de contrato, no confidencialidad. |
| T6 | **Lectura accidental de `CURRENT` a mitad del cálculo.** | `revision_id` se fija al inicio; `snapshot(revision_id)` no relee `CURRENT` después del pin (`store.py:173-186`). La vista nunca llama `read_current()`. |
| T7 | **Efectos de coordinación / "escrituras indirectas" (corregido vs. intento 1).** | La vista **no** invoca `commit*`, `rebuild-index`, `plan_write`, ni el check de actualizaciones (omitido con `--no-update-check`). **No adquiere `.write.lock`** y **no crea objetos** del sustrato. **PERO** `shared_reader_gate` puede crear/chmod `.reader-gate` (`reader_gate.py:38-49, 77-80`); este coordination artifact se declara en `capabilities()` (D15) y en el ADR (§3.7 L2). La vista **no** bloquea al writer ordinario (`store.py:569-625` usa `.write.lock` distinto); tampoco lo necesita. |
| T8 | **Compactación concurrente y revisiones archivadas.** | `shared_reader_gate` (LOCK_SH sobre `.reader-gate`) **sí** excluye compactación local (que usa LOCK_EX sobre el mismo archivo, `reader_gate.py:106`). Si la revisión pinneada fue archivada antes del pin externo, el snapshot ya creado es válido; si el caller pide una archivada que ya no está en disco → `view_revision_not_available`. Documentar: un pin no resurrects archived revisions; el caller debe mantener el export bundle referenciado si quiere garantizar disponibilidad histórica. |
| T9 | **Schemas/revisiones legacy sin `subject_ref`.** | D5 los cuenta sin agruparlos. La vista es robusta a `revision-v1`/`v2`/`v3` porque `snapshot` ya las maneja. |
| T10 | **Divergencia CLI/MCP/capabilities y drift docs/package schemas.** | Paridad byte-a-byte entre `docs/schemas/` y `an_kla/schemas/` exigida por `tests/test_agent_contracts.py:86-91`. El ADR debe añadir `context-view-v1` a `SCHEMA_FILES` (`an_kla/schemas/__init__.py:12-75`) y a `expected_names` (`tests/test_agent_contracts.py:21-84`). |
| T11 | **`record_sha256` dependiente de canonicalización.** | `digest_json(raw_record)` reutilizando `canonical.py:10-17, 40-45`; estable cross-runtime. |
| T12 | **Contenido `subject_ref` con kind ambiguo.** | ADR-0033 §4: precedencia semántica no ejecutable; la vista no desambigua kind, sólo enumera. |
| T13 | **Tamaño del cursor / DoS por cursor gigante.** | `subject_ref` ≤ 129 bytes (regex); el cursor es canonical JSON corto; validación de tamaño antes de parsear. |
| T14 | **Reveal de información por la envolvente.** | `subjects_without_subject_ref` expone sólo conteos por stream solicitado. `record_raw` y `record_text` sí revelan contenido (es su propósito); se declaran `untrusted_memory_data` y se documentan como dato potencialmente contaminado. `lineage_refs` puede contener URLs externas — la vista no las resuelve. |
| T15 | **Conflicto de datos mal inspeccionable.** | D16 proyecta `record_raw` + `record_text` completos por alternativa e history, para que el consumidor pueda observar el conflicto. |
| T16 | **Página sin progreso / subject oculto para siempre (intento 1).** | §5.3 paso 3d: `view_subject_exceeds_budget` fail-closed si el primer subject no cabe. Cursor apunta al "siguiente subject a considerar", no a la última alternativa emitida. |

---

## 10. Matriz de tests necesaria

Categorías mínimas para el PR de implementación:

**Determinismo y recomputabilidad**
- Misma `(revision, inputs)` → bytes idénticos entre corridas y procesos.
- Orden físico adversarial de segmentos no cambia la salida.
- Cursor redondo: `next_cursor` produce exactamente la continuación;
  `complete=true` al final.
- Convergencia de `budget_used_bytes` con `--budget` que fuerce truncamiento.

**Universo y vigencia**
- Snapshot con `sustituida` y `refutada`: sólo alternativas vigentes en
  `alternatives`, el resto en `history`.
- Cadena A→B→C **con mismo `subject_ref`**: vigente = C; A y B en history
  con `supersede_link`.
- Cadena A→B **con subjects distintos**: A y B en subjects distintos; cada
  uno con `supersede_link`; no se mezclan.
- Cadena A→B **donde A carece de `subject_ref` y B lo tiene**: B agrupado
  bajo su subject; A contado en `subjects_without_subject_ref`; `supersede_link`
  en B referencia el `target_id` físico.
- Streams combinados: un subject con alternativas en facts+events.

**Agrupación**
- Registro sin `subject_ref` → contador por stream solicitado, no subject.
- `--streams facts` no muestra conteos de events/episodes en subjects
  servidos, sólo en `subjects_without_subject_ref` (con `events:0,
  episodes:0`).
- `subject_filter` exacto: sólo ese subject, sin vecinos.
- `subject_filter` mal formado → `view_invalid_inputs`.

**Conflicto**
- Dos alternativas vigentes mismo subject, streams distintos →
  `data_conflict=true`, ambas servidas con `record_raw` completo, ordenadas
  por §5.1.
- Caso de regla insuficiente alcanzable: `status="draft"` →
  `view_rule_ambiguous`.
- Cross-stream con `record_sha256` idéntico → `data_conflict=true` (no
  error).
- Namespaces históricos múltiples en un pin → subjects separados, warning
  `multiple_namespaces_observed`.

**Paginación, presupuesto y cursor**
- `budget < 1` → `view_invalid_inputs` con detail `budget`.
- `limit ≤ 0` → `view_invalid_inputs` con detail `limit`.
- Primer subject no cabe ni solo → `view_subject_exceeds_budget` (exit 3),
  sin página parcial.
- Subject N no cabe después de servir 1..N-1 → página servida con
  `complete=false`, `next_cursor` apunta al subject N, `truncated_subjects`
  correcto.
- `limit=1` con 3 subjects → 3 páginas, última `complete=true`.
- Cursor válido entre procesos.
- Cursor manipulado (digest recalcularlo correctamente pero `n` que no
  existe en la secuencia) → `view_cursor_invalid`.
- Cursor con `revision` distinta → `view_cursor_invalid`.
- Cursor con `inputs_digest` distinta → `view_cursor_invalid`.
- Cursor con `contract_version` vieja → `view_cursor_invalid`.
- **Garantía H1 (ronda 3):** construir un caso donde el total corriente
  de subjects servidos cruce un dígito decimal (p. ej., 9→10, 99→100) y
  verificar que `len(canonical_json(sobre_final)) ≤ budget_bytes`
  hold; sin la cota superior del paso 3a este test fallaría.
- **Streams normalization (M3, ronda 3):** página 1 con `--streams
  events,facts`, página 2 con `--streams facts,events` → mismo `ih`,
  cursor válido, continuación correcta (no `view_cursor_invalid`).

**Revisión fijada**
- Revisión inexistente → `view_revision_not_available`.
- Revisión archivada por compactación → `view_revision_not_available`.
- Revisión con schema legacy (`revision-v1`) → vista servida; sin
  subjects_with_subject_ref salvo que los haya.

**Frontera de confianza**
- El sobre siempre lleva `canonicality`, `untrusted_memory_data`,
  `contract_version`, `revision`.
- `verified_at` se proyecta verbatim, sin `now` implícito.
- Con `--now`: `freshness` se rellena, `days_since_verified` por
  alternativa/history. Sin `--now`: ambos `null`.

**CLI/MCP/capabilities**
- `view context --revision … --no-update-check` stdout canónico.
- `view context` sin `--revision` → `view_invalid_inputs`.
- MCP `an_kla_view_context` paridad con CLI; mismo schema.
- `capabilities()` incluye bloque `view` aditivo con
  `read_coordination_side_effect`; dos invocaciones dan JSON canónico
  idéntico; dorado actualizado.
- `capabilities()` **no** expone kinds/namespaces/pattern (test
  `test_capabilities_do_not_expose_subject_view_or_kinds_or_namespaces`
  ampliado).
- Schema `context-view-v1` byte-idéntico entre `docs/schemas/` y
  `an_kla/schemas/`.

**Pureza de lectura (intento 2)**
- Antes/después de `view context`: `CURRENT` byte-idéntico, sin nuevos
  objetos bajo `revisions/`/`checkpoints/`/`segments/`/`transactions/`/`refutations/`,
  sin `.write.lock` adquirido.
- En raíz sin `.an-kla`: `view context` falla limpio (`view_revision_not_available`
  o equivalente) **sin crear** `.an-kla/` (paridad con `tests/test_subject_cli.py:351-375`).
- **Declara el coordination artifact:** si `.reader-gate` no existe antes
  de la llamada y la plataforma soporta `fcntl`, después de la llamada
  existe. Documentar en el test que esto es esperado bajo L2 (§3.7); si el
  maintainer elige L1, este test se invierte (la llamada no debe crear
  `.reader-gate`).
- **Parameterización por plataforma (M1, ronda 3):** el test de creación
  de `.reader-gate` se ejecuta sólo en plataformas con `fcntl` (skip con
  `unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), ...)`); en plataformas
  non-fcntl, otro test confirma que la lectura **no** crea `.reader-gate`
  (paridad con el yield-sin-gate de `reader_gate.py:72-76`).
- **Conteo M2 (ronda 3):** un stream con 2 registros sin `subject_ref`
  (uno vigente, uno `sustituida`) → `subjects_without_subject_ref.{stream}=2`,
  no 1; la vista no filtra por vigencia al contar este campo.

**Compatibilidad**
- Vista sobre la revisión 28 de la raíz principal corre sin error y
  devuelve `subjects_without_subject_ref` con los conteos reales (23/21/10
  si los tres streams).

---

## 11. Ledger de archivos previstos (ADR + implementación)

> Este spike no crea ninguno de estos archivos. Sólo los lista.

**Gate G-VIEW-DOC (PR docs/, antes que código)**
- `docs/architecture/0034-derived-contextual-view-v1-impl.md` (congela
  D1–D18, códigos, schema, cursor, proyección de contenido, frontera de
  pureza).
- Posible sub-ADR `docs/architecture/0035-read-gate-v2.md` **sólo si el
  maintainer elige L1** (§3.7): primitiva read-only que abre `.reader-gate`
  sin `O_CREAT`, fallando cerrado si no existe.
- Actualización `docs/README.md` (registro canónico) y
  `tests/test_adr_registry.py` (conteo).

**Gate G-VIEW-CORE (fase 1)**
- `an_kla/view.py` (módulo leaf: `compute_view(store, revision_id, inputs)
  → dict`; importa `snapshot`, `canonical`, `subject_ref`, `temporal`,
  `record_text`; no importa `write_policy`/`commit*`).
- `an_kla/schemas/context-view-v1.schema.json` (+ gemelo en `docs/schemas/`).
- `an_kla/schemas/__init__.py` (+ entrada `context-view-v1`).
- `tests/test_view.py` (matriz §10).

**Gate G-VIEW-CLI (fase 2)**
- `an_kla/__main__.py` (subcomando `view context`, mapping de códigos,
  stdout canónico, exit codes).
- `tests/test_view_cli.py`.

**Gate G-VIEW-MCP (fase 3)**
- `an_kla/mcp.py` (tool `an_kla_view_context`, inputSchema,
  `_safe_error` ampliado con códigos `view_*`).
- `tests/test_mcp.py` / `tests/test_mcp_stdio.py`.

**Gate G-VIEW-CAP (fase 4)**
- `an_kla/capabilities.py` (bloque `view` aditivo con
  `read_coordination_side_effect`).
- `tests/test_agent_contracts.py` (expected_names + assertions).

**Gate G-VIEW-REL (fase 5)**
- `docs/releases/v0.1.0-beta.13.md` (o la versión que corresponda).
- `docs/releases/v0.1.0-beta.13-adversarial.md` (plantilla
  `docs/adversarial-template.md`).
- Bump de `VERSION`.

---

## 12. DAG por fases

```
G-VIEW-DOC (ADR + contrato + decisión L1/L2)
        │ cierra: congelar D1–D18, códigos, schema, cursor, pureza
        │        main no etiquetable entre fases
        ▼
G-VIEW-CORE (vista pura)
        │ cierra: determinismo, recomputabilidad, matriz §10
        ▼
G-VIEW-CLI (subcommand view context)
        │ cierra: stdout canónico, exit codes, validación
        ▼
G-VIEW-MCP (tool an_kla_view_context)
        │ cierra: paridad CLI, _safe_error ampliado
        ▼
G-VIEW-CAP (capabilities bloque view)
        │ cierra: dorado actualizado, determinismo capabilities()
        ▼
G-VIEW-REL (docs de release + adversarial)
        │ cierra: ronda adversarial proceed; tag apunta a este commit
        ▼
   tag vX.Y.Z
```

Cada fase = su PR + verificación local
(`scripts/ci_local.py --simulate-ci`, `scripts/check_sizes.py`,
`python3 -m unittest discover -s tests -p 'test_*.py'`). `main` no
etiquetable entre fases (práctica §4). El tag apunta al commit que cierra
G-VIEW-REL.

---

## 13. Top-3 riesgos residuales

1. **Vista mayoritariamente vacía hasta adopción.** En stores legacy sin
   `subject_ref`, `subjects: []` y conteos altos. El valor del contrato es
   habilitar escritura futura. Comunicar a kairos/argos/kratos que deben
   escribir `subject_ref` para poblar la vista. **Decisión Q1.**
2. **Fragmentación por kind.** Un mismo ADR como `doc` y como `decision`
   produce dos subjects sin navegación entre ellos en v1 (relaciones
   diferidas a un ADR posterior). Documentar; no introducir heurística de
   fusión en v1.
3. **Frontera conflicto-de-datos vs. ambigüedad-de-regla es fina.** La
   línea entre `data_conflict=true` (éxito) y `view_rule_ambiguous`
   (fail-closed) depende de los casos congelados en el ADR. Cualquier caso
   nuevo detectado al codear debe volver al ADR, no al código.

Riesgos menores declarados:
- Migración de anchor produce namespaces históricos abandonados (T1): la
  vista los muestra ordenados; v1 no remapea.
- Stores muy grandes sin cache pueden hacer la vista costosa; v1 lo acepta.
- L1 vs L2 (§3.7): si el maintainer elige L1 global, el gate G-VIEW-DOC se
  amplía con un sub-ADR de primitiva read-only y el cronograma se alarga.
  Además la decisión depende de la plataforma (M1/§3.7): en non-fcntl L1 es
  trivialmente cierto, en POSIX es falso sin `read_gate/v2`.
- **Subjects con records muy grandes son total/opaco al consumidor (M4,
  ronda 3):** `view_subject_exceeds_budget` es terminal (exit 3) sin
  página parcial ni detalle de cuál subject o tamaño impidió caber. El
  consumidor sólo aprende "algún subject no cabe"; debe iterar a ciegas
  subiendo `--budget`. Fail-closed es correcto para v1, pero la
  usabilidad es pobre. **Decisión Q12 al maintainer:** ¿acepta terminal
  sin detalle en v1, o requiere un `detail` con el `subject_ref` y tamaño
  del primer subject que no cupo (dato ya marcado
  `untrusted_memory_data`, sin nueva superficie de autoridad)?

---

## 14. Preguntas para el maintainer

- **Q1 (D5).** ¿Confirmas que los registros sin `subject_ref` se exponen
  **sólo como conteo** por stream solicitado, sin contenidos ni
  agrupamiento heurístico?
- **Q2 (D2).** ¿Confirmas que `--revision` es **obligatorio** en v1?
- **Q3 (D9).** ¿Confirmas **sin cache persistente** en v1?
- **Q4 (D14/§5.2).** ¿Aprobas el esquema de cursor `(contract_version,
  revision, inputs_digest, next_subject_ref, digest)` con fail-closed ante
  cualquier drift, donde el cursor apunta al **siguiente subject a
  considerar** (no a la última alternativa emitida)?
- **Q5 (D11/D13).** ¿Aprobas el nombre `view context` para CLI y
  `an_kla_view_context` para MCP, con schema `an-kla/context-view-v1`?
- **Q6 (D6/T8).** ¿Confirmas que la vista no resurrects archived
  revisions? Un pin a una revisión que luego fue compactada producirá
  `view_revision_not_available` aunque el caller tenga export bundle.
- **Q7 (D10).** ¿Confirmas que `now` es input **explícito** del host (no
  implícito) y que, en su ausencia, no se proyecta `days_since_verified`?
- **Q8 (D16).** ¿Aprobas proyectar `record_raw` (objeto verbatim, forma
  abierta) **y** `record_text` (derivado por `record_text()`) en cada
  alternativa e history? Esto hace el sobre más grande pero inspeccionable.
- **Q9 (D17).** ¿Aprobas que un supersede con subjects distintos (o sin
  subject_ref en alguno) **no** se fuerce al mismo grupo, exponiendo la
  relación sólo vía `supersede_link`?
- **Q10 (§5.3).** ¿Aprobas la semántica fail-closed: `budget ≥ 1`,
  primer subject que no cabe ni solo → `view_subject_exceeds_budget`,
  cursor apunta al siguiente subject?
- **Q11 (§3.7, BLOCKER pureza).** ¿Decides L1, L2 o L3 para el invariante
  #4 "cero escrituras"? **La decisión depende de la plataforma (M1, ronda 3):**
  en POSIX `fcntl`, `shared_reader_gate` crea `.reader-gate` (L1 falso); en
  plataformas non-fcntl, no lo crea (L1 trivialmente cierto). Indica si la
  decisión es global o per-plataforma.
  - **L2 (recomendada):** `.reader-gate` es coordination artifact fuera
    del sustrato; se declara en `capabilities()` y en el ADR. En non-fcntl
    el artifact simplemente no se materializa.
  - **L1:** "cero escrituras" incluye cualquier byte bajo `.an-kla/`;
    requiere sub-ADR `read-gate/v2` (primitiva read-only sin `O_CREAT`)
    antes de implementar — al menos en POSIX.
  - **L3:** rechazada (deja ambigua la frontera).
- **Q12 (§5.3/§13, M4 ronda 3).** `view_subject_exceeds_budget` es
  terminal (exit 3) sin detalle. ¿Acepta terminal sin detalle en v1, o
  requiere un `detail` con el `subject_ref` y tamaño del primer subject
  que no cupo (dato `untrusted_memory_data`, sin nueva autoridad)?

---

## 15. Rondas adversariales

Este spike se cerró con **dos rondas adversariales de contexto fresco**
(rondas 1 y 3) y una auditoría independiente del controlador (ronda 2),
conforme a la práctica §1. Las decisiones y correcciones se aplicaron sobre
este mismo informe. Los reportes completos viven en el log del run; aquí se
resumen los hallazgos y la decisión final.

### 15.1 Ronda 1 (sobre el borrador del intento 1)

**Agente:** subagente `explore` con contexto fresco (sin haber visto el
análisis previo). **Decisión:** `fix-and-retry`.

Hallazgos (12):

| # | Severidad | Hallazgo | Acción |
|---|---|---|---|
| 1 | HIGH | Falsa equivalencia con `retrieve` sobre `now` (D10 decía "igual que retrieve"). | Corregido: la vista NO copia el fallback `datetime.now()` (`retrieval.py:124-126`). |
| 2 | HIGH | Cursor por `(subject_ref, alternative_id)` ambiguo cross-stream (id no único cross-stream). | Corregido (en intento 1): tupla `(subject_ref, stream, record_sha256)`. Vuelto a revisar en intento 2 (HIGH 2). |
| 3 | HIGH | `view_rule_ambiguous` inalcanzable; ejemplo cross-stream falso. | Corregido (en intento 1): trigger = status fuera del enum conocido. |
| 4 | MED | Ordenación de `history` contradictoria. | Corregido: descendente por `verified_at` textual con desempate `(stream, record_sha256)`. |
| 5 | MED | `verify_revision` no es pre-check barato. | Corregido: removida la afirmación. |
| 6 | MED | Predicado de vigencia omitía fallback legacy `nu`. | Corregido: predicado exacto. |
| 7 | MED | Inconsistencia en códigos de `limit`. | Corregido: un solo código. |
| 8 | MED | `days_since_verified` sin ubicación cuando se pasa `--now`. | Corregido: ubicación por alternativa/history + bloque `freshness`. |
| 9 | MED | Convergencia de `budget_used_bytes` bajo truncamiento no especificada. | Corregido en intento 1; **re-abierto** en intento 2 (HIGH 2). |
| 10 | LOW | Cita imprecisa `store.py:740`. | Corregido: cite `store.py:198-205` primario. |
| 11 | LOW | `subjects_without_subject_ref` vs `--streams` no interactuado. | Corregido: conteos por stream solicitado. |
| 12 | LOW | "canonical_json ordena strings". | Corregido: aclara code point. |

### 15.2 Ronda 2 (sobre el informe corregido del intento 1)

**Revisor:** controlador Codex, mediante la tarjeta de corrección `attempt-2`,
después de auditar independientemente el informe y el código. La sesión del
ejecutor fue reanudada con `--continue`, por lo que esta ronda no se presenta
como contexto fresco. **Decisión: aplicada; todas las correcciones quedaron
incorporadas en este informe (intentos 1+2).**

Hallazgos (7):

| # | Severidad | Hallazgo | Acción aplicada |
|---|---|---|---|
| B1 | BLOCKER | Afirmación "cero escrituras" falsa: `shared_reader_gate` crea/chmod `.reader-gate` (`reader_gate.py:38-49, 77-80`; `tests/test_reader_gate.py:43`). | §3.7 distingue tres capas; veredicto `refine`; Q11 al maintainer (L1/L2/L3). |
| H1 | HIGH | Presupuesto y cursor no garantizan progreso: `budget=0` devuelve sobre positivo; cursor = "última alternativa emitida" no avanza en página vacía. | §5.2/§5.3 reescritos: cursor = "siguiente subject a considerar"; `budget ≥ 1` cubre sobre completo; primer subject que no cabe → `view_subject_exceeds_budget`. |
| H2 | HIGH | Envelope sólo metadata, sin contenido; consumidor no puede inspeccionar conflicto. | D16 añade `record_raw` + `record_text`; §7.1 detalla proyección; §9 T15; tests en §10. |
| H3 | HIGH | Supersede no conserva `subject_ref` (`supersede.py:25-59`); el intento 1 forzaba cadena supersede al subject del sucesor. | D17: agrupa por subject_ref propio; `supersede_link` como metadata; §3.2/§6.1 corregidos; tests en §10. |
| M1 | MED | Sobreafirmación "no puede llegar al store" para namespaces históricos. | T1 corregido: anchor reemplazado deja namespaces históricos; la vista no mezcla; warning `multiple_namespaces_observed`. |
| M2 | MED | `shared_reader_gate` no excluye writer ordinario (`.write.lock` distinto). | §8 y T7 corregidos: gate excluye sólo compactación; writer puede correr concurrente; la snapshot pinneada es consistente consigo misma. |
| M3 | MED | Cursor SHA-256 no keyed descrito como protección criptográfica. | T5 corregido: digest es detección de corrupción accidental; la protección real es semántica (posición debe existir en secuencia recomputada). |
| P1 | BLOCKER (proceso) | Ronda adversarial ausente del informe del intento 1. | §15 añadida con ambas rondas y decisión. |

**Decisión final del spike:** `refine`. El gate ADR puede avanzar **sólo
después** de las decisiones Q1–Q12 (especialmente Q11 sobre pureza de
lectura y Q12 sobre diagnóstico de presupuesto). Las correcciones
BLOCKER/HIGH/MED de las tres rondas están incorporadas.

### 15.3 Ronda 3 (sobre el informe corregido del intento 2)

**Agente:** tarjeta de corrección `attempt-3` con contexto fresco
(subagente opencode/GLM, sin haber visto el análisis previo; verificación
independiente contra código, ADRs e issue #60). **Decisión: aplicada,
todas las correcciones incorporadas en este informe.**

**Verificación independiente (H, contra código real):** se confirmaron
contra `archivo:línea` las 25 citas técnicas centrales del informe
(`reader_gate.py:38-49,72-80,90-117`; `store.py:169-171,173-245,198-205,
215-244,569-625`; `supersede.py:17-61`; `revision_validation.py:195-308`;
`compaction.py:678-737`; `canonical.py:10-54`; `record_text.py:15-32`;
`subject_ref.py:21-65`; `retrieval.py:124-126,159-178`; `temporal.py:
24-148`; `mcp.py:24-104`; `tests/test_reader_gate.py:38-43`) y los ADRs
0032/0033 y el cuerpo del issue #60. Las correcciones del intento 2
(`.reader-gate` effect, cursor/progreso, contenido de alternativas,
supersede cross-subject, namespaces históricos, concurrencia, digest no
autenticado) se verificaron **correctas**; no se reintrodujeron.

Hallazgos (1 HIGH, 4 MED, 5 LOW):

| # | Severidad | Hallazgo | Acción aplicada |
|---|---|---|---|
| H1 | HIGH | **Garantía de presupuesto no demostrable.** §5.3 paso 3b medía con "valor tentativo" sin especificar; el natural (total corriente) puede tener menos dígitos que el `budget_used_bytes` final (paso 5), haciendo el sobre final exceder `budget_bytes` por el delta de dígitos. La propiedad "bytes medidos ≤ presupuesto" era afirmación, no teorema. | §5.3 reescrito: paso 3a fija `budget_used_bytes` en cota superior `budget_bytes` (máximo dígitos posible); cadena demostrable añadida (`sobre_final ≤ sobre_medido_3b ≤ budget_bytes`). Alternativa de ancho fijo descartada por complejidad. |
| M1 | MED | **L1/L2 depende de la plataforma.** En non-fcntl, `shared_reader_gate` yields sin abrir gate (`reader_gate.py:72-76`); `.reader-gate` no se crea (L1 trivialmente cierto). En POSIX sí se crea (L1 falso). Q11 presentaba L1/L2 como elección global. | §3.7 añade nota condicionada por plataforma; Q11 reformulada (global vs. por plataforma); §13 y §10 actualizados. |
| M2 | MED | **Conteo `subjects_without_subject_ref` ambiguo.** D5 no especificaba si cuenta todos los registros sin `subject_ref` o sólo vigentes. | D5 congelado: cuenta TODOS sin `subject_ref` (vigencia irrelevante para el contador, que señala cobertura pre-subject_ref). |
| M3 | MED | **`inputs.streams` orden-sensible en digest del cursor.** `canonical_json` no reordena lists; `--streams events,facts` vs `--streams facts,events` romperían el cursor silenciosamente. | §5.2 `ih` normaliza `streams` al orden canónico del enum con dedup antes de digerir y computar. |
| M4 | MED | **`view_subject_exceeds_budget` terminal sin diagnóstico.** Consumidor no sabe cuál subject ni tamaño impidió caber; debe iterar a ciegas subiendo budget. | §13 lo declara como riesgo residual; Q12 pide al maintainer decidir terminal-sin-detalle vs `detail` con `subject_ref`+tamaño (dato `untrusted_memory_data`). |
| L1 | LOW | Forma de `supersede_link` en lado sucesor no especificada. | §7.1 congela forma simétrica `{stream, target_id, sustituida_por}` en ambos extremos; campo `succeeds` descartado. |
| L2 | LOW | `.reader-gate` excluido de exports no citado como evidencia L2. | §3.7 layer 2 cita `tests/test_reader_gate.py:38` (`..._ignored_by_export`). |
| L3 | LOW | `bare_digest` (`canonical.py:48-54`) disponible para validar `r`/`record_sha256`, no citado. | §5.2 indica reutilizar `bare_digest`. |
| L4 | LOW | Endurecimiento `O_NOFOLLOW`+`st_nlink!=1` del gate no mencionado. | §3.7 layer 2 documenta la defensa en profundidad (`reader_gate.py:39-47`). |
| L5 | LOW | Supersede es siempre intra-stream (`revision_validation.py:285`); D17 no lo explicitaba. | D17 y §7.1 aclaran que `stream` es compartido por ambos extremos del link. |

**Decisión final del spike (tras ronda 3):** `refine` se mantiene. La
ronda 3 no elevó a `proceed` porque Q11/Q12 siguen abiertas y la garantía
H1 —ahora demostrable— depende de la implementación que congele el ADR.
No hay BLOCKER residual; el HIGH H1 quedó cerrado contractualmente en el
informe. El gate G-VIEW-DOC puede abrir tras Q1–Q12.

**Cierre — comando → resultado real (ronda 3, post-correcciones):**

| Comando | Resultado |
|---|---|
| `git diff --check` | sin errores de whitespace (sin salida) |
| `git status --short` | sólo `?? docs/planning/issue-60-g-view-spike-2026-08-12.md` (único cambio rastreable = este informe) |
| `python3 scripts/check_sizes.py` | `check_sizes: OK — todos los archivos dentro del límite duro.` (`docs/planning/` está en `DOCS_HISTORICOS`, exento; `scripts/check_sizes.py:33`) |
| `python3 -m unittest discover -s tests -p 'test_*.py'` | Auditoría independiente final: `Ran 468 tests in 33.808s` / `OK` (sin tocar código; el informe no importa tests) |
| `wc -l docs/planning/issue-60-g-view-spike-2026-08-12.md` | 1267 líneas finales (incluye correcciones editoriales de auditoría del controlador) |

---

## Cierre

Este spike confirma que la pregunta central del issue #60 tiene respuesta
técnica viable con las decisiones D1–D18. El veredicto es `refine`, no
`proceed`, porque la frontera de pureza de lectura (§3.7), la semántica de
cursor/presupuesto (§5), la proyección de contenido (§7/D16) y el
agrupamiento cross-subject (§6.1/D17) son contractuales y deben cerrarse
en el ADR G-VIEW-DOC antes de cualquier línea de código (práctica §3).

No se modificaron archivos del repositorio salvo este informe. No se hizo
commit, push, PR, tag ni release. No se ejecutaron comandos mutativos de
AN-KLA. No se consultaron fuentes vivas durante el análisis del cálculo de
la vista (las verificaciones de `verify`/`context status`/`gh` son
preflight, no cálculo).
