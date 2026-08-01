"""Read-only MCP server over stdio; intentionally dependency-free for alpha."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from .context import assemble_context
from .retrieval import retrieve
from .store import IntegrityError, MemoryStore, StoreError
from .version import VERSION

PROTOCOL_VERSION = "2025-11-25"
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
})


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, (IntegrityError, StoreError, ValueError)):
        code = str(exc).split(":", 1)[0]
        if code in SAFE_ERROR_CODES:
            return code
    return "internal_error"


class ReadOnlyMcp:
    def __init__(self, project_root: str | Path) -> None:
        self.root = Path(project_root).resolve()
        self.store = MemoryStore(self.root)
        if not self.store.current_path.exists():
            raise ValueError("memory_not_initialized")

    def _retrieve_payload(self, query: str, budget: int) -> dict[str, Any]:
        if budget < 0:
            raise ValueError("negative_budget")
        # Obtain deterministic relevance ordering without applying a transport
        # budget. Selection below measures the exact UTF-8 text payload.
        source = retrieve(self.store, query, 2**63 - 1)
        base_excluded = dict(source["excluded_summary"])
        candidates = source["selected"]
        selected: list[dict[str, Any]] = []
        budget_excluded = 0

        def build(used: int = 0) -> dict[str, Any]:
            exclusions = dict(base_excluded)
            if budget_excluded:
                exclusions["budget"] = budget_excluded
            return {"schema": "an-kla/mcp-retrieve-v1", "untrusted_memory_data": True,
                    "host_framing_unmeasured": True,
                    "revision": source["revision"], "budget_bytes": budget,
                    "used_bytes": used, "excluded_summary": exclusions, "records": selected}

        def encode_exact() -> tuple[dict[str, Any], int]:
            used = 0
            for _ in range(4):
                payload = build(used)
                measured = len(_json(payload).encode("utf-8"))
                if measured == used:
                    return payload, measured
                used = measured
            raise ValueError("payload_size_not_converged")

        for item in candidates:
            selected.append({"id": item["id"], "text": item["render"], "score": item["score"]})
            _payload, measured = encode_exact()
            if measured > budget:
                selected.pop()
                budget_excluded += 1
        payload, measured = encode_exact()
        if measured > budget:
            raise ValueError("budget_too_small_for_envelope")
        return payload

    @staticmethod
    def tools() -> list[dict[str, Any]]:
        empty = {"type": "object", "additionalProperties": False}
        return [
            {"name": "an_kla_status", "description": "Estado de memoria local.", "inputSchema": empty},
            {"name": "an_kla_verify", "description": "Verifica revisión actual.", "inputSchema": empty},
            {"name": "an_kla_doctor", "description": "Diagnóstico saneado sin rutas locales.", "inputSchema": empty},
            {"name": "an_kla_get_checkpoint", "description": "Checkpoint como datos no confiables.", "inputSchema": empty},
            {"name": "an_kla_retrieve", "description": "Recupera datos no confiables bajo presupuesto UTF-8 exacto.", "inputSchema": {"type":"object","properties":{"query":{"type":"string"},"budget_bytes":{"type":"integer","minimum":0}},"required":["query","budget_bytes"],"additionalProperties":False}},
            {"name": "an_kla_assemble_context", "description": "Ensambla checkpoint, información nueva y memoria bajo un presupuesto UTF-8 global.", "inputSchema": {"type":"object","properties":{"query":{"type":"string"},"budget_bytes":{"type":"integer","minimum":0},"new_information":{"type":"string"}},"required":["query","budget_bytes"],"additionalProperties":False}},
        ]

    def call(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if name in {"an_kla_status", "an_kla_verify"}:
            return self.store.verify()
        if name == "an_kla_doctor":
            report = self.store.doctor()
            return {key: report[key] for key in ("schema", "current_ok", "current_error", "quarantine_objects", "quarantine_bytes", "durability_profile")}
        if name == "an_kla_get_checkpoint":
            snapshot = self.store.snapshot()
            return {"schema":"an-kla/mcp-checkpoint-v1", "untrusted_memory_data":True, "revision":snapshot.revision_id, "checkpoint":snapshot.checkpoint}
        if name == "an_kla_retrieve":
            query, budget = arguments.get("query"), arguments.get("budget_bytes")
            if not isinstance(query, str) or not isinstance(budget, int) or isinstance(budget, bool):
                raise ValueError("invalid_retrieve_arguments")
            return self._retrieve_payload(query, budget)
        if name == "an_kla_assemble_context":
            query, budget = arguments.get("query"), arguments.get("budget_bytes")
            new_information = arguments.get("new_information")
            if (
                not isinstance(query, str)
                or not isinstance(budget, int)
                or isinstance(budget, bool)
                or (new_information is not None and not isinstance(new_information, str))
            ):
                raise ValueError("invalid_context_arguments")
            return assemble_context(
                self.store,
                query,
                budget,
                new_information=new_information,
            )
        raise ValueError("unknown_tool")

    def handle(self, request: Mapping[str, Any]) -> dict[str, Any] | None:
        if request.get("jsonrpc") != "2.0":
            return {"jsonrpc":"2.0","id":request.get("id"),"error":{"code":-32600,"message":"invalid_request"}}
        method, request_id = request.get("method"), request.get("id")
        if (isinstance(method, str) and method.startswith("notifications/")) or "id" not in request:
            return None
        if method == "initialize":
            params = request.get("params", {})
            if not isinstance(params, Mapping) or params.get("protocolVersion") != PROTOCOL_VERSION:
                return {"jsonrpc":"2.0","id":request_id,"error":{"code":-32602,"message":"unsupported_protocol_version"}}
            return {"jsonrpc":"2.0","id":request_id,"result":{"protocolVersion":PROTOCOL_VERSION,"capabilities":{"tools":{"listChanged":False}},"serverInfo":{"name":"an-kla-read","version":VERSION}}}
        if method == "tools/list": return {"jsonrpc":"2.0","id":request_id,"result":{"tools":self.tools()}}
        if method == "tools/call":
            params = request.get("params", {})
            try:
                if not isinstance(params, Mapping) or not isinstance(params.get("arguments", {}), Mapping): raise ValueError("invalid_tool_arguments")
                value = self.call(str(params.get("name", "")), params.get("arguments", {}))
                return {"jsonrpc":"2.0","id":request_id,"result":{"content":[{"type":"text","text":_json(value)}],"isError":False}}
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
