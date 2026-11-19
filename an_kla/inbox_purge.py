"""``inbox purge-rejected``: purga de ``rejected/`` con respaldo obligatorio fuera del store (ADR-0068, #234).

Por rechazo: cada archivo que exista (la entrada y su ``.reason``, o sólo el ``.reason`` de un inodo
inseguro) se copia al respaldo como ``.<nombre>.tmp`` con ``fsync`` y se renombra a ``<nombre>``; se
hace ``fsync`` del directorio del respaldo; se compara el sha256 de cada copia con el original y sólo
entonces se borran los originales. Sin respaldo no se purga. Un respaldo puede traer copias de purgas
anteriores (terminadas o cortadas): así se reanuda y se purgan más de 50 rechazos con el mismo respaldo.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Any, Iterable

from .inbox import REASON_SUFFIX, InboxError, InboxPaths, inbox_paths
from .inbox_entries import kind_of_path
from .inbox_rejected import (
    BATCH,
    Rejection,
    base_of,
    file_digest,
    list_rejections,
    parse_targets,
    read_reason,
    reason_code,
    rejected_locks,
    rejected_present,
    select,
)
from .storage_primitives import fsync_directory

PURGE_SCHEMA = "an-kla/inbox-purge-result-v1"
INVALID_BACKUP = "inbox_purge_backup_invalid"
_CHUNK = 1 << 20
_TMP_NAME = re.compile(r"\.(.+)\.tmp")


def _invalid(hint: str) -> InboxError:
    return InboxError(INVALID_BACKUP, hint)


def backup_path(store: Any, backup: Any) -> Path:
    """El respaldo pedido: absoluto, no enlazado y fuera del store y de ``.an-kla/`` (sin tocar el disco)."""

    if not isinstance(backup, str) or not backup or "\0" in backup or not os.path.isabs(backup):
        raise _invalid("--backup debe ser un directorio absoluto")
    path = Path(os.path.normpath(backup))
    forbidden = [Path(os.path.realpath(store.root)), Path(os.path.realpath(Path(store.project_root) / ".an-kla"))]
    inside = Path(os.path.realpath(path))
    if any(inside == place or place in inside.parents for place in forbidden):
        raise _invalid("--backup debe estar fuera del store y de .an-kla/")
    return path


def _prepare_backup(path: Path) -> None:
    """Lo crea (0700, su padre tiene que existir) o comprueba que es un directorio real."""

    try:
        info = os.lstat(path)
    except FileNotFoundError:
        try:
            os.mkdir(path, 0o700)
        except OSError:
            raise _invalid("el respaldo no se pudo crear (su directorio padre debe existir)") from None
        fsync_directory(path.parent)
        return
    except OSError:
        raise _invalid("el respaldo no se puede inspeccionar") from None
    if not stat.S_ISDIR(info.st_mode):
        raise _invalid("--backup debe ser un directorio, no un enlace ni un archivo")


def _scan_backup(backup: Path, rejected: Path, present: set[str]) -> list[Path]:
    """Valida el contenido del respaldo; devuelve los ``.<nombre>.tmp`` huérfanos (aún sin borrar)."""

    orphans: list[Path] = []
    try:
        names = sorted(os.listdir(backup))
    except OSError:
        raise _invalid("el respaldo no se puede leer") from None
    for name in names:
        path = backup / name
        try:
            info = os.lstat(path)
        except OSError:
            raise _invalid("el respaldo cambió mientras se leía") from None
        if not stat.S_ISREG(info.st_mode):
            raise _invalid("el respaldo sólo puede contener copias de rechazos")
        tmp = _TMP_NAME.fullmatch(name)
        if tmp and base_of(tmp.group(1)) is not None:
            orphans.append(path)
        elif base_of(name) is None:
            raise _invalid("el respaldo contiene un archivo que no es de un rechazo")
        elif name in present and (file_digest(path) is None or file_digest(path) != file_digest(rejected / name)):
            raise _invalid("una copia del respaldo difiere del rechazo con su mismo nombre")
    return orphans


def _copy(source: Path, directory: Path, name: str) -> None:
    """``.<nombre>.tmp`` con ``fsync`` y ``rename`` atómico a ``<nombre>``: nunca una copia truncada con el nombre final."""

    tmp = directory / f".{name}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    read_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    source_fd = os.open(source, read_flags)
    try:
        if not stat.S_ISREG(os.fstat(source_fd).st_mode):
            raise OSError("not a regular file")
        target_fd = os.open(tmp, flags, 0o600)
        try:
            while chunk := os.read(source_fd, _CHUNK):
                view = memoryview(chunk)
                while view:
                    view = view[os.write(target_fd, view):]
            os.fsync(target_fd)
        finally:
            os.close(target_fd)
    finally:
        os.close(source_fd)
    os.rename(tmp, directory / name)


def _files_of(rejection: Rejection) -> list[str]:
    return ([rejection.base] if rejection.has_file else []) + ([rejection.base + REASON_SUFFIX] if rejection.has_reason else [])


def _purge_one(paths: InboxPaths, backup: Path, rejection: Rejection) -> tuple[str, list[dict[str, Any]]]:
    """``(resultado, files)`` de un rechazo; sin copia verificada de cada archivo no se borra ninguno."""

    names = _files_of(rejection)
    copied = True
    try:
        if rejection.has_file and kind_of_path(paths.rejected / rejection.base) != "ok":
            raise OSError("not a regular file")
        for name in names:
            if not os.path.lexists(backup / name):  # una copia de una purga anterior ya está verificada
                _copy(paths.rejected / name, backup, name)
        fsync_directory(backup)
    except OSError:
        copied = False
    files = [{"name": name, "sha256": file_digest(backup / name)} for name in names]
    if not copied or any(
        item["sha256"] is None or item["sha256"] != file_digest(paths.rejected / item["name"]) for item in files
    ):
        return "backup_failed", files
    for name in names:  # la entrada primero: un corte deja un `.reason` sin entrada, que ya está respaldado
        os.unlink(paths.rejected / name)
    fsync_directory(paths.rejected)
    return "purged", files


def purge_rejected(
    store: Any, names: Iterable[str] = (), *, everything: bool = False, backup: Any = None
) -> dict[str, Any]:
    """``inbox purge-rejected``: respalda y borra los rechazos pedidos (50 por invocación como mucho)."""

    targets = parse_targets(names)
    if not targets and not everything:
        raise InboxError("inbox_purge_target_missing", "indica rechazos o --all")
    directory = backup_path(store, backup)
    result: dict[str, Any] = {
        "schema": PURGE_SCHEMA, "untrusted_memory_data": True, "purged": [], "failed": [], "remaining": 0,
    }
    if not rejected_present(store):
        if targets:
            raise InboxError("inbox_purge_target_missing", "el rechazo no está en rejected/")
        return result
    paths = inbox_paths(store)
    try:
        with rejected_locks(store):
            rejections = list_rejections(paths)
            chosen = select(rejections, targets, everything, "inbox_purge_target_missing")
            if not chosen:
                return result
            _prepare_backup(directory)
            present = {name for rejection in rejections for name in _files_of(rejection)}
            orphans = _scan_backup(directory, paths.rejected, present)
            for orphan in orphans:
                os.unlink(orphan)
            if orphans:
                fsync_directory(directory)
            for rejection in chosen:
                if len(result["purged"]) >= BATCH:
                    result["remaining"] += 1
                    continue
                code = reason_code(read_reason(paths.rejected / (rejection.base + REASON_SUFFIX)))
                outcome, files = _purge_one(paths, directory, rejection)
                item = {"rejected_name": rejection.shown, "code": code, "result": outcome, "files": files}
                result["purged" if outcome == "purged" else "failed"].append(item)
    except OSError:
        raise InboxError("inbox_unavailable") from None
    return result


__all__ = ["INVALID_BACKUP", "PURGE_SCHEMA", "backup_path", "purge_rejected"]
