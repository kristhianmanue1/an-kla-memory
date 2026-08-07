"""Pure record-text extraction shared by the write path and the FTS index.

This module performs no I/O and imports nothing non-deterministic.  It exists so
``write_policy`` (the pure decision core) can detect records that would produce
no indexable text without importing the SQLite/OS-bearing ``index`` module; see
ADR-0018 and issue #15.  ``index`` re-exports :func:`record_text` for backward
compatibility with callers that imported it from there.
"""

from __future__ import annotations

from typing import Any


def record_text(record: dict[str, Any]) -> str:
    """Return the first supported non-empty string in normative priority.

    Priority: ``indexable_text`` > ``text`` > ``render`` > ``summary`` > ``p``.
    ``indexable_text`` is the writer's explicit declaration of what FTS should
    index (see ADR-0018); the other fields are inspected as fallbacks so the
    beta contract that selected ``text|render|summary|p`` keeps working.
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


__all__ = ["record_text"]
