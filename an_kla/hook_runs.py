"""hook_runs.py — registro de invocaciones de hooks del host (ADR-0047 §4).

Formato propio variante de `attest-receipt-v1` (misma mecánica:
canonical-json, HMAC-SHA256 con `attest.key`, escritura O_EXCL+fsync
content-addressed; NO consume tombstones ni quema nonces). Sólo el motor
acuña: la entrada nace cuando una acción corre con contexto de hook
explícito (`--on-behalf-of-hook <hook-id>`); una invocación plana no
escribe nada (ADR-0047 §4; goldens de no-escritura intactos).

`subject_digest` (congelado aquí): digest canónico del descriptor de lo
actuado — `{"kind": "revision", "value": <current>}` para `status` y
`checkpoint` (en commit, la revisión resultante); `{"kind": "query",
"query": <q>, "budget": <b>}` para `retrieve` y `assemble-context`.

Lectura (`read_verified_runs`): por entrada exige schema, claves exactas,
HMAC válido y binding de identidad vivo; entrada inválida jamás
contribuye al perfil y se reporta como `hook_run_invalid` sin filtrar
rutas. La verificación exige `attest.key`: sin llave, código
`attest_not_initialized`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .attest import (
    AttestError,
    SIGNATURE_PREFIX,
    _load_key,
    _write_exclusive,
)
from .canonical import canonical_json, digest_bytes, digest_json
from .host_hooks import ID_PATTERN, ACTIONS, TRIGGERS
from .identity import IdentityError, read_binding

RUNS_SCHEMA = "an-kla/hook-run-v1"
RUNS_RELATIVE = Path(".an-kla") / "hook-runs" / "runs" / "sha256"

_MAX_ENTRY_BYTES = 65536
_MAX_ENTRIES_SCANNED = 2000

_HOOK_RUN_KEYS = (
    "schema", "run_id", "hook_id", "trigger", "action", "exit_code",
    "subject_digest", "project_uuid", "store_identity",
    "adapter_fingerprint", "observed_at", "run_hmac",
)


class HookRunError(ValueError):
    """Entrada de hook-run inválida en la acuñación."""


def mint_hook_run(
    store: Any,
    *,
    hook_id: str,
    trigger: str,
    action: str,
    exit_code: int,
    subject: dict[str, Any],
    adapter_fingerprint: str | None = None,
    now: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Acuña y persiste la evidencia de una invocación de hook.

    Idempotente por `run_id`: el reintento del host con el mismo id
    reproduce contenido canónico idéntico y la re-escritura es no-op
    (O_EXCL). Invocaciones distintas -> `run_id` distinto -> nada se
    pierde en silencio.
    """
    if not isinstance(hook_id, str) or not ID_PATTERN.match(hook_id):
        raise HookRunError("hook_run_invalid_input")
    if trigger not in TRIGGERS or action not in ACTIONS:
        raise HookRunError("hook_run_invalid_input")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        raise HookRunError("hook_run_invalid_input")
    key = _load_key(store.project_root)
    binding = read_binding(store)
    entry = {
        "schema": RUNS_SCHEMA,
        "run_id": run_id or uuid.uuid4().hex,
        "hook_id": hook_id,
        "trigger": trigger,
        "action": action,
        "exit_code": exit_code,
        "subject_digest": digest_json(subject),
        "project_uuid": binding["store"]["project_uuid"],
        "store_identity": binding["store_identity"],
        "adapter_fingerprint": adapter_fingerprint,
        "observed_at": now or _utc_now(),
    }
    entry["run_hmac"] = SIGNATURE_PREFIX + hmac.new(
        key, canonical_json(entry), hashlib.sha256
    ).hexdigest()
    payload = canonical_json(entry) + b"\n"
    identifier = digest_bytes(payload)
    target = Path(store.project_root) / RUNS_RELATIVE / (
        identifier[len("sha256:"):] + ".json"
    )
    try:
        _write_exclusive(target, payload, 0o600)
    except FileExistsError:
        pass
    return {"run_id": entry["run_id"], "digest": identifier}


def read_verified_runs(
    store: Any,
    declared_ids: set[str] | frozenset[str] | None,
    *,
    key: bytes | None = None,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Lee y verifica `.an-kla/hook-runs/` sin mutar nada.

    Devuelve `(runs, degraded_codes, unknown_hook_ids)` con `runs`
    ordenado por `observed_at` descendente. Entradas inválidas o con
    binding ajeno no se sirven: quedan como `hook_run_invalid`. Sin
    llave del motor, la verificación es imposible -> código
    `attest_not_initialized` y lista vacía.
    """
    directory = Path(store.project_root) / RUNS_RELATIVE
    try:
        with os.scandir(directory) as scanner:
            names = sorted(entry.name for entry in scanner)
    except FileNotFoundError:
        return [], [], []  # sin runs todavía: lectura limpia, sin degradación
    except (NotADirectoryError, PermissionError, OSError):
        return [], ["hook_runs_unreadable"], []
    paths = [directory / name for name in names if name.endswith(".json")]
    truncated = len(paths) > _MAX_ENTRIES_SCANNED
    paths = paths[:_MAX_ENTRIES_SCANNED]
    if not paths:
        return [], ([] if not truncated else ["hook_runs_truncated"]), []
    try:
        signing_key = key if key is not None else _load_key(store.project_root)
    except AttestError:
        return [], ["attest_not_initialized"], []
    try:
        binding = read_binding(store)
    except IdentityError:
        return [], ["hook_runs_unreadable"], []

    runs: list[dict[str, Any]] = []
    degraded: list[str] = []
    if truncated:
        degraded.append("hook_runs_truncated")
    for path in paths:
        try:
            if path.stat().st_size > _MAX_ENTRY_BYTES:
                degraded.append("hook_run_invalid")
                continue
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            degraded.append("hook_run_invalid")
            continue
        if not isinstance(entry, dict) or set(entry) != set(_HOOK_RUN_KEYS):
            degraded.append("hook_run_invalid")
            continue
        if entry.get("schema") != RUNS_SCHEMA:
            degraded.append("hook_run_invalid")
            continue
        if not isinstance(entry.get("exit_code"), int) or isinstance(
            entry["exit_code"], bool
        ) or not 0 <= entry["exit_code"] <= 255:
            degraded.append("hook_run_invalid")
            continue
        try:
            datetime.strptime(entry["observed_at"], "%Y-%m-%dT%H:%M:%SZ")
        except (TypeError, ValueError):
            degraded.append("hook_run_invalid")
            continue
        expected_mac = SIGNATURE_PREFIX + hmac.new(
            signing_key,
            canonical_json({k: v for k, v in entry.items() if k != "run_hmac"}),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(entry["run_hmac"], expected_mac):
            degraded.append("hook_run_invalid")
            continue
        if (
            entry.get("project_uuid") != binding["store"]["project_uuid"]
            or entry.get("store_identity") != binding["store_identity"]
        ):
            degraded.append("hook_run_invalid")
            continue
        runs.append(entry)

    runs.sort(key=lambda item: item["observed_at"], reverse=True)
    known = set(declared_ids or ())
    unknown = sorted({r["hook_id"] for r in runs if r["hook_id"] not in known})
    return runs, degraded, unknown


def is_recent(observed_at: str, now: datetime | None) -> bool:
    """Recencia congelada (ADR-0047 §5): ventana de HOOK_RECENCY_HOURS."""
    from .integration import HOOK_RECENCY_HOURS

    try:
        moment = datetime.strptime(observed_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except (TypeError, ValueError):
        return False
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return (
        reference - moment <= timedelta(hours=HOOK_RECENCY_HOURS)
        and reference >= moment
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = [
    "RUNS_SCHEMA",
    "HookRunError",
    "is_recent",
    "mint_hook_run",
    "read_verified_runs",
]
