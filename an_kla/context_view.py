"""Deterministic G-VIEW core shared by its public adapters (ADR-0034)."""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Mapping, Sequence

from .canonical import bare_digest, canonical_json, digest_bytes, digest_json, exact_sized_payload
from .record_text import record_text
from .reader_gate import ReaderGateError
from .reader_gate import shared_reader_gate
from .store import STREAMS, IntegrityError, MemoryStore, Snapshot
from .subject_ref import SubjectRefError, parse_subject_ref
from .temporal import (
    FRESHNESS_SEMANTICS,
    FRESHNESS_SOURCE_FIELD,
    TemporalError,
    compute_freshness,
    format_utc,
    parse_freshness_now,
    validate_stale_after_days,
)


CONTRACT_VERSION = "g-view/v1"
SUCCESS_SCHEMA = "an-kla/context-view-v1"
ERROR_SCHEMA = "an-kla/view-error-v1"
PROJECTIONS = ("metadata", "text", "full")
DEFAULT_STREAMS = STREAMS
DEFAULT_LIMIT = 50
DEFAULT_BUDGET_BYTES = 65536
MAX_BUDGET_BYTES = 1_000_000_000
MAX_CURSOR_CHARS = 16_384
_MISSING = object()


class ContextViewError(ValueError):
    """Stable invalid-input error raised before snapshot I/O."""

    def __init__(self, detail: str) -> None:
        super().__init__("view_invalid_inputs")
        self.code = "view_invalid_inputs"
        self.detail = detail


def _error(code: str, *, retryable: bool = False, **fields: Any) -> dict[str, Any]:
    return {
        "schema": ERROR_SCHEMA,
        "ok": False,
        "code": code,
        "retryable": retryable,
        "untrusted_memory_data": True,
        **fields,
    }


def _invalid(detail: str) -> dict[str, Any]:
    return _error("view_invalid_inputs", detail=detail)


def _normalize_streams(streams: Sequence[str] | None) -> tuple[str, ...]:
    if streams is None:
        return DEFAULT_STREAMS
    if not isinstance(streams, (list, tuple)) or not 1 <= len(streams) <= len(STREAMS):
        raise ContextViewError("streams")
    requested = tuple(streams)
    if any(not isinstance(value, str) or value not in STREAMS for value in requested):
        raise ContextViewError("streams")
    selected = set(requested)
    return tuple(stream for stream in STREAMS if stream in selected)


def _normalize_inputs(
    revision: Any,
    streams: Iterable[str] | None,
    subject_filter: Any,
    projection: Any,
    limit: Any,
    budget_bytes: Any,
    now: Any,
    stale_after_days: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        if not isinstance(revision, str):
            raise ValueError
        bare_digest(revision)
    except ValueError as exc:
        raise ContextViewError("revision") from exc
    selected_streams = _normalize_streams(streams)
    if subject_filter is not None:
        try:
            parse_subject_ref(subject_filter)
        except SubjectRefError as exc:
            raise ContextViewError("subject_filter") from exc
    if projection not in PROJECTIONS:
        raise ContextViewError("projection")
    if projection == "full" and subject_filter is None:
        raise ContextViewError("subject_filter")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ContextViewError("limit")
    if (
        isinstance(budget_bytes, bool)
        or not isinstance(budget_bytes, int)
        or not 1 <= budget_bytes <= MAX_BUDGET_BYTES
    ):
        raise ContextViewError("budget_bytes")
    parsed_now = None
    canonical_now = None
    if now is not None:
        try:
            parsed_now = parse_freshness_now(now)
            canonical_now = format_utc(parsed_now)
        except TemporalError as exc:
            raise ContextViewError("now") from exc
    try:
        threshold = validate_stale_after_days(stale_after_days)
    except TemporalError as exc:
        raise ContextViewError("stale_after_days") from exc
    if threshold is not None and parsed_now is None:
        raise ContextViewError("stale_after_days")
    identity = {
        "revision": revision,
        "streams": list(selected_streams),
        "subject_filter": subject_filter,
        "projection": projection,
        "now": canonical_now,
        "stale_after_days": threshold,
        "contract_version": CONTRACT_VERSION,
    }
    page = {"limit": limit, "budget_bytes": budget_bytes}
    return identity, {**page, "parsed_now": parsed_now}


def _encode_cursor(revision: str, identity_digest: str, next_subject: str) -> str:
    core = {"v": CONTRACT_VERSION, "r": revision, "ih": identity_digest, "n": next_subject}
    document = {**core, "d": digest_json(core)}
    return canonical_json(document).hex()


def _decode_cursor(cursor: Any, revision: str, identity_digest: str, subjects: list[str]) -> int:
    if cursor is None:
        return 0
    try:
        if not isinstance(cursor, str) or not cursor or len(cursor) > MAX_CURSOR_CHARS:
            raise ValueError
        document = json.loads(bytes.fromhex(cursor).decode("utf-8"))
        if not isinstance(document, dict) or set(document) != {"v", "r", "ih", "n", "d"}:
            raise ValueError
        core = {key: document[key] for key in ("v", "r", "ih", "n")}
        if canonical_json(document).hex() != cursor or document["d"] != digest_json(core):
            raise ValueError
        if document["v"] != CONTRACT_VERSION or document["r"] != revision or document["ih"] != identity_digest:
            raise ValueError
        next_subject = document["n"]
        if not isinstance(next_subject, str):
            raise ValueError
        return subjects.index(next_subject)
    except (ValueError, TypeError, UnicodeError, json.JSONDecodeError):
        raise ContextViewError("cursor") from None


def _supersede_links(snapshot: Snapshot) -> dict[tuple[str, str], list[dict[str, str]]]:
    links: dict[tuple[str, str], list[dict[str, str]]] = {}
    for entry in snapshot.manifest.get("supersedes_map", []):
        link = {
            "stream": str(entry["stream"]),
            "target_id": str(entry["target_id"]),
            "sustituida_por": str(entry["sustituida_por"]),
        }
        for record_id in (link["target_id"], link["sustituida_por"]):
            links.setdefault((link["stream"], record_id), []).append(link)
    for values in links.values():
        values.sort(key=lambda item: (item["stream"], item["target_id"], item["sustituida_por"]))
    return links


def _governed_states(snapshot: Snapshot) -> dict[tuple[str, str], str]:
    states: dict[tuple[str, str], str] = {}
    for entry in snapshot.manifest.get("supersedes_map", []):
        states[(str(entry["stream"]), str(entry["target_id"]))] = "superseded"
    refuted = {
        (str(entry["stream"]), str(entry["target_record_sha256"]))
        for entry in snapshot.manifest.get("refutations_map", [])
    }
    for stream in STREAMS:
        for raw in snapshot.raw_records[stream]:
            if (stream, digest_json(raw)) in refuted:
                states[(stream, str(raw.get("id", "")))] = "refuted"
    return states


def _physical_state(raw: Mapping[str, Any]) -> tuple[str, str, Any]:
    if "status" in raw:
        physical = raw["status"]
    elif "nu" in raw:
        physical = raw["nu"]
    else:
        physical = _MISSING
    state = (
        "active"
        if physical is _MISSING or physical is None or physical in ("vigente", "active")
        else "inactive_untrusted"
    )
    return state, "physical_status_untrusted", None if physical is _MISSING else deepcopy(physical)


def _project_record(
    raw: Mapping[str, Any], stream: str, projection: str, governed: str | None,
    links: list[dict[str, str]], now: Any, stale_after_days: int | None,
) -> dict[str, Any]:
    if governed is not None:
        _physical_state_value, _physical_source, physical = _physical_state(raw)
        state, source = governed, "governed_overlay"
    else:
        state, source, physical = _physical_state(raw)
    projected: dict[str, Any] = {
        "subject_ref": str(raw["subject_ref"]),
        "stream": stream,
        "id": str(raw.get("id", "")),
        "record_sha256": digest_json(raw),
        "state": state,
        "state_source": source,
        "physical_status_untrusted": physical,
        "lineage_refs": deepcopy(raw.get("lineage", {}).get("refs", []))
        if isinstance(raw.get("lineage"), Mapping)
        and isinstance(raw.get("lineage", {}).get("refs", []), list)
        else [],
        "supersede_links": deepcopy(links),
        "untrusted_memory_data": True,
    }
    verified_at = raw.get("verified_at")
    if isinstance(verified_at, str):
        projected["verified_at"] = verified_at
        projected["self_asserted_timestamp"] = True
    if now is not None:
        freshness = compute_freshness(verified_at, now, stale_after_days)
        projected["days_since_verified"] = freshness.get("days_since_verified")
        projected["stale"] = freshness.get("stale")
        projected["freshness_error"] = freshness.get("freshness_error")
    if projection in {"text", "full"}:
        projected["record_text"] = record_text(dict(raw))
    if projection == "full":
        projected["record_raw"] = deepcopy(dict(raw))
    return projected


def _derive(snapshot: Snapshot, streams: tuple[str, ...], subject_filter: str | None,
            projection: str, now: Any, stale_after_days: int | None) -> tuple[list[dict[str, Any]], dict[str, int], list[str]]:
    governed = _governed_states(snapshot)
    links = _supersede_links(snapshot)
    grouped: dict[str, list[dict[str, Any]]] = {}
    missing = {stream: 0 for stream in streams}
    namespaces: set[str] = set()
    for stream in streams:
        for raw in snapshot.raw_records[stream]:
            subject = raw.get("subject_ref", _MISSING)
            if subject is _MISSING:
                missing[stream] += 1
                continue
            try:
                parsed = parse_subject_ref(subject)
            except SubjectRefError:
                raise ContextViewError(f"invalid_subject_ref:{stream}:{digest_json(raw)}") from None
            if subject_filter is not None and subject != subject_filter:
                continue
            namespaces.add(parsed["namespace"])
            record_id = str(raw.get("id", ""))
            grouped.setdefault(str(subject), []).append(
                _project_record(raw, stream, projection, governed.get((stream, record_id)),
                                links.get((stream, record_id), []), now, stale_after_days)
            )
    subjects: list[dict[str, Any]] = []
    for subject_ref in sorted(grouped):
        records = grouped[subject_ref]
        alternatives = sorted(
            (item for item in records if item["state"] == "active"),
            key=lambda item: (STREAMS.index(item["stream"]), item["record_sha256"]),
        )
        history = sorted(
            (item for item in records if item["state"] != "active"),
            key=lambda item: (STREAMS.index(item["stream"]), item["record_sha256"]),
        )
        history.sort(
            key=lambda item: (
                isinstance(item.get("verified_at"), str),
                item.get("verified_at") if isinstance(item.get("verified_at"), str) else "",
            ),
            reverse=True,
        )
        texts = {item.get("record_text") for item in records if "record_text" in item}
        raw_digests = {item["record_sha256"] for item in records}
        subject_out = {
            "subject_ref": subject_ref,
            "data_conflict": len(alternatives) >= 2,
            "alternatives": alternatives,
            "history": history,
        }
        if projection == "text" and len(raw_digests) > len(texts):
            subject_out["content_differs_beyond_text"] = True
        subjects.append(subject_out)
    warnings = []
    if any(missing.values()):
        warnings.append("legacy_records_without_subject_ref")
    if len(namespaces) > 1:
        warnings.append("multiple_namespaces_observed")
    return subjects, missing, warnings


def _base_payload(identity: Mapping[str, Any], page: Mapping[str, Any], revision: str,
                  subjects: list[dict[str, Any]], missing: Mapping[str, int],
                  warnings: list[str], *, complete: bool, next_cursor: str | None,
                  served: int, total: int, truncated: int, used: int) -> dict[str, Any]:
    public_inputs = {key: deepcopy(value) for key, value in identity.items() if key != "contract_version"}
    public_inputs.update({"limit": page["limit"], "budget_bytes": page["budget_bytes"]})
    freshness = None
    if identity["now"] is not None:
        freshness = {
            "semantics": FRESHNESS_SEMANTICS,
            "source_field": FRESHNESS_SOURCE_FIELD,
            "computed_at": identity["now"],
            "stale_after_days": identity["stale_after_days"],
        }
    return {
        "schema": SUCCESS_SCHEMA,
        "contract_version": CONTRACT_VERSION,
        "serialization": "canonical-json/v1",
        "canonicality": "non-authoritative",
        "untrusted_memory_data": True,
        "host_framing_unmeasured": True,
        "live_revalidation_performed": False,
        "consumer_action_required": "revalidate_against_canonical_sources_before_action",
        "revision": revision,
        "inputs": public_inputs,
        "freshness": freshness,
        "subjects_without_subject_ref": deepcopy(dict(missing)),
        "subjects": deepcopy(subjects),
        "pagination": {
            "complete": complete,
            "next_cursor": next_cursor,
            "served_subjects": served,
            "total_subjects": total,
            "truncated_subjects": truncated,
            "budget_used_bytes": used,
            "budget_bytes": page["budget_bytes"],
            "limit": page["limit"],
        },
        "warnings": warnings,
    }


def _fixed(payload_builder: Any) -> dict[str, Any]:
    return exact_sized_payload(payload_builder)[0]


def _minimum_budget(build: Any, provided: int) -> int | None:
    lower = provided + 1
    while lower <= MAX_BUDGET_BYTES:
        width = len(str(lower))
        band_end = min(MAX_BUDGET_BYTES, 10**width - 1)
        representative = lower
        try:
            witness = _fixed(lambda used: build(representative, used))
        except ValueError:
            return None
        candidate = max(lower, len(canonical_json(witness)))
        if candidate <= band_end:
            try:
                checked = _fixed(lambda used: build(candidate, used))
            except ValueError:
                return None
            if len(canonical_json(checked)) <= candidate:
                return candidate
        lower = band_end + 1
    return None


def _context_view(
    store: MemoryStore, *, revision: str, streams: Sequence[str] | None = None,
    subject_filter: str | None = None, projection: str = "text",
    limit: int = DEFAULT_LIMIT, budget_bytes: int = DEFAULT_BUDGET_BYTES,
    cursor: str | None = None, now: str | None = None,
    stale_after_days: int | None = None, _gate_held: bool = False,
) -> dict[str, Any]:
    """Return the closed semantic result union for G-VIEW CORE."""

    try:
        identity, page = _normalize_inputs(
            revision, streams, subject_filter, projection, limit, budget_bytes,
            now, stale_after_days,
        )
    except ContextViewError as exc:
        return _invalid(exc.detail)
    selected_streams = tuple(identity["streams"])
    try:
        snapshot = store._snapshot_under_gate(revision) if _gate_held else store.snapshot(revision)
    except ReaderGateError:
        return _error("view_reader_gate_unavailable")
    except IntegrityError as exc:
        if str(exc) in {"object_missing:revisions", "revision_archived_by_compaction"}:
            return _error("view_revision_not_available")
        return _error("view_internal_error")
    try:
        subjects, missing, warnings = _derive(
            snapshot, selected_streams, subject_filter, projection,
            page["parsed_now"], identity["stale_after_days"],
        )
    except ContextViewError as exc:
        if exc.detail.startswith("invalid_subject_ref:"):
            _, stream, record_sha256 = exc.detail.split(":", 2)
            return _error(
                "view_invalid_subject_ref_in_revision",
                detail={"stream": stream, "record_sha256": record_sha256},
            )
        return _error("view_rule_ambiguous")
    except (KeyError, TypeError, ValueError):
        return _error("view_rule_ambiguous")
    identity_digest = digest_json(identity)
    refs = [item["subject_ref"] for item in subjects]
    try:
        start = _decode_cursor(cursor, revision, identity_digest, refs)
    except ContextViewError:
        return _error("view_cursor_invalid")
    total = len(subjects)

    def build(selected: list[dict[str, Any]], next_index: int, budget: int, used: int) -> dict[str, Any]:
        complete = next_index >= total
        next_value = None if complete else _encode_cursor(revision, identity_digest, refs[next_index])
        local_page = {**page, "budget_bytes": budget}
        return _base_payload(identity, local_page, revision, selected, missing, warnings,
                             complete=complete, next_cursor=next_value,
                             served=len(selected), total=total,
                             truncated=total - next_index, used=used)

    try:
        empty = _fixed(lambda used: build([], start, budget_bytes, used))
    except ValueError:
        return _error("view_internal_error")
    if len(canonical_json(empty)) > budget_bytes:
        minimum = _minimum_budget(lambda budget, used: build([], start, budget, used), budget_bytes)
        if minimum is None:
            return _error("view_budget_measurement_unavailable", provided_budget_bytes=budget_bytes, resume_cursor=cursor)
        return _error(
            "view_envelope_exceeds_budget", retryable=True, subject_ref=None,
            minimum_budget_bytes=minimum, provided_budget_bytes=budget_bytes,
            resume_cursor=cursor,
        )

    selected: list[dict[str, Any]] = []
    index = start
    while index < total and len(selected) < limit:
        candidate = [*selected, subjects[index]]
        try:
            measured = _fixed(lambda used: build(candidate, index + 1, budget_bytes, used))
        except ValueError:
            return _error("view_internal_error")
        if len(canonical_json(measured)) > budget_bytes:
            break
        selected = candidate
        index += 1
    if not selected and start < total:
        minimum = _minimum_budget(
            lambda budget, used: build([subjects[start]], start + 1, budget, used),
            budget_bytes,
        )
        if minimum is None:
            return _error("view_budget_measurement_unavailable", provided_budget_bytes=budget_bytes, resume_cursor=cursor)
        return _error(
            "view_subject_exceeds_budget", retryable=True,
            subject_ref=subjects[start]["subject_ref"],
            minimum_budget_bytes=minimum, provided_budget_bytes=budget_bytes,
            resume_cursor=cursor,
        )
    try:
        return _fixed(lambda used: build(selected, index, budget_bytes, used))
    except ValueError:
        return _error("view_internal_error")


def context_view(
    store: MemoryStore, *, revision: str, streams: Sequence[str] | None = None,
    subject_filter: str | None = None, projection: str = "text",
    limit: int = DEFAULT_LIMIT, budget_bytes: int = DEFAULT_BUDGET_BYTES,
    cursor: str | None = None, now: str | None = None,
    stale_after_days: int | None = None,
) -> dict[str, Any]:
    """Return a fail-closed semantic result; never expose host exceptions."""

    try:
        normalized_streams = streams
        _normalize_inputs(
            revision, normalized_streams, subject_filter, projection, limit,
            budget_bytes, now, stale_after_days,
        )
        with shared_reader_gate(store):
            return _context_view(
                store, revision=revision, streams=normalized_streams,
                subject_filter=subject_filter, projection=projection, limit=limit,
                budget_bytes=budget_bytes, cursor=cursor, now=now,
                stale_after_days=stale_after_days, _gate_held=True,
            )
    except ContextViewError as exc:
        return _invalid(exc.detail)
    except ReaderGateError:
        return _error("view_reader_gate_unavailable")
    except Exception:
        return _error("view_internal_error")


__all__ = [
    "CONTRACT_VERSION",
    "ContextViewError",
    "DEFAULT_BUDGET_BYTES",
    "DEFAULT_LIMIT",
    "ERROR_SCHEMA",
    "MAX_BUDGET_BYTES",
    "MAX_CURSOR_CHARS",
    "PROJECTIONS",
    "SUCCESS_SCHEMA",
    "context_view",
]
