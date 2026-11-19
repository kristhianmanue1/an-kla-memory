"""``list``: todos los registros de los streams pedidos, con su vigencia, de sólo lectura (ADR-0067).

Lee una sola revisión (la del ``snapshot``) y no usa Git. Orden total: partición por stream, en el orden pedido,
y dentro de cada una la clave de :func:`an_kla.history._order` (con sobre antes que legados, ``enqueued_at``,
``id``). El presupuesto es exacto y poda del final; ``--limit`` corta antes por número. Un cursor opaco lleva la
revisión, los filtros y la clave del último registro devuelto.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections import Counter
from typing import Any, Mapping

from .disputes import _valid_disputes
from .history import _describe, _order
from .read_budget import fit_prefix
from .record_text import record_text
from .state_show import StateReadError
from .state_slot import SLOT_PATTERN
from .store import STREAMS
from .vigency import is_active

RESULT_SCHEMA = "an-kla/list-result-v1"
DEFAULT_STREAMS = "facts"
DEFAULT_LIMIT = 1000
MAX_LIMIT = 10000
DEFAULT_BUDGET = 65536
STATUSES = ("active", "superseded", "refuted", "all")
KINDS = ("fact", "decision", "state", "event")
_REVISION = "sha256:"
_CURSOR_KEYS = {"r", "f", "k"}


def _positive(value: Any, code: str, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or (maximum is not None and value > maximum):
        raise StateReadError(code, "entero positivo" if maximum is None else f"entero positivo, máximo {maximum}")
    return value


def parse_streams(value: Any) -> list[str]:
    """``facts,events``: nombres de stream sin repetir, en el orden pedido."""

    names = value.split(",") if isinstance(value, str) else None
    if not names or any(name not in STREAMS for name in names) or len(set(names)) != len(names):
        raise StateReadError("list_streams_invalid", "facts[,events,episodes], sin repetir")
    return names


def _filters(streams: Any, status: Any, kind: Any, slot: Any, limit: Any, budget: Any, text: Any) -> dict[str, Any]:
    names = parse_streams(streams)
    if status not in STATUSES:
        raise StateReadError("list_status_invalid", "active|superseded|refuted|all")
    if kind is not None and kind not in KINDS:
        raise StateReadError("list_kind_invalid", "fact|decision|state|event")
    if slot is not None and not (isinstance(slot, str) and SLOT_PATTERN.fullmatch(slot)):
        raise StateReadError("list_slot_invalid", "slot: [a-z][a-z0-9_-]{0,31}")
    return {
        "streams": names, "status": status, "kind": kind, "slot": slot,
        "limit": _positive(limit, "list_limit_invalid", MAX_LIMIT), "budget": _positive(budget, "list_budget_invalid"),
        "text": bool(text),
    }


def _cursor_scope(filters: Mapping[str, Any]) -> dict[str, Any]:
    """Lo que el cursor fija: el tamaño de página (``limit``, ``budget``) puede cambiar entre páginas."""

    return {key: filters[key] for key in ("streams", "status", "kind", "slot", "text")}


def _sort_key(item: Mapping[str, Any], streams: list[str]) -> tuple[int, int, str, str]:
    group, stamp, rid, _ = _order(item)
    return (streams.index(item["stream"]), group, stamp, rid)


def encode_cursor(revision: str, filters: Mapping[str, Any], key: tuple[int, int, str, str] | None) -> str:
    raw = json.dumps({"r": revision, "f": _cursor_scope(filters), "k": key}, sort_keys=True, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: Any, filters: Mapping[str, Any]) -> tuple[str, tuple[int, int, str, str] | None]:
    """``(revisión, clave)`` del cursor; ``list_cursor_invalid`` si está mal formado o es de otros filtros."""

    invalid = StateReadError("list_cursor_invalid")
    if not isinstance(cursor, str) or not cursor:
        raise invalid
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    except (binascii.Error, ValueError):
        raise invalid from None
    if not isinstance(data, dict) or set(data) != _CURSOR_KEYS:
        raise invalid
    revision, scope, key = data["r"], data["f"], data["k"]
    if not (isinstance(revision, str) and revision.startswith(_REVISION)) or scope != _cursor_scope(filters):
        raise invalid
    if key is not None:
        ok = (
            isinstance(key, list) and len(key) == 4 and isinstance(key[0], int) and not isinstance(key[0], bool)
            and key[1] in (0, 1) and isinstance(key[2], str) and isinstance(key[3], str)
            and 0 <= key[0] < len(filters["streams"])
        )
        if not ok:
            raise invalid
        key = (key[0], key[1], key[2], key[3])
    return revision, key


def _superseded_by(snapshot: Any) -> dict[tuple[str, str], str]:
    found: dict[tuple[str, str], str] = {}
    for entry in snapshot.manifest.get("supersedes_map", []):
        if isinstance(entry, dict) and entry.get("stream") in STREAMS and entry.get("target_id") and entry.get("sustituida_por"):
            found[(entry["stream"], str(entry["target_id"]))] = str(entry["sustituida_por"])
    return found


def _disputes_count(snapshot: Any) -> Counter[tuple[str, str]]:
    """Disputas vigentes por objetivo ``(stream, id)``, contadas como ``disputes list``."""

    count: Counter[tuple[str, str]] = Counter()
    for stream in STREAMS:
        for row in snapshot.records[stream]:
            disputes = row.get("disputes")
            if _valid_disputes(disputes) and is_active(row):
                count[(disputes["stream"], disputes["target_id"])] += 1
    return count


def _item(
    stream: str, row: Mapping[str, Any], replaced: Mapping[tuple[str, str], str], disputes: Mapping[tuple[str, str], int],
    with_text: bool,
) -> dict[str, Any]:
    item = _describe(stream, row)
    key = (stream, item["id"])
    text = record_text(dict(row))
    if key in replaced:
        item["superseded_by"] = replaced[key]
    item["disputes_count"] = disputes.get(key, 0)
    anchors = row.get("anchors")
    if isinstance(anchors, list) and anchors:  # ADR-0066: sólo lo guardado; no se comprueba ninguna ancla
        item["anchors_count"] = len(anchors)
        coverage = row.get("coverage")
        if isinstance(coverage, dict) and "level" in coverage:
            item["coverage_level"] = coverage["level"]
    item["text_bytes"] = len(text.encode("utf-8"))
    if with_text:
        item["text"] = text
    if item["enqueued_at"] is None:
        item["legacy"] = True
    return item


def _response(
    revision: str, filters: Mapping[str, Any], items: list[dict[str, Any]], total: int, limited: int, used: int,
    next_cursor: str | None,
) -> dict[str, Any]:
    by_limit = total - limited
    by_budget = limited - len(items)
    return {
        "schema": RESULT_SCHEMA,
        "untrusted_memory_data": True,
        "revision": revision,
        "filters": dict(filters),
        "items": items,
        "total": total,
        "returned": len(items),
        "truncated": by_limit + by_budget > 0,
        "excluded": {"limit": by_limit, "budget": by_budget},
        "next": next_cursor,
        "used_bytes": used,
    }


def list_records(
    snapshot: Any, *, streams: str = DEFAULT_STREAMS, status: str = "active", kind: str | None = None,
    slot: str | None = None, limit: int = DEFAULT_LIMIT, budget: int = DEFAULT_BUDGET, after: str | None = None,
    text: bool = False,
) -> dict[str, Any]:
    """``list-result-v1`` de la revisión de ``snapshot``.

    ``total`` cuenta los registros que pasan los filtros y quedan después del cursor, de modo que
    ``total = returned + excluded.limit + excluded.budget`` en cada página.
    """

    filters = _filters(streams, status, kind, slot, limit, budget, text)
    revision = snapshot.revision_id
    start = None
    if after is not None:
        cursor_revision, start = decode_cursor(after, filters)
        if cursor_revision != revision:
            raise StateReadError("list_cursor_stale", "la revisión cambió: vuelve a empezar sin --after")
    names = filters["streams"]
    replaced, disputes = _superseded_by(snapshot), _disputes_count(snapshot)
    items: list[tuple[tuple[int, int, str, str], dict[str, Any]]] = []
    for stream in names:
        for row in snapshot.records[stream]:
            item = _item(stream, row, replaced, disputes, filters["text"])
            if status != "all" and item["status"] != status:
                continue
            if kind is not None and item["kind"] != kind:
                continue
            if slot is not None and item["slot"] != slot:
                continue
            items.append((_sort_key(item, names), item))
    items.sort(key=lambda pair: pair[0])
    if start is not None:
        items = [pair for pair in items if pair[0] > start]
    total = len(items)
    limited = items[:filters["limit"]]

    def build(count: int, used: int) -> dict[str, Any]:
        kept = limited[:count]
        more = count < total
        last = kept[-1][0] if kept else start  # sin ningún registro devuelto el cursor no avanza
        cursor = encode_cursor(revision, filters, last) if more else None
        return _response(revision, filters, [item for _, item in kept], total, len(limited), used, cursor)

    return dict(fit_prefix(build, len(limited), filters["budget"], "list_budget_too_small"))


__all__ = ["DEFAULT_BUDGET", "DEFAULT_LIMIT", "MAX_LIMIT", "RESULT_SCHEMA", "list_records"]
