"""Governed, export-bound compaction for ADR-0028."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping

from .canonical import bare_digest, digest_bytes, digest_json
from .compaction_contracts import (
    CompactionError, ensure_supported_platform, policy_config,
    policy_fingerprint, validate_catalog, validate_catalog_chain, validate_epoch_manifest,
    validate_proposal, validate_restore_proof,
)
from .compaction_inventory import (
    delete_exact, inventory_deletable, sync_cleanup_parents, validate_no_links,
)
from .compaction_projection import project_snapshot
from .export_restore import _validated, restore_export
from .identity import assert_unchanged, identity_lock, read_binding
from .reader_gate import exclusive_reader_gate, shared_reader_gate
from .receipt_validation import validate_receipt_evidence
from .revision_validation import validate_manifest
from .transaction_attempts import begin_transaction
from .transactions import (
    candidate_relation, inspect_transaction, protected_directory,
    protected_file, write_receipt,
)


PLANNING_SCHEMA = "an-kla/compaction-planning-result-v1"
PLAN_SCHEMA = "an-kla/compaction-plan-v1"
RESULT_SCHEMA = "an-kla/compaction-result-v1"
_TX_JOURNAL = re.compile(
    r"anchor/memory/transactions/([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\.json"
)
_TX_TOMBSTONE = re.compile(
    r"transactions/([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\.json"
)


def _restore_proof(bundle: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest, payloads, _verified = _validated(bundle, 100000, 10 * 1024**3)
    with tempfile.TemporaryDirectory(prefix="an-kla-compaction-restore-") as root:
        result = restore_export(bundle, root)
        if result.get("state") != "published" or result.get("published") is not True:
            raise CompactionError("compaction_restore_not_durable")
        from .store import MemoryStore

        restored = MemoryStore(root)
        status = restored.verify()
        if not status.get("ok") or restored.read_current() != manifest["core"]["current_revision"]:
            raise CompactionError("compaction_restore_verify_failed")
        binding = read_binding(restored)
        if (
            digest_bytes(binding["project_bytes"]) != manifest["core"]["project_identity_sha256"]
            or digest_bytes(binding["store_bytes"]) != manifest["core"]["store_identity_sha256"]
        ):
            raise CompactionError("compaction_restore_identity_mismatch")
        transaction_ids: set[str] = set()
        for relative in sorted(payloads):
            matched = _TX_JOURNAL.fullmatch(relative)
            if matched is not None:
                transaction_ids.add(matched.group(1))
        current_manifest = restored.snapshot().manifest
        if current_manifest.get("schema") == "an-kla/revision-v3":
            catalogs = validate_catalog_chain(
                restored,
                current_manifest["compaction_epoch"]["tombstone_catalog"],
            )
            for _epoch_id, (_identifier, catalog) in catalogs.items():
                for item in catalog["object_tombstones"]:
                    matched = _TX_TOMBSTONE.fullmatch(item["path"])
                    if matched is not None:
                        transaction_ids.add(matched.group(1))
        outcomes = [
            {
                "transaction_id": txid,
                "outcome": restored.inspect_transaction(txid),
            }
            for txid in sorted(transaction_ids)
        ]
        proof = {
            "schema": "an-kla/compaction-restore-proof-v1",
            "manifest_sha256": manifest["manifest_sha256"],
            "inventory_sha256": digest_json(manifest["core"]["entries"]),
            "current_revision": manifest["core"]["current_revision"],
            "project_identity_sha256": manifest["core"]["project_identity_sha256"],
            "store_identity_sha256": manifest["core"]["store_identity_sha256"],
            "transaction_outcomes_sha256": digest_json(outcomes),
            "restore_result_sha256": digest_json(result),
        }
        return validate_restore_proof(proof), manifest


def _live_revision_ids(store: Any, base: str) -> list[str]:
    result: list[str] = []
    cursor = base
    for _ in range(100000):
        result.append(cursor)
        manifest = store._read_json_object("revisions", cursor)
        parent = manifest.get("parent")
        if parent is None:
            return result
        if not isinstance(parent, str):
            raise CompactionError("compaction_revision_chain_invalid")
        cursor = parent
    raise CompactionError("compaction_revision_chain_invalid")


def _prior_catalog(store: Any, manifest: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if manifest.get("schema") != "an-kla/revision-v3":
        return [], []
    link = manifest["compaction_epoch"]
    catalog_id = link["tombstone_catalog"]
    catalog = validate_catalog(store._read_json_object("compaction/catalogs", catalog_id))
    validate_catalog_chain(store, catalog_id)
    previous = list(catalog["previous_catalogs"])
    previous.append(
        {
            "epoch_id": catalog["epoch_id"],
            "catalog_sha256": catalog_id,
            "export_manifest_sha256": catalog["export_manifest_sha256"],
        }
    )
    previous.sort(key=lambda item: item["epoch_id"])
    if len({item["epoch_id"] for item in previous}) != len(previous):
        raise CompactionError("compaction_catalog_invalid")
    return list(catalog["archived_revisions"]), previous


def _protected_paths(
    store: Any, proposal: Mapping[str, Any], checkpoint: str,
    segment_ids: Mapping[str, list[str]], candidate: str | None = None,
) -> set[str]:
    protected = {
        f"checkpoints/sha256/{bare_digest(checkpoint)}.json",
        f"transactions/{proposal['transaction_id']}.json",
    }
    for stream, identifiers in segment_ids.items():
        for identifier in identifiers:
            protected.add(f"segments/{stream}/sha256/{bare_digest(identifier)}.jsonl")
    if candidate is not None:
        protected.add(f"revisions/sha256/{bare_digest(candidate)}.json")
    transaction_root = store.root / "transactions" / proposal["transaction_id"]
    if transaction_root.exists():
        for path in transaction_root.rglob("*"):
            if path.is_file() or path.is_symlink():
                protected.add(path.relative_to(store.root).as_posix())
    return protected


def _build_under_gate(
    store: Any, proposal: Mapping[str, Any], proof: Mapping[str, Any]
) -> dict[str, Any]:
    validate_no_links(store)
    if store.read_current() != proposal["base_revision"]:
        raise CompactionError("compaction_base_changed")
    snapshot = store._snapshot_under_gate(proposal["base_revision"])
    binding = read_binding(store)
    if (
        proof["current_revision"] != proposal["base_revision"]
        or proof["manifest_sha256"] != proposal["export_manifest_sha256"]
        or proof["project_identity_sha256"] != digest_bytes(binding["project_bytes"])
        or proof["store_identity_sha256"] != binding["store_identity"]
        or snapshot.manifest.get("store_identity") != binding["store_identity"]
    ):
        raise CompactionError("compaction_bundle_binding_mismatch")
    projection = project_snapshot(snapshot)
    prior_archived, previous_catalogs = _prior_catalog(store, snapshot.manifest)
    archived = list(prior_archived)
    archived.extend(
        {
            "revision": revision,
            "epoch_id": proposal["epoch_id"],
            "export_manifest_sha256": proposal["export_manifest_sha256"],
        }
        for revision in _live_revision_ids(store, proposal["base_revision"])
    )
    archived.sort(key=lambda item: item["revision"])
    if len({item["revision"] for item in archived}) != len(archived):
        raise CompactionError("compaction_archived_revision_conflict")
    checkpoint = str(snapshot.manifest["checkpoint"])
    protected = _protected_paths(store, proposal, checkpoint, projection["segment_ids"])
    object_tombstones = inventory_deletable(store, protected)
    delete_set_sha256 = digest_json(object_tombstones)
    catalog = {
        "schema": "an-kla/compaction-tombstone-catalog-v1",
        "epoch_id": proposal["epoch_id"],
        "source_revision": proposal["base_revision"],
        "export_manifest_sha256": proposal["export_manifest_sha256"],
        "delete_set_sha256": delete_set_sha256,
        "archived_revisions": archived,
        "record_tombstones": projection["record_tombstones"],
        "object_tombstones": object_tombstones,
        "previous_catalogs": previous_catalogs,
    }
    validate_catalog(catalog)
    catalog_id = digest_json(catalog)
    proof_id = digest_json(proof)
    epoch = {
        "schema": "an-kla/compaction-epoch-v1",
        "epoch_id": proposal["epoch_id"],
        "transaction_id": proposal["transaction_id"],
        "base_revision": proposal["base_revision"],
        "proposal_sha256": digest_json(proposal),
        "export_manifest_sha256": proposal["export_manifest_sha256"],
        "restore_proof": proof_id,
        "tombstone_catalog": catalog_id,
        "delete_set_sha256": delete_set_sha256,
        "compaction_policy": policy_fingerprint(),
    }
    validate_epoch_manifest(epoch)
    epoch_id = digest_json(epoch)
    candidate = {
        "schema": "an-kla/revision-v3",
        "revision": int(snapshot.manifest["revision"]) + 1,
        "parent": None,
        "facts_segments": projection["segment_ids"]["facts"],
        "events_segments": projection["segment_ids"]["events"],
        "episodes_segments": projection["segment_ids"]["episodes"],
        "checkpoint": checkpoint,
        "transaction_id": proposal["transaction_id"],
        "canonicalization": "canonical-json/v1",
        "integrity_claim": "content_identity_not_truth_or_authorship",
        "store_identity": binding["store_identity"],
        "features": ["refutations/v1", "compaction/v1"],
        "supersedes_map": [],
        "refutations_map": [],
        "compaction_epoch": {
            "epoch_id": proposal["epoch_id"],
            "source_revision": proposal["base_revision"],
            "export_manifest_sha256": proposal["export_manifest_sha256"],
            "tombstone_catalog": catalog_id,
            "epoch_manifest": epoch_id,
        },
    }
    validate_manifest(candidate, CompactionError)
    candidate_id = digest_json(candidate)
    core = {
        "base_revision": proposal["base_revision"],
        "transaction_id": proposal["transaction_id"],
        "epoch_id": proposal["epoch_id"],
        "proposal_sha256": digest_json(proposal),
        "restore_proof_sha256": proof_id,
        "catalog_sha256": catalog_id,
        "epoch_manifest_sha256": epoch_id,
        "delete_set_sha256": delete_set_sha256,
        "project_identity_sha256": proof["project_identity_sha256"],
        "store_identity_sha256": binding["store_identity"],
        "policy_fingerprint": policy_fingerprint(),
        "candidate_revision": candidate_id,
    }
    plan = {"schema": PLAN_SCHEMA, "core": core, "fingerprint": digest_json(core)}
    return {
        "schema": PLANNING_SCHEMA,
        "proposal": deepcopy(dict(proposal)),
        "restore_proof": deepcopy(dict(proof)),
        "catalog": catalog,
        "epoch_manifest": epoch,
        "candidate_manifest": candidate,
        "delete_set": object_tombstones,
        "plan": plan,
    }


def validate_planning_result(
    value: Mapping[str, Any], *, require_installed_policy: bool = False
) -> dict[str, Any]:
    fields = {
        "schema", "proposal", "restore_proof", "catalog", "epoch_manifest",
        "candidate_manifest", "delete_set", "plan",
    }
    if not isinstance(value, dict) or set(value) != fields or value.get("schema") != PLANNING_SCHEMA:
        raise CompactionError("compaction_planning_result_invalid")
    checked = deepcopy(dict(value))
    proposal = validate_proposal(checked["proposal"])
    proof = validate_restore_proof(checked["restore_proof"])
    catalog = validate_catalog(checked["catalog"])
    epoch = validate_epoch_manifest(checked["epoch_manifest"])
    candidate = checked["candidate_manifest"]
    validate_manifest(candidate, CompactionError)
    plan = checked["plan"]
    if not isinstance(plan, dict) or set(plan) != {"schema", "core", "fingerprint"} or plan.get("schema") != PLAN_SCHEMA:
        raise CompactionError("compaction_plan_invalid")
    core = plan["core"]
    if not isinstance(core, dict) or set(core) != {
        "base_revision", "transaction_id", "epoch_id", "proposal_sha256",
        "restore_proof_sha256", "catalog_sha256", "epoch_manifest_sha256",
        "delete_set_sha256", "project_identity_sha256", "store_identity_sha256",
        "policy_fingerprint", "candidate_revision",
    }:
        raise CompactionError("compaction_plan_invalid")
    if (
        checked["delete_set"] != catalog["object_tombstones"]
        or digest_json(core) != plan["fingerprint"]
        or core["proposal_sha256"] != digest_json(proposal)
        or core["restore_proof_sha256"] != digest_json(proof)
        or core["catalog_sha256"] != digest_json(catalog)
        or core["epoch_manifest_sha256"] != digest_json(epoch)
        or core["delete_set_sha256"] != catalog["delete_set_sha256"]
        or core["candidate_revision"] != digest_json(candidate)
        or core["base_revision"] != proposal["base_revision"]
        or core["transaction_id"] != proposal["transaction_id"]
        or core["epoch_id"] != proposal["epoch_id"]
        or core["policy_fingerprint"] != epoch["compaction_policy"]
        or epoch["proposal_sha256"] != digest_json(proposal)
        or epoch["restore_proof"] != digest_json(proof)
        or epoch["tombstone_catalog"] != digest_json(catalog)
        or candidate["compaction_epoch"]["epoch_manifest"] != digest_json(epoch)
    ):
        raise CompactionError("compaction_plan_binding_invalid")
    if require_installed_policy and core["policy_fingerprint"] != policy_fingerprint():
        raise CompactionError("compaction_policy_fingerprint_mismatch")
    return checked


def plan_compaction(store: Any, proposal: Mapping[str, Any], bundle: str | Path) -> dict[str, Any]:
    ensure_supported_platform()
    checked = validate_proposal(proposal)
    proof, manifest = _restore_proof(Path(bundle))
    if (
        manifest["manifest_sha256"] != checked["export_manifest_sha256"]
        or manifest["core"]["current_revision"] != checked["base_revision"]
    ):
        raise CompactionError("compaction_bundle_binding_mismatch")
    with shared_reader_gate(store):
        return _build_under_gate(store, checked, proof)


def _candidate_protected(planning: Mapping[str, Any], stage_id: str, intent_id: str) -> list[dict[str, Any]]:
    proposal = planning["proposal"]
    candidate = planning["plan"]["core"]["candidate_revision"]
    manifest = planning["candidate_manifest"]
    txid = proposal["transaction_id"]
    protected = [
        protected_file(f"revisions/sha256/{bare_digest(candidate)}.json", candidate),
        protected_file(f"checkpoints/sha256/{bare_digest(manifest['checkpoint'])}.json", manifest["checkpoint"]),
        protected_file(f"compaction/restore-proofs/sha256/{bare_digest(planning['plan']['core']['restore_proof_sha256'])}.json", planning["plan"]["core"]["restore_proof_sha256"]),
        protected_file(f"compaction/catalogs/sha256/{bare_digest(planning['plan']['core']['catalog_sha256'])}.json", planning["plan"]["core"]["catalog_sha256"]),
        protected_file(f"compaction/epochs/sha256/{bare_digest(planning['plan']['core']['epoch_manifest_sha256'])}.json", planning["plan"]["core"]["epoch_manifest_sha256"]),
        protected_file(f"refs/ref-log/sha256/{bare_digest(intent_id)}.json", intent_id),
        protected_file(f"transactions/{txid}/stages/sha256/{bare_digest(stage_id)}.json", stage_id),
    ]
    for stream in ("facts", "events", "episodes"):
        for identifier in manifest[f"{stream}_segments"]:
            protected.append(protected_file(f"segments/{stream}/sha256/{bare_digest(identifier)}.jsonl", identifier))
    for directory in {
        "revisions/sha256", "checkpoints/sha256", "compaction/restore-proofs/sha256",
        "compaction/catalogs/sha256", "compaction/epochs/sha256",
        "refs/ref-log/sha256", f"transactions/{txid}/stages/sha256",
        *(
            f"segments/{stream}/sha256"
            for stream in ("facts", "events", "episodes")
            if manifest[f"{stream}_segments"]
        ),
    }:
        protected.append(protected_directory(directory))
    return protected


def _result(
    planning: Mapping[str, Any], state: str, committed: bool | None,
    current: str | None, remaining: int, outcome: Mapping[str, Any] | None,
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "schema": RESULT_SCHEMA,
        "state": state,
        "committed": committed,
        "candidate_revision": planning["plan"]["core"]["candidate_revision"],
        "current_after": current,
        "epoch_id": planning["proposal"]["epoch_id"],
        "plan_fingerprint": planning["plan"]["fingerprint"],
        "cleanup_remaining": remaining,
        "outcome": deepcopy(dict(outcome)) if outcome is not None else None,
        "warnings": sorted(set(warnings)),
    }


def _remaining(store: Any, delete_set: list[dict[str, Any]]) -> int:
    count = 0
    for item in delete_set:
        path = store.root / item["path"]
        try:
            path.lstat()
            count += 1
        except FileNotFoundError:
            pass
    return count


def _cleanup(store: Any, planning: Mapping[str, Any], journal: dict[str, Any]) -> tuple[int, list[str]]:
    delete_set = planning["delete_set"]
    for tombstone in delete_set:
        delete_exact(store, tombstone)
    directories = sync_cleanup_parents(store, delete_set)
    paths = [item["path"] for item in delete_set]
    if _remaining(store, delete_set) != 0:
        raise CompactionError("compaction_cleanup_remaining")
    receipt = {
        "schema": "an-kla/compaction-cleanup-receipt-v1",
        "transaction_id": planning["proposal"]["transaction_id"],
        "candidate_revision": planning["plan"]["core"]["candidate_revision"],
        "delete_set_sha256": planning["plan"]["core"]["delete_set_sha256"],
        "deleted_or_absent_sha256": digest_json(paths),
        "synced_directories": directories,
        "remaining": 0,
    }
    receipt_id = store._write_json_object(
        f"transactions/{planning['proposal']['transaction_id']}/receipts", receipt
    )
    journal["cleanup_receipt"] = receipt_id
    store._write_transaction(planning["proposal"]["transaction_id"], journal)
    return 0, []


def _reconcile_committed_journal(
    store: Any, planning: Mapping[str, Any], attempt: Mapping[str, Any],
    current: str,
) -> dict[str, Any]:
    txid = planning["proposal"]["transaction_id"]
    candidate = planning["plan"]["core"]["candidate_revision"]
    path = store.root / "transactions" / f"{txid}.json"
    try:
        journal = json.loads(path.read_bytes())
    except Exception as exc:
        raise CompactionError("transaction_evidence_missing_or_invalid") from exc
    if journal.get("attempt") != attempt or journal.get("candidate") != candidate:
        raise CompactionError("transaction_binding_conflict")
    # A replay may reconcile descriptive journal fields, but it must never
    # manufacture either receipt used as authority for destructive cleanup.
    # If publication completed before current-durable was persisted, the
    # committed revision remains readable while cleanup fails closed.
    journal["stage"] = "committed"
    if not isinstance(journal.get("observed_log"), str):
        intent_id = journal.get("intent_id")
        if not isinstance(intent_id, str):
            intent_id = store._write_ref_log(
                {
                    "schema": "an-kla/ref-log-v1",
                    "kind": "intent",
                    "transaction_id": txid,
                    "parent": planning["proposal"]["base_revision"],
                    "candidate": candidate,
                }
            )
            journal["intent_id"] = intent_id
        journal["observed_log"] = store._write_ref_log(
            {
                "schema": "an-kla/ref-log-v1",
                "kind": "observed_commit",
                "transaction_id": txid,
                "parent": planning["proposal"]["base_revision"],
                "candidate": candidate,
                "intent": intent_id,
            }
        )
    store._write_transaction(txid, journal)
    return journal


def _validate_cleanup_evidence(
    store: Any, planning: Mapping[str, Any], attempt: Mapping[str, Any],
    journal: Mapping[str, Any], current: str,
) -> None:
    txid = planning["proposal"]["transaction_id"]
    candidate = planning["plan"]["core"]["candidate_revision"]
    relation = candidate_relation(store, candidate, current)
    if relation not in {"current", "ancestor"}:
        raise CompactionError("compaction_authority_unknown")
    candidate_id = journal.get("candidate_receipt")
    current_id = journal.get("current_receipt")
    if not isinstance(candidate_id, str) or not isinstance(current_id, str):
        raise CompactionError("compaction_durability_evidence_incomplete")
    try:
        candidate_receipt = validate_receipt_evidence(
            store,
            txid=txid,
            identifier=candidate_id,
            attempt=attempt,
            candidate=candidate,
            kind="candidate-data-durable",
            relation=relation,
        )
        current_receipt = validate_receipt_evidence(
            store,
            txid=txid,
            identifier=current_id,
            attempt=attempt,
            candidate=candidate,
            kind="current-durable",
            relation=relation,
        )
    except Exception as exc:
        raise CompactionError("compaction_durability_evidence_incomplete") from exc
    if (
        digest_json(candidate_receipt) != candidate_id
        or digest_json(current_receipt) != current_id
        or current_receipt.get("predecessor_receipt") != candidate_id
        or journal.get("stage") != "committed"
    ):
        raise CompactionError("compaction_durability_evidence_incomplete")


def commit_compaction(
    store: Any, planning_result: Mapping[str, Any], expected_current: str,
    bundle: str | Path | None = None,
) -> dict[str, Any]:
    ensure_supported_platform()
    planning = validate_planning_result(planning_result)
    bare_digest(expected_current)
    if expected_current != planning["proposal"]["base_revision"]:
        raise CompactionError("compaction_expected_current_mismatch")
    proposal = planning["proposal"]
    txid = proposal["transaction_id"]
    candidate = planning["plan"]["core"]["candidate_revision"]
    attempt = begin_transaction(
        "compact", transaction_id=txid, base_revision=expected_current,
        plan_fingerprint=planning["plan"]["fingerprint"],
    )
    with identity_lock(store):
        binding = read_binding(store)
        with store.write_lock() as lock_result:
            with exclusive_reader_gate(store):
                validate_no_links(store)
                current = store.read_current()
                relation = candidate_relation(store, candidate, current)
                if relation not in {"current", "ancestor"}:
                    if current != expected_current:
                        raise CompactionError("compaction_base_changed")
                    if (
                        planning["plan"]["core"]["policy_fingerprint"]
                        != policy_fingerprint()
                    ):
                        raise CompactionError(
                            "compaction_policy_fingerprint_mismatch"
                        )
                    assert_unchanged(store, binding, current)
                    if bundle is None:
                        raise CompactionError("compaction_bundle_required")
                    proof, manifest = _restore_proof(Path(bundle))
                    if manifest["manifest_sha256"] != proposal["export_manifest_sha256"]:
                        raise CompactionError("compaction_bundle_binding_mismatch")
                    rebuilt = _build_under_gate(store, proposal, proof)
                    if rebuilt != planning:
                        raise CompactionError("compaction_plan_drift")
                    journal_path = store.root / "transactions" / f"{txid}.json"
                    if journal_path.exists():
                        try:
                            prior = json.loads(journal_path.read_bytes())
                        except Exception as exc:
                            raise CompactionError("transaction_evidence_missing_or_invalid") from exc
                        if prior.get("attempt") != attempt:
                            raise CompactionError("transaction_binding_conflict")
                    try:
                        projection = project_snapshot(store._snapshot_under_gate(current))
                        for stream, rows in projection["active"].items():
                            if rows:
                                identifier = store._write_segment(stream, list(rows))
                                if [identifier] != planning["candidate_manifest"][f"{stream}_segments"]:
                                    raise CompactionError("compaction_projection_changed")
                        proof_id = store._write_json_object("compaction/restore-proofs", planning["restore_proof"])
                        catalog_id = store._write_json_object("compaction/catalogs", planning["catalog"])
                        epoch_id = store._write_json_object("compaction/epochs", planning["epoch_manifest"])
                        if (
                            proof_id != planning["plan"]["core"]["restore_proof_sha256"]
                            or catalog_id != planning["plan"]["core"]["catalog_sha256"]
                            or epoch_id != planning["plan"]["core"]["epoch_manifest_sha256"]
                        ):
                            raise CompactionError("compaction_content_hash_mismatch")
                        written_candidate = store._write_json_object("revisions", planning["candidate_manifest"])
                        if written_candidate != candidate:
                            raise CompactionError("compaction_content_hash_mismatch")
                        intent_id = store._write_ref_log({
                            "schema": "an-kla/ref-log-v1", "kind": "intent",
                            "transaction_id": txid, "parent": expected_current,
                            "candidate": candidate,
                        })
                        stage = {
                            "schema": "an-kla/transaction-stage-v1",
                            "stage": "candidate_prepared",
                            "parent": expected_current,
                            "candidate": candidate,
                            "attempt": attempt,
                            "compaction_policy": policy_config(),
                        }
                        stage_id = store._write_json_object(f"transactions/{txid}/stages", stage)
                        journal = {
                            **stage, "stage_object": stage_id,
                            "candidate_receipt": None, "current_receipt": None,
                            "cleanup_receipt": None, "intent_id": intent_id,
                        }
                        store._write_transaction(txid, journal)
                        candidate_receipt = write_receipt(
                            store, attempt=attempt, kind="candidate-data-durable",
                            candidate_revision=candidate,
                            protected=_candidate_protected(planning, stage_id, intent_id),
                        )
                        journal["candidate_receipt"] = candidate_receipt
                        store._write_transaction(txid, journal)
                        if store.read_current() != expected_current:
                            raise CompactionError("compaction_base_changed")
                        store._replace_current(candidate)
                        current_receipt = write_receipt(
                            store, attempt=attempt, kind="current-durable",
                            candidate_revision=candidate,
                            predecessor_receipt=candidate_receipt,
                            protected=[
                                protected_file("refs/CURRENT", digest_bytes((candidate + "\n").encode("ascii"))),
                                protected_directory("refs"),
                            ],
                        )
                        journal.update({"stage": "committed", "current_receipt": current_receipt})
                        store._write_transaction(txid, journal)
                        observed_id = store._write_ref_log({
                            "schema": "an-kla/ref-log-v1", "kind": "observed_commit",
                            "transaction_id": txid, "parent": expected_current,
                            "candidate": candidate, "intent": intent_id,
                        })
                        journal["observed_log"] = observed_id
                        store._write_transaction(txid, journal)
                    except OSError as exc:
                        after = None
                        try:
                            after = store.read_current()
                        except Exception:
                            pass
                        outcome = inspect_transaction(store, txid)
                        committed = outcome.get("committed")
                        exterior_state = (
                            "committed_cleanup_incomplete"
                            if committed is True
                            else "not_committed"
                            if committed is False
                            else "outcome_unknown"
                        )
                        return _result(
                            planning,
                            exterior_state,
                            committed,
                            outcome.get("current_observed", after),
                            _remaining(store, planning["delete_set"]),
                            outcome,
                            [f"compaction_error:{getattr(exc, 'code', type(exc).__name__)}"],
                        )
                    current = candidate
                try:
                    # Replay may omit the external bundle only after authority
                    # moved.  Revalidate the authoritative epoch/catalog and
                    # every live dependency before deleting any historical byte.
                    store._snapshot_under_gate(current)
                    validate_no_links(store)
                    journal = _reconcile_committed_journal(
                        store, planning, attempt, current
                    )
                    _validate_cleanup_evidence(
                        store, planning, attempt, journal, current
                    )
                    remaining, warnings = _cleanup(store, planning, journal)
                    outcome = inspect_transaction(store, txid)
                    result = _result(planning, "committed", True, current, remaining, outcome, warnings)
                except Exception as exc:
                    outcome = inspect_transaction(store, txid)
                    result = _result(
                        planning, "committed_cleanup_incomplete", True, current,
                        _remaining(store, planning["delete_set"]), outcome,
                        [f"cleanup_error:{type(exc).__name__}:{exc}"],
                    )
        if lock_result.release_error is not None:
            result["warnings"] = sorted(set([*result["warnings"], lock_result.release_error]))
        return result


def verify_revision(store: Any, revision: str) -> dict[str, Any]:
    bare_digest(revision)
    with shared_reader_gate(store):
        current = store.read_current()
        current_manifest = store._read_json_object("revisions", current)
        catalog_id = None
        epoch_id = None
        export_id = None
        if current_manifest.get("schema") == "an-kla/revision-v3":
            link = current_manifest["compaction_epoch"]
            catalog_id = link["tombstone_catalog"]
            catalog = validate_catalog(store._read_json_object("compaction/catalogs", catalog_id))
            catalogs = validate_catalog_chain(store, catalog_id)
            archived = next((item for item in catalog["archived_revisions"] if item["revision"] == revision), None)
            if archived is not None:
                archived_catalog = catalogs.get(archived["epoch_id"])
                if archived_catalog is None:
                    raise CompactionError("compaction_catalog_chain_invalid")
                return {
                    "schema": "an-kla/verify-revision-v1", "revision": revision,
                    "availability": "archived_by_compaction",
                    "epoch_id": archived["epoch_id"],
                    "export_manifest_sha256": archived["export_manifest_sha256"],
                    "tombstone_catalog": archived_catalog[0], "integrity": "catalog_verified",
                }
            epoch_id = link["epoch_id"]
            export_id = link["export_manifest_sha256"]
        path = store._path_for("revisions", revision)
        if not path.exists():
            availability = "unknown"
            integrity = "not_available"
        else:
            store._snapshot_under_gate(revision)
            availability = "present"
            integrity = "verified"
        return {
            "schema": "an-kla/verify-revision-v1", "revision": revision,
            "availability": availability, "epoch_id": epoch_id,
            "export_manifest_sha256": export_id,
            "tombstone_catalog": catalog_id, "integrity": integrity,
        }


def archived_revision_link_under_gate(store: Any, revision: str) -> dict[str, Any] | None:
    """Resolve current catalog precedence without acquiring a second gate."""

    current = store.read_current()
    manifest = store._read_json_object("revisions", current)
    if manifest.get("schema") != "an-kla/revision-v3":
        return None
    catalog_id = manifest["compaction_epoch"]["tombstone_catalog"]
    catalog = validate_catalog(store._read_json_object("compaction/catalogs", catalog_id))
    catalogs = validate_catalog_chain(store, catalog_id)
    for item in catalog["archived_revisions"]:
        if item["revision"] == revision:
            archived_catalog = catalogs.get(item["epoch_id"])
            if archived_catalog is None:
                raise CompactionError("compaction_catalog_chain_invalid")
            return {**item, "tombstone_catalog": archived_catalog[0]}
    return None


def archived_transaction_link_under_gate(store: Any, transaction_id: str) -> dict[str, Any] | None:
    current = store.read_current()
    manifest = store._read_json_object("revisions", current)
    if manifest.get("schema") != "an-kla/revision-v3":
        return None
    link = manifest["compaction_epoch"]
    catalog_id = link["tombstone_catalog"]
    catalogs = validate_catalog_chain(store, catalog_id)
    wanted = f"transactions/{transaction_id}.json"
    for epoch_id, (identifier, catalog) in catalogs.items():
        if any(item["path"] == wanted for item in catalog["object_tombstones"]):
            return {
                "epoch_id": epoch_id,
                "export_manifest_sha256": catalog["export_manifest_sha256"],
                "tombstone_catalog": identifier,
            }
    return None


__all__ = [
    "CompactionError", "archived_revision_link_under_gate",
    "archived_transaction_link_under_gate", "commit_compaction", "plan_compaction",
    "validate_planning_result", "verify_revision",
]
