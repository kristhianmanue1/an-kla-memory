"""Deterministic, project-independent capability discovery for agents."""

from __future__ import annotations

from typing import Any

from .index import INDEX_PROFILE
from .compaction_contracts import policy_fingerprint as compaction_policy_fingerprint
from .context_view import (
    CONTRACT_VERSION as VIEW_CONTRACT_VERSION,
    DEFAULT_BUDGET_BYTES as VIEW_DEFAULT_BUDGET_BYTES,
    DEFAULT_LIMIT as VIEW_DEFAULT_LIMIT,
    DEFAULT_STREAMS as VIEW_DEFAULT_STREAMS,
    ERROR_CODES as VIEW_ERROR_CODES,
    ERROR_SCHEMA as VIEW_ERROR_SCHEMA,
    MAX_BUDGET_BYTES as VIEW_MAX_BUDGET_BYTES,
    MAX_CURSOR_CHARS as VIEW_MAX_CURSOR_CHARS,
    OPERATION as VIEW_OPERATION,
    PROFILE as VIEW_PROFILE,
    PROJECTIONS as VIEW_PROJECTIONS,
    READ_COORDINATION_SIDE_EFFECT as VIEW_READ_COORDINATION_SIDE_EFFECT,
    SUCCESS_SCHEMA as VIEW_SUCCESS_SCHEMA,
    SURFACES as VIEW_SURFACES,
    WARNING_CODES as VIEW_WARNING_CODES,
)
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
                "source_state_profiles": {
                    "none/v1": "head/branch/dirty_digest unavailable",
                    "git/v1": "caller_asserted only; full object id for head (ADR-0038); CLI never runs git",
                },
                "resume": "an-kla/resume-v1",
            },
            "inventory": {
                "command": "inventory --revision <sha256>",
                "schema": "an-kla/inventory-v1",
                "read_only": True,
                "content": "metadata-only",
                "default_limit": 200,
                "max_limit": 1000,
                "mcp": False,
                "decision": "ADR-0041",
            },
            "integration": {
                "command": "integration status",
                "schema": "an-kla/integration-status-v1",
                "read_only": True,
                "supported_profiles": ["agent-owned/v1", "host-managed/v1"],
                "observed_profile_v1": "unspecified",
                "agent_binding": "unverified",
                "sharing_boundary": "filesystem-access/unverified",
                "decision": "ADR-0039",
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
                "denominators": {
                    "population": "final_selected",
                    "counts": ["evaluated", "not_evaluable", "unparseable", "stale"],
                    "invariant": "evaluated + not_evaluable + unparseable = len(selected); stale <= evaluated",
                    "decision": "ADR-0037",
                },
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
        "view": {
            "profile": VIEW_PROFILE,
            "contract_version": VIEW_CONTRACT_VERSION,
            "canonicality": "non-authoritative",
            "untrusted_memory_data": True,
            "requires_explicit_revision": True,
            "resolves_current": False,
            "operations": [VIEW_OPERATION],
            "surfaces": dict(VIEW_SURFACES),
            "schemas": {
                "success": VIEW_SUCCESS_SCHEMA,
                "error": VIEW_ERROR_SCHEMA,
            },
            "projections": list(VIEW_PROJECTIONS),
            "default_streams": list(VIEW_DEFAULT_STREAMS),
            "limits": {
                "default_limit": VIEW_DEFAULT_LIMIT,
                "default_budget_bytes": VIEW_DEFAULT_BUDGET_BYTES,
                "maximum_budget_bytes": VIEW_MAX_BUDGET_BYTES,
                "maximum_cursor_chars": VIEW_MAX_CURSOR_CHARS,
                "subject_atomic_pagination": True,
            },
            "purity": {
                "level": "L2",
                "substrate_mutation": False,
                "write_lock": False,
                "persistent_cache": False,
            },
            "read_coordination_side_effect": VIEW_READ_COORDINATION_SIDE_EFFECT,
            "warnings": list(VIEW_WARNING_CODES),
            "terminal_codes": list(VIEW_ERROR_CODES),
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
            "record_validators": dict(policy["record_validators"]),
            "cli_authority_classes": [
                "derived_from_retrieval",
                "model_derived",
                "tool_observed",
                "unresolved",
            ],
            "privileged_authority_requires_external_adapter": True,
            "tool_observed_resolution": "attest-receipt-v1 (ADR-0046: receipt firmado por el motor; channel_confirmed sigue requiriendo adaptador externo)",
            "retrieval_requires_indexable_text": True,
            "no_text_warning_reason_code": "record_without_indexable_text",
            "plan_time_error_codes": [
                "plan_duplicate_id",
                "plan_supersede_target_missing",
                "plan_supersede_target_not_vigente",
            ],
            "attest": {
                "profile": "attest/v1",
                "decision": "ADR-0046",
                "receipt_schema": "an-kla/attest-receipt-v1",
                "authority_schema": "an-kla/write-authority-v2",
                "signature": "hmac-sha256/local-key",
                "whitelist_path": ".an-kla/attest-whitelist.json",
                "whitelist_matching": "exact_argv_or_prefix_with_deny_flags",
                "fail_closed": True,
                "requires_store_with_key": True,
                "receipt_verified_authority_classes": ["tool_observed"],
                "verification_points": ["plan-write", "commit-write-plan"],
                "tombstone": "nonce-addressed/O_EXCL-under-write-lock",
                "checkpoint_authority": False,
                "refute_authority": False,
                "survives_export_restore": False,
                "provenance_not_purity": True,
            },
            "context_diagnostics_in_write_result": True,
            "context_diagnostics_in_init_result": True,
            "legacy_unguarded_cli": {
                "available": False,
                "removed_in": "v0.1.0-beta.11",
            },
        },
        "upgrade": {
            "profile": "project-context-upgrade/v1",
            "operations": ["inspect", "apply", "verify"],
            "package_self_update": False,
            "requires_exact_installed_target": True,
            "baseline_adoption": "adopt-baseline (ADR-0040)",
            "context_drift_adoption_required": True,
            "plan_schema": "an-kla/upgrade-plan-v3",
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
        "cli_error_surface": {
            "unexpected_failure": {
                "stderr": "an-kla error: cli_unexpected_failure",
                "stderr_note": "Relative log hint appended when the local log is enabled and writable; never an absolute path.",
                "exit_code": 1,
                "stderr_traceback": False,
                "local_log": {
                    "enabled": True,
                    "mode": "0600",
                    "parent_mode": "0700",
                    "path_convention": "$XDG_CACHE_HOME|$LOCALAPPDATA|~/.cache /an-kla/cli-errors.log",
                    "contents": "argv + full traceback",
                    "max_bytes": 5242880,
                    "overflow_policy": "reset",
                },
                "debug_stderr_traceback_env": "AN_KLA_DEBUG",
                "disable_local_log_env": "AN_KLA_NO_CLI_ERROR_LOG",
            },
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
