"""Installed normative JSON Schemas for agent-facing contracts."""

from __future__ import annotations

from importlib.resources import files
import json
from typing import Any

from ..canonical import digest_bytes


SCHEMA_FILES = {
    "attest-receipt-v1": "attest-receipt-v1.schema.json",
    "checkpoint-authority-v1": "checkpoint-authority-v1.schema.json",
    "checkpoint-decision-v1": "checkpoint-decision-v1.schema.json",
    "checkpoint-plan-v1": "checkpoint-plan-v1.schema.json",
    "checkpoint-proposal-v1": "checkpoint-proposal-v1.schema.json",
    "checkpoint-v2": "checkpoint-v2.schema.json",
    "commit-outcome-v2": "commit-outcome-v2.schema.json",
    "compaction-cleanup-receipt-v1": "compaction-cleanup-receipt-v1.schema.json",
    "compaction-epoch-v1": "compaction-epoch-v1.schema.json",
    "compaction-plan-v1": "compaction-plan-v1.schema.json",
    "compaction-planning-result-v1": "compaction-planning-result-v1.schema.json",
    "compaction-policy-config-v1": "compaction-policy-config-v1.schema.json",
    "compaction-proposal-v1": "compaction-proposal-v1.schema.json",
    "compaction-restore-proof-v1": "compaction-restore-proof-v1.schema.json",
    "compaction-result-v1": "compaction-result-v1.schema.json",
    "compaction-tombstone-catalog-v1": "compaction-tombstone-catalog-v1.schema.json",
    "cost-certificate-v1": "cost-certificate-v1.schema.json",
    "context-assembly-v2": "context-assembly-v2.schema.json",
    "context-view-v1": "context-view-v1.schema.json",
    "durability-receipt-v1": "durability-receipt-v1.schema.json",
    "export-manifest-v1": "export-manifest-v1.schema.json",
    "export-result-v1": "export-result-v1.schema.json",
    "export-verify-result-v1": "export-verify-result-v1.schema.json",
    "identity-adoption-plan-v1": "identity-adoption-plan-v1.schema.json",
    "identity-durability-receipt-v1": "identity-durability-receipt-v1.schema.json",
    "identity-intent-v1": "identity-intent-v1.schema.json",
    "identity-operation-result-v1": "identity-operation-result-v1.schema.json",
    "identity-status-v1": "identity-status-v1.schema.json",
    "integration-status-v1": "integration-status-v1.schema.json",
    "inventory-v1": "inventory-v1.schema.json",
    "mcp-retrieve-v2": "mcp-retrieve-v2.schema.json",
    "provenance-manifest-v1": "provenance-manifest-v1.schema.json",
    "reference-benchmark-v1": "reference-benchmark-v1.schema.json",
    "refutation-v1": "refutation-v1.schema.json",
    "refute-authority-attestation-v1": "refute-authority-attestation-v1.schema.json",
    "refute-authority-claim-v1": "refute-authority-claim-v1.schema.json",
    "refute-commit-result-v1": "refute-commit-result-v1.schema.json",
    "refute-decision-v1": "refute-decision-v1.schema.json",
    "refute-inspect-v1": "refute-inspect-v1.schema.json",
    "refute-observations-v1": "refute-observations-v1.schema.json",
    "refute-plan-v1": "refute-plan-v1.schema.json",
    "refute-planning-result-v1": "refute-planning-result-v1.schema.json",
    "refute-policy-config-v1": "refute-policy-config-v1.schema.json",
    "refute-policy-transaction-v1": "refute-policy-transaction-v1.schema.json",
    "refute-proposal-v1": "refute-proposal-v1.schema.json",
    "revision-v2": "revision-v2.schema.json",
    "revision-v3": "revision-v3.schema.json",
    "retrieval-eval-query-v2": "retrieval-eval-query-v2.schema.json",
    "retrieval-eval-report-v2": "retrieval-eval-report-v2.schema.json",
    "retrieval-result-v2": "retrieval-result-v2.schema.json",
    "retrieval-strategy-report-v1": "retrieval-strategy-report-v1.schema.json",
    "resume-evidence-v1": "resume-evidence-v1.schema.json",
    "resume-v1": "resume-v1.schema.json",
    "restore-result-v1": "restore-result-v1.schema.json",
    "project-identity-v1": "project-identity-v1.schema.json",
    "startup-diagnostic-v1": "startup-diagnostic-v1.schema.json",
    "store-identity-v1": "store-identity-v1.schema.json",
    "subject-namespace-result-v1": "subject-namespace-result-v1.schema.json",
    "transaction-attempt-v1": "transaction-attempt-v1.schema.json",
    "transaction-archived-v1": "transaction-archived-v1.schema.json",
    "context-baseline-adoption-plan-v1": "context-baseline-adoption-plan-v1.schema.json",
    "context-baseline-adoption-result-v1": "context-baseline-adoption-result-v1.schema.json",
    "upgrade-plan-v1": "upgrade-plan-v1.schema.json",
    "upgrade-plan-v3": "upgrade-plan-v3.schema.json",
    "verify-revision-v1": "verify-revision-v1.schema.json",
    "view-error-v1": "view-error-v1.schema.json",
    "write-authority-v1": "write-authority-v1.schema.json",
    "write-authority-v2": "write-authority-v2.schema.json",
    "write-decision-v1": "write-decision-v1.schema.json",
    "write-plan-v1": "write-plan-v1.schema.json",
    "write-proposal-v1": "write-proposal-v1.schema.json",
    "working-state-v2": "working-state-v2.schema.json",
}


def schema_names() -> tuple[str, ...]:
    return tuple(sorted(SCHEMA_FILES))


def schema_bytes(name: str) -> bytes:
    if not isinstance(name, str) or name not in SCHEMA_FILES:
        raise ValueError("unknown_schema")
    try:
        return files(__package__).joinpath(SCHEMA_FILES[name]).read_bytes()
    except OSError:
        raise ValueError("schema_resource_unavailable") from None


def schema_document(name: str) -> dict[str, Any]:
    try:
        value = json.loads(schema_bytes(name))
    except json.JSONDecodeError:
        raise ValueError("schema_resource_invalid") from None
    if not isinstance(value, dict):
        raise ValueError("schema_resource_invalid")
    return value


def schema_catalog() -> dict[str, Any]:
    schemas = []
    for name in schema_names():
        payload = schema_bytes(name)
        document = schema_document(name)
        identifier = document.get("$id")
        if not isinstance(identifier, str):
            raise ValueError("schema_resource_invalid")
        schemas.append(
            {
                "name": name,
                "id": identifier,
                "sha256": digest_bytes(payload),
            }
        )
    return {
        "schema": "an-kla/schema-list-v1",
        "canonicalization": "canonical-json/v1",
        "schemas": schemas,
    }


__all__ = [
    "SCHEMA_FILES",
    "schema_bytes",
    "schema_catalog",
    "schema_document",
    "schema_names",
]
