# Plan: v0.1.0-beta.5 — fix #12 + decide #14

**Fecha:** 2026-08-04
**Targets:** cerrar issue #12 (target drift), implementar #14 opción C (indexable_text).

## Alcance

Bundle único beta.5 con:
- **#12:** transparencia de target drift en upgrade flow (ADR-0017).
- **#14 opción C:** campo explícito `indexable_text` en records.
- Sin cambios adicionales (no scope creep).

## #12 — Implementación siguiendo ADR-0017

### Archivos afectados

| Archivo | Cambio |
|---|---|
| `an_kla/upgrade.py` | `inspect_upgrade` añade `target_drift` al `core`. `apply_upgrade` declara `target_drift_absorbed`. `_validate_plan` acepta v1 y v2. |
| `an_kla/__main__.py` | Flag `--confirm-target-drift` en subcomando `upgrade apply`. |
| `an_kla/schemas/upgrade-plan-v1.schema.json` | Comentario "deprecated" en header. |
| `docs/schemas/upgrade-plan-v2.schema.json` | **Nuevo** schema con campo `target_drift` opcional. |
| `docs/schemas/README.md` | Añadir entrada upgrade-plan-v2. |
| `tests/test_upgrade.py` | 5 tests nuevos (matrix de ADR-0017). |

### Lógica de drift detection

```python
def _detect_target_drift(project_root, target):
    manifest = _load_manifest(project_root)
    if manifest is None:
        return {
            "outside_managed_block": False,
            "manifest_target_sha256_at_install": None,
            "observed_target_sha256": None,
            "managed_content_sha256": None,
            "will_be_absorbed_by_apply": False,
        }
    target_path = _target_path(_project_root(project_root), target)
    target_bytes, _ = _read_utf8(target_path)
    observed = _observed_sha(target_bytes)
    manifest_target = manifest.get("target_sha256")
    return {
        "outside_managed_block": manifest_target != observed,
        "manifest_target_sha256_at_install": manifest_target,
        "observed_target_sha256": observed,
        "managed_content_sha256": manifest.get("managed_content_sha256"),
        "will_be_absorbed_by_apply": manifest_target != observed,
    }
```

### CLI — fail-closed

```python
# __main__.py upgrade apply handler
if (
    plan["core"].get("target_drift", {}).get("outside_managed_block")
    and not args.confirm_target_drift
):
    raise ValueError("target_drift_requires_confirmation")
```

### Schema v2 — backwards compatibility

`_validate_plan` acepta v1 (sin `target_drift`) y v2 (con `target_drift`). La
fingerprint se calcula sobre `core` — añadir campo cambia fingerprint, pero
eso es esperado en un bump de versión.

## #14 — Opción C: campo `indexable_text`

### Decisión

Añadir convención: records pueden llevar campo `indexable_text` (opcional) que
`record_text()` prioriza sobre `text|render|summary|p`.

### Justificación (frente a A y B)

- **vs A (documentar):** A deja sin recuperación gran parte de la memoria
  estructurada (events/episodes con `outcome`, `lessons`, `type` pero sin
  `text`). Mala UX.
- **vs B (concatenar strings):** B indexa timestamps, ids, números — falso
  positivo alto. El writer pierde control.
- **C (explícito):** el writer declara qué quiere indexar. Schema-discoverable.
  No rompe records existentes (campo opcional).

### Implementación

`an_kla/index.py:record_text`:

```python
def record_text(record: dict[str, Any]) -> str:
    """Return the first supported non-empty string in normative priority.

    Priority: indexable_text > text > render > summary > p.
    `indexable_text` is the writer's explicit declaration of what FTS should
    index; the other fields are inspected as fallbacks.
    """
    payload = record.get("payload")
    containers = (payload, record) if isinstance(payload, dict) else (record,)
    for field in ("indexable_text", "text", "render", "summary", "p"):
        for container in containers:
            value = container.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(payload, str) and payload.strip():
        return payload.strip()
    return ""
```

### Schema bump

Sin bump formal de `an-kla/event-v1` / `an-kla/episode-v1` (no existen como
JSON Schema publicado en `docs/schemas/`). Convención documentada en:

- ADR-0018 (nuevo).
- `capabilities()` añade nota en `retrieval.indexable_text_field`.
- `AN-KLA.md` sección "## Flujo gobernado de escritura" mencionar campo.

### Tests

- `tests/test_index_streams.py::test_record_text_prefers_indexable_text`
- `tests/test_index_streams.py::test_record_text_falls_back_without_indexable_text`
- `tests/test_index_streams.py::test_rebuild_index_covers_records_with_indexable_text`

## Sequencing de commits

1. `feat(upgrade): expose target_drift in inspect and apply (#12)` — #12 fix
   + tests.
2. `feat(index): support explicit indexable_text field (#14)` — #14 fix +
   tests + ADR-0018.
3. `feat(release): bump TEMPLATE_VERSION to 0.1.0-beta.5` — version bump,
   contract update, release notes.
4. Tag `v0.1.0-beta.5` + GitHub Release.

## Cierre de issues

- `#12` se cierra cuando beta.5 se publique, con comentario linkando el
  commit y la sección del ADR-0017 finalizado.
- `#14` se cierra cuando beta.5 se publique, con comentario linkando el ADR-0018.
- `#10` queda abierto hasta validación externa de argos.

## Validación final

- Suite completa verde (175 tests existentes + 5 nuevos #12 + 3 nuevos #14 = 183).
- Smoke test: repro del bug #12 ahora falla cerrado sin `--confirm-target-drift`.
- Smoke test: registro con sólo `indexable_text` ahora se indexa.

## No incluye (out of scope)

- Helper CLI `build-proposal`/`build-authority` (mencionado en #10c) → beta.6.
- Auto-cierre de #10 sin validación externa.
- Migración asistida de records existentes a `indexable_text` (cada operador
  decide si reescribir).
