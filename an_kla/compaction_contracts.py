"""Closed, no-I/O contracts shared by governed compaction and revision-v3."""

from __future__ import annotations

from copy import deepcopy
import os
import uuid
from typing import Any, Mapping

from .canonical import bare_digest, digest_json
from .transaction_attempts import canonical_uuid


class CompactionError(RuntimeError):
    pass


STREAMS = ("facts", "events", "episodes")
POLICY_SCHEMA = "an-kla/compaction-policy-config-v1"
PROPOSAL_SCHEMA = "an-kla/compaction-proposal-v1"
CATALOG_SCHEMA = "an-kla/compaction-tombstone-catalog-v1"
EPOCH_SCHEMA = "an-kla/compaction-epoch-v1"
PROOF_SCHEMA = "an-kla/compaction-restore-proof-v1"


def _digest(value: Any, code: str = "compaction_digest_invalid") -> str:
    if not isinstance(value, str):
        raise CompactionError(code)
    try:
        bare_digest(value)
    except ValueError as exc:
        raise CompactionError(code) from exc
    return value


def _uuid(value: Any, code: str = "compaction_uuid_invalid") -> str:
    if not isinstance(value, str):
        raise CompactionError(code)
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, ValueError) as exc:
        raise CompactionError(code) from exc
    if str(parsed) != value or parsed.version not in {1, 2, 3, 4, 5} or parsed.variant != uuid.RFC_4122:
        raise CompactionError(code)
    return value


_HISTORICAL_POLICY_V1 = {
    "schema": POLICY_SCHEMA,
    "profile": "compaction-policy/v1",
    "platform": "posix",
    "export_profile": "export/v1",
    "revision_schema": "an-kla/revision-v3",
    "projection_precedence": ["refuted", "superseded", "physical"],
    "segmenting": "one-canonical-jsonl-per-nonempty-stream",
    "result_states": [
        "not_committed",
        "committed_cleanup_incomplete",
        "committed",
        "outcome_unknown",
    ],
}

# The active writer policy is deliberately a separate object.  Future
# installations may change it without reinterpreting durable v1 stages.
_POLICY_V1 = deepcopy(_HISTORICAL_POLICY_V1)


def policy_config() -> dict[str, Any]:
    return deepcopy(_POLICY_V1)


def policy_fingerprint() -> str:
    return digest_json(_POLICY_V1)


def validate_policy_config(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or value != _HISTORICAL_POLICY_V1:
        raise CompactionError("compaction_policy_invalid")
    return deepcopy(dict(value))


def validate_proposal(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "schema", "base_revision", "epoch_id", "transaction_id",
        "export_manifest_sha256",
    }:
        raise CompactionError("compaction_proposal_invalid")
    if value.get("schema") != PROPOSAL_SCHEMA:
        raise CompactionError("compaction_proposal_invalid")
    checked = deepcopy(dict(value))
    _digest(checked["base_revision"], "compaction_proposal_invalid")
    _digest(checked["export_manifest_sha256"], "compaction_proposal_invalid")
    _uuid(checked["epoch_id"], "compaction_proposal_invalid")
    canonical_uuid(checked["transaction_id"])
    return checked


def validate_restore_proof(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "schema", "manifest_sha256", "inventory_sha256", "current_revision",
        "project_identity_sha256", "store_identity_sha256",
        "transaction_outcomes_sha256", "restore_result_sha256",
    }
    if not isinstance(value, dict) or set(value) != fields or value.get("schema") != PROOF_SCHEMA:
        raise CompactionError("compaction_restore_proof_invalid")
    checked = deepcopy(dict(value))
    for key in fields - {"schema"}:
        _digest(checked[key], "compaction_restore_proof_invalid")
    return checked


def validate_catalog(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "schema", "epoch_id", "source_revision", "export_manifest_sha256",
        "delete_set_sha256", "archived_revisions", "record_tombstones",
        "object_tombstones", "previous_catalogs",
    }
    if not isinstance(value, dict) or set(value) != fields or value.get("schema") != CATALOG_SCHEMA:
        raise CompactionError("compaction_catalog_invalid")
    checked = deepcopy(dict(value))
    _uuid(checked["epoch_id"], "compaction_catalog_invalid")
    for key in ("source_revision", "export_manifest_sha256", "delete_set_sha256"):
        _digest(checked[key], "compaction_catalog_invalid")
    archived = checked["archived_revisions"]
    if not isinstance(archived, list):
        raise CompactionError("compaction_catalog_invalid")
    prior_revision = ""
    seen_revisions: set[str] = set()
    for item in archived:
        if not isinstance(item, dict) or set(item) != {"revision", "epoch_id", "export_manifest_sha256"}:
            raise CompactionError("compaction_catalog_invalid")
        _digest(item["revision"], "compaction_catalog_invalid")
        _uuid(item["epoch_id"], "compaction_catalog_invalid")
        _digest(item["export_manifest_sha256"], "compaction_catalog_invalid")
        if item["revision"] <= prior_revision or item["revision"] in seen_revisions:
            raise CompactionError("compaction_catalog_invalid")
        prior_revision = item["revision"]
        seen_revisions.add(item["revision"])
    records = checked["record_tombstones"]
    if not isinstance(records, list):
        raise CompactionError("compaction_catalog_invalid")
    ordering = {stream: index for index, stream in enumerate(STREAMS)}
    prior_record: tuple[int, str] | None = None
    for item in records:
        if not isinstance(item, dict) or set(item) != {"stream", "record_sha256", "state"}:
            raise CompactionError("compaction_catalog_invalid")
        if item["stream"] not in STREAMS or item["state"] not in {"superseded", "refuted", "inactive"}:
            raise CompactionError("compaction_catalog_invalid")
        _digest(item["record_sha256"], "compaction_catalog_invalid")
        key = (ordering[item["stream"]], item["record_sha256"])
        if prior_record is not None and key <= prior_record:
            raise CompactionError("compaction_catalog_invalid")
        prior_record = key
    objects = checked["object_tombstones"]
    if not isinstance(objects, list):
        raise CompactionError("compaction_catalog_invalid")
    prior_path = ""
    for item in objects:
        if not isinstance(item, dict) or set(item) != {"path", "content_sha256", "kind"}:
            raise CompactionError("compaction_catalog_invalid")
        if not isinstance(item["path"], str) or not item["path"] or item["path"] <= prior_path:
            raise CompactionError("compaction_catalog_invalid")
        if item["kind"] not in {"revision", "checkpoint", "segment", "ref-log", "transaction", "stage", "receipt", "refutation", "authority-claim", "authority-attestation", "index"}:
            raise CompactionError("compaction_catalog_invalid")
        _digest(item["content_sha256"], "compaction_catalog_invalid")
        prior_path = item["path"]
    previous = checked["previous_catalogs"]
    if not isinstance(previous, list):
        raise CompactionError("compaction_catalog_invalid")
    prior_epoch = ""
    for item in previous:
        if not isinstance(item, dict) or set(item) != {"epoch_id", "catalog_sha256", "export_manifest_sha256"}:
            raise CompactionError("compaction_catalog_invalid")
        _uuid(item["epoch_id"], "compaction_catalog_invalid")
        _digest(item["catalog_sha256"], "compaction_catalog_invalid")
        _digest(item["export_manifest_sha256"], "compaction_catalog_invalid")
        if item["epoch_id"] <= prior_epoch:
            raise CompactionError("compaction_catalog_invalid")
        prior_epoch = item["epoch_id"]
    if digest_json(objects) != checked["delete_set_sha256"]:
        raise CompactionError("compaction_catalog_invalid")
    return checked


def validate_epoch_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "schema", "epoch_id", "transaction_id", "base_revision",
        "proposal_sha256", "export_manifest_sha256", "restore_proof",
        "tombstone_catalog", "delete_set_sha256", "compaction_policy",
    }
    if not isinstance(value, dict) or set(value) != fields or value.get("schema") != EPOCH_SCHEMA:
        raise CompactionError("compaction_epoch_invalid")
    checked = deepcopy(dict(value))
    _uuid(checked["epoch_id"], "compaction_epoch_invalid")
    canonical_uuid(checked["transaction_id"])
    for key in fields - {"schema", "epoch_id", "transaction_id"}:
        _digest(checked[key], "compaction_epoch_invalid")
    return checked


def validate_catalog_chain(
    store: Any, catalog_id: str,
) -> dict[str, tuple[str, dict[str, Any]]]:
    """Validate every retained catalog CAS with cycle and fanout bounds."""

    _digest(catalog_id, "compaction_catalog_invalid")
    queue: list[tuple[str, str | None, str | None, frozenset[str]]] = [
        (catalog_id, None, None, frozenset())
    ]
    by_epoch: dict[str, tuple[str, dict[str, Any]]] = {}
    by_id: dict[str, dict[str, Any]] = {}
    visited: set[str] = set()
    while queue:
        if len(visited) >= 1024:
            raise CompactionError("compaction_catalog_chain_invalid")
        identifier, expected_epoch, expected_export, ancestors = queue.pop(0)
        if identifier in ancestors:
            raise CompactionError("compaction_catalog_chain_invalid")
        if identifier in visited:
            existing = by_id[identifier]
            if (
                expected_epoch is not None
                and existing["epoch_id"] != expected_epoch
            ) or (
                expected_export is not None
                and existing["export_manifest_sha256"] != expected_export
            ):
                raise CompactionError("compaction_catalog_chain_invalid")
            continue
        try:
            catalog = validate_catalog(
                store._read_json_object("compaction/catalogs", identifier)
            )
        except Exception as exc:
            raise CompactionError("compaction_catalog_chain_invalid") from exc
        if (
            (expected_epoch is not None and catalog["epoch_id"] != expected_epoch)
            or (
                expected_export is not None
                and catalog["export_manifest_sha256"] != expected_export
            )
        ):
            raise CompactionError("compaction_catalog_chain_invalid")
        prior = by_epoch.get(catalog["epoch_id"])
        if prior is not None and prior[0] != identifier:
            raise CompactionError("compaction_catalog_chain_invalid")
        by_epoch[catalog["epoch_id"]] = (identifier, catalog)
        by_id[identifier] = catalog
        visited.add(identifier)
        next_ancestors = frozenset({*ancestors, identifier})
        for item in catalog["previous_catalogs"]:
            queue.append(
                (
                    item["catalog_sha256"], item["epoch_id"],
                    item["export_manifest_sha256"], next_ancestors,
                )
            )
    return by_epoch


def ensure_supported_platform() -> None:
    if os.name != "posix":
        raise CompactionError("compaction_platform_unsupported")


__all__ = [
    "CATALOG_SCHEMA", "CompactionError", "EPOCH_SCHEMA", "POLICY_SCHEMA",
    "PROOF_SCHEMA", "PROPOSAL_SCHEMA", "ensure_supported_platform",
    "policy_config", "policy_fingerprint", "validate_catalog",
    "validate_catalog_chain", "validate_epoch_manifest", "validate_policy_config",
    "validate_proposal", "validate_restore_proof",
]
