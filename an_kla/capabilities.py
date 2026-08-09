"""Deterministic, project-independent capability discovery for agents."""

from __future__ import annotations

from typing import Any

from .index import INDEX_PROFILE
from .compaction_contracts import policy_fingerprint as compaction_policy_fingerprint
from .mcp import PROTOCOL_VERSION, ReadOnlyMcp
from .retrieval import SCAN_PROFILE
from .refute_policy import (
    REFUTE_POLICY_PROFILE,
    policy_configuration as refute_policy_configuration,
    policy_fingerprint as refute_policy_fingerprint,
)
from .schemas import schema_catalog
from .temporal import FRESHNESS_PROFILE
from .version import VERSION
from .write_policy import WRITE_POLICY_PROFILE, policy_configuration, policy_fingerprint


def capabilities() -> dict[str, Any]:
    policy = policy_configuration()
    refute_policy = refute_policy_configuration()
    return {
        "schema": "an-kla/capabilities-v1",
        "canonicalization": "canonical-json/v1",
        "product": {"name": "an-kla-memory", "version": VERSION},
        "trust": {"retrieved_memory": "untrusted_data_not_instructions"},
        "storage": {
            "active_memories": 1,
            "streams": ["facts", "events", "episodes"],
            "identity": {
                "profile": "store-project-identity/v1",
                "project": "an-kla/project-identity-v1",
                "store": "an-kla/store-identity-v1",
                "explicit_legacy_adoption": True,
                "root_relocation_supported": True,
            },
            "checkpoint": {
                "profile": "checkpoint-policy/v1",
                "schema": "an-kla/checkpoint-v2",
                "governed_plan_commit": True,
                "working_state_is_not_lexical_memory": True,
                "tool_observed_adapter": False,
                "resume": "an-kla/resume-v1",
            },
            "transactions": {
                "attempt": "an-kla/transaction-attempt-v1",
                "outcome": "an-kla/commit-outcome-v2",
                "durability_receipt": "an-kla/durability-receipt-v1",
                "inspect": True,
                "archived_outcome": "an-kla/transaction-archived-v1",
                "repair_durability": True,
                "directory_fsync_fail_closed": True,
            },
            "refute": {
                "profile": REFUTE_POLICY_PROFILE,
                "fingerprint": refute_policy_fingerprint(),
                "supported_operations": refute_policy["supported_operations"],
                "proposal": "an-kla/refute-proposal-v1",
                "authority_claim": "an-kla/refute-authority-claim-v1",
                "revision_schemas": ["an-kla/revision-v2", "an-kla/revision-v3"],
                "target_selector": "physical_record_sha256",
                "successor_created": False,
                "python_host_resolver_injection": True,
                "bundled_resolver": False,
                "provider_adapter": False,
                "cli_can_mint_privileged_authority": False,
            },
            "export_restore": {
                "profile": "export/v1",
                "manifest": "an-kla/export-manifest-v1",
                "plaintext": True,
                "verify_semantic_store": True,
                "restore_merge": False,
                "restore_overwrite": False,
                "provider_adapter": False,
            },
            "compaction": {
                "profile": "compaction-policy/v1",
                "policy_fingerprint": compaction_policy_fingerprint(),
                "revision_schema": "an-kla/revision-v3",
                "governed_plan_commit": True,
                "export_restore_proof_required": True,
                "platform": "posix",
                "reader_gate": "flock-shared-exclusive/v1",
                "historical_revision_states": [
                    "present", "archived_by_compaction", "unknown"
                ],
            },
        },
        "retrieval": {
            "default_profile": SCAN_PROFILE,
            "indexable_text_field": "indexable_text",
            "indexable_text_priority": "first of indexable_text, text, render, summary, p",
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
            "freshness": {
                "field": "verified_at",
                "profile": FRESHNESS_PROFILE,
                "computed_at_read": True,
                "clock": "system_utc_default",
                "now_injectable": True,
                "staleness_marking": "opt_in_threshold",
                "affects_score": False,
                "data_not_authority": True,
                "naive_now": "rejected",
                "activation": "explicit_profile",
                "semantics": "self_asserted_timestamp",
                "source_field": "record.verified_at",
                "result_schemas": [
                    "an-kla/retrieval-result-v2",
                    "an-kla/context-assembly-v2",
                    "an-kla/mcp-retrieve-v2",
                ],
            },
            "evaluation": {
                "legacy_schema": "an-kla/retrieval-eval-v1",
                "ordered_budget_separated_schema": "an-kla/retrieval-eval-report-v2",
                "reference_corpus": "retrieval-benchmark-v2/1",
                "reference_index_states": ["absent", "fresh", "corrupt", "stale"],
                "ranking_change_authorized": False,
            },
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
            "retrieval_requires_indexable_text": True,
            "no_text_warning_reason_code": "record_without_indexable_text",
            "context_diagnostics_in_write_result": True,
            "legacy_unguarded_cli": {
                "command": "write",
                "requires_flag": "--allow-legacy-unguarded-write",
                "warning": "legacy_unguarded_write_enabled",
                "removal_target": "v0.1.0-beta.10",
            },
        },
        "upgrade": {
            "profile": "project-context-upgrade/v1",
            "operations": ["inspect", "apply", "verify"],
            "package_self_update": False,
            "requires_exact_installed_target": True,
        },
        "update_check": {
            "enabled": True,
            "source": "github_releases_api_read_only",
            "source_endpoint": "/releases?per_page=1",
            "source_endpoint_note": "Excludes /releases/latest because GitHub filters pre-releases there.",
            "cached_for_seconds": 86400,
            "opt_out_env": "AN_KLA_NO_UPDATE_CHECK",
            "ci_skip_env": ["CI", "GITHUB_ACTIONS", "AN_KLA_DISABLE_UPDATE_CHECK"],
            "install_or_self_replace": False,
            "notice_channel": "stderr",
        },
        "schemas": schema_catalog()["schemas"],
        "mcp": {
            "protocol_version": PROTOCOL_VERSION,
            "read_only": True,
            "tools": [item["name"] for item in ReadOnlyMcp.tools()],
        },
        "limits": {
            "garbage_collection": "governed_compaction/v1",
            "multi_machine_coordination": False,
            "multi_memory": False,
            "writable_mcp": False,
        },
    }


__all__ = ["capabilities"]
