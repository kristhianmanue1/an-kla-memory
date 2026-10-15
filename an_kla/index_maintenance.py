"""Poda de índices derivados huérfanos (ADR-0055, issue #149 P2c).

Operación sobre caché derivada: elimina los directorios de índice de las
revisiones no vigentes. Sin efecto en corrección (un índice ausente
degrada a ``scan-fallback/v1``), sin escritura de store, sin journal.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


def prune_indexes(store: Any, keep_revision: str | None = None) -> dict[str, Any]:
    keep = keep_revision or store.read_current()
    indexes_dir = Path(store.root) / "indexes"
    pruned: list[str] = []
    freed = 0
    if indexes_dir.is_dir():
        for entry in sorted(indexes_dir.iterdir()):
            if not entry.is_dir():
                continue
            revision_dir = _revision_of(entry)
            if revision_dir is None:
                continue
            if _same_revision(revision_dir, keep):
                continue
            freed += _dir_size(entry)
            shutil.rmtree(entry, ignore_errors=True)
            pruned.append(revision_dir)
    return {
        "schema": "an-kla/index-prune-result/v1",
        "kept_revision": keep,
        "pruned_revisions": pruned,
        "bytes_freed": freed,
        "pruned_count": len(pruned),
    }


def _revision_of(entry: Path) -> str | None:
    """El directorio de índice se nombra con el digest de la revisión."""
    name = entry.name
    return f"sha256:{name}" if len(name) == 64 and all(
        c in "0123456789abcdef" for c in name
    ) else None


def _same_revision(revision: str, keep: str) -> bool:
    return revision.removeprefix("sha256:") == keep.removeprefix("sha256:")


def _dir_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


__all__ = ["prune_indexes"]
