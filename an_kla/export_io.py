"""Fail-closed filesystem helpers for ADR-0027."""

from __future__ import annotations

import ctypes
import errno
import os
from pathlib import Path
import stat
import sys
from typing import Iterable

from .storage_primitives import fsync_directory, fsync_file


class ExportIOError(OSError):
    pass


def safe_read(root: Path, relative: str) -> bytes:
    """Read one regular single-link file without following any path link."""

    parts = relative.split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ExportIOError("export_path_invalid")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None or os.open not in os.supports_dir_fd:
        raise ExportIOError("export_platform_unsafe")
    descriptors: list[int] = []
    try:
        current = os.open(root, flags | directory | nofollow)
        descriptors.append(current)
        for part in parts[:-1]:
            current = os.open(part, flags | directory | nofollow, dir_fd=current)
            descriptors.append(current)
        file_descriptor = os.open(parts[-1], flags | nofollow, dir_fd=current)
        descriptors.append(file_descriptor)
        before = os.fstat(file_descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ExportIOError("export_unsafe_file")
        chunks = []
        while True:
            chunk = os.read(file_descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(file_descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
        ):
            raise ExportIOError("export_source_changed")
        return b"".join(chunks)
    except OSError as exc:
        if isinstance(exc, ExportIOError):
            raise
        raise ExportIOError("export_unsafe_path") from exc
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass


def validate_tree(root: Path, expected_files: set[str]) -> None:
    """Reject links, specials, hardlinks, unexpected files and orphan dirs."""

    try:
        root_stat = root.lstat()
    except OSError as exc:
        raise ExportIOError("export_bundle_invalid") from exc
    if not stat.S_ISDIR(root_stat.st_mode) or root.is_symlink():
        raise ExportIOError("export_bundle_invalid")
    actual_files: set[str] = set()
    actual_dirs: set[str] = set()
    for base, directories, files in os.walk(root, topdown=True, followlinks=False):
        base_path = Path(base)
        for name in [*directories, *files]:
            path = base_path / name
            relative = path.relative_to(root).as_posix()
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise ExportIOError("export_unsafe_link")
            if stat.S_ISDIR(info.st_mode):
                actual_dirs.add(relative)
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                actual_files.add(relative)
            else:
                raise ExportIOError("export_unsafe_file")
    if actual_files != expected_files:
        raise ExportIOError("export_extra_or_missing_entry")
    allowed_dirs = {
        prefix
        for path in expected_files
        for prefix in (
            "/".join(path.split("/")[:index])
            for index in range(1, len(path.split("/")))
        )
    }
    if not actual_dirs.issubset(allowed_dirs):
        raise ExportIOError("export_extra_or_missing_entry")


def normalize_and_sync_tree(root: Path, files: Iterable[Path]) -> None:
    file_list = list(files)
    directories = {root}
    for path in file_list:
        path.chmod(0o600)
        fsync_file(path)
        cursor = path.parent
        while cursor == root or root in cursor.parents:
            directories.add(cursor)
            if cursor == root:
                break
            cursor = cursor.parent
    for directory_path in directories:
        directory_path.chmod(0o700)
    for directory_path in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        fsync_directory(directory_path)


def rename_noreplace(source: Path, destination: Path) -> None:
    """Publish a directory atomically without replacing an existing path."""

    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    if sys.platform == "darwin" and hasattr(libc, "renamex_np"):
        result = libc.renamex_np(source_bytes, destination_bytes, ctypes.c_uint(0x4))
    elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        result = libc.renameat2(-100, source_bytes, -100, destination_bytes, 1)
    else:
        raise ExportIOError("restore_platform_unsafe")
    if result != 0:
        value = ctypes.get_errno()
        if value in {errno.EEXIST, errno.ENOTEMPTY}:
            raise ExportIOError("restore_destination_conflict")
        raise ExportIOError("restore_publish_failed") from OSError(value, os.strerror(value))


__all__ = ["ExportIOError", "normalize_and_sync_tree", "rename_noreplace", "safe_read", "validate_tree"]
