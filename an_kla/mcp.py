"""Read-only MCP server over stdio; intentionally dependency-free for beta."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

from .canonical import exact_sized_payload
from .context import assemble_context
from .context_view import (
    DEFAULT_BUDGET_BYTES as VIEW_DEFAULT_BUDGET_BYTES,
    DEFAULT_LIMIT as VIEW_DEFAULT_LIMIT,
    ERROR_CODES as VIEW_ERROR_CODES,
    ERROR_SCHEMA as VIEW_ERROR_SCHEMA,
    MAX_BUDGET_BYTES as VIEW_MAX_BUDGET_BYTES,
    MAX_CURSOR_CHARS as VIEW_MAX_CURSOR_CHARS,
    PROJECTIONS as VIEW_PROJECTIONS,
    SURFACES as VIEW_SURFACES,
    WARNING_CODES as VIEW_WARNING_CODES,
    context_view,
)
from .retrieval import retrieve
from .store import STREAMS, IntegrityError, MemoryStore, StoreError
from .subject_ref import SUBJECT_REF_PATTERN
from .temporal import (
    FRESHNESS_PROFILE,
    FRESHNESS_PROJECTION_KEYS,
    TemporalError,
    VERIFIED_AT_PATTERN,
    parse_freshness_now,
    summarize_freshness,
)
from .version import VERSION

PROTOCOL_VERSION = "2025-11-25"
VIEW_OUTPUT_TIMESTAMP_PATTERN = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"\.[0-9]{6}Z$"
)
SAFE_ERROR_CODES = frozenset({
    "memory_not_initialized", "negative_budget", "budget_too_small_for_envelope",
    "invalid_retrieve_arguments", "invalid_tool_arguments", "unknown_tool",
    "unsupported_protocol_version", "payload_size_not_converged",
    "current_missing", "current_invalid_length", "current_invalid_syntax",
    "revision_hash_mismatch", "revision_schema_invalid", "object_missing",
    "object_hash_mismatch", "object_json_invalid", "object_not_canonical",
    "duplicate_or_missing_facts_id",
    "invalid_context_arguments", "invalid_context_query",
    "invalid_context_budget", "invalid_new_information",
    "budget_too_small_for_required_context",
    "invalid_freshness_now", "invalid_stale_after_days",
    "freshness_profile_required", "unsupported_freshness_profile",
}) | frozenset(VIEW_ERROR_CODES)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, (IntegrityError, StoreError, ValueError)):
        code = str(exc).split(":", 1)[0]
        if code in SAFE_ERROR_CODES:
            return code
    return "internal_error"


def _closed(value: Any, required: set[str], optional: set[str] = set()) -> None:
    if not isinstance(value, Mapping):
        raise ValueError("internal_error")
    keys = set(value)
    if not required.issubset(keys) or not keys.issubset(required | optional):
        raise ValueError("internal_error")


def _validate_view_result(value: Any) -> bool:
    """Validate the closed transport shape before exposing a core result."""

    if not isinstance(value, Mapping):
        raise ValueError("internal_error")
    schema = value.get("schema")
    if schema == VIEW_ERROR_SCHEMA:
        common = {"schema", "ok", "code", "retryable", "untrusted_memory_data"}
        code = value.get("code")
        fields = {
            "view_invalid_inputs": {"detail"},
            "view_invalid_subject_ref_in_revision": {"detail"},
            "view_envelope_exceeds_budget": {"subject_ref", "minimum_budget_bytes", "provided_budget_bytes", "resume_cursor"},
            "view_subject_exceeds_budget": {"subject_ref", "minimum_budget_bytes", "provided_budget_bytes", "resume_cursor"},
            "view_budget_measurement_unavailable": {"provided_budget_bytes", "resume_cursor"},
            "view_revision_not_available": set(),
            "view_rule_ambiguous": set(),
            "view_cursor_invalid": set(),
            "view_reader_gate_unavailable": set(),
            "view_internal_error": set(),
        }
        if code not in fields or set(value) != common | fields[code]:
            raise ValueError("internal_error")
        retryable = code in {"view_envelope_exceeds_budget", "view_subject_exceeds_budget"}
        if (
            value.get("ok") is not False
            or value.get("retryable") is not retryable
            or value.get("untrusted_memory_data") is not True
        ):
            raise ValueError("internal_error")
        if code == "view_invalid_inputs" and value.get("detail") not in {
            "revision", "streams", "subject_filter", "projection", "limit",
            "budget_bytes", "now", "stale_after_days",
        }:
            raise ValueError("internal_error")
        if code == "view_invalid_subject_ref_in_revision":
            detail = value.get("detail")
            _closed(detail, {"stream", "record_sha256"})
            if detail["stream"] not in STREAMS or not _digest(detail["record_sha256"]):
                raise ValueError("internal_error")
        if code in {"view_envelope_exceeds_budget", "view_subject_exceeds_budget"}:
            if (
                not _positive_int(value.get("minimum_budget_bytes"))
                or not _positive_int(value.get("provided_budget_bytes"))
                or value["minimum_budget_bytes"] <= value["provided_budget_bytes"]
                or not _optional_string(value.get("resume_cursor"))
            ):
                raise ValueError("internal_error")
            if code == "view_envelope_exceeds_budget" and value.get("subject_ref") is not None:
                raise ValueError("internal_error")
            if code == "view_subject_exceeds_budget" and not _subject_ref(value.get("subject_ref")):
                raise ValueError("internal_error")
        if code == "view_budget_measurement_unavailable" and (
            not _positive_int(value.get("provided_budget_bytes"))
            or not _optional_string(value.get("resume_cursor"))
        ):
            raise ValueError("internal_error")
        return True
    if schema != "an-kla/context-view-v1":
        raise ValueError("internal_error")
    _closed(value, {
        "schema", "contract_version", "serialization", "canonicality",
        "untrusted_memory_data", "host_framing_unmeasured",
        "live_revalidation_performed", "consumer_action_required", "revision",
        "inputs", "freshness", "subjects_without_subject_ref", "subjects",
        "pagination", "warnings",
    })
    if (
        value.get("contract_version") != "g-view/v1"
        or value.get("serialization") != "canonical-json/v1"
        or value.get("canonicality") != "non-authoritative"
        or value.get("untrusted_memory_data") is not True
        or value.get("host_framing_unmeasured") is not True
        or value.get("live_revalidation_performed") is not False
        or value.get("consumer_action_required") != "revalidate_against_canonical_sources_before_action"
        or not _digest(value.get("revision"))
    ):
        raise ValueError("internal_error")
    inputs = value["inputs"]
    _closed(inputs, {
        "revision", "streams", "subject_filter", "projection", "now",
        "stale_after_days", "limit", "budget_bytes",
    })
    streams = inputs.get("streams")
    if (
        inputs.get("revision") != value["revision"]
        or not isinstance(streams, list)
        or not 1 <= len(streams) <= len(STREAMS)
        or len(streams) != len(set(streams))
        or any(stream not in STREAMS for stream in streams)
        or not _optional_subject_ref(inputs.get("subject_filter"))
        or inputs.get("projection") not in VIEW_PROJECTIONS
        or not _optional_timestamp(inputs.get("now"))
        or not _optional_nonnegative_int(inputs.get("stale_after_days"))
        or not _positive_int(inputs.get("limit"))
        or not _positive_int(inputs.get("budget_bytes"))
    ):
        raise ValueError("internal_error")
    if inputs["projection"] == "full" and inputs["subject_filter"] is None:
        raise ValueError("internal_error")
    counts = value["subjects_without_subject_ref"]
    _closed(counts, set(streams))
    if any(not _nonnegative_int(count) for count in counts.values()):
        raise ValueError("internal_error")
    pagination = value["pagination"]
    _closed(pagination, {
        "complete", "next_cursor", "served_subjects", "total_subjects",
        "truncated_subjects", "budget_used_bytes", "budget_bytes", "limit",
    })
    if (
        not isinstance(pagination.get("complete"), bool)
        or not _optional_string(pagination.get("next_cursor"))
        or any(not _nonnegative_int(pagination.get(key)) for key in ("served_subjects", "total_subjects", "truncated_subjects"))
        or not _positive_int(pagination.get("budget_used_bytes"))
        or pagination.get("budget_bytes") != inputs["budget_bytes"]
        or pagination.get("limit") != inputs["limit"]
    ):
        raise ValueError("internal_error")
    if pagination["complete"]:
        if pagination["next_cursor"] is not None or pagination["truncated_subjects"] != 0:
            raise ValueError("internal_error")
    elif (
        not isinstance(pagination["next_cursor"], str)
        or not pagination["next_cursor"]
        or pagination["truncated_subjects"] < 1
    ):
        raise ValueError("internal_error")
    freshness = value["freshness"]
    if inputs["now"] is None:
        if freshness is not None:
            raise ValueError("internal_error")
    else:
        _closed(freshness, {"semantics", "source_field", "computed_at", "stale_after_days"})
        if (
            freshness.get("semantics") != "self_asserted_timestamp"
            or freshness.get("source_field") != "record.verified_at"
            or freshness.get("computed_at") != inputs["now"]
            or not _optional_nonnegative_int(freshness.get("stale_after_days"))
            or freshness.get("stale_after_days") != inputs["stale_after_days"]
        ):
            raise ValueError("internal_error")
    warnings = value["warnings"]
    if (
        not isinstance(warnings, list)
        or len(warnings) != len(set(warnings))
        or any(item not in VIEW_WARNING_CODES for item in warnings)
        or not isinstance(value["subjects"], list)
    ):
        raise ValueError("internal_error")
    projection = inputs["projection"]
    fresh = inputs["now"] is not None
    record_required = {
        "subject_ref", "stream", "id", "record_sha256", "state", "state_source",
        "physical_status_untrusted", "lineage_refs", "supersede_links",
        "untrusted_memory_data",
    }
    if projection in {"text", "full"}:
        record_required.add("record_text")
    if projection == "full":
        record_required.add("record_raw")
    if fresh:
        record_required.update({"days_since_verified", "stale", "freshness_error"})
    for subject in value["subjects"]:
        subject_optional = {"content_differs_beyond_text"} if projection == "text" else set()
        _closed(subject, {"subject_ref", "data_conflict", "alternatives", "history"}, subject_optional)
        if (
            not _subject_ref(subject.get("subject_ref"))
            or not isinstance(subject.get("data_conflict"), bool)
            or not isinstance(subject.get("alternatives"), list)
            or not isinstance(subject.get("history"), list)
            or subject["data_conflict"] != (len(subject["alternatives"]) >= 2)
            or (
                "content_differs_beyond_text" in subject
                and subject["content_differs_beyond_text"] is not True
            )
        ):
            raise ValueError("internal_error")
        for position, records in (("alternatives", subject["alternatives"]), ("history", subject["history"])):
            for record in records:
                optional = {"verified_at", "self_asserted_timestamp"}
                _closed(record, record_required, optional)
                if (
                    record.get("subject_ref") != subject["subject_ref"]
                    or record.get("stream") not in streams
                    or not isinstance(record.get("id"), str) or not record["id"]
                    or not _digest(record.get("record_sha256"))
                    or record.get("untrusted_memory_data") is not True
                    or not isinstance(record.get("lineage_refs"), list)
                    or not isinstance(record.get("supersede_links"), list)
                    or ("verified_at" in record) != ("self_asserted_timestamp" in record)
                    or ("verified_at" in record and not isinstance(record["verified_at"], str))
                    or ("self_asserted_timestamp" in record and record["self_asserted_timestamp"] is not True)
                    or (projection in {"text", "full"} and not isinstance(record.get("record_text"), str))
                    or (projection == "full" and not isinstance(record.get("record_raw"), Mapping))
                ):
                    raise ValueError("internal_error")
                if position == "alternatives":
                    if record.get("state") != "active" or record.get("state_source") != "physical_status_untrusted":
                        raise ValueError("internal_error")
                elif not (
                    (record.get("state") == "inactive_untrusted" and record.get("state_source") == "physical_status_untrusted")
                    or (record.get("state") in {"superseded", "refuted"} and record.get("state_source") == "governed_overlay")
                ):
                    raise ValueError("internal_error")
                if fresh and (
                    not _optional_int(record.get("days_since_verified"))
                    or not _optional_bool(record.get("stale"))
                    or not _optional_string(record.get("freshness_error"))
                ):
                    raise ValueError("internal_error")
                for link in record["supersede_links"]:
                    _closed(link, {"stream", "target_id", "sustituida_por"})
                    if (
                        link.get("stream") not in STREAMS
                        or not isinstance(link.get("target_id"), str) or not link["target_id"]
                        or not isinstance(link.get("sustituida_por"), str) or not link["sustituida_por"]
                    ):
                        raise ValueError("internal_error")
    return False


def _digest(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


def _subject_ref(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(SUBJECT_REF_PATTERN, value) is not None


def _optional_subject_ref(value: Any) -> bool:
    return value is None or _subject_ref(value)


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _optional_nonnegative_int(value: Any) -> bool:
    return value is None or _nonnegative_int(value)


def _optional_int(value: Any) -> bool:
    return value is None or isinstance(value, int) and not isinstance(value, bool)


def _optional_bool(value: Any) -> bool:
    return value is None or isinstance(value, bool)


def _optional_string(value: Any) -> bool:
    return value is None or isinstance(value, str)


def _optional_timestamp(value: Any) -> bool:
    return value is None or (
        isinstance(value, str)
        and re.fullmatch(VIEW_OUTPUT_TIMESTAMP_PATTERN, value) is not None
    )


class ReadOnlyMcp:
    def __init__(self, project_root: str | Path) -> None:
        self.root = Path(project_root).resolve()
        self.store = MemoryStore(self.root)
        if not self.store.current_path.exists():
            raise ValueError("memory_not_initialized")
        self._initialize_responded = False
        self._initialized = False

    def _retrieve_payload(
        self,
        query: str,
        budget: int,
        *,
        freshness_profile: str | None = None,
        now: Any = None,
        stale_after_days: int | None = None,
    ) -> dict[str, Any]:
        if budget < 0:
            raise ValueError("negative_budget")
        # Obtain deterministic relevance ordering without applying a transport
        # budget. Selection below measures the exact UTF-8 text payload.
        if freshness_profile is None and now is None and stale_after_days is None:
            # Keep the beta.8 call path exact: this also protects consumers
            # that wrap or mock the three-argument retrieval function.
            source = retrieve(self.store, query, 2**63 - 1)
        else:
            source = retrieve(
                self.store,
                query,
                2**63 - 1,
                freshness_profile=freshness_profile,
                now=now,
                stale_after_days=stale_after_days,
            )
        base_excluded = dict(source["excluded_summary"])
        candidates = source["selected"]
        freshness_enabled = source["schema"] == "an-kla/retrieval-result-v2"
        selected: list[dict[str, Any]] = []
        budget_excluded = 0

        def build(used: int = 0) -> dict[str, Any]:
            exclusions = dict(base_excluded)
            if budget_excluded:
                exclusions["budget"] = budget_excluded
            payload = {"schema": "an-kla/mcp-retrieve-v2" if freshness_enabled else "an-kla/mcp-retrieve-v1", "untrusted_memory_data": True,
                    "host_framing_unmeasured": True,
                    "revision": source["revision"], "budget_bytes": budget,
                    "used_bytes": used, "excluded_summary": exclusions, "records": selected}
            if freshness_enabled:
                payload["freshness_profile"] = FRESHNESS_PROFILE
                # ADR-0037: counts describe the records served after the
                # envelope budget cut, not the unbounded retrieval set.
                payload["freshness"] = {
                    **source["freshness"],
                    **summarize_freshness(selected),
                }
            return payload

        for item in candidates:
            record = {"id": item["id"], "text": item["render"], "score": item["score"]}
            if freshness_enabled:
                record.update(
                    {key: item[key] for key in FRESHNESS_PROJECTION_KEYS if key in item}
                )
            selected.append(record)
            _payload, measured = exact_sized_payload(build)
            if measured > budget:
                selected.pop()
                budget_excluded += 1
        payload, measured = exact_sized_payload(build)
        if measured > budget:
            raise ValueError("budget_too_small_for_envelope")
        return payload

    @staticmethod
    def tools() -> list[dict[str, Any]]:
        empty = {"type": "object", "additionalProperties": False}
        freshness = {
            "freshness_profile": {"type": "string", "enum": [FRESHNESS_PROFILE]},
            "now": {"type": "string", "pattern": VERIFIED_AT_PATTERN},
            "stale_after_days": {"type": "integer", "minimum": 0},
        }
        view = {
            "type": "object",
            "properties": {
                "revision": {"type": "string", "pattern": r"^sha256:[0-9a-f]{64}$", "minLength": 71, "maxLength": 71},
                "streams": {
                    "type": "array", "items": {"type": "string", "enum": list(STREAMS)},
                    "minItems": 1, "maxItems": len(STREAMS),
                },
                "subject_filter": {"type": "string", "pattern": SUBJECT_REF_PATTERN, "not": {"pattern": "[\\r\\n]"}},
                "projection": {"type": "string", "enum": list(VIEW_PROJECTIONS), "default": "text"},
                "limit": {"type": "integer", "minimum": 1, "default": VIEW_DEFAULT_LIMIT},
                "budget_bytes": {
                    "type": "integer", "minimum": 1, "maximum": VIEW_MAX_BUDGET_BYTES,
                    "default": VIEW_DEFAULT_BUDGET_BYTES,
                },
                "cursor": {"type": "string", "minLength": 1, "maxLength": VIEW_MAX_CURSOR_CHARS},
                "now": {"type": "string", "pattern": VERIFIED_AT_PATTERN, "not": {"pattern": "[\\r\\n]"}},
                "stale_after_days": {"type": "integer", "minimum": 0},
            },
            "required": ["revision"],
            "additionalProperties": False,
        }
        return [
            {"name": "an_kla_status", "description": "Estado de memoria local.", "inputSchema": empty},
            {"name": "an_kla_verify", "description": "Verifica revisión actual.", "inputSchema": empty},
            {"name": "an_kla_doctor", "description": "Diagnóstico saneado sin rutas locales.", "inputSchema": empty},
            {"name": "an_kla_get_checkpoint", "description": "Checkpoint como datos no confiables.", "inputSchema": empty},
            {"name": "an_kla_retrieve", "description": "Recupera datos no confiables bajo presupuesto UTF-8 exacto.", "inputSchema": {"type":"object","properties":{"query":{"type":"string"},"budget_bytes":{"type":"integer","minimum":0}, **freshness},"required":["query","budget_bytes"],"additionalProperties":False}},
            {"name": "an_kla_assemble_context", "description": "Ensambla checkpoint, información nueva y memoria bajo un presupuesto UTF-8 global.", "inputSchema": {"type":"object","properties":{"query":{"type":"string"},"budget_bytes":{"type":"integer","minimum":0},"new_information":{"type":"string"}, **freshness},"required":["query","budget_bytes"],"additionalProperties":False}},
            {"name": VIEW_SURFACES["mcp"], "description": "Proyecta una vista contextual non-authoritative sobre una revisión fijada.", "inputSchema": view},
        ]

    @staticmethod
    def _freshness_arguments(
        arguments: Mapping[str, Any],
        *,
        required: set[str],
        optional: set[str],
        invalid_arguments: str,
    ) -> tuple[str | None, Any, int | None]:
        keys = set(arguments)
        if not required.issubset(keys) or not keys.issubset(required | optional):
            raise ValueError(invalid_arguments)
        query, budget = arguments["query"], arguments["budget_bytes"]
        if (
            not isinstance(query, str)
            or not isinstance(budget, int)
            or isinstance(budget, bool)
            or (
                "freshness_profile" in arguments
                and not isinstance(arguments["freshness_profile"], str)
            )
        ):
            raise ValueError(invalid_arguments)
        profile = arguments.get("freshness_profile")
        if profile is not None and profile != FRESHNESS_PROFILE:
            raise TemporalError("unsupported_freshness_profile")
        temporal_present = "now" in arguments or "stale_after_days" in arguments
        if profile is None and temporal_present:
            raise TemporalError("freshness_profile_required")
        parsed_now = None
        threshold = None
        if profile is not None:
            if "now" in arguments:
                parsed_now = parse_freshness_now(arguments["now"])
            if "stale_after_days" in arguments:
                value = arguments["stale_after_days"]
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise TemporalError("invalid_stale_after_days")
                threshold = value
        return profile, parsed_now, threshold

    def call(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if name in {
            "an_kla_status",
            "an_kla_verify",
            "an_kla_doctor",
            "an_kla_get_checkpoint",
        } and arguments:
            raise ValueError("invalid_tool_arguments")
        if name in {"an_kla_status", "an_kla_verify"}:
            return self.store.verify()
        if name == "an_kla_doctor":
            report = self.store.doctor()
            return {key: report[key] for key in ("schema", "current_ok", "current_error", "quarantine_objects", "quarantine_bytes", "durability_profile")}
        if name == "an_kla_get_checkpoint":
            snapshot = self.store.snapshot()
            return {"schema":"an-kla/mcp-checkpoint-v1", "untrusted_memory_data":True, "revision":snapshot.revision_id, "checkpoint":snapshot.checkpoint}
        if name == "an_kla_retrieve":
            profile, now, threshold = self._freshness_arguments(
                arguments,
                required={"query", "budget_bytes"},
                optional={"freshness_profile", "now", "stale_after_days"},
                invalid_arguments="invalid_retrieve_arguments",
            )
            return self._retrieve_payload(
                arguments["query"], arguments["budget_bytes"],
                freshness_profile=profile, now=now, stale_after_days=threshold,
            )
        if name == "an_kla_assemble_context":
            if "new_information" in arguments and not isinstance(
                arguments["new_information"], str
            ):
                raise ValueError("invalid_context_arguments")
            profile, now, threshold = self._freshness_arguments(
                arguments,
                required={"query", "budget_bytes"},
                optional={"new_information", "freshness_profile", "now", "stale_after_days"},
                invalid_arguments="invalid_context_arguments",
            )
            return assemble_context(
                self.store, arguments["query"], arguments["budget_bytes"],
                new_information=arguments.get("new_information"),
                freshness_profile=profile, now=now, stale_after_days=threshold,
            )
        if name == VIEW_SURFACES["mcp"]:
            allowed = {
                "revision", "streams", "subject_filter", "projection", "limit",
                "budget_bytes", "cursor", "now", "stale_after_days",
            }
            if not set(arguments).issubset(allowed):
                raise ValueError("invalid_tool_arguments")
            return context_view(
                self.store,
                revision=arguments.get("revision"),
                streams=arguments.get("streams"),
                subject_filter=arguments.get("subject_filter"),
                projection=arguments.get("projection", "text"),
                limit=arguments.get("limit", VIEW_DEFAULT_LIMIT),
                budget_bytes=arguments.get("budget_bytes", VIEW_DEFAULT_BUDGET_BYTES),
                cursor=arguments.get("cursor"),
                now=arguments.get("now"),
                stale_after_days=arguments.get("stale_after_days"),
            )
        raise ValueError("unknown_tool")

    def handle(self, request: Mapping[str, Any]) -> dict[str, Any] | None:
        if request.get("jsonrpc") != "2.0":
            return {"jsonrpc":"2.0","id":request.get("id"),"error":{"code":-32600,"message":"invalid_request"}}
        method, request_id = request.get("method"), request.get("id")
        if method == "notifications/initialized":
            if self._initialize_responded:
                self._initialized = True
            return None
        if (isinstance(method, str) and method.startswith("notifications/")) or "id" not in request:
            return None
        if method == "initialize":
            params = request.get("params", {})
            requested = params.get("protocolVersion") if isinstance(params, Mapping) else None
            if not isinstance(requested, str) or not requested:
                return {"jsonrpc":"2.0","id":request_id,"error":{"code":-32602,"message":"unsupported_protocol_version"}}
            self._initialize_responded = True
            return {"jsonrpc":"2.0","id":request_id,"result":{"protocolVersion":PROTOCOL_VERSION,"capabilities":{"tools":{"listChanged":False}},"serverInfo":{"name":"an-kla-read","version":VERSION}}}
        if not self._initialized:
            return {"jsonrpc":"2.0","id":request_id,"error":{"code":-32002,"message":"server_not_initialized"}}
        if method == "tools/list": return {"jsonrpc":"2.0","id":request_id,"result":{"tools":self.tools()}}
        if method == "tools/call":
            params = request.get("params", {})
            try:
                if not isinstance(params, Mapping) or not isinstance(params.get("arguments", {}), Mapping): raise ValueError("invalid_tool_arguments")
                value = self.call(str(params.get("name", "")), params.get("arguments", {}))
                is_error = (
                    _validate_view_result(value)
                    if params.get("name") == VIEW_SURFACES["mcp"]
                    else False
                )
                return {"jsonrpc":"2.0","id":request_id,"result":{"content":[{"type":"text","text":_json(value)}],"isError":is_error}}
            except Exception as exc:
                return {"jsonrpc":"2.0","id":request_id,"result":{"content":[{"type":"text","text":_json({"error":_safe_error(exc)})}],"isError":True}}
        return {"jsonrpc":"2.0","id":request_id,"error":{"code":-32601,"message":"method_not_found"}}


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--project-root", required=True)
    server = ReadOnlyMcp(parser.parse_args().project_root)
    for line in sys.stdin:
        try:
            response = server.handle(json.loads(line))
            if response is not None: print(_json(response), flush=True)
        except Exception as exc:
            print(_json({"jsonrpc":"2.0","id":None,"error":{"code":-32700,"message":_safe_error(exc)}}), flush=True)


if __name__ == "__main__": main()
