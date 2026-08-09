"""Strict revision-v1/v2/v3 and lifecycle validation."""

from __future__ import annotations

import uuid
from typing import Any, Mapping

from .canonical import bare_digest, digest_json
from .identity import verify_manifest_link


STREAMS = ("facts", "events", "episodes")


def validate_manifest(manifest: Mapping[str, Any], error: type[Exception]) -> None:
    schema = manifest.get("schema")
    required = {
        "schema", "revision", "parent", "facts_segments", "events_segments",
        "episodes_segments", "checkpoint", "transaction_id", "canonicalization",
        "integrity_claim",
    }
    optional = {"store_identity", "supersedes_map"}
    if schema == "an-kla/revision-v2":
        required |= {"store_identity", "features", "refutations_map"}
    elif schema == "an-kla/revision-v3":
        required |= {
            "store_identity", "features", "refutations_map",
            "supersedes_map", "compaction_epoch",
        }
    elif schema != "an-kla/revision-v1":
        raise error("manifest_schema_invalid")
    if not isinstance(manifest, dict) or not required.issubset(manifest) or not set(manifest).issubset(required | optional):
        raise error("manifest_shape_invalid")
    revision = manifest.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        raise error("manifest_revision_invalid")
    for key in ("checkpoint", "parent"):
        value = manifest.get(key)
        if key == "parent" and value is None and (
            revision == 0 or schema == "an-kla/revision-v3"
        ):
            continue
        if not isinstance(value, str):
            raise error("manifest_identifier_missing")
        bare_digest(value)
    if schema == "an-kla/revision-v3":
        if revision == 0 or (
            manifest.get("parent") is None
            and not isinstance(manifest.get("compaction_epoch"), dict)
        ):
            raise error("manifest_parent_invalid")
    elif (revision == 0) != (manifest.get("parent") is None):
        raise error("manifest_parent_invalid")
    if manifest.get("canonicalization") != "canonical-json/v1" or manifest.get("integrity_claim") != "content_identity_not_truth_or_authorship":
        raise error("manifest_constants_invalid")
    transaction_id = manifest.get("transaction_id")
    if transaction_id == "root":
        if revision != 0 or manifest.get("parent") is not None or schema != "an-kla/revision-v1":
            raise error("manifest_transaction_id_invalid")
    else:
        try:
            parsed = uuid.UUID(str(transaction_id))
        except (ValueError, AttributeError) as exc:
            raise error("manifest_transaction_id_invalid") from exc
        if str(parsed) != transaction_id or parsed.version not in {1, 2, 3, 4, 5} or parsed.variant != uuid.RFC_4122:
            raise error("manifest_transaction_id_invalid")
    for stream in STREAMS:
        values = manifest.get(f"{stream}_segments")
        if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
            raise error("manifest_segments_invalid")
        if len(values) != len(set(values)):
            raise error("manifest_segments_invalid")
        for identifier in values:
            bare_digest(identifier)
    if manifest.get("store_identity") is not None:
        bare_digest(str(manifest["store_identity"]))
    supersede_map = manifest.get("supersedes_map")
    if supersede_map is not None:
        if not isinstance(supersede_map, list):
            raise error("manifest_supersedes_map_invalid")
        for entry in supersede_map:
            if not isinstance(entry, dict) or set(entry) != {"stream", "target_id", "sustituida_por"}:
                raise error("manifest_supersedes_map_invalid")
            if (
                entry.get("stream") not in STREAMS
                or not isinstance(entry.get("target_id"), str)
                or not entry["target_id"]
                or not isinstance(entry.get("sustituida_por"), str)
                or not entry["sustituida_por"]
            ):
                raise error("manifest_supersedes_map_invalid")
    if schema in {"an-kla/revision-v2", "an-kla/revision-v3"}:
        expected_features = (
            ["refutations/v1"] if schema == "an-kla/revision-v2"
            else ["refutations/v1", "compaction/v1"]
        )
        if manifest.get("features") != expected_features:
            raise error("manifest_features_invalid")
        entries = manifest.get("refutations_map")
        if not isinstance(entries, list) or (
            schema == "an-kla/revision-v2" and not entries
        ):
            raise error("manifest_refutations_map_invalid")
        seen: set[tuple[str, str]] = set()
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"stream", "target_record_sha256", "refutation_id"}:
                raise error("manifest_refutations_map_invalid")
            key = (entry.get("stream"), entry.get("target_record_sha256"))
            if key[0] not in STREAMS or key in seen:
                raise error("manifest_refutations_map_invalid")
            seen.add(key)  # type: ignore[arg-type]
            try:
                bare_digest(str(key[1]))
                bare_digest(str(entry.get("refutation_id")))
            except ValueError as exc:
                raise error("manifest_refutations_map_invalid") from exc
    if schema == "an-kla/revision-v3":
        epoch = manifest.get("compaction_epoch")
        if not isinstance(epoch, dict) or set(epoch) != {
            "epoch_id", "source_revision", "export_manifest_sha256",
            "tombstone_catalog", "epoch_manifest",
        }:
            raise error("manifest_compaction_epoch_invalid")
        try:
            uuid_value = uuid.UUID(str(epoch["epoch_id"]))
            if (
                str(uuid_value) != epoch["epoch_id"]
                or uuid_value.version not in {1, 2, 3, 4, 5}
                or uuid_value.variant != uuid.RFC_4122
            ):
                raise ValueError
            for key in (
                "source_revision", "export_manifest_sha256",
                "tombstone_catalog", "epoch_manifest",
            ):
                bare_digest(str(epoch[key]))
        except (ValueError, AttributeError) as exc:
            raise error("manifest_compaction_epoch_invalid") from exc


def _validate_compaction_root(
    store: Any, manifest: Mapping[str, Any], error: type[Exception]
) -> None:
    from .compaction_contracts import (
        CompactionError, validate_catalog, validate_catalog_chain,
        validate_epoch_manifest, validate_policy_config, validate_restore_proof,
    )

    link = manifest["compaction_epoch"]
    try:
        catalog = validate_catalog(
            store._read_json_object("compaction/catalogs", link["tombstone_catalog"])
        )
        epoch = validate_epoch_manifest(
            store._read_json_object("compaction/epochs", link["epoch_manifest"])
        )
        proof = validate_restore_proof(
            store._read_json_object("compaction/restore-proofs", epoch["restore_proof"])
        )
        validate_catalog_chain(store, link["tombstone_catalog"])
        from .transactions import _stage_evidence

        stage = _stage_evidence(
            store, str(manifest["transaction_id"]), digest_json(manifest)
        )
        if stage is None:
            raise CompactionError("compaction_stage_invalid")
        historical_policy = validate_policy_config(stage.get("compaction_policy"))
    except (CompactionError, KeyError, ValueError, OSError) as exc:
        raise error("manifest_compaction_epoch_invalid") from exc
    if (
        catalog["epoch_id"] != link["epoch_id"]
        or catalog["source_revision"] != link["source_revision"]
        or catalog["export_manifest_sha256"] != link["export_manifest_sha256"]
        or epoch["epoch_id"] != link["epoch_id"]
        or epoch["transaction_id"] != manifest["transaction_id"]
        or epoch["base_revision"] != link["source_revision"]
        or epoch["export_manifest_sha256"] != link["export_manifest_sha256"]
        or epoch["tombstone_catalog"] != link["tombstone_catalog"]
        or epoch["delete_set_sha256"] != catalog["delete_set_sha256"]
        or epoch["compaction_policy"] != digest_json(historical_policy)
        or proof["manifest_sha256"] != link["export_manifest_sha256"]
        or proof["current_revision"] != link["source_revision"]
        or proof["store_identity_sha256"] != manifest["store_identity"]
        or not any(
            item["revision"] == link["source_revision"]
            and item["epoch_id"] == link["epoch_id"]
            and item["export_manifest_sha256"] == link["export_manifest_sha256"]
            for item in catalog["archived_revisions"]
        )
    ):
        raise error("manifest_compaction_epoch_invalid")


def validate_revision_chain(
    store: Any, revision_id: str, manifest: Mapping[str, Any], error: type[Exception]
) -> None:
    child_id, child = revision_id, manifest
    seen: set[str] = set()
    for _ in range(int(manifest["revision"]) + 2):
        if child_id in seen:
            raise error("revision_transition_invalid")
        seen.add(child_id)
        parent_id = child.get("parent")
        if parent_id is None:
            if child.get("schema") == "an-kla/revision-v3":
                _validate_compaction_root(store, child, error)
                return
            if child.get("revision") != 0 or child.get("schema") != "an-kla/revision-v1":
                raise error("revision_transition_invalid")
            return
        parent = store._read_json_object("revisions", str(parent_id))
        if digest_json(parent) != parent_id:
            raise error("revision_hash_mismatch")
        validate_manifest(parent, error)
        verify_manifest_link(store, parent)
        if child.get("revision") != int(parent["revision"]) + 1:
            raise error("revision_transition_invalid")
        if parent.get("store_identity") is not None and child.get("store_identity") != parent.get("store_identity"):
            raise error("revision_transition_invalid")
        prior_super = list(parent.get("supersedes_map", []))
        current_super = list(child.get("supersedes_map", []))
        if current_super[: len(prior_super)] != prior_super:
            raise error("revision_transition_invalid")
        new_refutations: list[Mapping[str, Any]] = []
        if parent.get("schema") in {"an-kla/revision-v2", "an-kla/revision-v3"}:
            if child.get("schema") != parent.get("schema"):
                raise error("revision_schema_downgrade")
            if child.get("features") != parent.get("features"):
                raise error("revision_transition_invalid")
            if (
                parent.get("schema") == "an-kla/revision-v3"
                and child.get("compaction_epoch") != parent.get("compaction_epoch")
            ):
                raise error("revision_transition_invalid")
            prior_refute = list(parent.get("refutations_map", []))
            current_refute = list(child.get("refutations_map", []))
            if current_refute[: len(prior_refute)] != prior_refute or len(current_refute) - len(prior_refute) not in {0, 1}:
                raise error("revision_transition_invalid")
            new_refutations = current_refute[len(prior_refute):]
        elif child.get("schema") == "an-kla/revision-v2":
            if len(child.get("refutations_map", [])) != 1:
                raise error("revision_transition_invalid")
            new_refutations = list(child["refutations_map"])
        for entry in new_refutations:
            refutation = store._read_json_object("refutations", entry["refutation_id"])
            if (
                refutation.get("target_revision") != parent_id
                or refutation.get("stream") != entry["stream"]
                or refutation.get("target_record_sha256") != entry["target_record_sha256"]
            ):
                raise error("revision_transition_invalid")
        if child.get("schema") in {"an-kla/revision-v2", "an-kla/revision-v3"}:
            from .receipt_validation import required_candidate_files
            from .transactions import _stage_evidence

            txid = str(child.get("transaction_id"))
            stage = _stage_evidence(store, txid, child_id)
            if stage is None:
                raise error("revision_transition_invalid")
            attempt = stage.get("attempt")
            operation = attempt.get("operation") if isinstance(attempt, dict) else None
            if (operation == "refute") != (len(new_refutations) == 1):
                raise error("revision_transition_invalid")
            try:
                required_candidate_files(store, txid, child_id, attempt)
            except Exception as exc:
                raise error("revision_transition_invalid") from exc
        child_id, child = str(parent_id), parent
    raise error("revision_transition_invalid")


def validate_lifecycle(
    store: Any, manifest: Mapping[str, Any], raw_records: Mapping[str, tuple[Mapping[str, Any], ...]],
    error: type[Exception],
) -> None:
    by_id = {
        stream: {str(row.get("id", "")): row for row in raw_records[stream]}
        for stream in STREAMS
    }
    superseded: set[tuple[str, str]] = set()
    successor: dict[tuple[str, str], str] = {}
    for entry in manifest.get("supersedes_map", []):
        key = (entry["stream"], entry["target_id"])
        if key in superseded or entry["target_id"] not in by_id[entry["stream"]] or entry["sustituida_por"] not in by_id[entry["stream"]]:
            raise error("legacy_supersedes_adoption_required")
        superseded.add(key)
        successor[key] = entry["sustituida_por"]
    for key in successor:
        visited: set[str] = set()
        cursor = key[1]
        while (key[0], cursor) in successor:
            if cursor in visited:
                raise error("legacy_supersedes_adoption_required")
            visited.add(cursor)
            cursor = successor[(key[0], cursor)]
    from .refutations import validate_refutation_storage

    for entry in manifest.get("refutations_map", []):
        stream = entry["stream"]
        matches = [row for row in raw_records[stream] if digest_json(row) == entry["target_record_sha256"]]
        if len(matches) != 1:
            raise error("manifest_refutations_map_invalid")
        target_id = str(matches[0].get("id", ""))
        if (stream, target_id) in superseded:
            raise error("manifest_lifecycle_overlay_conflict")
        refutation = store._read_json_object("refutations", entry["refutation_id"])
        validate_refutation_storage(store, refutation, entry)


__all__ = ["validate_lifecycle", "validate_manifest", "validate_revision_chain"]
