# Plan técnico — issue #59 `subject_ref` v1 (G-SUBJECT)

- **Estado:** propuesta operativa; no autoriza implementación por sí sola.
- **Fecha:** 2026-08-11 (retry adversarial documental).
- **Issue:** #59 · **ADR:** ADR-0033 (aceptada en HEAD `827f943`).
- **Base SHA:** `827f943dc7dfc8f1457e357f0053682fd2d91602`.
- **Serialización por defecto:** Fase 0 → A → B → C → D (→ E condicional).
- **Autoridad por defecto:** **read-only**. Editar, commit, push, PR, merge,
  bump, tag, cierre de issue y registro ADR requieren autorización separada.
- **CI remoto:** sin créditos; estado máximo `PARCIAL (ci-remoto-no-ejecutado)`.

## 1. Objetivo

Implementar el contrato `subject_ref` de ADR-0033: campo opcional
`record.subject_ref` con forma `an-kla:subject:v1:<kind>:<namespace>:<id>`,
namespace derivado del project-identity digest, validación pura de forma,
binding bajo `write_lock` con cero efectos en discrepancia, comando de
resolución `subject namespace` con schema versionado, y `record_validators`
aditivo en `capabilities()`. Los invariantes normativos vive en ADR-0033
§Decisión 1-12 y §Modelo de amenazas; este plan no los reescribe.

## 2. No-objetivos

G-VIEW (#60: vista, navegación de relaciones, proyección a schemas v2);
`relation` como kind; aliases como claves; namespace cross-project; migración
de namespaces tras reemplazo de anchor; exponer kinds/namespaces/`subject_view`
en `capabilities()`. Publicar, bumpar o tagear sin autorización separada.

## 3. Arquitectura sin ciclos

DAG de dependencia unidireccional. Imports concretos por módulo:

```
canonical.py       ← hoja (sin imports internos)
subject_ref.py     ← importa: canonical.digest_bytes
                       define: SUBJECT_REF_PATTERN, SubjectRefError,
                                parse_subject_ref(), derive_namespace()
                       NO importa write_policy/store/identity.
write_policy.py    ← importa: subject_ref.parse_subject_ref,
                                subject_ref.SubjectRefError
                       (NO importa SUBJECT_REF_PATTERN; la única regex
                        compilada vive en subject_ref.py)
subject_binding.py ← importa: subject_ref.parse_subject_ref,
                                subject_ref.derive_namespace,
                                write_policy.WritePolicyError
supersede.py       ← importa: write_policy.WritePolicyError
store.py           ← importa: supersede.resolve_supersede_targets,
                                subject_binding.check_subject_ref_binding,
                                write_policy.* (existente), identity.* (existente)
subject.py         ← importa: subject_ref.derive_namespace,
                                identity.identity_status, identity.read_binding
__main__.py        ← importa: subject.resolve_namespace (más imports CLI existentes)
```

**Regla:** ningún módulo importa a otro que lo importa a él. `subject_ref.py`
es hoja; todos los demás consumen hacia abajo. `write_policy.py` **no** importa
`SUBJECT_REF_PATTERN` ni compila regex propia: delega el parsing a
`parse_subject_ref` y traduce `SubjectRefError` →
`WritePolicyError("invalid_write_proposal", "record.subject_ref")`. La única
`re.compile(SUBJECT_REF_PATTERN)` vive en `subject_ref.py`.

**Sin `split(':')[-2]` desnudo:** `parse_subject_ref` valida estructura vía
regex antes de separar componentes. La regex garantiza **exactamente 6**
componentes (`an-kla`, `subject`, `v1`, kind, namespace, id); tras `fullmatch`,
se hace unpacking posicional de los 6 — no indexación `[-2]` ni asunción
`≥6`. Malformado produce `SubjectRefError` (mensaje estable), nunca
`IndexError`.

## 4. Fases y ownership

| Archivo | Fase | Acción |
|---|---|---|
| `an_kla/supersede.py` | **0** | nuevo (extracto de store.py) |
| `an_kla/store.py` | **0, B** | 0: reemplaza bloque por call; B: añade call a `check_subject_ref_binding` |
| `an_kla/subject_ref.py` | **A** | nuevo (puro) |
| `an_kla/subject_binding.py` | **A** | nuevo (puro) |
| `an_kla/write_policy.py` | **A** | edita |
| `docs/schemas/write-proposal-v1.schema.json` | **A** | edita |
| `an_kla/schemas/write-proposal-v1.schema.json` | **A** | edita (byte-idéntica) |
| `tests/test_subject_ref.py` | **A** | nuevo |
| `tests/test_subject_binding.py` | **A** | nuevo |
| `tests/test_write_policy.py` | **A** | edita |
| `tests/test_store.py` | **0, B** | 0: sin cambios (gate baseline); B: nuevos |
| `an_kla/subject.py` | **C** | nuevo |
| `docs/schemas/subject-namespace-result-v1.schema.json` | **C** | nuevo |
| `an_kla/schemas/subject-namespace-result-v1.schema.json` | **C** | nuevo (byte-idéntica) |
| `an_kla/schemas/__init__.py` | **C** | edita (registra schema) |
| `an_kla/__main__.py` | **C** | edita (CLI) |
| `tests/test_agent_contracts.py` | **C→D** | edita (C: schema catalog; D: capabilities); **secuencial C antes que D** |
| `tests/test_subject_cli.py` | **C** | nuevo |
| `an_kla/capabilities.py` | **D** | edita |
| `tests/test_agent_contracts.py` | **C→D** | (ver fila C arriba; mismo archivo, secuencial) |
| `docs/write-policy-cli.md`, guía de usuario | **D** | edita |
| `an_kla/version.py`, `CITATION.cff`, `README.md`, release notes, adversarial | **E** | bloqueados (autorización separada) |

Dos fases no editan el mismo archivo en paralelo. `store.py` se edita en 0 y B
**secuencialmente**. `test_store.py` y `test_agent_contracts.py` se editan en
fases distintas también secuenciales. Dependencias: 0→B, A→B, A→C, B+C→D,
D→E (condicional). C no depende de B pero se serializa por auditabilidad.

---

## 5. Fase 0 — Refactor previo (behavior-preserving)

- **Riesgo:** R3 (toca `store.py`; 797/800 líneas).
- **Objetivo:** liberar margen en `store.py` extrayendo el bloque de resolución
  supersede (`store.py:364-404`, ~41 líneas) a `an_kla/supersede.py`.
- **Dependencias:** tarjeta y autoridad separada; baseline verde.
- **Archivos permitidos:** `an_kla/supersede.py` (nuevo), `an_kla/store.py`,
  `tests/test_store.py` o `tests/test_supersede.py` para los characterization
  tests obligatorios; además, suite completa verde antes y después.

### Extracción candidata

`resolve_supersede_targets(store, checked_plan, observed) -> list[dict[str,
str]]`: toma `store` (para `snapshot`), el plan verificado y la revisión
observada; devuelve `pending_supersedes` o levanta `WritePolicyError` (mismos
códigos `invalid_supersede_target` con mismos details). Precedente formal:
`assert_unchanged(store, ...)` (`identity.py:174`), mixins existentes
(`compaction_store_mixin.py`, `refute_store_mixin.py`). `store.py` reemplaza
las ~41 líneas por una llamada de una línea.

### Invariantes behavior-preserving

- Mismos inputs → mismos outputs → mismos errores (códigos y details estables).
- Misma semántica de lock (se llama dentro de `write_lock`, después de
  `assert_unchanged` y `verify_write_plan`).
- Misma orden de fallos: CAS → identity → policy → supersede → (binding en B).
- `snapshot(observed)` se llama sólo si hay items con `operation=supersede`.

### Tests (characterization obligatorios)

La baseline sola no basta: se congelan los contratos del bloque antes de
extraerlo para que la extracción sea verificable como behavior-preserving.

`tests/test_store.py` (o `tests/test_supersede.py`):
- `test_supersede_resolution_freezes_error_codes_and_details` — para target
  self-ref/missing/not-vigente: `code="invalid_supersede_target"` con details
  `"self_reference"`, `"target_missing"`, `"target_not_vigente"` (exactos).
- `test_supersede_resolution_order_under_lock` — el bloque corre después de
  CAS (`write_plan_base_changed`), `assert_unchanged` y `verify_write_plan`, y
  antes de la construcción de `pending`.
- `test_snapshot_called_only_when_supersede_present` — `snapshot(observed)` no
  se llama si ningún item tiene `operation=supersede`.
- `test_supersede_commit_effects_stable_across_refactor` — mismo plan fijo
  (supersede válido): revisión resultante, estado de vigencia del target
  (`sustituida`), snapshot y efectos observables (objetos, journal, CURRENT)
  son idénticos antes (inline en `store.py`) y después (call a `supersede.py`).

Estos tests se escriben **antes** de extraer (contra `store.py` inline), se
mantienen verdes tras la extracción (contra `supersede.py`), y perduran como
regresión.

### DoD

- `store.py` ≤ 765 líneas (umbral duro del maintainer).
- `python3 -m unittest discover -s tests -p 'test_*.py'` → conteo incrementado
  por los characterization tests, sin fallos ni skips nuevos.
- `check_sizes.py` OK.

### Stop conditions

- Algún test existente cambia de resultado (rompería behavior-preserving).
- `supersede.py` importa de un módulo que crearía ciclo.
- La extracción cambia el orden de fallos o la semántica de lock.
- `store.py` > 765 líneas tras la extracción → **stop/escalate**.
  Cualquier declaration TECH_DEBT requiere issue nombrado + autoridad separada;
  no es salida automática de esta fase.

### Adversarial: obligatoria (toca `store.py`). Sin `proceed` no mergeea.

---

## 6. Fase A — Contrato puro

- **Riesgo:** R3 (toca `write_policy.py`; cambia `policy_fingerprint()`).
- **Dependencias:** ADR-0033 aceptada.
- **Archivos permitidos:** `an_kla/subject_ref.py` (nuevo),
  `an_kla/subject_binding.py` (nuevo), `an_kla/write_policy.py`,
  `docs/schemas/write-proposal-v1.schema.json`,
  `an_kla/schemas/write-proposal-v1.schema.json`, `tests/test_subject_ref.py`
  (nuevo), `tests/test_subject_binding.py` (nuevo),
  `tests/test_write_policy.py`.

### Implementación

**`an_kla/subject_ref.py`** (~60 líneas, puro):

- `SUBJECT_REF_PATTERN`: raw string anclada `^...$` con enum de 11 kinds
  embebido (definición normativa en ADR-0033 §Decisión 1). Sin backslashes →
  idéntica byte a byte como string Python y como valor JSON `pattern`.
- `class SubjectRefError(ValueError)`: `code` estable (`"invalid_subject_ref"`);
  `detail` evolutivo. Análogo a `TemporalError` (`temporal.py:33`).
- `parse_subject_ref(value) -> dict`: valida vía
  `re.compile(SUBJECT_REF_PATTERN).fullmatch(value)`; si falla →
  `SubjectRefError`. Si pasa, la regex garantiza exactamente 6 componentes;
  unpacking posicional (`_, _, _, kind, namespace, id = value.split(":")`)
  y devuelve `{"kind": ..., "namespace": ..., "id": ...}`.
- `derive_namespace(project_bytes: bytes) -> str`: devuelve
  `"p-" + digest_bytes(project_bytes)[7:39]` (128 bits de entropía; ADR-0033
  §Decisión 2).
- Imports: `re`, `.canonical.digest_bytes`. **No** importa write_policy/store/identity.

**`an_kla/subject_binding.py`** (~25 líneas, puro):

- `check_subject_ref_binding(checked_plan: Mapping, binding: Mapping) -> None`:
  para cada `item` en `checked_plan["records"]` cuyo `record` tenga
  `subject_ref`, llama `parse_subject_ref` (estable, no IndexError), compara
  `parsed["namespace"]` contra `derive_namespace(binding["project_bytes"])`;
  discrepancia → `WritePolicyError("subject_ref_namespace_mismatch")`.
  Registros sin `subject_ref` → no-op. Pure: no lee store ni reloj.
- Imports: `.subject_ref` (parse_subject_ref, derive_namespace, SubjectRefError)
  + `.write_policy.WritePolicyError`.

**`an_kla/write_policy.py`**:

- `from .subject_ref import parse_subject_ref, SubjectRefError`.
  **No** importar `SUBJECT_REF_PATTERN`; la única compilación de regex vive en
  `subject_ref.py`. No añadir `_SUBJECT_REF` ni ninguna regex duplicada.
- Registrar `"subject_ref": "an-kla-subject-ref/v1"` en
  `_POLICY_CONFIGURATION["record_validators"]` (`:84`).
- Añadir `"subject_ref_namespace_mismatch"` a
  `_POLICY_CONFIGURATION["terminal_error_codes"]` (`:68-78`) en orden alfabético.
- En `validate_write_proposal`, después de la rama `verified_at` (`:212-216`):
  `if "subject_ref" in record:` → intentar `parse_subject_ref(record["subject_ref"])`;
  capturar `SubjectRefError` → `raise WritePolicyError("invalid_write_proposal",
  "record.subject_ref") from exc`.

**Schemas** (byte-idénticos docs/ y an_kla/): añadir `subject_ref` bajo
`properties.record.properties` (hermano de `verified_at`) con
`{"type": "string", "pattern": "<SUBJECT_REF_PATTERN>"}`. `record` permanece
abierto (sin `additionalProperties:false`).

### Una sola regex (3 ubicaciones)

`SUBJECT_REF_PATTERN` se define **una vez** en `subject_ref.py`. El `pattern`
del JSON Schema en ambas copias debe ser el mismo string. Como no contiene
backslashes, no hay ambigüedad de escaping. Test de igualdad:

```text
test_subject_ref_pattern_identical_in_code_and_both_schemas:
  1. from an_kla.subject_ref import SUBJECT_REF_PATTERN
  2. pattern_docs = json.loads(read("docs/schemas/write-proposal-v1.schema.json"))["properties"]["record"]["properties"]["subject_ref"]["pattern"]
  3. pattern_pkg  = schema_document("write-proposal-v1")[...mismo path...]
  4. assert pattern_docs == SUBJECT_REF_PATTERN
  5. assert pattern_pkg  == SUBJECT_REF_PATTERN
```

### Tests rojos (`tests/test_subject_ref.py`, `tests/test_write_policy.py`)

Convención: todo test file nuevo empieza con newline tras imports y termina
con newline final (POSIX text file).

`tests/test_subject_ref.py`:
- `test_subject_ref_pattern_rejects_invalid` — parametrizado: None, 7, vacío,
  uppercase (`P-...`, `ACTOR`), no-ASCII, `:` extra, namespace 33/31 hex,
  `P-...`, hex `g-z`, versión `v2`, kind fuera de enum, longitud > 129 bytes,
  `/ \` `@` `?` `#` espacio en id, **`<subject_ref_válido> + "\n"`**
  (newline trailing), **`"\n" + <subject_ref_válido>`** (newline leading).
  La regex `fullmatch` rechaza ambos: `\n` no está en el alfabeto permitido.
- `test_subject_ref_pattern_accepts_valid` — un valor well-formed por kind.
- `test_parse_subject_ref_returns_typed_components` —
  `{kind, namespace, id}` correctos.
- `test_parse_subject_ref_malformed_raises_subject_ref_error` — no IndexError.
- `test_derive_namespace_matches_project_bytes_digest` —
  `"p-" + digest_bytes(project_bytes)[7:39]`.
- `test_subject_ref_pattern_identical_in_code_and_both_schemas` — § arriba.
- `test_subject_ref_does_not_import_write_policy_or_store` —
  inspección de módulo (AST o `sys.modules`) verifica ausencia de import cycle.

`tests/test_write_policy.py`:
- `test_invalid_subject_ref_rejected_via_validate_write_proposal` —
  `validate_write_proposal` con `record.subject_ref` malformado →
  `WritePolicyError(code="invalid_write_proposal", detail="record.subject_ref")`.
  Incluye casos newline: `<subject_ref_válido> + "\n"` y
  `"\n" + <subject_ref_válido>` → mismo code/detail.
- `test_subject_ref_validator_registered_in_record_validators`.
- `test_subject_ref_and_terminal_code_freeze_policy_fingerprint` —
  nuevo golden (medir tras implementar; no adivinar).
- `test_subject_ref_not_in_self_asserted_authority_keys`.
- `test_subject_ref_does_not_elevate_authority` — `unresolved` → skip igual.
- `test_subject_ref_persists_verbatim_in_plan`.
- Actualizar `test_policy_fingerprint_binds_reason_and_terminal_code_catalogs`
  (10 códigos, orden alfabético: `subject_ref_namespace_mismatch` entre
  `invalid_write_proposal` y `write_content_hash_mismatch`).
- `test_beta11_valid_plan_fails_with_policy_fingerprint_mismatch` —
  plan con fingerprint pre-A stale → `write_policy_fingerprint_mismatch`.

### Tests rojos de binding (`tests/test_subject_binding.py`)

- `test_check_binding_accepts_matching_namespace` — plan con `subject_ref`
  cuyo namespace == `derive_namespace(binding["project_bytes"])` → no levanta.
- `test_check_binding_rejects_mismatch` — namespace distinto →
  `WritePolicyError("subject_ref_namespace_mismatch")`; `str(exc) == code`.
- `test_check_binding_skips_records_without_subject_ref` — items sin
  `subject_ref` → no-op (no levanta, no valida).
- `test_check_binding_malformed_raises_write_policy_error_stable` —
  `subject_ref` malformado (vía binding) → `WritePolicyError` con code/detail
  estables. **No** propaga `SubjectRefError` crudo ni `IndexError`.

### Invariantes ADR-0033 cubiertos

§1 (forma canónica), §3 (ASCII reject-only), §4 (enum cerrado), §5 (pure),
§7 (opcional verbatim non-authority), §9 (terminal code nuevo).

### DoD

- Todos los tests de arriba pasan.
- `policy_fingerprint()` cambia; nuevo golden registrado.
- `evaluate_write` no lee estado (sólo regex fullmatch).
- Regex idéntica en las 3 ubicaciones.
- `subject_ref.py` no importa write_policy/store/identity.

### Comandos

Focales: `python3 -m unittest tests.test_subject_ref tests.test_subject_binding tests.test_write_policy -v`.
Suite + gates estándar (ver §13).

### Stop conditions

- `subject_ref.py` importa write_policy/store/identity (ciclo).
- `parse_subject_ref` puede levantar `IndexError` (split sin validar).
- `record` se cierra con `additionalProperties:false`.
- El `pattern` del JSON ≠ código.
- `evaluate_write` lee estado para validar `subject_ref`.

### Adversarial: obligatoria (toca `write_policy.py`). Sin `proceed` no mergeea.

---

## 7. Fase B — Binding bajo lock

- **Riesgo:** R3 (toca `store.py`; concurrencia; cero efectos).
- **Dependencias:** Fase A (`subject_binding.check_subject_ref_binding`) + Fase 0
  (margen en `store.py`).
- **Archivos permitidos:** `an_kla/store.py` (un call site), `tests/test_store.py`.

### Implementación

En `commit_write_plan` (`store.py:307`), **después** del bloque supersede (que
tras Fase 0 es una llamada a `resolve_supersede_targets`) y **antes** de
construir `pending` (`store.py:406`). El import va a **nivel de módulo** (con
los demás imports de `store.py`); el call site va bajo `write_lock`, separado:

```python
# a nivel de módulo, junto al resto de imports:
from .subject_binding import check_subject_ref_binding

# dentro de commit_write_plan, bajo write_lock:
check_subject_ref_binding(checked_plan, binding)
```

No usar import function-local. `binding` es el capturado por `mutation_preflight` (`store.py:319`) y
revalidado por `assert_unchanged` (`store.py:325`). **No** se relee
project-identity fuera del binding (patrón `compaction.py:59,167`).

**Orden de fallos bajo lock:**

1. `write_plan_base_changed` (CAS).
2. `IdentityError("store_identity_changed")` vía `assert_unchanged` (TOCTOU).
3. `verify_write_plan` (fingerprint, hashes).
4. `invalid_supersede_target` (resolución de target).
5. **`subject_ref_namespace_mismatch`** (nuevo; binding de namespace).
6. Construcción de `pending` y commit.

Si la identidad migró entre `subject namespace` y commit, el paso 2 falla
**primero**; el caller nunca ve mismatch por TOCTOU.

### Tests rojos (`tests/test_store.py`)

- `test_commit_accepts_matching_subject_ref_namespace` — namespace correcto →
  commit OK; record persiste verbatim.
- `test_commit_rejects_mismatch_with_zero_effects` — namespace incorrecto →
  `subject_ref_namespace_mismatch`; cero objetos/journal/CURRENT (comparar
  counts antes/después).
- `test_mismatch_analogous_to_supersede_target_missing` — mismo post-estado.
- `test_binding_check_after_assert_unchanged` — identidad migrada →
  `store_identity_changed` antes que mismatch.
- `test_binding_check_after_verify_write_plan` — fingerprint stale → mismatch
  fingerprint antes que binding.
- `test_record_without_subject_ref_commits_unchanged` (legacy).
- `test_multiple_records_each_checked`.

### DoD

- Tests de arriba pasan.
- `store.py` crece sólo el call site + import (~3 líneas); ≤ 800.
- Orden de fallos del § arriba verificado.
- `check_sizes.py` OK.

### Comandos

Focales: `python3 -m unittest tests.test_store -v`. Suite + gates estándar (§13).

### Stop conditions

- `store.py` excede 800 → **stop/escalate**. Cualquier TECH_DEBT requiere issue
  + autoridad separada; no es salida automática de la fase.
- Binding check antes de `assert_unchanged` (rompe TOCTOU).
- Relee project-identity fuera del binding.
- Fallo deja efectos parciales.

### Adversarial: obligatoria (toca `store.py`). Sin `proceed` no mergeea.

---

## 8. Fase C — Resolución observable completa

- **Riesgo:** R2 (nuevo módulo, schema, CLI; sin mutaciones, sin lock).
- **Dependencias:** Fase A (`subject_ref.derive_namespace`); **no** depende de B.
- **Archivos permitidos:** `an_kla/subject.py` (nuevo),
  `docs/schemas/subject-namespace-result-v1.schema.json` (nuevo),
  `an_kla/schemas/subject-namespace-result-v1.schema.json` (nuevo, byte-idéntica),
  `an_kla/schemas/__init__.py`, `an_kla/__main__.py`,
  `tests/test_agent_contracts.py`, `tests/test_subject_cli.py` (nuevo).

El comando y el schema aterrizan juntos para respetar ADR-0033 §10 (no existen
comandos sin schema ni schemas sin comando). Fase C posee
`tests/test_agent_contracts.py` porque registra el schema en el catálogo.

### Schema `subject-namespace-result-v1` (cerrado, condicional)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:an-kla:schema:subject-namespace-result:v1",
  "title": "AN-KLA SubjectNamespaceResult v1",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema", "result", "namespace"],
  "properties": {
    "schema": {"const": "an-kla/subject-namespace-result-v1"},
    "result": {"enum": ["namespace_available", "namespace_unavailable"]},
    "namespace": {"type": ["string", "null"]}
  },
  "allOf": [
    {
      "if": {"properties": {"result": {"const": "namespace_available"}}, "required": ["result"]},
      "then": {"properties": {"namespace": {"type": "string", "pattern": "^p-[0-9a-f]{32}$"}}}
    },
    {
      "if": {"properties": {"result": {"const": "namespace_unavailable"}}, "required": ["result"]},
      "then": {"properties": {"namespace": {"type": "null"}}}
    }
  ]
}
```

`namespace` disponible → string con pattern `^p-[0-9a-f]{32}$`; no disponible →
`null`. No expone `project_identity_sha256` (ADR-0033 §10/M1).

### `an_kla/subject.py` (~40 líneas)

`resolve_namespace(store) -> dict`:
1. `status = identity_status(store)` (sin `include_ids`).
2. Si `status["identity_status"] != "complete"` →
   `{"schema": "an-kla/subject-namespace-result-v1", "result":
   "namespace_unavailable", "namespace": None}`.
3. Si `complete`: intentar `binding = read_binding(store)`. Si levanta
   `IdentityError` (catálogo controlado: `project_identity_missing`,
   `project_identity_invalid`, `store_identity_missing`,
   `store_identity_invalid`, `project_identity_mismatch`) →
   `namespace_unavailable`/exit 3 (la identidad migró entre las dos lecturas).
   Cualquier excepción que **no** sea `IdentityError` (`IntegrityError`,
   `StoreError`, `OSError`, etc.) —tanto de `identity_status` como de
   `read_binding`— **no se captura** en `resolve_namespace`: propaga al handler
   general del CLI (`__main__.py:530`): stderr saneado + exit 1.
4. `namespace = derive_namespace(binding["project_bytes"])` →
   `{"schema": ..., "result": "namespace_available", "namespace": namespace}`.

Sin `write_lock`, sin crear `.an-kla/`, sin mutar `CURRENT`. Imports:
`.subject_ref.derive_namespace`, `.identity.identity_status/read_binding`.

### CLI (`__main__.py`)

Subparser top-level `subject` con subcommand `namespace`. Dispatch:
`resolve_namespace(store)` → `canonical_json` a stdout. Exit 0 si available,
exit 3 si unavailable (stderr vacío). `OSError`/inesperado → handler general
(`:530`): stderr saneado + exit 1.

### Tabla de estados y exit codes

| `identity_status` | `result` | `namespace` | exit |
|---|---|---|---|
| `complete` | `namespace_available` | `p-<32hex>` | 0 |
| `absent`/`legacy_unadopted`/`intent_only`/`store_only`/`project_only`/`partial_consistent`/`identities_ready_root_pending`/`conflict` | `namespace_unavailable` | `null` | 3 |
| `IdentityError` de `read_binding` tras `complete` (catálogo §arriba) | `namespace_unavailable` | `null` | 3 |
| `IntegrityError`/`StoreError`/`OSError`/no-`IdentityError` | n/a | n/a | 1 |

**Error layering** (jerarquías no se mezclan): `IdentityError(RuntimeError)`
(`identity.py:32`), `StoreError(RuntimeError)` (`store.py:53`),
`IntegrityError(StoreError)` (store), `WritePolicyError(ValueError)`
(`write_policy.py:89`). El CLI captura todas en el handler (`:530`).
`resolve_namespace` **sólo** captura `IdentityError` del catálogo controlado
(paso 3) → exit 3. `IntegrityError`, `StoreError`, `OSError` y cualquier otra
excepción de `identity_status` o `read_binding` no se capturan → handler
general exit 1.

### Tests rojos

`tests/test_subject_cli.py`:
- `test_namespace_available_exit_0_when_complete` — stdout JSON canónico;
  stderr vacío.
- `test_namespace_unavailable_exit_3_for_each_non_complete_state` —
  parametrizado (8 estados).
- `test_no_an_kla_dir_exit_3` — root sin `.an-kla/` → exit 3, sin crear dir.
- `test_oserror_exit_1`.
- `test_integrity_error_exit_1` — `IntegrityError`/`StoreError` desde
  `identity_status` o `read_binding` → exit 1 (no capturado por
  `resolve_namespace`, va al handler general).
- `test_does_not_mutate_current`.
- `test_outputs_validate_against_draft_2020_12` — validar stdout real contra
  `subject-namespace-result-v1` con `jsonschema.Draft202012Validator` si
  disponible, `skipTest` si no (precedente `test_evaluation_v2.py:237-241`).

`tests/test_agent_contracts.py`:
- `test_schema_catalog_includes_subject_namespace_result_v1` — el catálogo
  enumera el schema nuevo con digest.
- Actualizar `expected_names` (o equivalente) en el orden exacto de
  `schema_names()` (`sorted`); los tests existentes del catálogo deben
  mantenerse verdes.

### DoD

- Tests de arriba pasan.
- `resolve_namespace` no adquiere `write_lock`, no crea `.an-kla/`.
- Schema registrado en `schema_catalog()`; presente byte-idéntico en docs/ y
  an_kla/.
- `python3 -m an_kla schema show subject-namespace-result-v1` funciona.
- `__main__.py` ≤ 800.

### Comandos

Focales: `python3 -m unittest tests.test_subject_cli tests.test_agent_contracts -v`.
Suite + gates + `check_clean_wheel.py` (schema nuevo en wheel; §13).

### Stop conditions

- `resolve_namespace` adquiere lock o crea `.an-kla/`.
- Resultado expone `project_identity_sha256`.
- CLI acepta flags de escritura.
- Schema no usa `allOf/if-then` o no se registra en el catálogo.

### Adversarial: revisión ligera pero explícita (contrato observable nuevo). Sin `proceed` no mergeea.

---

## 9. Fase D — Capabilities + documentación

- **Riesgo:** R2.
- **Dependencias:** Fases B + C mergeadas.
- **Archivos permitidos:** `an_kla/capabilities.py`,
  `tests/test_agent_contracts.py`, `docs/write-policy-cli.md`,
  guía de usuario.

### `capabilities()` — `record_validators` como mapping

Decisión con evidencia: exponer **mapping validator→tag** (no sólo claves):

```python
"record_validators": dict(policy["record_validators"]),
```

→ `{"subject_ref": "an-kla-subject-ref/v1", "verified_at": "an-kla-verified-at/v1"}`

`policy["record_validators"]` ya es un dict detached (la propia
`policy_configuration()` hace `deepcopy` del `_POLICY_CONFIGURATION` subyacente,
`write_policy.py:105-108`); `dict(...)` crea una copia superficial suficiente
para serialización. No se necesita `sorted(...)`: el determinismo contractual
proviene de `canonical_json` (`sort_keys=True`, `canonical.py:14`), que ordena
las claves al serializar independientemente del orden de inserción. Dos
invocaciones de `capabilities()` producen JSON canónico idéntico. El mapping ya
vive en `_POLICY_CONFIGURATION` (bound por `policy_fingerprint()`); exponerlo es
información aditiva, no un binding nuevo. No exponer kinds, namespaces ni
`subject_view`.

### Tests

- `test_capabilities_exposes_record_validators_mapping` — claves y valores
  exactos; sin `subject_view`/kinds/namespaces.
- `test_capabilities_deterministic` — dos llamadas → JSON canónico idéntico.

### Documentación

`docs/write-policy-cli.md`: documentar `subject_ref` opcional, flujo `subject
namespace` → `plan-write` → `commit-write-plan`, exit 3 sin namespace. Guía de
usuario: ejemplo de escritura con `subject_ref`.

### DoD

- Tests de arriba pasan.
- `capabilities()` actualizada; fingerprint reflejado desde Fase A.
- Docs coherentes.

### Comandos

Focales: `python3 -m unittest tests.test_agent_contracts -v`.
Suite + gates + `check_clean_wheel.py` (§13).

### Adversarial: revisión ligera pero explícita. Sin `proceed` no mergeea.

---

## 10. Fase E — Release condicional

- **Sólo con tarjeta instanciada y autorización separada** del maintainer.
- **Número/VERSION/TAG no decididos** en este plan. Se usan placeholders
  `<TAG>`/`<VERSION>` hasta que el maintainer fije el candidato.
- **Acciones que requieren autoridad separada:** bump de `version.py`,
  `<TAG>`, notas de release, actualización del registro ADR en `docs/README.md`
  (columna "Vigencia o evidencia"), `CITATION.cff`, `README.md` y cierre del
  issue #59.
- **Adversarial pre-release adicional** (obligatoria para tocar `store.py`/\
  `write_policy.py`): cubre las 4 fases de código sobre `main` + invariantes
  ADR-0033 §"Test de regresión". Sin `proceed` no se tagea.

---

## 11. Concurrencia / TOCTOU

`commit_write_plan` adquiere `write_lock` (`store.py:321`); el binding check
se ejecuta dentro del lock, después de `assert_unchanged` (`store.py:325`).
Si la identidad migra entre la consulta `subject namespace` (sin lock) y el
commit (con lock), `assert_unchanged` detecta el cambio de bytes y lanza
`IdentityError("store_identity_changed")` (`identity.py:184`) **antes** del
binding. El lock es local (fcntl/msvcrt); no hay exclusión mutua entre
máquinas. El binding se deriva del `binding["project_bytes"]` capturado por
`mutation_preflight` (`identity.py:613-619`) y revalidado por
`assert_unchanged`, no se relee fuera del lock. `subject namespace` no adquiere
lock; el drift entre `identity_status` y `read_binding` se mapea a
`namespace_unavailable` (fail-closed); el commit revalida bajo lock.

## 12. Compatibilidad

Legacy sin `subject_ref`: ninguno (record abierto). `supersede`: ninguno (keyed
por target_id físico). `refute`: ninguno (`target_record_sha256` físico,
`refutations.py:198-204`). `compaction`: `subject_ref` viaja verbatim sin
interpretación. `export/restore`: preserva `subject_ref` y namespace
(project-identity byte-idéntico); si anchor se reemplaza, históricos retienen
namespace anterior (ADR-0033 §12). `retrieve`/MCP/assembly v2: sin proyección
(schemas cerrados; G-VIEW v3). `capabilities()`: aditivo mapping (Fase D).
`policy_fingerprint()`: cambia en Fase A; planes stale → `write_policy_fingerprint_mismatch`;
replan vía `plan-write`; sin migración de datos persistente.

## 13. CI local, wheel y CI remoto

Suite + gates estándar (toda fase con código): `python3 -m unittest discover -s
tests -p 'test_*.py'`; `python3 scripts/check_sizes.py`; `python3
scripts/check_adr_registry.py`; `python3 scripts/ci_local.py --simulate-ci`
(GITHUB_ACTIONS=true + CI=true); `git diff --check`. Fases C y D añaden
`python3 scripts/check_clean_wheel.py` (schema/código en wheel). `ci_local.py`
no sustituye la matriz 3 SO × 2 Python del CI remoto. Mientras Billing esté
bloqueado, estado máximo `PARCIAL (ci-remoto-no-ejecutado)`. Para cada SHA
candidato se registra SO, Python y output.

## 14. Git

- **Candidate SHA exacto probado:** cada fase prueba su candidate SHA con la
  batería completa; el SHA es inmutable.
- **Rebase/cherry-pick invalida toda evidencia:** tras cualquier rebase o
  cherry-pick, los SHAs cambian y toda la batería debe repetirse sobre el nuevo
  tip. No afirmar que rebase preserva SHA ni evidencia.
- **Tested merge SHA:** el integrador valida el merge SHA completo antes de que
  se convierta en base de la fase siguiente.
- Sin commit/push/PR/merge sin autorización vigente en la tarjeta.

## 15. Tarjeta instanciable

```markdown
# Task card — issue #59 Fase <0|A|B|C|D|E>

- Base SHA: <exacto; merge de fase anterior o 827f943 para Fase 0>
- Rama: codex/issue-59-phase-<X>
- Worktree absoluto: <ruta>
- Riesgo: R2|R3
- Objetivo único: <frase>
- No objetivos: <referenciar §2>
- Archivos permitidos: <del ledger §4>
- Archivos reservados: <del ledger §4>
- Ledger/owner/generación: <worktree> -> <agente> -> fase-<X>
- Invariantes: <referenciar ADR-0033 §Decisión + §Modelo de amenazas>
- Reproducción baseline: python3 -m unittest discover → <N> OK
- Test rojo: <nombres de §5-9, o NA justificado>
- Decisiones aceptadas / preguntas abiertas: <lista>
- Autoridad vigente / actor / vigencia: <quién/qué/cuándo>
- Editar: sí|no · Commit local: sí|no · Push: sí|no
- PR: sí|no · Issue mutation: sí|no (por acción) · Merge: sí|no
- Bump/tag/release: no (Fase E, autorización separada)
- Stop conditions: <§5-9 por fase>
- Comandos: <§5-9 por fase>
- Candidate SHA / tested merge SHA: <completar>
- Handoff RAG: OK|PARCIAL|BLOQ + comando→resultado
```

Sin campos instanciados el agente sólo hace exploración read-only.

## 16. Diferidos a G-VIEW (#60) y relacionados

| Item | Diferido a |
|---|---|
| Vista contextual por `subject_ref` | G-VIEW (#60) |
| Proyección a schemas v2 (retrieve/MCP/assembly) | G-VIEW v3 |
| `relation` como kind, endpoints, aliases | ADR posterior |
| Namespace cross-project, registry de authorities | ADR posterior (ADR-0031 G3/G4) |
| Migración/remapeo tras reemplazo de anchor | ADR posterior |
| Tratamiento de records históricos sin `subject_ref` en la vista | G-VIEW |
| Frescura por `subject_ref` (G-FRESH, #50) | post-G-VIEW |
| Revaluación #47 (churn de `id` físico) | post-G-VIEW |

`subject_ref` estabiliza la identidad contextual (#47); la vista G-VIEW la
consume sin navegar relaciones en v1.

## 17. Riesgos residuales

| Riesgo | Mitigación |
|---|---|
| Fase 0 deja `store.py` > 765 líneas | Stop/escalate antes de Fase B; no TECH_DEBT automático. |
| `policy_fingerprint()` rompe planes en vuelo | By design; replan sin migración. |
| Confused deputy: namespace de memoria | Binding falla cerrado; memoria no es autoridad. |
| Drift `subject namespace` vs commit | Fail-closed exit 3; commit revalida bajo lock. |
| Disclosure: correlación cross-store | Declarado (no privacidad; recomputable); no es path/URL/UUID crudo. |
| CI remoto sin créditos | `PARCIAL` explícito; evidencia local ligada al SHA. |

## 18. Verificación documental

Turno de planificación: sin código, schemas, tests, Git/GitHub, commits, PR,
release ni tag. Gates sobre `827f943`: `check_adr_registry.py` → OK (33 ADRs,
31 aceptadas, 2 propuestas); `check_sizes.py` → OK; `git diff --check` → limpio;
`unittest discover` → 401 tests OK; `gh issue view 59` → OPEN, 0 PRs.
Referencias verificadas: `store.py:319/321/325/364-404/406`,
`identity.py:32/174-192/184/613-619`, `write_policy.py:68-78/84/89/105-108/212-216`,
`canonical.py:10-17`, `compaction.py:59/167`, `refutations.py:198-204`,
`capabilities.py:141-158`, `__main__.py:530`, `test_evaluation_v2.py:237-241`.

## 19. Disposiciones del retry adversarial

IDs y severidades de la ronda; no renombrados.

| ID | Severidad | Hallazgo en plan v1 | Disposición |
|---|---|---|---|
| **B-1** | BLOCKER | Ownership: sin arquitectura modular; `SUBJECT_REF_PATTERN` inline en write_policy; helper de binding mezclado en `subject.py` con responsabilidades híbridas y dependencias en direcciones opuestas | DAG §3: `subject_ref.py` hoja pura, `subject_binding.py` separado, `subject.py` sólo resolución; imports concretos declarados por módulo |
| **B-2** | BLOCKER | La fase que registraba `subject-namespace-result-v1` no podía quedar verde: `SCHEMA_FILES` cambia `schema_names()`, pero `tests/test_agent_contracts.py` —con `expected_names` hardcodeado— estaba reservado a otra fase | Fase C posee schema, catálogo, CLI y `tests/test_agent_contracts.py`; actualiza `expected_names` y aterriza comando+schema juntos (§4, §8) |
| **B-3** | BLOCKER | Release: reserva concreta `beta.12`, archivos `v0.1.0-beta.12.md`, nodo TAG y `Closes #59` sin autoridad | Placeholders `<TAG>`/`<VERSION>` sólo en Fase E; bump/tag/release/cierre/registro ADR requieren autoridad separada |
| **H-1** | HIGH | Comando+schema: comando y schema vivían en fases separadas (violaba ADR-0033 §10: no comandos sin schema ni schemas sin comando) | Fase C los aterriza juntos |
| **H-2** | HIGH | Rondas adversariales: no se declaraba obligatoriedad ni cadencia por fase | Fase 0, A, B: obligatoria. C, D: revisión ligera explícita. E: adversarial pre-release adicional. Sin `proceed` no mergeea |
| **H-3** | HIGH | Git SHA: plan v1 afirmaba "rebase preserva commits" | Rebase/cherry-pick invalida toda evidencia; batería completa sobre nuevo tip; no afirmar que rebase preserva SHA |
| **H-4** | HIGH | Store size: `store.py` en 797/800; Fase B añadiría call site sin margen | Fase 0 extrae `supersede.py` (umbral ≤765); si >765 → stop/escalate (no TECH_DEBT automático) |
| **H-5** | HIGH | `split(':')[-2]` desnudo para extraer namespace → `IndexError` en malformado | `parse_subject_ref` con regex `fullmatch` que garantiza exactamente 6 componentes; unpacking posicional tras validación; `SubjectRefError` estable, nunca `IndexError` (§3, §6 Fase A) |
| **M-1** | MEDIUM | Schema condicional: `namespace: string\|null` sin condicional | `allOf`/`if-then`: `namespace_available` → `^p-[0-9a-f]{32}$`; `namespace_unavailable` → `null` |
| **M-2** | MEDIUM | Newline en datos: sin tests explícitos para `subject_ref` con `\n` embebido (trailing/leading) | Tests explícitos en `test_subject_ref_pattern_rejects_invalid` y vía `validate_write_proposal`: `<válido>+"\n"` y `"\n"+<válido>` → rechazo con code/detail estables |

### Hallazgo de audit (micro-retry, fuera de la ronda original)

**Import redundante / regex duplicada en `write_policy.py`** (no estaba en la
tabla original; detectado al auditar la disposición B-1): en el plan v2 (retry
anterior), `write_policy.py` aún importaba `SUBJECT_REF_PATTERN` desde
`subject_ref.py` y precompilaba `_SUBJECT_REF = re.compile(...)` a nivel
módulo — una segunda regex además de la que ya vive en `subject_ref.py`.
`write_policy.py` no usa `SUBJECT_REF_PATTERN` directamente: delega el parsing
a `parse_subject_ref` y traduce `SubjectRefError`.

**Disposición:** `write_policy.py` importa sólo `parse_subject_ref` y
`SubjectRefError`. No importa `SUBJECT_REF_PATTERN`, no compila regex propia.
La única `re.compile(SUBJECT_REF_PATTERN)` vive en `subject_ref.py`. Esto
elimina la duplicación y cierra el riesgo de drift entre dos compilaciones de
la misma regex. Corrección §3 (DAG con imports concretos) y §6 (Fase A) ya
reflejan esto.

## 20. Veredicto

**ready-for-focused-adversarial-plan-review.**

El plan cumple los 8 acuerdos del micro-retry: (1) write_policy importa sólo
`parse_subject_ref`+`SubjectRefError`, sin `SUBJECT_REF_PATTERN` ni regex
duplicada; (2) tests explícitos de newline-en-datos; (3) characterization tests
obligatorios en Fase 0; (4) error layering con catálogo explícito, sin
"esperado" ambiguo; (5) tabla §19 con IDs/severidades exactos + hallazgo de
audit separado; (6) conteo de líneas honesto sin reclamar exención de gate;
(7) TECH_DEBT no es salida automática en Fase 0 ni B; (8) DAG con imports
concretos en lista. Conserva topología 0→A→B→C→D→(E), release no decidido,
mapping capabilities, schema condicional `allOf` y Git SHA con invalidación.

**Decisiones que le pido al maintainer:**

1. Aprobar este plan como hoja de ruta (no autoriza implementación).
2. Confirmar que Fase 0 recibe tarjeta y autoridad separadas antes de A.
3. Confirmar mapping validator→tag en `capabilities()` (§9) vs lista de claves.
4. Fijar número/VERSION/TAG de Fase E cuando corresponda (no decidido aquí).
