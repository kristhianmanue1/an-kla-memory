"""``state show``: el estado vigente de cada casilla, de sólo lectura (ADR-0065 §4-5).

Un registro por casilla: la cabeza (:mod:`an_kla.state_slot`) del repo actual. No vacía la bandeja, no
puntúa y no depende de ``recall`` ni de su analizador. Con dos vigentes en una casilla (sólo por
``plan-write``, restauración o ``relocate``) sirve la cabeza y declara el resto en ``conflict``: nunca elige
en silencio.

Presupuesto (``--budget``): la salida completa, con su salto de línea final, nunca lo supera. Se decide con la
longitud exacta de la respuesta serializada, con cotas superiores en lugar de los contadores aún desconocidos
(``used_bytes`` = el presupuesto, ``excluded.budget`` = el número de casillas); al final ambos son los reales.
"""

from __future__ import annotations

from typing import Any, Mapping

from .anchor_checks import has_checks
from .anchors_coverage_v2 import has_rules
from .anchors_read import DEFAULT_ANCHOR_LIMIT, AnchorServer
from .audience import Reader, explicit_scope, has_scope, is_for_other, make_reader
from .canonical import canonical_json
from .identity_c0 import DEFAULT_SLOT, SLOT_PATTERN, IdentityC0Error, repo_id_for
from .inbox import entry_names
from .inbox_entries import Reject, load_entry
from .state_slot import STATE_STREAM, StateRow, active_by_slot, state_rows

RESULT_SCHEMA = "an-kla/state-result-v1"
RESULT_SCHEMA_V2 = "an-kla/state-result-v2"  # ADR-0069 §4: sólo con `for_reader`, `subject`, `audience` o `excluded.other_audience`
DEFAULT_BUDGET = 4000
MAX_PENDING_READ = 1000


class StateReadError(ValueError):
    """Error estable de las lecturas ``state show`` y ``history``: ``str(error)`` es el código (rc 1)."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


def serialized_size(result: Mapping[str, Any]) -> int:
    """Bytes de la salida tal como el CLI la escribe: JSON canónico y salto de línea final."""

    return len(canonical_json(result)) + 1


def render(result: Mapping[str, Any]) -> bytes:
    return canonical_json(result) + b"\n"


def current_repo_id(store: Any) -> str:
    try:
        return repo_id_for(store.project_root)
    except IdentityC0Error as exc:
        raise StateReadError("state_repo_unavailable", "state show exige un repo Git en --project-root") from exc


def pending_states(store: Any, repo_id: str) -> tuple[int, dict[str, int]]:
    """Entradas de la bandeja y, por casilla, cuántas son ``state`` del repo (se leen sin vaciar nada)."""

    names = entry_names(store)
    per_slot: dict[str, int] = {}
    for name in names[:MAX_PENDING_READ]:
        try:
            entry = load_entry(store, name)
        except Reject:
            continue
        if entry is None or entry.slot is None:
            continue
        if entry.envelope["writer"]["repo"]["id"] == repo_id:
            per_slot[entry.slot] = per_slot.get(entry.slot, 0) + 1
    return len(names), per_slot


def _entry(
    head: StateRow, actives: list[StateRow], retired_count: int, pending: int, with_repo: bool, served: Mapping[str, Any]
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "slot": head.slot,
        "id": head.id,
        "text": head.text if isinstance(head.text, str) else "",
        "writer": dict(head.writer),
        "enqueued_at": head.enqueued_at,
        "retired_count": retired_count,
        "pending_states": pending,
    }
    if with_repo:
        item["repo_id"] = head.repo_id
    if len(actives) > 1:
        item["conflict"] = [m.id for m in actives]
    item.update(served)  # ADR-0066: disputed, anchors with their freshness, coverage
    return item


def _stub(item: Mapping[str, Any]) -> dict[str, Any]:
    stub = {"slot": item["slot"], "id": item["id"], "enqueued_at": item["enqueued_at"], "truncated": True}
    if "repo_id" in item:
        stub["repo_id"] = item["repo_id"]
    return stub


def _response(
    revision: str, scope: str, slots: list[dict[str, Any]], excluded: int, inbox_pending: int,
    used: int, empty: bool, declared: Mapping[str, Any] | None = None, other: int = 0, scoped: bool = False,
) -> dict[str, Any]:
    return {
        **(declared or {}),
        "schema": RESULT_SCHEMA_V2 if scoped or other else RESULT_SCHEMA,  # ADR-0069 §4: v2 disperso
        "untrusted_memory_data": True,
        "revision": revision,
        "scope": scope,
        "inbox": {"pending": inbox_pending},
        "slots": slots,
        "excluded": {"budget": excluded, **({"other_audience": other} if other else {})},
        "used_bytes": used,
        "empty": empty,
    }


def fit_budget(
    revision: str, scope: str, items: list[dict[str, Any]], inbox_pending: int, budget: int, empty: bool,
    declared: Mapping[str, Any] | None = None, other: int = 0,
) -> dict[str, Any]:
    """Respuesta que cabe en ``budget`` bytes: entrada completa, si no su stub, si no ``excluded.budget``."""

    total = len(items)
    scoped = any(key in item for item in items for key in ("for_reader", "subject", "audience")) or any(has_rules(i) or has_checks(i) for i in items)
    # Cotas superiores mientras los contadores no se conocen (used_bytes = presupuesto; excluded = todas).
    floor = _response(revision, scope, [], total, inbox_pending, budget, empty, declared, other, scoped)
    if serialized_size(floor) > budget:
        raise StateReadError("state_budget_too_small", f"la respuesta vacía necesita {serialized_size(floor)} bytes")
    kept: list[dict[str, Any]] = []
    for item in items:
        for candidate in (item, _stub(item)):
            trial = _response(revision, scope, kept + [candidate], total, inbox_pending, budget, empty, declared, other, scoped)
            if serialized_size(trial) <= budget:
                kept.append(candidate)
                break
    excluded = total - len(kept)
    used = budget
    for _ in range(8):  # punto fijo: used_bytes es la longitud de la salida que lo contiene
        result = _response(revision, scope, kept, excluded, inbox_pending, used, empty, declared, other, scoped)
        size = serialized_size(result)
        if size == used:
            return result
        used = size
    return _response(revision, scope, kept, excluded, inbox_pending, budget, empty, declared, other, scoped)


def state_show(
    store: Any,
    *,
    slot: str | None = None,
    all_slots: bool = False,
    scope: str = "repo",
    budget: int = DEFAULT_BUDGET,
    repo_id: str | None = None,
    anchor_limit: int = DEFAULT_ANCHOR_LIMIT,
    reader: Reader | None = None,
) -> dict[str, Any]:
    """``state-result-v1`` de la revisión vigente. ``slot`` y ``all_slots`` son excluyentes (``main`` por defecto).

    ``reader`` (ADR-0069 §4): quien lee. Una casilla cuya cabeza es para otro no sale y cuenta en
    ``excluded.other_audience`` (con ``reader.include_other`` sale marcada ``for_reader: false``); el ``state``
    anterior no ocupa su lugar: la cabeza es la que es."""

    if slot is not None and all_slots:
        raise StateReadError("state_slot_conflict", "--slot y --all-slots son excluyentes")
    if slot is not None and not SLOT_PATTERN.fullmatch(slot):
        raise StateReadError("state_slot_invalid", "slot: [a-z][a-z0-9_-]{0,31}")
    if scope not in ("repo", "all"):
        raise StateReadError("state_scope_invalid", "repo|all")
    if isinstance(budget, bool) or not isinstance(budget, int) or budget <= 0:
        raise StateReadError("state_budget_invalid", "entero positivo")
    repo = repo_id if repo_id is not None else current_repo_id(store)
    try:
        snapshot = store.snapshot()
    except OSError:
        raise StateReadError("storage_io_failed") from None
    rows = state_rows(snapshot, repo_id=repo if scope == "repo" else None)
    inbox_pending, per_slot = pending_states(store, repo)
    wanted = None if all_slots else (slot or DEFAULT_SLOT)
    items: list[dict[str, Any]] = []
    scope_reader = reader if reader is not None else make_reader(store)
    other_count = 0
    server = AnchorServer(store, snapshot, anchor_limit)
    # Con scope `all` una casilla es (repo, slot): se agrupa por ambos y se ordena por slot y repo.
    groups: dict[tuple[str, str], list[StateRow]] = {}
    for member in rows:
        groups.setdefault((member.repo_id, member.slot), []).append(member)
    for (group_repo, group_slot), members in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        if wanted is not None and group_slot != wanted:
            continue
        actives = active_by_slot(members).get(group_slot, [])
        if not actives:
            continue
        retired = sum(1 for m in members if not m.active)
        pending = per_slot.get(group_slot, 0) if group_repo == repo else 0
        head = actives[-1]
        marks: dict[str, Any] = {}
        if has_scope(head.row):  # ADR-0069 §4: un registro sin los campos nuevos nunca se filtra
            other = is_for_other(head.row, scope_reader)
            if other and not scope_reader.include_other:
                other_count += 1
                continue
            if other:
                marks = {"for_reader": False, **explicit_scope(head.row)}
        items.append(_entry(head, actives, retired, pending, scope == "all", {**server.serve(STATE_STREAM, head.row), **marks}))
    with server:
        declared = server.declare()
    return fit_budget(snapshot.revision_id, scope, items, inbox_pending, budget, not items, declared, other_count)


__all__ = ["DEFAULT_BUDGET", "RESULT_SCHEMA", "StateReadError", "render", "serialized_size", "state_show"]
