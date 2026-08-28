"""Fault-addressable filesystem primitives for ADR-0024."""

from __future__ import annotations

import os
from pathlib import Path
import uuid
from typing import Callable

from .canonical import digest_bytes


class StorageOperationError(OSError):
    """An operational failure with a stable point code and original cause."""

    def __init__(self, code: str, cause: BaseException) -> None:
        super().__init__(code)
        self.code = code
        self.cause = cause
        self.cleanup_incomplete = False
        self.close_incomplete = False


def storage_error(code: str, cause: BaseException) -> StorageOperationError:
    return StorageOperationError(code, cause)


def _close(descriptor: int, primary: StorageOperationError | None, code: str) -> None:
    try:
        os.close(descriptor)
    except OSError as exc:
        if primary is None:
            raise storage_error(code, exc) from exc
        primary.close_incomplete = True


def fsync_directory(path: Path) -> None:
    """Flush a directory without masking open/fsync/close failures."""

    if os.name == "nt":
        return
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError as exc:
        raise storage_error("directory_open_failed", exc) from exc
    primary: StorageOperationError | None = None
    try:
        try:
            os.fsync(descriptor)
        except OSError as exc:
            primary = storage_error("directory_fsync_failed", exc)
            raise primary from exc
    finally:
        _close(descriptor, primary, "directory_close_failed")


def fsync_file(path: Path) -> None:
    """Flush an existing file without rewriting it."""

    # En NT, fsync() delega en _commit(), que exige un handle con acceso
    # de ESCRITURA: sobre O_RDONLY devuelve EBADF y todo receipt moriría
    # con durability_incomplete. O_RDWR satisface _commit() sin alterar
    # bytes (nunca se escribe con este descriptor). En POSIX, O_RDONLY
    # basta y es el modo mínimo.
    flags = os.O_RDWR if os.name == "nt" else os.O_RDONLY
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise storage_error("file_open_failed", exc) from exc
    primary: StorageOperationError | None = None
    try:
        try:
            os.fsync(descriptor)
        except OSError as exc:
            primary = storage_error("file_fsync_failed", exc)
            raise primary from exc
    finally:
        _close(descriptor, primary, "file_close_failed")


def atomic_write(
    target: Path,
    payload: bytes,
    *,
    fsync_directory: Callable[[Path], None],
) -> None:
    """Atomically replace ``target`` with stable error-point reporting."""

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise storage_error("parent_mkdir_failed", exc) from exc
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    descriptor: int | None = None
    primary: StorageOperationError | None = None
    try:
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                0o644,
            )
        except OSError as exc:
            raise storage_error("temporary_open_failed", exc) from exc
        try:
            view = memoryview(payload)
            while view:
                try:
                    written = os.write(descriptor, view)
                except OSError as exc:
                    raise storage_error("temporary_write_failed", exc) from exc
                if written <= 0:
                    raise storage_error(
                        "temporary_write_failed", OSError("zero_length_write")
                    )
                view = view[written:]
            try:
                os.fsync(descriptor)
            except OSError as exc:
                raise storage_error("temporary_fsync_failed", exc) from exc
        except StorageOperationError as exc:
            primary = exc
            raise
        finally:
            if descriptor is not None:
                _close(descriptor, primary, "temporary_close_failed")
                descriptor = None
        try:
            os.replace(temporary, target)
        except OSError as exc:
            raise storage_error("replace_failed", exc) from exc
        fsync_directory(target.parent)
    except StorageOperationError as exc:
        primary = exc
        raise
    finally:
        try:
            temporary_exists = temporary.exists()
        except OSError as exc:
            if primary is None:
                raise storage_error("cleanup_stat_failed", exc) from exc
            primary.cleanup_incomplete = True
            temporary_exists = False
        if temporary_exists:
            try:
                temporary.unlink()
            except OSError as exc:
                if primary is None:
                    raise storage_error("cleanup_unlink_failed", exc) from exc
                primary.cleanup_incomplete = True


def write_immutable(
    target: Path,
    payload: bytes,
    *,
    conflict: Callable[[Path], None],
    fsync_directory: Callable[[Path], None],
) -> None:
    """Create one immutable object or quarantine a conflicting path."""

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        exists = target.exists()
    except OSError as exc:
        raise storage_error("immutable_parent_or_stat_failed", exc) from exc
    if exists:
        try:
            existing = target.read_bytes()
        except OSError as exc:
            raise storage_error("immutable_read_failed", exc) from exc
        if existing != payload:
            conflict(target)
        else:
            return
    try:
        descriptor = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o644,
        )
    except FileExistsError:
        try:
            concurrent = target.read_bytes()
        except OSError as exc:
            raise storage_error("immutable_read_failed", exc) from exc
        if concurrent != payload:
            conflict(target)
            return write_immutable(
                target,
                payload,
                conflict=conflict,
                fsync_directory=fsync_directory,
            )
        return
    except OSError as exc:
        raise storage_error("immutable_open_failed", exc) from exc
    primary: StorageOperationError | None = None
    try:
        view = memoryview(payload)
        while view:
            try:
                written = os.write(descriptor, view)
            except OSError as exc:
                primary = storage_error("immutable_write_failed", exc)
                raise primary from exc
            if written <= 0:
                primary = storage_error(
                    "immutable_write_failed", OSError("zero_length_write")
                )
                raise primary
            view = view[written:]
        try:
            os.fsync(descriptor)
        except OSError as exc:
            primary = storage_error("immutable_fsync_failed", exc)
            raise primary from exc
    finally:
        try:
            os.close(descriptor)
        except OSError as exc:
            if primary is None:
                raise storage_error("immutable_close_failed", exc) from exc
            primary.close_incomplete = True
    fsync_directory(target.parent)


def sync_protected(root: Path, protected: list[dict[str, object]]) -> None:
    """Synchronize and verify every path immediately before a receipt."""

    for item in protected:
        target = root.joinpath(*str(item["path"]).split("/"))
        if item["operation"] == "file_fsync":
            fsync_file(target)
            try:
                actual = digest_bytes(target.read_bytes())
            except OSError as exc:
                raise storage_error("receipt_protected_read_failed", exc) from exc
            if actual != item["content_sha256"]:
                raise storage_error(
                    "receipt_protected_hash_mismatch", OSError("hash mismatch")
                )
        else:
            fsync_directory(target)


__all__ = [
    "StorageOperationError",
    "atomic_write",
    "fsync_directory",
    "fsync_file",
    "storage_error",
    "sync_protected",
    "write_immutable",
]
