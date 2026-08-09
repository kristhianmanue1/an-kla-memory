"""Transaction attempts, outcomes, receipts, and read-only reconciliation."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
import unicodedata
from typing import Any, Mapping

from .canonical import bare_digest, canonical_json, digest_bytes, digest_json
from .audit_validation import observed_log_complete
from .receipt_validation import validate_receipt_evidence
from .revision_builder import build_child_manifest
from .storage_primitives import storage_error, sync_protected
from .transaction_attempts import (
    ATTEMPT_SCHEMA,
    TransactionError,
    begin_transaction,
    canonical_uuid as _canonical_uuid,
    validate_attempt,
)


OUTCOME_SCHEMA = "an-kla/commit-outcome-v2"
RECEIPT_SCHEMA = "an-kla/durability-receipt-v1"


def protected_file(path: str, content_sha256: str) -> dict[str, Any]:
    bare_digest(content_sha256)
    return {
        "path": path,
        "operation": "file_fsync",
        "content_sha256": content_sha256,
    }


def protected_directory(path: str) -> dict[str, Any]:
    return {"path": path, "operation": "directory_fsync", "content_sha256": None}


def write_receipt(
    store: Any,
    *,
    attempt: Mapping[str, Any],
    kind: str,
    candidate_revision: str,
    protected: list[dict[str, Any]],
    predecessor_receipt: str | None = None,
    repair_for_kind: str | None = None,
) -> str:
    checked = validate_attempt(attempt)
    if kind not in {"candidate-data-durable", "current-durable", "repair"}:
        raise TransactionError("invalid_receipt_kind")
    bare_digest(candidate_revision)
    if predecessor_receipt is not None:
        bare_digest(predecessor_receipt)
    if repair_for_kind not in {None, "candidate-data-durable", "current-durable"}:
        raise TransactionError("invalid_repair_kind")
    if kind == "candidate-data-durable" and (
        predecessor_receipt is not None or repair_for_kind is not None
    ):
        raise TransactionError("invalid_candidate_receipt_link")
    if kind == "current-durable" and (
        predecessor_receipt is None or repair_for_kind is not None
    ):
        raise TransactionError("invalid_current_receipt_link")
    if kind == "repair" and repair_for_kind is None:
        raise TransactionError("invalid_repair_receipt_link")
    checked_protected: list[dict[str, Any]] = []
    for item in protected:
        if not isinstance(item, dict) or set(item) != {
            "path",
            "operation",
            "content_sha256",
        }:
            raise TransactionError("invalid_receipt_protected")
        path = item["path"]
        operation = item["operation"]
        content = item["content_sha256"]
        if (
            not isinstance(path, str)
            or not path
            or path != unicodedata.normalize("NFC", path)
            or "\\" in path
            or Path(path).is_absolute()
            or any(part in {"", ".", ".."} for part in path.split("/"))
        ):
            raise TransactionError("invalid_receipt_path")
        if operation == "file_fsync":
            if not isinstance(content, str):
                raise TransactionError("invalid_receipt_content_hash")
            bare_digest(content)
        elif operation == "directory_fsync":
            if content is not None:
                raise TransactionError("invalid_receipt_directory_hash")
        else:
            raise TransactionError("invalid_receipt_operation")
        checked_protected.append(dict(item))
    ordered = sorted(
        checked_protected, key=lambda item: (item["path"], item["operation"])
    )
    if len({(item["path"], item["operation"]) for item in ordered}) != len(ordered):
        raise TransactionError("duplicate_receipt_path")
    sync_protected(store.root, ordered)
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "kind": kind,
        "transaction_id": checked["transaction_id"],
        "execution_fingerprint": checked["execution_fingerprint"],
        "candidate_revision": candidate_revision,
        "predecessor_receipt": predecessor_receipt,
        "repair_for_kind": repair_for_kind,
        "protected": ordered,
    }
    return store._write_json_object(
        f"transactions/{checked['transaction_id']}/receipts", receipt
    )


def make_outcome(
    *,
    attempt: Mapping[str, Any],
    parent_revision: str | None,
    candidate_revision: str | None,
    current_observed: str | None,
    candidate_relation: str,
    recorded: bool | None,
    audit_state: str,
    durability_state: str,
    operation_error_code: str | None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    checked = validate_attempt(attempt)
    if candidate_relation in {"current", "ancestor"}:
        authority = "candidate_authoritative"
        committed: bool | None = True
    elif current_observed == parent_revision and candidate_relation in {
        "orphan",
        "unknown",
    }:
        authority = "parent_lineage_authoritative"
        committed = False
    else:
        authority = "unknown"
        committed = None
    if authority == "unknown":
        state = "outcome_unknown"
    elif durability_state == "incomplete":
        state = "durability_incomplete"
    elif committed and audit_state != "complete":
        state = "committed_audit_incomplete"
    elif committed:
        state = "committed"
    else:
        state = "not_committed"
    return {
        "schema": OUTCOME_SCHEMA,
        "transaction_id": checked["transaction_id"],
        "parent_revision": parent_revision,
        "candidate_revision": candidate_revision,
        "current_observed": current_observed,
        "candidate_relation": candidate_relation,
        "state": state,
        "committed": committed,
        "recorded": recorded,
        "authority_state": authority,
        "audit_state": audit_state,
        "durability_state": durability_state,
        "operation_error_code": operation_error_code,
        "warnings": sorted(set(warnings or [])),
    }


def _journal(store: Any, txid: str) -> Mapping[str, Any] | None:
    path = store.root / "transactions" / f"{_canonical_uuid(txid)}.json"
    try:
        value = json.loads(path.read_bytes())
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {"corrupt": True}
    return value if isinstance(value, dict) else {"corrupt": True}


def _manifest_candidates(store: Any, txid: str) -> list[str]:
    result: list[str] = []
    directory = store.root / "revisions" / "sha256"
    for path in sorted(directory.glob("*.json")):
        try:
            payload = path.read_bytes()
            identifier = "sha256:" + path.stem
            if digest_bytes(payload) != identifier:
                continue
            value = json.loads(payload)
            if canonical_json(value) != payload:
                continue
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if (
            isinstance(value, dict)
            and value.get("schema") in {
                "an-kla/revision-v1", "an-kla/revision-v2", "an-kla/revision-v3"
            }
            and value.get("transaction_id") == txid
        ):
            result.append(identifier)
    return result


def _receipt_ids(store: Any, txid: str) -> list[str]:
    directory = store.root / "transactions" / txid / "receipts" / "sha256"
    return ["sha256:" + path.stem for path in sorted(directory.glob("*.json"))]


def _stage_evidence(store: Any, txid: str, candidate: str) -> Mapping[str, Any] | None:
    directory = store.root / "transactions" / txid / "stages" / "sha256"
    matches: list[Mapping[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            identifier = "sha256:" + path.stem
            value = store._read_json_object(
                f"transactions/{txid}/stages", identifier
            )
            if (
                isinstance(value, dict)
                and value.get("schema") == "an-kla/transaction-stage-v1"
                and value.get("candidate") == candidate
            ):
                attempt = validate_attempt(value.get("attempt"))
                if attempt["transaction_id"] != txid:
                    continue
                matches.append(value)
        except Exception:
            continue
    return matches[0] if len(matches) == 1 else None


def _stage_attempts(store: Any, txid: str) -> list[Mapping[str, Any]]:
    directory = store.root / "transactions" / txid / "stages" / "sha256"
    attempts: list[Mapping[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            value = store._read_json_object(
                f"transactions/{txid}/stages", "sha256:" + path.stem
            )
            attempt = validate_attempt(value.get("attempt"))
            if attempt["transaction_id"] != txid:
                raise TransactionError("transaction_binding_conflict")
            attempts.append(attempt)
        except TransactionError:
            raise
        except Exception:
            raise TransactionError("transaction_evidence_missing_or_invalid") from None
    return attempts


def _valid_receipt(
    store: Any,
    txid: str,
    identifier: Any,
    attempt: Mapping[str, Any],
    candidate: str,
    kind: str,
) -> Mapping[str, Any] | None:
    if not isinstance(identifier, str):
        return None
    try:
        return validate_receipt_evidence(
            store,
            txid=txid,
            identifier=identifier,
            attempt=attempt,
            candidate=candidate,
            kind=kind,
            relation=candidate_relation(store, candidate, store.read_current()),
        )
    except Exception:
        return None


def candidate_relation(store: Any, candidate: str | None, current: str | None) -> str:
    if candidate is None or current is None:
        return "unknown"
    cursor = current
    seen: set[str] = set()
    for _ in range(10000):
        if cursor == candidate:
            return "current" if cursor == current else "ancestor"
        if cursor in seen:
            return "unknown"
        seen.add(cursor)
        try:
            manifest = store._read_json_object("revisions", cursor)
        except Exception:
            return "unknown"
        parent = manifest.get("parent")
        if parent is None:
            return "orphan"
        if not isinstance(parent, str):
            return "unknown"
        cursor = parent
    return "unknown"


def inspect_transaction(store: Any, transaction_id: str) -> dict[str, Any]:
    """Reconcile a transaction without mutating any byte."""

    journal = _journal(store, transaction_id)
    candidates = _manifest_candidates(store, transaction_id)
    try:
        current = store.read_current()
    except Exception:
        current = None
    if len(candidates) > 1:
        return {
            "schema": OUTCOME_SCHEMA,
            "transaction_id": _canonical_uuid(transaction_id),
            "parent_revision": None,
            "candidate_revision": None,
            "current_observed": current,
            "candidate_relation": "unknown",
            "state": "outcome_unknown",
            "committed": None,
            "recorded": True if journal and not journal.get("corrupt") else None,
            "authority_state": "unknown",
            "audit_state": "incomplete",
            "durability_state": "unknown",
            "operation_error_code": "transaction_candidate_ambiguous",
            "warnings": [],
        }
    journal_invalid = journal is None or journal.get("corrupt")
    if journal_invalid:
        attempt = None
    else:
        raw_attempt = journal.get("attempt")
        try:
            attempt = validate_attempt(raw_attempt)
        except Exception:
            attempt = None
    if attempt is None and len(candidates) == 1:
        recovered = _stage_evidence(store, transaction_id, candidates[0])
        if recovered is not None:
            journal = recovered
            attempt = validate_attempt(recovered["attempt"])
    if attempt is None:
        return {
            "schema": OUTCOME_SCHEMA,
            "transaction_id": _canonical_uuid(transaction_id),
            "parent_revision": None,
            "candidate_revision": None,
            "current_observed": current,
            "candidate_relation": "unknown",
            "state": "outcome_unknown",
            "committed": None,
            "recorded": None,
            "authority_state": "unknown",
            "audit_state": "incomplete",
            "durability_state": "unknown",
            "operation_error_code": "transaction_evidence_missing_or_invalid",
            "warnings": [],
        }
    candidate = journal.get("candidate")
    if not isinstance(candidate, str):
        candidate = candidates[0] if len(candidates) == 1 else None
    if attempt.get("operation") == "refute" and candidate is not None:
        immutable_stage = _stage_evidence(store, transaction_id, candidate)
        resumable_pre_stage = (
            immutable_stage is None
            and not journal_invalid
            and journal.get("stage") == "prepared"
            and current == attempt.get("base_revision")
        )
        if not resumable_pre_stage:
            if immutable_stage is None or "refute_policy" not in immutable_stage:
                raise TransactionError("refute_content_hash_mismatch")
            if not journal_invalid and journal.get("refute_policy") != immutable_stage.get("refute_policy"):
                raise TransactionError("refute_content_hash_mismatch")
    relation = candidate_relation(store, candidate, current)
    parent = journal.get("parent")
    if not isinstance(parent, str):
        parent = attempt.get("base_revision")
    candidate_receipt = _valid_receipt(
        store,
        transaction_id,
        journal.get("candidate_receipt"),
        attempt,
        candidate,
        "candidate-data-durable",
    )
    current_receipt = _valid_receipt(
        store,
        transaction_id,
        journal.get("current_receipt"),
        attempt,
        candidate,
        "current-durable",
    )
    repair_receipt: Mapping[str, Any] | None = None
    if candidate_receipt is None or current_receipt is None:
        for receipt_id in _receipt_ids(store, transaction_id):
            candidate_receipt = candidate_receipt or _valid_receipt(
                store,
                transaction_id,
                receipt_id,
                attempt,
                candidate,
                "candidate-data-durable",
            )
            current_receipt = current_receipt or _valid_receipt(
                store,
                transaction_id,
                receipt_id,
                attempt,
                candidate,
                "current-durable",
            )
            candidate_repair = _valid_receipt(
                store,
                transaction_id,
                receipt_id,
                attempt,
                candidate,
                "repair",
            )
            if candidate_repair is not None:
                repair_receipt = candidate_repair
    if current_receipt is not None and (
        candidate_receipt is None
        or current_receipt.get("predecessor_receipt") != digest_json(candidate_receipt)
    ):
        current_receipt = None
    repair_kind = repair_receipt.get("repair_for_kind") if repair_receipt else None
    durability = "complete" if (
        (current_receipt is not None or repair_kind == "current-durable")
        if relation in {"current", "ancestor"}
        else (candidate_receipt is not None or repair_kind == "candidate-data-durable")
    ) else "incomplete"
    journal_committed = not journal_invalid and journal.get("stage") == "committed"
    audit = "incomplete"
    if journal_committed and (
        attempt["operation"] == "initialize"
        or observed_log_complete(store, journal, transaction_id, candidate)
    ):
        audit = "complete"
    return make_outcome(
        attempt=attempt,
        parent_revision=parent,
        candidate_revision=candidate,
        current_observed=current,
        candidate_relation=relation,
        recorded=True,
        audit_state=audit,
        durability_state=durability,
        operation_error_code=None if audit == "complete" else "audit_incomplete",
    )


def commit_locked(
    store: Any,
    *,
    observed: str,
    checkpoint_patch: Mapping[str, Any],
    pending: Mapping[str, list[dict[str, Any]]],
    attempt: Mapping[str, Any],
    policy_metadata: Mapping[str, Any] | None = None,
    supersedes: list[dict[str, str]] | None = None,
    refute_objects: Mapping[str, Any] | None = None,
    store_identity: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Write/reconcile one candidate while the caller owns the store lock."""

    checked = validate_attempt(attempt)
    if checked["operation"] != "checkpoint" and checkpoint_patch:
        raise TransactionError("governed_checkpoint_update_required")
    if checked["operation"] == "refute":
        if policy_metadata is None or refute_objects is None:
            raise TransactionError("invalid_refute_objects")
    elif refute_objects is not None:
        raise TransactionError("invalid_refute_objects")
    txid = checked["transaction_id"]
    existing = _journal(store, txid)
    candidates = _manifest_candidates(store, txid)
    if len(candidates) > 1:
        raise TransactionError("transaction_candidate_ambiguous")
    evidence_attempts = _stage_attempts(store, txid)
    if existing is not None and not existing.get("corrupt"):
        prior = existing.get("attempt")
        if prior != checked:
            raise TransactionError("transaction_binding_conflict")
        evidence_attempts.append(validate_attempt(prior))
    elif existing is not None and not evidence_attempts and not candidates:
        raise TransactionError("transaction_evidence_missing_or_invalid")
    if any(prior != checked for prior in evidence_attempts):
        raise TransactionError("transaction_binding_conflict")
    if candidates and not evidence_attempts:
        raise TransactionError("transaction_evidence_missing_or_invalid")
    if candidates:
        inspected = inspect_transaction(store, txid)
        if inspected.get("committed") is True:
            return str(inspected["candidate_revision"]), inspected

    base = store.snapshot(observed)
    assigned = store._assign_records(base, pending)
    revision_number = int(base.manifest["revision"]) + 1
    if checked["operation"] == "checkpoint":
        checkpoint = deepcopy(dict(checkpoint_patch))
        checkpoint["revision"] = revision_number
    else:
        checkpoint = base.checkpoint
    candidate: str | None = None
    candidate_receipt: str | None = None
    current_receipt: str | None = None
    recorded = False
    audit_state = "not_started"
    try:
        prepared: dict[str, Any] = {
            "stage": "prepared",
            "parent": observed,
            "attempt": checked,
        }
        metadata_key = "refute_policy" if checked["operation"] == "refute" else "write_policy"
        if policy_metadata is not None:
            prepared[metadata_key] = deepcopy(dict(policy_metadata))
        store._write_transaction(txid, prepared)
        recorded = True
        audit_state = "prepared"

        segment_ids: dict[str, list[str]] = {}
        new_segments: list[tuple[str, str]] = []
        for stream in ("facts", "events", "episodes"):
            existing_segments = list(base.manifest.get(f"{stream}_segments", []))
            if assigned[stream]:
                segment_id = store._write_segment(stream, assigned[stream])
                existing_segments.append(segment_id)
                new_segments.append((stream, segment_id))
            segment_ids[stream] = existing_segments
        checkpoint_id = str(base.manifest["checkpoint"]) if checkpoint is base.checkpoint else store._write_json_object("checkpoints", checkpoint)
        inherited = list(base.manifest.get("supersedes_map", []))
        new_map = [*inherited, *(list(supersedes) if supersedes else [])]
        refutation_entry: dict[str, str] | None = None
        claim_id: str | None = None
        attestation_id: str | None = None
        refutation_id: str | None = None
        if refute_objects is not None:
            if checked["operation"] != "refute":
                raise TransactionError("invalid_refute_objects")
            claim = deepcopy(dict(refute_objects["authority_claim"]))
            attestation = deepcopy(dict(refute_objects["authority_attestation"]))
            refutation = deepcopy(dict(refute_objects["refutation"]))
            claim_id = store._write_json_object("authority-claims", claim)
            attestation_id = store._write_json_object("authority-attestations", attestation)
            refutation_id = store._write_json_object("refutations", refutation)
            if (
                claim_id != refutation.get("authority_claim_sha256")
                or attestation_id != refutation.get("authority_attestation_id")
                or refutation_id != policy_metadata.get("refutation_id")
            ):
                raise TransactionError("refute_content_hash_mismatch")
            refutation_entry = {
                "stream": str(refutation["stream"]),
                "target_record_sha256": str(refutation["target_record_sha256"]),
                "refutation_id": refutation_id,
            }
        elif checked["operation"] == "refute":
            raise TransactionError("invalid_refute_objects")
        inherited_refutations = list(base.manifest.get("refutations_map", []))
        refutations_map = [
            *inherited_refutations,
            *([refutation_entry] if refutation_entry is not None else []),
        ]
        manifest = build_child_manifest(
            base=base.manifest, revision=revision_number, parent=observed,
            segment_ids=segment_ids, checkpoint=checkpoint_id,
            transaction_id=txid, operation=checked["operation"],
            store_identity=store_identity, supersedes_map=new_map,
            refutations_map=refutations_map,
        )
        store._validate_manifest(manifest)
        candidate = store._write_json_object("revisions", manifest)
        intent_id = store._write_ref_log(
            {
                "schema": "an-kla/ref-log-v1",
                "kind": "intent",
                "transaction_id": txid,
                "parent": observed,
                "candidate": candidate,
            }
        )
        candidate_stage: dict[str, Any] = {
            "schema": "an-kla/transaction-stage-v1",
            "stage": "candidate_prepared",
            "parent": observed,
            "candidate": candidate,
            "attempt": checked,
        }
        if policy_metadata is not None:
            candidate_stage[metadata_key] = deepcopy(dict(policy_metadata))
        stage_id = store._write_json_object(f"transactions/{txid}/stages", candidate_stage)
        store._write_transaction(
            txid,
            {
                **candidate_stage,
                "stage_object": stage_id,
                "candidate_receipt": None,
                "current_receipt": None,
            },
        )
        protected = [
            protected_file(
                f"revisions/sha256/{candidate.removeprefix('sha256:')}.json",
                candidate,
            ),
            protected_file(
                f"checkpoints/sha256/{checkpoint_id.removeprefix('sha256:')}.json",
                checkpoint_id,
            ),
            protected_file(
                f"refs/ref-log/sha256/{intent_id.removeprefix('sha256:')}.json",
                intent_id,
            ),
            protected_file(
                f"transactions/{txid}/stages/sha256/{stage_id.removeprefix('sha256:')}.json",
                stage_id,
            ),
            protected_directory("revisions/sha256"),
            protected_directory("checkpoints/sha256"),
            protected_directory("refs/ref-log/sha256"),
            protected_directory(f"transactions/{txid}/stages/sha256"),
        ]
        for stream, segment_id in new_segments:
            protected.extend(
                [
                    protected_file(
                        f"segments/{stream}/sha256/{segment_id.removeprefix('sha256:')}.jsonl",
                        segment_id,
                    ),
                    protected_directory(f"segments/{stream}/sha256"),
                ]
            )
        if refute_objects is not None:
            assert claim_id is not None and attestation_id is not None and refutation_id is not None
            protected.extend(
                [
                    protected_file(
                        f"authority-claims/sha256/{claim_id.removeprefix('sha256:')}.json",
                        claim_id,
                    ),
                    protected_directory("authority-claims/sha256"),
                    protected_file(
                        f"authority-attestations/sha256/{attestation_id.removeprefix('sha256:')}.json",
                        attestation_id,
                    ),
                    protected_directory("authority-attestations/sha256"),
                    protected_file(
                        f"refutations/sha256/{refutation_id.removeprefix('sha256:')}.json",
                        refutation_id,
                    ),
                    protected_directory("refutations/sha256"),
                ]
            )
        candidate_receipt = write_receipt(
            store,
            attempt=checked,
            kind="candidate-data-durable",
            candidate_revision=candidate,
            protected=protected,
        )
        store._write_transaction(
            txid,
            {
                **candidate_stage,
                "stage_object": stage_id,
                "candidate_receipt": candidate_receipt,
                "current_receipt": None,
            },
        )
        if store.read_current() != observed:
            raise OSError("current_changed_before_commit")
        store._replace_current(candidate)
        current_receipt = write_receipt(
            store,
            attempt=checked,
            kind="current-durable",
            candidate_revision=candidate,
            predecessor_receipt=candidate_receipt,
            protected=[
                protected_file(
                    "refs/CURRENT", digest_bytes((candidate + "\n").encode("ascii"))
                ),
                protected_directory("refs"),
            ],
        )
        try:
            confirmed_current = store.read_current()
        except Exception as exc:
            raise storage_error("current_reread_failed", exc) from exc
        if confirmed_current != candidate:
            raise storage_error("current_reread_mismatch", OSError("CURRENT mismatch"))
        committed: dict[str, Any] = {
            "stage": "committed",
            "parent": observed,
            "candidate": candidate,
            "attempt": checked,
            "stage_object": stage_id,
            "candidate_receipt": candidate_receipt,
            "current_receipt": current_receipt,
            "observed_log": None,
        }
        if policy_metadata is not None:
            committed[metadata_key] = deepcopy(dict(policy_metadata))
        audit_state = "incomplete"
        store._write_transaction(txid, committed)
        try:
            observed_id = store._write_ref_log(
                {
                    "schema": "an-kla/ref-log-v1",
                    "kind": "observed_commit",
                    "transaction_id": txid,
                    "parent": observed,
                    "candidate": candidate,
                    "intent": intent_id,
                }
            )
            committed["observed_log"] = observed_id
            store._write_transaction(txid, committed)
            audit_state = "complete"
        except OSError:
            audit_state = "incomplete"
    except OSError as exc:
        current = observed
        if recorded:
            try:
                current = store.read_current()
            except Exception:
                current = None
        relation = candidate_relation(store, candidate, current)
        durability = (
            "complete"
            if (
                current_receipt is not None
                if relation in {"current", "ancestor"}
                else candidate_receipt is not None
            )
            else "incomplete"
        )
        outcome = make_outcome(
            attempt=checked,
            parent_revision=observed,
            candidate_revision=candidate,
            current_observed=current,
            candidate_relation=relation,
            recorded=recorded,
            audit_state=audit_state if audit_state != "not_started" else "incomplete",
            durability_state=durability,
            operation_error_code=getattr(exc, "code", "storage_io_failed"),
            warnings=[
                *(["transaction_not_recorded"] if not recorded else []),
                *(["cleanup_incomplete"] if getattr(exc, "cleanup_incomplete", False) else []),
                *(["close_incomplete"] if getattr(exc, "close_incomplete", False) else []),
            ],
        )
        return (current if isinstance(current, str) else observed), outcome

    relation = candidate_relation(store, candidate, candidate)
    outcome = make_outcome(
        attempt=checked,
        parent_revision=observed,
        candidate_revision=candidate,
        current_observed=candidate,
        candidate_relation=relation,
        recorded=True,
        audit_state=audit_state,
        durability_state="complete",
        operation_error_code=None if audit_state == "complete" else "observed_log_failed",
    )
    return str(candidate), outcome
