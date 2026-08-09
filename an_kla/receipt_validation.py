"""Semantic validation for content-addressed durability receipts."""

from __future__ import annotations

from pathlib import Path
import json
import unicodedata
from typing import Any, Mapping

from .canonical import bare_digest, digest_bytes, digest_json


def _safe_relative(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != unicodedata.normalize("NFC", value)
        or "\\" in value
        or Path(value).is_absolute()
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValueError("invalid_receipt_path")
    return value


def _exact_stage_path(
    store: Any, txid: str, candidate: str, attempt: Mapping[str, Any]
) -> str:
    journal_path = store.root / "transactions" / f"{txid}.json"
    stage_id = None
    try:
        journal = json.loads(journal_path.read_bytes())
        if isinstance(journal, dict) and isinstance(journal.get("stage_object"), str):
            stage_id = journal["stage_object"]
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        pass
    candidates = [stage_id] if stage_id is not None else [
        "sha256:" + path.stem
        for path in sorted(
            (store.root / "transactions" / txid / "stages" / "sha256").glob(
                "*.json"
            )
        )
    ]
    matches: list[str] = []
    for identifier in candidates:
        try:
            value = store._read_json_object(
                f"transactions/{txid}/stages", identifier
            )
        except Exception:
            continue
        if (
            value.get("schema") == "an-kla/transaction-stage-v1"
            and value.get("stage") == "candidate_prepared"
            and value.get("candidate") == candidate
            and value.get("attempt") == attempt
        ):
            matches.append(identifier)
    if len(matches) != 1:
        raise ValueError("candidate_stage_missing_or_ambiguous")
    return (
        f"transactions/{txid}/stages/sha256/"
        + matches[0].removeprefix("sha256:")
        + ".json"
    )


def _exact_intent_path(store: Any, txid: str, candidate: str, parent: Any) -> str:
    matches: list[str] = []
    directory = store.root / "refs" / "ref-log" / "sha256"
    for path in sorted(directory.glob("*.json")):
        try:
            identifier = "sha256:" + path.stem
            value = store._read_json_object("refs/ref-log", identifier)
        except Exception:
            continue
        if (
            value.get("schema") == "an-kla/ref-log-v1"
            and value.get("kind") == "intent"
            and value.get("transaction_id") == txid
            and value.get("candidate") == candidate
            and value.get("parent") == parent
        ):
            matches.append(identifier)
    if len(matches) != 1:
        raise ValueError("transaction_intent_missing_or_ambiguous")
    return "refs/ref-log/sha256/" + matches[0].removeprefix("sha256:") + ".json"


def required_candidate_files(
    store: Any, txid: str, candidate: str, attempt: Mapping[str, Any]
) -> set[str]:
    manifest = store._read_json_object("revisions", candidate)
    required = {
        f"revisions/sha256/{candidate.removeprefix('sha256:')}.json",
        "checkpoints/sha256/"
        + str(manifest["checkpoint"]).removeprefix("sha256:")
        + ".json",
    }
    parent = manifest.get("parent")
    parent_manifest = (
        store._read_json_object("revisions", parent) if isinstance(parent, str) else {}
    )
    for stream in ("facts", "events", "episodes"):
        inherited = set(parent_manifest.get(f"{stream}_segments", []))
        for identifier in manifest.get(f"{stream}_segments", []):
            if identifier not in inherited:
                required.add(
                    f"segments/{stream}/sha256/"
                    + str(identifier).removeprefix("sha256:")
                    + ".jsonl"
                )
    inherited_refutations = {
        item.get("refutation_id")
        for item in parent_manifest.get("refutations_map", [])
        if isinstance(item, dict)
    }
    new_refutations = []
    for entry in manifest.get("refutations_map", []):
        if not isinstance(entry, dict) or entry.get("refutation_id") in inherited_refutations:
            continue
        new_refutations.append(entry)
        refutation_id = str(entry["refutation_id"])
        refutation = store._read_json_object("refutations", refutation_id)
        claim_id = str(refutation["authority_claim_sha256"])
        attestation_id = str(refutation["authority_attestation_id"])
        required.update(
            {
                f"refutations/sha256/{refutation_id.removeprefix('sha256:')}.json",
                f"authority-claims/sha256/{claim_id.removeprefix('sha256:')}.json",
                f"authority-attestations/sha256/{attestation_id.removeprefix('sha256:')}.json",
            }
        )
    stage_path = _exact_stage_path(store, txid, candidate, attempt)
    required.add(stage_path)
    stage_id = "sha256:" + Path(stage_path).stem
    stage = store._read_json_object(f"transactions/{txid}/stages", stage_id)
    if attempt.get("operation") == "compact":
        from .compaction_contracts import (
            validate_epoch_manifest, validate_policy_config,
        )

        if manifest.get("schema") != "an-kla/revision-v3" or parent is not None:
            raise ValueError("compaction_transaction_binding_invalid")
        link = manifest["compaction_epoch"]
        epoch = validate_epoch_manifest(
            store._read_json_object("compaction/epochs", link["epoch_manifest"])
        )
        try:
            historical_policy = validate_policy_config(
                stage.get("compaction_policy")
            )
        except Exception as exc:
            raise ValueError("compaction_transaction_binding_invalid") from exc
        if (
            epoch["compaction_policy"] != digest_json(historical_policy)
            or epoch["transaction_id"] != txid
            or epoch["base_revision"] != attempt.get("base_revision")
        ):
            raise ValueError("compaction_transaction_binding_invalid")
        required.update(
            {
                f"compaction/restore-proofs/sha256/{str(epoch['restore_proof']).removeprefix('sha256:')}.json",
                f"compaction/catalogs/sha256/{str(epoch['tombstone_catalog']).removeprefix('sha256:')}.json",
                f"compaction/epochs/sha256/{str(link['epoch_manifest']).removeprefix('sha256:')}.json",
            }
        )
    elif attempt.get("operation") == "refute":
        if len(new_refutations) != 1:
            raise ValueError("refute_manifest_delta_invalid")
        entry = new_refutations[0]
        refutation = store._read_json_object("refutations", entry["refutation_id"])
        expected_metadata = {
            "schema": "an-kla/refute-policy-transaction-v1",
            "proposal_sha256": refutation["proposal_sha256"],
            "authority_claim_sha256": refutation["authority_claim_sha256"],
            "authority_attestation_id": refutation["authority_attestation_id"],
            "policy_fingerprint": refutation["policy_fingerprint"],
            "decision_sha256": refutation["decision_sha256"],
            "evidence_sha256": refutation["evidence_sha256"],
            "plan_fingerprint": refutation["plan_fingerprint"],
            "decision": "refute",
            "reason": refutation["reason"],
            "target": {
                "stream": refutation["stream"],
                "record_sha256": refutation["target_record_sha256"],
            },
            "refutation_id": entry["refutation_id"],
        }
        if (
            stage.get("refute_policy") != expected_metadata
            or attempt.get("plan_fingerprint") != refutation["plan_fingerprint"]
            or refutation.get("target_revision") != parent
        ):
            raise ValueError("refute_transaction_binding_invalid")
    elif new_refutations or "refute_policy" in stage or "compaction_policy" in stage:
        raise ValueError("refute_transaction_binding_invalid")
    if attempt.get("operation") != "initialize":
        intent_parent = (
            attempt.get("base_revision")
            if attempt.get("operation") == "compact"
            else parent
        )
        required.add(_exact_intent_path(store, txid, candidate, intent_parent))
    return required


def validate_receipt_evidence(
    store: Any,
    *,
    txid: str,
    identifier: str,
    attempt: Mapping[str, Any],
    candidate: str,
    kind: str,
    relation: str,
) -> Mapping[str, Any]:
    """Return a receipt only if shape, binding and protected bytes are valid."""

    value = store._read_json_object(f"transactions/{txid}/receipts", identifier)
    if set(value) != {
        "schema",
        "kind",
        "transaction_id",
        "execution_fingerprint",
        "candidate_revision",
        "predecessor_receipt",
        "repair_for_kind",
        "protected",
    }:
        raise ValueError("invalid_receipt_shape")
    if (
        value["schema"] != "an-kla/durability-receipt-v1"
        or value["kind"] != kind
        or value["transaction_id"] != txid
        or value["execution_fingerprint"] != attempt["execution_fingerprint"]
        or value["candidate_revision"] != candidate
    ):
        raise ValueError("invalid_receipt_binding")
    predecessor = value["predecessor_receipt"]
    repair_for = value["repair_for_kind"]
    if predecessor is not None:
        bare_digest(predecessor)
    if kind == "candidate-data-durable":
        if predecessor is not None or repair_for is not None:
            raise ValueError("invalid_candidate_receipt_link")
    elif kind == "current-durable":
        if predecessor is None or repair_for is not None:
            raise ValueError("invalid_current_receipt_link")
    elif kind == "repair":
        if repair_for not in {"candidate-data-durable", "current-durable"}:
            raise ValueError("invalid_repair_receipt_link")
    else:
        raise ValueError("invalid_receipt_kind")

    protected = value["protected"]
    if not isinstance(protected, list) or not protected:
        raise ValueError("invalid_receipt_protected")
    normalized: list[tuple[str, str, Any]] = []
    for item in protected:
        if not isinstance(item, dict) or set(item) != {
            "path",
            "operation",
            "content_sha256",
        }:
            raise ValueError("invalid_receipt_protected")
        relative = _safe_relative(item["path"])
        operation = item["operation"]
        content = item["content_sha256"]
        target = store.root.joinpath(*relative.split("/"))
        if target.is_symlink():
            raise ValueError("invalid_receipt_symlink")
        if operation == "file_fsync":
            if not isinstance(content, str):
                raise ValueError("invalid_receipt_content_hash")
            bare_digest(content)
            payload = target.read_bytes()
            if not (relative == "refs/CURRENT" and relation == "ancestor"):
                if digest_bytes(payload) != content:
                    raise ValueError("receipt_content_hash_mismatch")
        elif operation == "directory_fsync":
            if content is not None or not target.is_dir():
                raise ValueError("invalid_receipt_directory")
        else:
            raise ValueError("invalid_receipt_operation")
        normalized.append((relative, operation, content))
    if normalized != sorted(normalized, key=lambda item: (item[0], item[1])):
        raise ValueError("receipt_protected_not_sorted")
    if len({(item[0], item[1]) for item in normalized}) != len(normalized):
        raise ValueError("receipt_protected_duplicate")
    files = {path for path, operation, _content in normalized if operation == "file_fsync"}
    directories = {
        path for path, operation, _content in normalized if operation == "directory_fsync"
    }
    target_kind = repair_for if kind == "repair" else kind
    expected_files: set[str]
    if target_kind == "candidate-data-durable":
        expected_files = required_candidate_files(store, txid, candidate, attempt)
    elif kind == "repair":
        expected_files = required_candidate_files(store, txid, candidate, attempt) | {"refs/CURRENT"}
    else:
        expected_files = {"refs/CURRENT"}
    if files != expected_files:
        raise ValueError("receipt_required_files_mismatch")
    expected_directories = {path.rsplit("/", 1)[0] for path in expected_files}
    if directories != expected_directories:
        raise ValueError("receipt_required_directories_mismatch")
    for path in files:
        parent = path.rsplit("/", 1)[0]
        if parent not in directories:
            raise ValueError("receipt_parent_directory_missing")
    return value


__all__ = ["required_candidate_files", "validate_receipt_evidence"]
