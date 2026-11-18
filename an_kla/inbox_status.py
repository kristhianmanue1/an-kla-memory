"""``inbox status``: vista de sólo lectura de la bandeja (ADR-0063 D1), sin candados y sin crear nada.

Vive aparte de :mod:`an_kla.inbox` (que la reexporta) para que ese módulo siga bajo el tope de tamaño.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from .inbox import (
    MAX_LISTED, REASON_SUFFIX, STATUS_SCHEMA, _MAX_REASON_BYTES, _REASON_CODE, _counted_names,
    _dir_state, _names, inbox_paths, is_entry_name, is_marker_name, root_state,
)


def _listing(names: list[str]) -> dict[str, Any]:
    return {"count": len(names), "names": names[:MAX_LISTED], "truncated": len(names) > MAX_LISTED}


def _read_reason(directory: Path, name: str) -> dict[str, Any]:
    """Motivo de un rechazo desde su archivo ``.reason``; nunca bloquea ni devuelve texto libre."""

    path = directory / (name + REASON_SUFFIX)
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return {"reason": None, "reason_codes": []}
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return {"reason": None, "reason_codes": []}
        raw = os.read(fd, _MAX_REASON_BYTES + 1)
    finally:
        os.close(fd)
    try:
        value = json.loads(raw) if len(raw) <= _MAX_REASON_BYTES else None
    except (ValueError, UnicodeError):
        value = None
    if not isinstance(value, dict):
        return {"reason": None, "reason_codes": []}
    code = value.get("code")
    codes = value.get("reason_codes")
    return {
        "reason": code if isinstance(code, str) and _REASON_CODE.fullmatch(code) else None,
        "reason_codes": [c for c in codes if isinstance(c, str) and _REASON_CODE.fullmatch(c)][:32]
        if isinstance(codes, list)
        else [],
    }


def read_status(store: Any) -> dict[str, Any]:
    """Estado de la bandeja para ``inbox status``: sólo lectura, sin candados y sin crear nada.

    Con ``memory/inbox/`` ausente informa ``inbox: "absent"`` y listas vacías. Sólo lista
    nombres (nunca abre una entrada: un FIFO colgaría la lectura); de ``rejected/`` lee,
    acotado y sin bloquear, el archivo ``.reason`` de cada entrada. Es una vista sin
    candado: un encolado o vaciado concurrente puede moverla entre dos lecturas.
    """

    paths = inbox_paths(store)
    top = root_state(store)
    dirs = {"tmp": paths.tmp, "pending": paths.pending, "inflight": paths.inflight, "rejected": paths.rejected}
    states: dict[str, str] = {}
    names: dict[str, list[str]] = {}
    for label, directory in dirs.items():
        state = top if top != "present" else _dir_state(directory)  # raíz ausente o insegura: no se desciende
        names[label] = []
        if state == "present":
            try:
                names[label] = _names(directory)
            except InboxError:
                state = "unsafe"
        states[label] = state
    rejected = []
    present = set(names["rejected"])
    for name in names["rejected"]:
        if name.endswith(REASON_SUFFIX):
            # R3-01 de B2: un inodo inseguro no se mueve a `rejected/`; su único rastro es el `.reason`.
            base = name[: -len(REASON_SUFFIX)]
            if base in present:
                continue
            rejected.append({"name": name, **_read_reason(paths.rejected, base)})
            continue
        rejected.append({"name": name, **_read_reason(paths.rejected, name)})
    pending_entries = _counted_names(paths.pending, names["pending"], is_entry_name)
    inflight_markers = _counted_names(paths.inflight, names["inflight"], is_marker_name)
    counted_pending, counted_inflight = set(pending_entries), set(inflight_markers)
    return {
        "schema": STATUS_SCHEMA,
        "untrusted_memory_data": True,
        "inbox": top,
        "directories": states,
        "pending": _listing(pending_entries),
        "inflight": _listing(inflight_markers),
        "rejected": {
            "count": len(rejected),
            "entries": rejected[:MAX_LISTED],
            "truncated": len(rejected) > MAX_LISTED,
        },
        "tmp": _listing(names["tmp"]),
        "ignored": {
            "pending": _listing([n for n in names["pending"] if n not in counted_pending]),
            "inflight": _listing([n for n in names["inflight"] if n not in counted_inflight]),
        },
    }
