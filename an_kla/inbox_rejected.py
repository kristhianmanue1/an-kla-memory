"""Salida explícita de ``rejected/``: lo común y ``inbox requeue`` (ADR-0068, #234).

Las dos órdenes (``requeue`` aquí, ``purge-rejected`` en :mod:`an_kla.inbox_purge`) toman los candados
en el orden total de ``lock_order``: bandeja exclusiva, ``identity_lock`` compartido y ``write_lock``
con plazo de 0,5 s. Si ``write_lock`` no llega, se sueltan los otros dos y la respuesta es
``write_lock_busy`` reintentable: nunca se retiene el exclusivo de la bandeja esperando el de escritura.
El recorrido es completo y en orden de bytes; el lote (50) sólo cuenta lo que cambia.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from .identity import IdentityError, _mutation_preflight_with_context, identity_lock
from .inbox import (
    ENQUEUE_IDENTITY_WAIT_SECONDS,
    ENQUEUE_LOCK_WAIT_SECONDS,
    ENTRY_NAME,
    REASON_SUFFIX,
    _MAX_REASON_BYTES,
    _NAME_ATTEMPTS,
    _REASON_CODE,
    _entry_name,
    _names,
    ensure_layout,
    inbox_lock,
    inbox_paths,
    root_state,
    InboxError,
    InboxPaths,
)
from .inbox_entries import INVALID, Reject, kind_of_path, parse_entry_file
from .remember import RememberError
from .storage_primitives import fsync_directory
from .store_errors import LockBusyError

REQUEUE_SCHEMA = "an-kla/inbox-requeue-result-v1"
BATCH = 50
WRITE_LOCK_WAIT_SECONDS = 0.5
_REJECTED_NAME = re.compile(rf"({ENTRY_NAME.pattern})(?:\.[0-9]+)?")
_CHUNK = 1 << 20
_IDENTITY_HINT = "hay un cambio de custodia o de identidad en curso; reintenta en unos segundos"
_WRITE_HINT = "otro proceso tiene el candado de escritura; reintenta en unos segundos"


@dataclass(frozen=True)
class Rejection:
    """Un rechazo de ``rejected/``: su nombre base y qué archivos tiene (entrada y/o ``.reason``)."""

    base: str
    has_file: bool
    has_reason: bool

    @property
    def shown(self) -> str:
        """El nombre que ``inbox status`` lista: el de la entrada o, en un rechazo de sólo ``.reason``, ese archivo."""

        return self.base if self.has_file else self.base + REASON_SUFFIX

    @property
    def canonical(self) -> str:
        match = _REJECTED_NAME.fullmatch(self.base)
        return match.group(1) if match else self.base


def base_of(name: str) -> str | None:
    """Nombre base de un rechazo (sin ``.reason``), o ``None`` si no es un nombre que ``reject_entry`` produzca."""

    base = name[: -len(REASON_SUFFIX)] if name.endswith(REASON_SUFFIX) else name
    return base if isinstance(name, str) and _REJECTED_NAME.fullmatch(base) else None


def parse_targets(names: Iterable[str]) -> list[str]:
    """Nombres pedidos por quien llama; cualquier ruta, ``..`` u otro nombre es ``inbox_entry_name_invalid``."""

    found = set()
    for name in names:
        base = base_of(name)
        if base is None:
            raise InboxError("inbox_entry_name_invalid", "usa el nombre que lista `inbox status`, sin rutas")
        found.add(base)
    return sorted(found, key=os.fsencode)


def list_rejections(paths: InboxPaths) -> list[Rejection]:
    """Todo ``rejected/`` agrupado por rechazo y en orden de bytes; los nombres ajenos no se tocan."""

    names = set(_names(paths.rejected))
    bases: dict[str, tuple[bool, bool]] = {}
    for name in names:
        base = base_of(name)
        if base is not None:
            bases[base] = (base in names, base + REASON_SUFFIX in names)
    return [Rejection(base, *bases[base]) for base in sorted(bases, key=os.fsencode)]


def select(rejections: list[Rejection], targets: list[str], everything: bool, missing_code: str) -> list[Rejection]:
    by_base = {rejection.base: rejection for rejection in rejections}
    if any(target not in by_base for target in targets):
        raise InboxError(missing_code, "el rechazo no está en rejected/ (¿ya se reencoló o purgó?)")
    return rejections if everything else [by_base[target] for target in targets]


def file_digest(path: Path) -> str | None:
    """``sha256:<hex>`` de los bytes tal como están en disco; ``None`` si no existe, no es regular o no se lee."""

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return None
    digest = hashlib.sha256()
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        while chunk := os.read(fd, _CHUNK):
            digest.update(chunk)
    except OSError:
        return None
    finally:
        os.close(fd)
    return "sha256:" + digest.hexdigest()


def read_reason(path: Path) -> dict[str, Any] | None:
    """El ``.reason`` como objeto, acotado y sin seguir enlaces; ``None`` si no existe o no es un objeto JSON."""

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        raw = os.read(fd, _MAX_REASON_BYTES + 1)
    except OSError:
        return None
    finally:
        os.close(fd)
    try:
        value = json.loads(raw) if len(raw) <= _MAX_REASON_BYTES else None
    except (ValueError, UnicodeError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def reason_code(reason: dict[str, Any] | None) -> str | None:
    code = None if reason is None else reason.get("code")
    return code if isinstance(code, str) and _REASON_CODE.fullmatch(code) else None


@contextlib.contextmanager
def rejected_locks(store: Any) -> Iterator[None]:
    """Bandeja exclusiva -> ``identity_lock`` compartido -> ``write_lock`` (0,5 s); suelta todo si éste no llega."""

    paths = inbox_paths(store)
    create = not os.path.lexists(paths.lock)  # layout hecho a mano sin `.lock`: se crea sólo él, como `collect_tmp`
    with inbox_lock(store, exclusive=True, wait_seconds=ENQUEUE_LOCK_WAIT_SECONDS, create=create, layout=False):
        try:
            with identity_lock(store, wait_seconds=ENQUEUE_IDENTITY_WAIT_SECONDS, shared=True):
                _mutation_preflight_with_context(store)
                with store.write_lock(deadline=WRITE_LOCK_WAIT_SECONDS):
                    yield
        except IdentityError as exc:
            if str(exc) != "identity_lock_busy":
                raise
            raise RememberError("identity_lock_busy", _IDENTITY_HINT, retryable=True) from None
        except LockBusyError as exc:
            if str(exc) != "write_lock_busy":
                raise
            raise RememberError("write_lock_busy", _WRITE_HINT, retryable=True) from None


def rejected_present(store: Any) -> bool:
    """``False`` si la bandeja o ``rejected/`` no existen (nada que hacer, nada que crear); insegura, error."""

    state = root_state(store)
    if state == "unsafe":
        raise InboxError("inbox_unsafe_path")
    if state == "absent":
        return False
    return bool(_names(inbox_paths(store).rejected))


def classify(paths: InboxPaths, rejection: Rejection) -> tuple[str, str | None, str | None, dict[str, Any] | None]:
    """``(resultado, código, sha256, datos)``; ``resultado`` es uno de ADR-0068 o ``requeueable``."""

    reason_path = paths.rejected / (rejection.base + REASON_SUFFIX)
    reason = read_reason(reason_path) if rejection.has_reason else None
    code = reason_code(reason)
    if not rejection.has_file:
        # Sin entrada: o un inodo inseguro (el `.reason` lleva la evidencia `lstat`) o el resto de un corte.
        result = "not_requeueable_unsafe" if reason is not None and "lstat" in reason else "orphan_reason"
        return result, code, file_digest(reason_path), None
    path = paths.rejected / rejection.base
    sha = file_digest(path)
    if kind_of_path(path) != "ok":
        return "not_requeueable_unsafe", code, sha, None
    if code != INVALID:
        return "not_requeueable_policy", code, sha, None
    try:
        data = parse_entry_file(path)
    except Reject:
        return "still_invalid", code, sha, None
    return "requeueable", code, sha, data


def _destination(paths: InboxPaths, canonical: str, key: str, time_ns: Callable[[], int], token: Callable[[], str]) -> str:
    """El nombre canónico si ``pending/`` no lo tiene; si lo tiene, nombres nuevos hasta uno libre (R68-03, R68-15)."""

    name = canonical
    for _ in range(_NAME_ATTEMPTS):
        try:
            os.lstat(paths.pending / name)
        except FileNotFoundError:
            return name
        name = _entry_name(time_ns(), os.getpid(), key, token())
    raise InboxError("inbox_name_exhausted")


def _requeue_one(
    paths: InboxPaths, rejection: Rejection, key: str, time_ns: Callable[[], int], token: Callable[[], str]
) -> str:
    """Dos pasos: ``rename`` a ``pending/`` (con ``fsync`` de los dos directorios) y después ``unlink`` del ``.reason``."""

    name = _destination(paths, rejection.canonical, key, time_ns, token)
    os.rename(paths.rejected / rejection.base, paths.pending / name)
    fsync_directory(paths.pending)
    fsync_directory(paths.rejected)
    if rejection.has_reason:
        os.unlink(paths.rejected / (rejection.base + REASON_SUFFIX))
        fsync_directory(paths.rejected)
    return name


def requeue(
    store: Any,
    names: Iterable[str] = (),
    *,
    all_format: bool = False,
    time_ns: Callable[[], int] = time.time_ns,
    token: Callable[[], str] = lambda: secrets.token_hex(4),
) -> dict[str, Any]:
    """``inbox requeue``: devuelve a ``pending/`` los rechazos de formato que esta versión ya entiende."""

    targets = parse_targets(names)
    if not targets and not all_format:
        raise InboxError("inbox_requeue_target_missing", "indica rechazos o --all-format")
    result: dict[str, Any] = {
        "schema": REQUEUE_SCHEMA, "untrusted_memory_data": True, "requeued": [], "skipped": [], "remaining": 0,
    }
    if not rejected_present(store):
        if targets:
            raise InboxError("inbox_requeue_target_missing", "el rechazo no está en rejected/")
        return result
    paths = inbox_paths(store)
    try:
        with rejected_locks(store):
            ensure_layout(store)
            chosen = select(list_rejections(paths), targets, all_format, "inbox_requeue_target_missing")
            for rejection in chosen:
                kind, code, sha, data = classify(paths, rejection)
                item = {"rejected_name": rejection.shown, "code": code, "result": kind, "sha256": sha}
                if kind != "requeueable":
                    result["skipped"].append(item)
                elif len(result["requeued"]) >= BATCH:
                    result["remaining"] += 1
                else:
                    item["result"] = "requeued"
                    item["pending_name"] = _requeue_one(paths, rejection, data["idempotency_key"], time_ns, token)
                    result["requeued"].append(item)
    except OSError:
        raise InboxError("inbox_unavailable") from None
    return result


__all__ = [
    "BATCH", "REQUEUE_SCHEMA", "Rejection", "WRITE_LOCK_WAIT_SECONDS", "base_of", "classify", "file_digest",
    "list_rejections", "parse_targets", "read_reason", "reason_code", "rejected_locks", "rejected_present",
    "requeue", "select",
]
