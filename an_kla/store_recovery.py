"""Recuperación y doctor del store (#117: partición de store.py)."""

from __future__ import annotations

import json
from typing import Any

from .store_errors import IntegrityError


def recover_report(store: Any) -> dict[str, Any]:
    """Diagnose interrupted work without guessing a replacement CURRENT."""
    current = store.read_current()
    # A valid CURRENT is authoritative even if its operational transaction
    # record is stale.  Prepared journals are retained for inspection.
    prepared = []
    for path in sorted((store.root / "transactions").glob("*.json")):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prepared.append({"path": path.name, "status": "invalid_journal"})
            continue
        if entry.get("stage") != "committed":
            prepared.append(
                {"path": path.name, "status": str(entry.get("stage", "unknown"))}
            )
    return {
        "schema": "an-kla/recovery-report-v1",
        "current": current,
        "action": "none_current_authoritative",
        "pending_transactions": prepared,
    }


def doctor_report(store: Any) -> dict[str, Any]:
    try:
        status = store.verify()
        current_error = None
    except IntegrityError as exc:
        status = None
        current_error = str(exc)
    quarantine = store.root / "quarantine"
    objects = (
        [path for path in quarantine.rglob("*") if path.is_file()]
        if quarantine.exists()
        else []
    )
    return {
        "schema": "an-kla/doctor-v1",
        "current_ok": current_error is None,
        "current_error": current_error,
        "status": status,
        "quarantine_objects": len(objects),
        "quarantine_bytes": sum(path.stat().st_size for path in objects),
        "durability_profile": store.durability_profile,
        "index_orphan_temporaries": (
            sum(
                1
                for path in (store.root / "indexes").rglob(".build-*.sqlite")
                if path.is_file()
            )
            if (store.root / "indexes").exists()
            else 0
        ),
    }


__all__ = ["doctor_report", "recover_report"]
