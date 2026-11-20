"""``history <id>``: la cadena de sustituciones y disputas de un registro, de sólo lectura (ADR-0065 §6).

Grafo: nodos = registros de la revisión; aristas dirigidas ``supersedes`` (de ``supersedes_map``, nuevo →
antiguo, incluida la jubilación por casilla) y ``disputes`` (del campo ``disputes``, disputa → target). Se
recorre en anchura desde ``<id>`` por las aristas en los dos sentidos, con conjunto de visitados (un ciclo no se
recorre dos veces). Una arista sólo existe si sus dos extremos están en la revisión (una colgante no crea nodo ni
arista) y, tras la poda por ``--limit`` o por presupuesto, si sus dos extremos siguen en ``nodes``.

Orden total de ``nodes``: ``enqueued_at`` ascendente, los legados (sin sobre válido) después y por ``id``. El
orden de expansión es el de los nodos ordenados, así que el corte por ``--limit`` también es determinista.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Mapping

from datetime import datetime
from typing import Callable

from . import directive as directive_mod
from .anchors_conversation import ConversationVerifier
from .anchors_read import AnchorServer
from .audience import Reader, explicit_scope, has_scope, is_for_other, make_reader
from .directive import DirectiveReader
from .disputes import _valid_disputes
from .identity_c0 import validate_envelope
from .read_budget import fit_prefix
from .state_show import StateReadError
from .state_slot import slot_of
from .store import STREAMS

RESULT_SCHEMA = "an-kla/history-result-v1"
RESULT_SCHEMA_V2 = "an-kla/history-result-v2"  # ADR-0069 §4: sólo con `for_reader`, `subject`, `audience` o `directive`
SCOPE_NODE_KEYS = ("for_reader", "subject", "audience", "directive")
DEFAULT_LIMIT = 200
DEFAULT_BUDGET = 16000
_STREAM_KIND = {"facts": "fact", "events": "event", "episodes": "state"}
Node = tuple[str, str]  # (stream, id)


def _status(row: Mapping[str, Any]) -> str:
    value = row.get("status", row.get("nu", "vigente"))
    if value is None or value in ("vigente", "active"):
        return "active"
    return "refuted" if value == "refutada" else "superseded"


def _describe(stream: str, row: Mapping[str, Any]) -> dict[str, Any]:
    envelope = row.get("an_kla_envelope")
    valid = isinstance(envelope, dict) and not validate_envelope(envelope)
    kind = envelope["kind"] if valid else _STREAM_KIND[stream]
    slot = slot_of(row) if valid and kind == "state" and stream == "episodes" else None
    return {
        "id": str(row.get("id", "")),
        "kind": kind,
        "stream": stream,
        "slot": slot,
        "writer": dict(envelope["writer"]) if valid else None,
        "enqueued_at": envelope["enqueued_at"] if valid else None,
        "status": _status(row),
    }


def _order(node: Mapping[str, Any]) -> tuple[int, str, str, str]:
    stamp = node["enqueued_at"]
    return (0 if stamp is not None else 1, stamp or "", node["id"], node["stream"])


def _graph(snapshot: Any) -> tuple[dict[Node, dict[str, Any]], set[tuple[Node, Node, str]]]:
    nodes: dict[Node, dict[str, Any]] = {}
    for stream in STREAMS:
        for row in snapshot.records[stream]:
            nodes[(stream, str(row.get("id", "")))] = _describe(stream, row)
    edges: set[tuple[Node, Node, str]] = set()
    for entry in snapshot.manifest.get("supersedes_map", []):
        if not isinstance(entry, dict) or entry.get("stream") not in STREAMS:
            continue
        old, new = (entry["stream"], entry.get("target_id")), (entry["stream"], entry.get("sustituida_por"))
        if old in nodes and new in nodes:
            edges.add((new, old, "supersedes"))
    for stream in STREAMS:
        for row in snapshot.records[stream]:
            disputes = row.get("disputes")
            if not _valid_disputes(disputes):
                continue
            source, target = (stream, str(row.get("id", ""))), (disputes["stream"], disputes["target_id"])
            if source in nodes and target in nodes:
                edges.add((source, target, "disputes"))
    return nodes, edges


def _walk(nodes: dict[Node, dict[str, Any]], edges: set[tuple[Node, Node, str]], start: Node, limit: int) -> tuple[list[Node], bool]:
    """BFS en los dos sentidos; ``(visitados, truncated)``. Vecinos en orden total de nodos."""

    neighbours: dict[Node, set[Node]] = {}
    for source, target, _ in edges:
        neighbours.setdefault(source, set()).add(target)
        neighbours.setdefault(target, set()).add(source)
    visited = [start]
    seen = {start}
    queue = deque([start])
    truncated = False
    while queue:
        current = queue.popleft()
        for other in sorted(neighbours.get(current, ()), key=lambda n: _order(nodes[n])):
            if other in seen:
                continue
            if len(visited) >= limit:
                truncated = True
                continue
            seen.add(other)
            visited.append(other)
            queue.append(other)
    return visited, truncated


def _response(
    revision: str, root: str, nodes: list[dict[str, Any]], edges: list[dict[str, str]], truncated: bool, used: int,
    declared: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    scoped = any(key in node for node in nodes for key in SCOPE_NODE_KEYS)
    return {
        **(declared or {}),
        "schema": RESULT_SCHEMA_V2 if scoped else RESULT_SCHEMA,  # ADR-0069 §4: v2 disperso
        "untrusted_memory_data": True,
        "revision": revision,
        "root": root,
        "nodes": nodes,
        "edges": edges,
        "truncated": truncated,
        "used_bytes": used,
    }


def _edges_among(kept: set[Node], edges: set[tuple[Node, Node, str]]) -> list[dict[str, str]]:
    rows = {(a[1], b[1], kind) for a, b, kind in edges if a in kept and b in kept}
    return [{"from": a, "to": b, "type": kind} for a, b, kind in sorted(rows)]


def history(
    snapshot: Any, record_id: str, *, limit: int = DEFAULT_LIMIT, budget: int = DEFAULT_BUDGET,
    anchors: AnchorServer | None = None, reader: Reader | None = None, store: Any = None,
    clock: Callable[[], datetime] | None = None, verifier: ConversationVerifier | None = None,
) -> dict[str, Any]:
    """``history-result-v1`` de ``record_id``: nodos y aristas de su componente, acotados por ``limit`` y ``budget``.

    ``history`` audita: no filtra, marca (ADR-0069 §4). Cada registro para otro lleva ``for_reader: false``; ``subject``
    y ``audience`` salen siempre que sean explícitos, y una ``directive`` lleva su objeto con su ``status``."""

    if not isinstance(record_id, str) or not record_id:
        raise StateReadError("history_id_invalid", "id no vacío")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise StateReadError("history_limit_invalid", "entero positivo")
    if isinstance(budget, bool) or not isinstance(budget, int) or budget <= 0:
        raise StateReadError("history_budget_invalid", "entero positivo")
    nodes, edges = _graph(snapshot)
    starts = [key for key in nodes if key[1] == record_id]
    if not starts:
        raise StateReadError("history_id_not_found")
    if len(starts) > 1:
        raise StateReadError("history_id_ambiguous", "el id está en más de un stream")
    visited, truncated = _walk(nodes, edges, starts[0], limit)
    ordered = sorted(visited, key=lambda n: _order(nodes[n]))
    revision = snapshot.revision_id
    scope_reader = reader if reader is not None else make_reader(store)
    directives = DirectiveReader(store, snapshot, scope_reader, clock=clock, verifier=verifier)
    by_node = {(s, str(r.get("id", ""))): r for s in STREAMS for r in snapshot.records[s]}
    for node in ordered:  # ADR-0069 §4: sólo lo que trae ámbito explícito o es una directive se marca
        row = by_node.get(node)
        if row is None or not (has_scope(row) or directive_mod.is_directive(row)):
            continue
        other = is_for_other(row, scope_reader)
        nodes[node].update(explicit_scope(row))
        if other:
            nodes[node]["for_reader"] = False
        if directive_mod.is_directive(row):
            view = directives.render(node[0], row, freshness=False)
            nodes[node]["directive"] = {**view, "actionable": False} if other else view
    declared: dict[str, int] = {}
    if anchors is not None:  # ADR-0066 §4: freshness of the anchors of what is served, in serving order
        rows = {(s, str(r.get("id", ""))): r for s in STREAMS for r in snapshot.records[s]}
        for node in ordered:
            nodes[node].update(anchors.serve(node[0], rows[node]))
        declared = anchors.declare()

    def build(count: int, used: int) -> dict[str, Any]:
        kept = ordered[:count]
        return _response(
            revision, record_id, [nodes[n] for n in kept], _edges_among(set(kept), edges),
            truncated or count < len(ordered), used, declared,
        )

    return dict(fit_prefix(build, len(ordered), budget, "history_budget_too_small"))


__all__ = ["DEFAULT_BUDGET", "DEFAULT_LIMIT", "RESULT_SCHEMA", "history"]
