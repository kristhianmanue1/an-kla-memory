"""Best-effort refresh of the derived FTS cache after authoritative commit."""

from __future__ import annotations

from typing import Any


def maybe_reindex(store: Any, parent_revision: str, candidate_revision: str) -> None:
    try:
        from .index import build_index, index_resolution
    except ImportError:
        return
    try:
        parent = index_resolution(store, parent_revision)
        if parent.path is None:
            return
    except Exception:
        return
    try:
        build_index(store, revision_id=candidate_revision)
    except Exception:
        pass


__all__ = ["maybe_reindex"]
