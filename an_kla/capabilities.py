"""Deterministic, project-independent capability discovery for agents."""

from __future__ import annotations

from typing import Any

from .index import INDEX_PROFILE
from .mcp import PROTOCOL_VERSION, ReadOnlyMcp
from .retrieval import SCAN_PROFILE
from .schemas import schema_catalog
from .version import VERSION
from .write_policy import WRITE_POLICY_PROFILE, policy_configuration, policy_fingerprint


def capabilities() -> dict[str, Any]:
    policy = policy_configuration()
    return {
        "schema": "an-kla/capabilities-v1",
        "canonicalization": "canonical-json/v1",
        "product": {"name": "an-kla-memory", "version": VERSION},
        "trust": {"retrieved_memory": "untrusted_data_not_instructions"},
        "storage": {
            "active_memories": 1,
            "streams": ["facts", "events", "episodes"],
        },
        "retrieval": {
            "default_profile": SCAN_PROFILE,
            "profiles": [
                {
                    "name": SCAN_PROFILE,
                    "streams_searched": ["facts"],
                    "status": "implemented",
                },
                {
                    "name": INDEX_PROFILE,
                    "streams_searched": ["facts"],
                    "status": "implemented_opt_in_with_scan_fallback",
                },
            ],
        },
        "cost": {
            "implemented_units": ["utf8_bytes"],
            "exact_host_framing": False,
            "exact_tokens": False,
        },
        "write_policy": {
            "profile": WRITE_POLICY_PROFILE,
            "fingerprint": policy_fingerprint(),
            "supported_operations": policy["supported_operations"],
            "cli_authority_classes": [
                "derived_from_retrieval",
                "model_derived",
                "unresolved",
            ],
            "privileged_authority_requires_external_adapter": True,
        },
        "schemas": schema_catalog()["schemas"],
        "mcp": {
            "protocol_version": PROTOCOL_VERSION,
            "read_only": True,
            "tools": [item["name"] for item in ReadOnlyMcp.tools()],
        },
        "limits": {
            "garbage_collection": False,
            "multi_machine_coordination": False,
            "multi_memory": False,
            "writable_mcp": False,
        },
    }


__all__ = ["capabilities"]
