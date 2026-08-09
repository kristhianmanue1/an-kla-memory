"""Exact deletable inventory and no-follow cleanup for ADR-0028."""

from __future__ import annotations

import os
from pathlib import Path
import re
import stat
from typing import Any

from .canonical import digest_bytes
from .compaction_contracts import CompactionError
from .export_io import safe_read


_HEX = r"[0-9a-f]{64}"
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
_RULES = (
    (re.compile(rf"revisions/sha256/{_HEX}\.json"), "revision"),
    (re.compile(rf"checkpoints/sha256/{_HEX}\.json"), "checkpoint"),
    (re.compile(rf"segments/(?:facts|events|episodes)/sha256/{_HEX}\.jsonl"), "segment"),
    (re.compile(rf"refs/ref-log/sha256/{_HEX}\.json"), "ref-log"),
    (re.compile(rf"transactions/{_UUID}\.json"), "transaction"),
    (re.compile(rf"transactions/{_UUID}/stages/sha256/{_HEX}\.json"), "stage"),
    (re.compile(rf"transactions/{_UUID}/receipts/sha256/{_HEX}\.json"), "receipt"),
    (re.compile(rf"refutations/sha256/{_HEX}\.json"), "refutation"),
    (re.compile(rf"authority-claims/sha256/{_HEX}\.json"), "authority-claim"),
    (re.compile(rf"authority-attestations/sha256/{_HEX}\.json"), "authority-attestation"),
    (re.compile(rf"indexes/{_HEX}/sqlite-fts5-v1/CURRENT"), "index"),
    (re.compile(rf"indexes/{_HEX}/sqlite-fts5-v1/{_HEX}\.sqlite"), "index"),
)


def _kind(relative: str) -> str | None:
    for pattern, kind in _RULES:
        if pattern.fullmatch(relative):
            return kind
    return None


def inventory_deletable(store: Any, protected: set[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not store.root.is_dir():
        raise CompactionError("compaction_store_missing")
    for base, directories, files in os.walk(store.root, topdown=True, followlinks=False):
        base_path = Path(base)
        for name in files:
            path = base_path / name
            relative = path.relative_to(store.root).as_posix()
            kind = _kind(relative)
            if kind is None or relative in protected:
                continue
            try:
                payload = safe_read(store.root, relative)
            except Exception as exc:
                raise CompactionError("compaction_inventory_unsafe") from exc
            rows.append(
                {"path": relative, "content_sha256": digest_bytes(payload), "kind": kind}
            )
        for name in directories:
            path = base_path / name
            if path.is_symlink() and _kind(path.relative_to(store.root).as_posix()) is not None:
                raise CompactionError("compaction_inventory_unsafe")
    rows.sort(key=lambda item: item["path"])
    return rows


def validate_no_links(store: Any) -> None:
    """Reject linked/special namespaces before any compaction write or delete."""

    try:
        root_info = store.root.lstat()
    except OSError as exc:
        raise CompactionError("compaction_store_missing") from exc
    if not stat.S_ISDIR(root_info.st_mode) or store.root.is_symlink():
        raise CompactionError("compaction_namespace_unsafe")
    for base, directories, files in os.walk(
        store.root, topdown=True, followlinks=False
    ):
        base_path = Path(base)
        for name in [*directories, *files]:
            info = (base_path / name).lstat()
            if stat.S_ISLNK(info.st_mode):
                raise CompactionError("compaction_namespace_unsafe")
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise CompactionError("compaction_namespace_unsafe")
            if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                raise CompactionError("compaction_namespace_unsafe")


def _open_parent(root: Path, parts: list[str]) -> tuple[int, list[int]]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None or os.open not in os.supports_dir_fd:
        raise CompactionError("compaction_platform_unsafe")
    descriptors: list[int] = []
    try:
        current = os.open(root, flags | nofollow)
        descriptors.append(current)
        for part in parts:
            current = os.open(part, flags | nofollow, dir_fd=current)
            descriptors.append(current)
        return current, descriptors
    except Exception:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
        raise


def delete_exact(store: Any, tombstone: dict[str, str]) -> bool:
    relative = tombstone["path"]
    if _kind(relative) != tombstone["kind"]:
        raise CompactionError("compaction_delete_path_invalid")
    parts = relative.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise CompactionError("compaction_delete_path_invalid")
    parent, descriptors = _open_parent(store.root, parts[:-1])
    file_descriptor: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            file_descriptor = os.open(parts[-1], flags, dir_fd=parent)
        except FileNotFoundError:
            return False
        info = os.fstat(file_descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise CompactionError("compaction_delete_unsafe_file")
        chunks = []
        while True:
            chunk = os.read(file_descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        if digest_bytes(b"".join(chunks)) != tombstone["content_sha256"]:
            raise CompactionError("compaction_delete_content_changed")
        entry = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        if (entry.st_dev, entry.st_ino) != (info.st_dev, info.st_ino):
            raise CompactionError("compaction_delete_raced")
        os.unlink(parts[-1], dir_fd=parent)
        return True
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def sync_cleanup_parents(store: Any, tombstones: list[dict[str, str]]) -> list[str]:
    parents = {str(Path(item["path"]).parent.as_posix()) for item in tombstones}
    ordered = sorted(parents, key=lambda value: (-len(Path(value).parts), value))
    for relative in ordered:
        directory, descriptors = _open_parent(store.root, relative.split("/"))
        try:
            os.fsync(directory)
        except OSError as exc:
            raise CompactionError("compaction_cleanup_fsync_failed") from exc
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)
    return ordered


__all__ = [
    "delete_exact", "inventory_deletable", "sync_cleanup_parents",
    "validate_no_links",
]
