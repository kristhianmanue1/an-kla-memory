"""Deterministic beta retrieval with a byte budget."""

from __future__ import annotations

from datetime import datetime, timezone
import contextlib
from contextlib import nullcontext
import contextvars
import re
import sqlite3
from typing import Any, Callable, Iterator, Mapping

from . import directive as directive_mod
from .anchors_conversation import ConversationVerifier
from .audience import Reader, explicit_scope, has_scope, is_for_other, make_reader
from .canonical import canonical_json
from .directive import DirectiveReader
from .index import (
    INDEX_PROFILE,
    detect_fts5,
    index_integrity_status,
    index_resolution,
    record_text,
)
from .store import MemoryStore, STREAMS
from .reader_gate import shared_reader_gate
from .vigency import is_active
from .temporal import (
    FRESHNESS_PROFILE,
    FRESHNESS_SEMANTICS,
    FRESHNESS_SOURCE_FIELD,
    TemporalError,
    format_utc,
    normalize_freshness_now,
    project_record_freshness,
    summarize_freshness,
    validate_stale_after_days,
)


TOKEN = re.compile(r"[\w]+", re.UNICODE)
SCAN_PROFILE = "scan-fallback/v1"
SUPPORTED_PROFILES = frozenset({SCAN_PROFILE, INDEX_PROFILE})
# Default keeps the historical beta contract so existing consumers (e.g.
# argos-epistemic) keep seeing ``streams_searched == ["facts"]``.  Multi-stream
# retrieval is opt-in via the ``streams`` argument.
DEFAULT_STREAMS = ("facts",)
EXCLUDED_DETAIL_CAP = 50


def _terms(text: str) -> set[str]:
    return {item.casefold() for item in TOKEN.findall(text)}


def _render(record: Mapping[str, Any]) -> str:
    return record_text(dict(record))


def _match_clause(query: str) -> str | None:
    tokens = TOKEN.findall(query)
    return " OR ".join(f'"{token}"' for token in tokens) if tokens else None


_INJECT: contextvars.ContextVar[bool] = contextvars.ContextVar("an_kla_inject_surface", default=False)


@contextlib.contextmanager
def injecting() -> Iterator[None]:
    """Marca las lecturas de dentro como de una superficie que inyecta texto (``assemble-context``, ``resume``).

    Una variable de contexto y no un argumento: esas superficies conservan la llamada de tres argumentos a ``retrieve``
    que sus consumidores envuelven o sustituyen (la ruta exacta de beta.8)."""

    token = _INJECT.set(True)
    try:
        yield
    finally:
        _INJECT.reset(token)


EMPTY_REASON_NO_LEXICAL_OVERLAP = "no_lexical_overlap"
SCOPE_EXCLUSIONS = ("other_audience", "directive_inactive", "directive_not_injected")
SCOPE_ITEM_KEYS = ("directive", "for_reader", "subject", "audience")


def is_scope_visible(excluded_summary: Mapping[str, Any], records: Any) -> bool:
    """True si la respuesta lleva alguna clave de ADR-0069: sólo entonces sube a ``retrieval-result-v4`` (o ``mcp-retrieve-v4``)."""

    return any(key in excluded_summary for key in SCOPE_EXCLUSIONS) or any(
        key in item for item in records for key in SCOPE_ITEM_KEYS
    )


def empty_reason_for(
    result: Mapping[str, Any], *, transport_budget_excluded: int = 0
) -> str | None:
    """ADR-0049 §3: señal única de selección vacía por cero solapamiento.

    Tabla de verdad: emite ``no_lexical_overlap`` sólo cuando la selección
    está vacía, hubo al menos un registro activo con score 0 y no hubo
    exclusión por presupuesto (ni de base ni de transporte). Los estados
    *puros* all-inactive/no_text/invalid_record y el store vacío no emiten
    — la causa real es otra; una **mezcla** con ``zero_score >= 1`` sí
    emite (hubo solapamiento cero en registros sanos).
    """

    if result.get("selected"):
        return None
    if transport_budget_excluded:
        return None
    summary = result.get("excluded_summary") or {}
    if "budget" in summary:
        return None
    if summary.get("zero_score", 0) < 1:
        return None
    return EMPTY_REASON_NO_LEXICAL_OVERLAP


def _narrow_with_index(
    index_path: Any, revision_id: str, clause: str, streams: tuple[str, ...]
) -> set[str] | None:
    try:
        con = sqlite3.connect(f"file:{index_path}?mode=ro", uri=True)
        try:
            claimed = con.execute("SELECT value FROM metadata WHERE key = ?", ("revision",)).fetchone()
            if not claimed or claimed[0] != revision_id:
                return None
            narrowed: set[str] = set()
            for stream in streams:
                table = f"{stream}_fts"
                try:
                    rows = con.execute(
                        f"SELECT id FROM {table} WHERE {table} MATCH ?", (clause,)
                    ).fetchall()
                except sqlite3.DatabaseError:
                    # Index v1 only exposed ``facts_fts``; missing tables for
                    # other streams degrade to scan for those streams.
                    continue
                narrowed.update(str(row[0]) for row in rows)
            return narrowed
        finally:
            con.close()
    except sqlite3.DatabaseError:
        return None


def _retrieve_under_gate(
    store: MemoryStore,
    query: str,
    budget: int,
    *,
    fixed_overhead_bytes: int = 0,
    per_record_overhead_bytes: int = 0,
    profile: str = SCAN_PROFILE,
    streams: tuple[str, ...] | list[str] | None = None,
    freshness_profile: str | None = None,
    now: datetime | None = None,
    stale_after_days: int | None = None,
    revision_id: str | None = None,
    reader: Reader | None = None,
    clock: Callable[[], datetime] | None = None,
    verifier: ConversationVerifier | None = None,
    inject: bool = False,
) -> dict[str, Any]:
    """Retrieve deterministically, reserving any caller-owned envelope cost.

    ``reader`` (ADR-0069 §4) is who reads: by default the C0 identity of the environment.  What is for another
    audience or subject is not served (``excluded_summary.other_audience``) unless ``reader.include_other``; a
    ``directive`` carries its object (§5).  ``inject`` is for the surfaces that inject text (``assemble-context``,
    ``resume``): they never serve a ``directive`` (``directive_not_injected``).

    ``fixed_overhead_bytes`` and ``per_record_overhead_bytes`` let a transport
    reserve its JSON wrapper before selection.  They must be conservative: the
    transport remains responsible for proving its serialized response fits.

    ``streams`` selects which record streams are scanned.  Defaults to
    ``("facts",)`` to preserve the historical beta contract; pass e.g.
    ``("facts", "events", "episodes")`` for multi-stream retrieval.
    """

    if budget < 0:
        raise ValueError("negative_budget")
    if fixed_overhead_bytes < 0 or per_record_overhead_bytes < 0:
        raise ValueError("negative_overhead")
    if fixed_overhead_bytes > budget:
        raise ValueError("fixed_overhead_exceeds_budget")
    if profile not in SUPPORTED_PROFILES:
        raise ValueError("unsupported_retrieval_profile")
    freshness_now: datetime | None = None
    freshness_threshold: int | None = None
    if freshness_profile is None:
        if now is not None or stale_after_days is not None:
            raise TemporalError("freshness_profile_required")
    elif freshness_profile != FRESHNESS_PROFILE:
        raise TemporalError("unsupported_freshness_profile")
    else:
        freshness_now = normalize_freshness_now(
            datetime.now(timezone.utc) if now is None else now
        )
        freshness_threshold = validate_stale_after_days(stale_after_days)
    selected_streams = tuple(streams) if streams is not None else DEFAULT_STREAMS
    if not selected_streams or any(s not in STREAMS for s in selected_streams):
        raise ValueError("unsupported_retrieval_stream")
    # De-duplicate while preserving caller order: ``--streams facts,facts``
    # must not produce duplicate records in the output.
    seen_streams: set[str] = set()
    deduped: list[str] = []
    for s in selected_streams:
        if s not in seen_streams:
            seen_streams.add(s)
            deduped.append(s)
    selected_streams = tuple(deduped)
    snapshot = store.snapshot() if revision_id is None else store.snapshot(revision_id)
    query_terms = _terms(query)
    ranked: list[tuple[int, str, Mapping[str, Any], str, str]] = []
    excluded: dict[str, int] = {
        "inactive": 0,
        "zero_score": 0,
        "budget": 0,
        "invalid_record": 0,
        "no_text": 0,
        "other_audience": 0,
        "directive_inactive": 0,
        "directive_not_injected": 0,
    }
    scope_reader = reader if reader is not None else make_reader(store)
    inject = inject or _INJECT.get()
    directives: DirectiveReader | None = None
    served_extra: dict[str, dict[str, Any]] = {}
    # Track IDs for every exclusion reason so the operator can debug silent
    # drops uniformly; counters without an entry here simply aren't tracked.
    excluded_detail: dict[str, list[str]] = {
        "inactive": [],
        "zero_score": [],
        "budget": [],
        "invalid_record": [],
        "no_text": [],
        "other_audience": [],
        "directive_inactive": [],
        "directive_not_injected": [],
    }

    def exclude(reason: str, record: Mapping[str, Any]) -> None:
        excluded[reason] += 1
        if len(excluded_detail[reason]) < EXCLUDED_DETAIL_CAP:
            excluded_detail[reason].append(str(record.get("id", "")))

    for stream in selected_streams:
        for record in snapshot.records[stream]:
            if not is_active(record):
                excluded["inactive"] += 1
                if len(excluded_detail["inactive"]) < EXCLUDED_DETAIL_CAP:
                    excluded_detail["inactive"].append(str(record.get("id", "")))
                continue
            if not record.get("id"):
                excluded["invalid_record"] += 1
                continue
            is_directive = directive_mod.is_directive(record)
            if is_directive or has_scope(record):  # ADR-0069 §4: un registro sin los campos nuevos nunca se filtra
                other = is_for_other(record, scope_reader)
                if other and not scope_reader.include_other:
                    exclude("other_audience", record)
                    continue
                if is_directive and inject:
                    exclude("directive_not_injected", record)
                    continue
                served_extra[str(record["id"])] = {"other": other, "directive": is_directive}
            rendered = _render(record)
            if not rendered:
                excluded["no_text"] += 1
                if len(excluded_detail["no_text"]) < EXCLUDED_DETAIL_CAP:
                    excluded_detail["no_text"].append(str(record["id"]))
                continue
            score = len(query_terms & _terms(rendered))
            identifier = str(record["id"])
            ranked.append((score, identifier, record, rendered, stream))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    # #118/R3: única contabilidad de zero-score, post-sort y previa al
    # narrowing del índice — scan e índice cuentan el mismo conjunto y el
    # detalle conserva el orden determinista (-score, id) de ADR-0015.
    scored: list[tuple[int, str, Mapping[str, Any], str, str]] = []
    for score, identifier, record, rendered, stream in ranked:
        if score == 0:
            excluded["zero_score"] += 1
            if len(excluded_detail["zero_score"]) < EXCLUDED_DETAIL_CAP:
                excluded_detail["zero_score"].append(identifier)
            continue
        scored.append((score, identifier, record, rendered, stream))
    ranked = scored
    actual_profile = SCAN_PROFILE
    degradation = "none"
    clause = _match_clause(query)
    if profile == INDEX_PROFILE and query_terms and clause:
        if not detect_fts5():
            degradation = "fts5_unavailable"
        else:
            resolution = index_resolution(store, snapshot.revision_id)
            degradation = resolution.status
            if resolution.path is not None:
                integrity = index_integrity_status(resolution.path)
                if integrity != "none":
                    degradation = integrity
                else:
                    narrowed = _narrow_with_index(
                        resolution.path, snapshot.revision_id, clause, selected_streams
                    )
                    if narrowed is None:
                        degradation = "index_unresolvable"
                    elif any(
                        score > 0 and identifier not in narrowed
                        for score, identifier, _record, _rendered, _stream in ranked
                    ):
                        degradation = "index_candidate_mismatch"
                    else:
                        ranked = [item for item in ranked if item[1] in narrowed]
                        actual_profile = INDEX_PROFILE
                        degradation = "none"
    selected: list[dict[str, Any]] = []
    used = fixed_overhead_bytes
    for score, identifier, _record, rendered, stream in ranked:
        added: dict[str, Any] = {}
        info = served_extra.get(identifier)
        if info is not None:  # ADR-0069 §5: the directive object and the marks of what is for another reader
            if info["directive"]:
                if directives is None:
                    directives = DirectiveReader(store, snapshot, scope_reader, clock=clock, verifier=verifier)
                view = directives.render(stream, _record)
                if view["status"] in directive_mod.INACTIVE:
                    exclude("directive_inactive", _record)
                    continue
                if info["other"]:
                    view["actionable"] = False
                added["directive"] = view
            if info["other"]:
                added["for_reader"] = False
                if not info["directive"]:
                    added.update(explicit_scope(_record))
        # ADR-0069 §6: what the record gains counts in its cost, so an exact budget stays exact
        cost = len(rendered.encode("utf-8")) + (len(canonical_json(added)) if added else 0) + per_record_overhead_bytes
        if used + cost > budget:
            excluded["budget"] += 1
            if len(excluded_detail["budget"]) < EXCLUDED_DETAIL_CAP:
                excluded_detail["budget"].append(identifier)
            continue
        item = {
            "id": identifier,
            "stream": stream,
            "score": score,
            "render": rendered,
            "cost_bytes": cost,
        }
        item.update(added)
        if freshness_now is not None:
            item.update(
                project_record_freshness(
                    _record,
                    freshness_now,
                    freshness_threshold,
                )
            )
        selected.append(item)
        used += cost
    if directives is not None:
        directives.close()
    excluded_summary = {key: value for key, value in excluded.items() if value}
    truncated: dict[str, bool] = {}
    visible_detail: dict[str, list[str]] = {}
    for key, ids in excluded_detail.items():
        if not ids:
            continue
        truncated[key] = excluded[key] > len(ids)
        visible_detail[key] = ids
    result = {
        "schema": "an-kla/retrieval-result-v1",
        "revision": snapshot.revision_id,
        "requested_profile": profile,
        "profile": actual_profile,
        "degradation": degradation,
        "streams_searched": list(selected_streams),
        "budget_bytes": budget,
        "used_bytes": used,
        "reserved_overhead_bytes": {
            "fixed": fixed_overhead_bytes,
            "per_record": per_record_overhead_bytes,
        },
        "excluded_summary": excluded_summary,
        "excluded_detail": {
            "ids": visible_detail,
            "truncated": truncated,
            "cap": EXCLUDED_DETAIL_CAP,
        },
        "selected": selected,
    }
    if freshness_now is not None:
        result["freshness_profile"] = FRESHNESS_PROFILE
        result["freshness"] = {
            "semantics": FRESHNESS_SEMANTICS,
            "source_field": FRESHNESS_SOURCE_FIELD,
            "computed_at": format_utc(freshness_now),
            "stale_after_days": freshness_threshold,
            **summarize_freshness(selected),
        }
    # ADR-0049: v3 disperso — el id sube a v3 sólo por la ruta empty_reason;
    # v1/v2 permanecen byte-idénticos en todos los demás casos.
    reason = empty_reason_for(result)
    if reason is not None:
        result["empty_reason"] = reason
        result["schema"] = "an-kla/retrieval-result-v3"
    elif freshness_now is not None:
        result["schema"] = "an-kla/retrieval-result-v2"
    if is_scope_visible(excluded_summary, selected):  # ADR-0069 §6: v4 disperso, superconjunto de v1-v3
        result["schema"] = "an-kla/retrieval-result-v4"
    return result


def retrieve(
    store: MemoryStore,
    query: str,
    budget: int,
    *,
    fixed_overhead_bytes: int = 0,
    per_record_overhead_bytes: int = 0,
    profile: str = SCAN_PROFILE,
    streams: tuple[str, ...] | list[str] | None = None,
    freshness_profile: str | None = None,
    now: datetime | None = None,
    stale_after_days: int | None = None,
    revision_id: str | None = None,
    reader: Reader | None = None,
    clock: Callable[[], datetime] | None = None,
    verifier: ConversationVerifier | None = None,
    inject: bool = False,
) -> dict[str, Any]:
    """Hold the archival reader lease through scan and index consumption."""

    gate = shared_reader_gate(store) if hasattr(store, "root") else nullcontext()
    with gate:
        return _retrieve_under_gate(
            store,
            query,
            budget,
            fixed_overhead_bytes=fixed_overhead_bytes,
            per_record_overhead_bytes=per_record_overhead_bytes,
            profile=profile,
            streams=streams,
            freshness_profile=freshness_profile,
            now=now,
            stale_after_days=stale_after_days,
            revision_id=revision_id,
            reader=reader,
            clock=clock,
            verifier=verifier,
            inject=inject,
        )
