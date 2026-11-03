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
import re
import stat
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .attest import (
    AttestError,
    SIGNATURE_PREFIX,
    _fsync_dir,
    _load_key,
    custody_anchor,
    _write_exclusive,
)
from .canonical import canonical_json, digest_bytes, digest_json
from .custody import check_custody
from .host_hooks import ID_PATTERN, ACTIONS, TRIGGERS
from .identity import IdentityError, read_binding
from .store_errors import LockBusyError
from .store_locks import write_lock

RUNS_SCHEMA = "an-kla/hook-run-v1"
RUNS_RELATIVE = Path(".an-kla") / "hook-runs" / "runs" / "sha256"


def _runs_dir(store: Any) -> Path:
    # ADR-0048 F0-B: hook-runs travel with the vault (custody root).
    return custody_anchor(store) / RUNS_RELATIVE.relative_to(".an-kla")

_MAX_ENTRY_BYTES = 65536
_MAX_ENTRIES_SCANNED = 2000
_RUN_ID_MAX_LENGTH = 256

_HOOK_RUN_KEYS = (
    "schema", "run_id", "hook_id", "trigger", "action", "exit_code",
    "subject_digest", "project_uuid", "store_identity",
    "adapter_fingerprint", "observed_at", "run_hmac",
)

# Payload funcional del reintento (diseño 2026-11-02 §2): observed_at y
# run_hmac no participan de la comparación de deduplicación.
_FUNCTIONAL_FIELDS = (
    "hook_id", "trigger", "action", "exit_code", "subject_digest",
    "project_uuid", "store_identity", "adapter_fingerprint",
)
_CONTROL_CHARS = re.compile(r"[\x00-\x1f]")


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

    Camino B (`run_id` explícito), diseño 2026-11-02: idempotente por
    `run_id` — el reintento del host con el mismo id y el mismo payload
    funcional devuelve los bytes, digest y hora ORIGINALES (verificación
    y re-fsync en una sola apertura); payload funcional distinto falla
    cerrado (`hook_run_conflict`); duplicados históricos fallan cerrado
    (`hook_run_duplicate_evidence`). Bajo `write_lock(store.root)`
    directo (sin recrear layout), con revalidación de binding, custodia
    y llave dentro del lock.

    Camino A (`run_id` ausente, todo el CLI): uuid fresco, sin lock ni
    escaneo; publicación O_EXCL+fsync paso a paso como la vigente.

    Errores de custodia/identidad conservan sus tipos (`CustodyError`,
    `IdentityError`); la contención del lock se traduce a
    `HookRunError("hook_run_lock_busy")`; sin O_NOFOLLOW/O_NONBLOCK el
    camino B falla con `hook_run_platform_unsupported`.
    """
    _validate_input(hook_id, trigger, action, exit_code, subject,
                    adapter_fingerprint, run_id, now)
    if run_id is not None:
        # Delta de locks 2026-11-02: disponibilidad de flags obligatorios
        # verificada antes de cualquier efecto del camino B.
        _require_run_platform_flags()
    key = _load_key(store)
    binding = read_binding(store)
    check_custody(store, binding=binding)
    if run_id is None:
        entry = _new_entry(binding, key, hook_id, trigger, action, exit_code,
                           subject, adapter_fingerprint, uuid.uuid4().hex, now)
        return _publish(store, entry)
    try:
        # Do not call MemoryStore.write_lock: its layout creation can recreate
        # a relinquished vault during relocation. This lock opens existing root.
        with write_lock(store.root):
            binding = read_binding(store)
            check_custody(store, binding=binding)
            key = _load_key(store)
            entry = _new_entry(binding, key, hook_id, trigger, action, exit_code,
                               subject, adapter_fingerprint, run_id, now)
            matches = _find_runs(store, key, binding, run_id)
            if len(matches) > 1:
                raise HookRunError("hook_run_duplicate_evidence")
            if matches:
                path, original = matches[0]
                if any(original[k] != entry[k] for k in _FUNCTIONAL_FIELDS):
                    raise HookRunError("hook_run_conflict")
                _restore_durability(path, key, binding)
                return {"run_id": run_id, "digest": "sha256:" + path.stem}
            try:
                return _publish(store, entry, exclusive_retry=True,
                                key=key, binding=binding)
            except OSError as exc:
                raise HookRunError("hook_run_publication_uncertain") from exc
    except LockBusyError as exc:
        raise HookRunError("hook_run_lock_busy") from exc


def _validate_input(hook_id, trigger, action, exit_code, subject,
                    fingerprint, run_id, now):
    try:
        valid = (isinstance(hook_id, str) and ID_PATTERN.fullmatch(hook_id)
                 and isinstance(trigger, str) and trigger in TRIGGERS
                 and isinstance(action, str) and action in ACTIONS
                 and type(exit_code) is int and 0 <= exit_code <= 255
                 and isinstance(subject, Mapping)
                 and (fingerprint is None or isinstance(fingerprint, str)))
        if run_id is not None:
            valid = valid and (isinstance(run_id, str) and
                0 < len(run_id) <= _RUN_ID_MAX_LENGTH and
                not _CONTROL_CHARS.search(run_id))
        if now is not None:
            datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ")
        digest_json(dict(subject))
        if not valid:
            raise ValueError()
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise HookRunError("hook_run_invalid_input") from exc


def _new_entry(binding, key, hook_id, trigger, action, exit_code,
               subject, fingerprint, run_id, now):
    entry = dict(schema=RUNS_SCHEMA, run_id=run_id, hook_id=hook_id,
                 trigger=trigger, action=action, exit_code=exit_code,
                 subject_digest=digest_json(dict(subject)),
                 project_uuid=binding["store"]["project_uuid"],
                 store_identity=binding["store_identity"],
                 adapter_fingerprint=fingerprint, observed_at=now or _utc_now())
    entry["run_hmac"] = SIGNATURE_PREFIX + hmac.new(
        key, canonical_json(entry), hashlib.sha256).hexdigest()
    if len(canonical_json(entry)) + 1 > _MAX_ENTRY_BYTES:
        raise HookRunError("hook_run_invalid_input")
    return entry


def _publish(store, entry, *, exclusive_retry=False, key=None, binding=None):
    payload = canonical_json(entry) + b"\n"
    identifier = digest_bytes(payload)
    path = _runs_dir(store) / (identifier[7:] + ".json")
    try:
        _write_exclusive(path, payload, 0o600)
    except FileExistsError:
        if exclusive_retry:
            # Escritor no cooperante: verificar y re-fsync en UNA apertura.
            # La igualdad con nuestro payload queda probada por
            # nombre==digest de los bytes verificados (mismo sha256).
            _restore_durability(path, key, binding)
    return {"run_id": entry["run_id"], "digest": identifier}


def _require_run_platform_flags() -> None:
    """Delta de locks 2026-11-02: O_NOFOLLOW y O_NONBLOCK son obligatorios
    en el camino B y se verifican ANTES de abrir candidatos o publicar,
    sin fallback cero (no basta fstat posterior: la apertura puede
    bloquear en un FIFO o seguir un enlace). En plataformas sin los
    flags el camino B no está disponible y falla saneado."""
    if not all(hasattr(os, flag) for flag in ("O_NOFOLLOW", "O_NONBLOCK")):
        raise HookRunError("hook_run_platform_unsupported")


def _reject_symlink_ancestors(directory: Path, anchor: Path) -> None:
    """Rechaza symlinks en los componentes del directorio de runs dentro
    de la bóveda (precedente `_reject_symlink_path`,
    an_kla/identity.py:71-84): la resolución de rutas sigue enlaces en
    componentes intermedios, así que `hook-runs` o `runs` symlinkeados
    sacarían el escaneo fuera de la custodia sin que el leaf lo muestre."""
    cursor = directory
    while cursor != anchor:
        if cursor.is_symlink():
            raise HookRunError("hook_run_evidence_invalid")
        if anchor not in cursor.parents:
            raise HookRunError("hook_run_evidence_invalid")
        cursor = cursor.parent


def _safe_open(path: Path) -> int:
    """Apertura FIFO-segura de un candidato: rechaza no-regulares,
    enlaces, multi-enlace y sobre-medidos; compara (dev, ino) antes y
    después de abrir para cerrar la sustitución de ruta."""
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise HookRunError("hook_run_evidence_invalid")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    after = os.fstat(fd)
    if (not stat.S_ISREG(after.st_mode) or after.st_nlink != 1 or
            (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino) or
            after.st_size > _MAX_ENTRY_BYTES):
        os.close(fd)
        raise HookRunError("hook_run_evidence_invalid")
    return fd


def _entry_is_valid(entry: Any, signing_key: bytes,
                    binding: Mapping[str, Any]) -> bool:
    """Criterios de verificación por entrada, compartidos por el lector
    y el escaneo de acuñación (diseño §4: una sola fuente de verdad para
    que no deriven). El escaneo añade, por encima, igualdad byte a byte
    con el canónico, nombre==digest y revalidación de gramática."""
    if not isinstance(entry, dict) or set(entry) != set(_HOOK_RUN_KEYS):
        return False
    if entry.get("schema") != RUNS_SCHEMA:
        return False
    if (not isinstance(entry.get("exit_code"), int) or isinstance(
            entry["exit_code"], bool) or not 0 <= entry["exit_code"] <= 255):
        return False
    try:
        datetime.strptime(entry["observed_at"], "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return False
    if not isinstance(entry.get("run_hmac"), str):
        return False
    expected_mac = SIGNATURE_PREFIX + hmac.new(
        signing_key,
        canonical_json({k: v for k, v in entry.items() if k != "run_hmac"}),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(entry["run_hmac"], expected_mac):
        return False
    if (
        entry.get("project_uuid") != binding["store"]["project_uuid"]
        or entry.get("store_identity") != binding["store_identity"]
    ):
        return False
    return True


def _open_verified(path: Path, key: bytes,
                   binding: Mapping[str, Any]) -> tuple[int, dict[str, Any], bytes]:
    """UNA sola apertura: lee y verifica por completo sobre ese mismo
    descriptor. Corrección TOCTOU del relevo (2026-11-02): la
    verificación y la durabilidad comparten fd; el contenido verificado
    nunca se re-abre después. La igualdad con un payload esperado queda
    probada por nombre==digest de los bytes verificados."""
    try:
        fd = _safe_open(path)
    except OSError as exc:
        raise HookRunError("hook_run_evidence_invalid") from exc
    try:
        chunks: list[bytes] = []
        remaining = _MAX_ENTRY_BYTES + 1
        while remaining > 0:
            chunk = os.read(fd, min(1 << 16, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        entry = json.loads(raw)
        if (len(raw) > _MAX_ENTRY_BYTES or
                raw != canonical_json(entry) + b"\n" or
                path.name != digest_bytes(raw)[7:] + ".json"):
            raise HookRunError("hook_run_evidence_invalid")
        if not _entry_is_valid(entry, key, binding):
            raise HookRunError("hook_run_evidence_invalid")
        _validate_input(entry["hook_id"], entry["trigger"], entry["action"],
                        entry["exit_code"], {}, entry["adapter_fingerprint"],
                        entry["run_id"], entry["observed_at"])
        if not isinstance(entry["subject_digest"], str):
            raise HookRunError("hook_run_evidence_invalid")
        return fd, entry, raw
    except (OSError, ValueError, TypeError, UnicodeError,
            RecursionError) as exc:
        os.close(fd)
        raise HookRunError("hook_run_evidence_invalid") from exc


def _restore_durability(path: Path, key: bytes, binding: Mapping[str, Any]) -> None:
    """Re-establece durabilidad de una entrada verificada SIN re-abrirla:
    fsync del mismo descriptor que la leyó, luego fsync del directorio.
    Un fallo deja el resultado como incierto fail closed (diseño §6)."""
    fd, _, _ = _open_verified(path, key, binding)
    try:
        os.fsync(fd)
    except OSError as exc:
        raise HookRunError("hook_run_publication_uncertain") from exc
    finally:
        os.close(fd)
    try:
        _fsync_dir(path.parent)
    except OSError as exc:
        raise HookRunError("hook_run_publication_uncertain") from exc


def _find_runs(store, key, binding, run_id):
    directory = _runs_dir(store)
    _reject_symlink_ancestors(directory, custody_anchor(store))
    try:
        metadata = directory.lstat()
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise HookRunError("hook_run_scan_incomplete") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise HookRunError("hook_run_evidence_invalid")
    paths = []
    try:
        with os.scandir(directory) as scanner:
            for candidate in scanner:
                if candidate.name.endswith(".json"):
                    paths.append(directory / candidate.name)
                    if len(paths) > _MAX_ENTRIES_SCANNED:
                        raise HookRunError("hook_run_scan_limit")
    except OSError as exc:
        raise HookRunError("hook_run_scan_incomplete") from exc
    matches = []
    for path in paths:
        fd, entry, _ = _open_verified(path, key, binding)
        os.close(fd)
        if entry["run_id"] == run_id:
            matches.append((path, entry))
    return matches


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
    directory = _runs_dir(store)
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
        signing_key = key if key is not None else _load_key(store)
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
        # Criterios compartidos con el escaneo de acuñación (diseño §4):
        # una sola definición para que no deriven. Cambio declarado frente
        # al texto previo: un run_hmac no-str crafted ahora degrada como
        # hook_run_invalid en lugar de romper el lector con TypeError.
        if not _entry_is_valid(entry, signing_key, binding):
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
