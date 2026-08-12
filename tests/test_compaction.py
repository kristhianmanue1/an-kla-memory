from __future__ import annotations

import tempfile
from pathlib import Path
import json
import os
import subprocess
import sys
import unittest
import uuid
from unittest.mock import patch

from an_kla.compaction import (
    CompactionError, commit_compaction, plan_compaction, verify_revision,
)
from an_kla.canonical import digest_json
from an_kla.checkpoints import commit_checkpoint, plan_checkpoint
from an_kla.export_restore import create_export
from an_kla.store import MemoryStore
from an_kla.schemas import schema_document
from tests.test_checkpoints import _authority, _state
from tests.test_refute import Resolver, proposal_and_claim


class CompactionTests(unittest.TestCase):
    def test_first_epoch_projects_active_and_archives_source(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            project = Path(root) / "project"
            project.mkdir()
            store = MemoryStore(project)
            initial = store.initialize()
            subject_ref = (
                "an-kla:subject:v1:service:"
                "p-0123456789abcdef0123456789abcdef:service-a"
            )
            source = store.commit(
                expected_current_hash=initial,
                checkpoint_patch={},
                facts=[
                    {
                        "id": "f-active",
                        "text": "keep",
                        "status": "active",
                        "subject_ref": subject_ref,
                    },
                    {"id": "f-inactive", "text": "drop", "status": "inactive"},
                ],
            )
            source_txid = store.snapshot(source).manifest["transaction_id"]
            bundle = Path(root) / "bundle"
            exported = create_export(store, bundle)
            proposal = {
                "schema": "an-kla/compaction-proposal-v1",
                "base_revision": source,
                "epoch_id": str(uuid.uuid4()),
                "transaction_id": str(uuid.uuid4()),
                "export_manifest_sha256": exported["manifest_sha256"],
            }
            planning = plan_compaction(store, proposal, bundle)
            try:
                from jsonschema import Draft202012Validator
            except ImportError:
                Draft202012Validator = None  # type: ignore[assignment,misc]
            if Draft202012Validator is not None:
                Draft202012Validator(
                    schema_document("compaction-planning-result-v1")
                ).validate(planning)
            self.assertEqual(
                [item["state"] for item in planning["catalog"]["record_tombstones"]],
                ["inactive"],
            )
            result = commit_compaction(store, planning, source, bundle)
            if Draft202012Validator is not None:
                Draft202012Validator(schema_document("compaction-result-v1")).validate(result)
            self.assertEqual(result["state"], "committed")
            self.assertEqual(result["outcome"]["state"], "committed", result["outcome"])
            current = store.snapshot()
            self.assertEqual(current.manifest["schema"], "an-kla/revision-v3")
            self.assertEqual([row["id"] for row in current.records["facts"]], ["f-active"])
            self.assertEqual(current.records["facts"][0]["subject_ref"], subject_ref)
            archived = verify_revision(store, source)
            self.assertEqual(archived["availability"], "archived_by_compaction")
            self.assertEqual(verify_revision(store, current.revision_id)["availability"], "present")
            self.assertEqual(
                store.inspect_transaction(source_txid)["state"],
                "transaction_archived_by_compaction",
            )
            with self.assertRaisesRegex(Exception, "revision_archived_by_compaction"):
                store.snapshot(source)

            child = store.commit(
                expected_current_hash=current.revision_id,
                checkpoint_patch={},
                facts=[{"id": "f-after", "text": "after epoch", "status": "active"}],
            )
            child_snapshot = store.snapshot(child)
            self.assertEqual(child_snapshot.manifest["schema"], "an-kla/revision-v3")
            self.assertEqual(
                child_snapshot.manifest["compaction_epoch"],
                current.manifest["compaction_epoch"],
            )

            state = _state(child_snapshot.manifest["checkpoint"], "after compaction")
            checkpoint_plan = plan_checkpoint(store, state, _authority(store, state))
            checkpoint_result = commit_checkpoint(
                store, checkpoint_plan, child, transaction_id=str(uuid.uuid4())
            )
            checkpoint_revision = checkpoint_result["revision"]
            checkpoint_snapshot = store.snapshot(checkpoint_revision)
            self.assertEqual(checkpoint_snapshot.manifest["schema"], "an-kla/revision-v3")

            refute_store = MemoryStore(project, refute_authority_resolver=Resolver())
            refute_proposal, claim = proposal_and_claim(
                refute_store,
                digest_json(
                    {
                        "id": "f-active",
                        "text": "keep",
                        "status": "active",
                        "subject_ref": subject_ref,
                    }
                ),
            )
            refute_plan = refute_store.plan_refute(refute_proposal, claim)
            refuted = refute_store.commit_refute_plan(
                expected_current=checkpoint_revision,
                planning_result=refute_plan,
                transaction_id=str(uuid.uuid4()),
            )
            self.assertTrue(refuted["committed"])
            self.assertEqual(
                refute_store.snapshot(refuted["revision"]).manifest["schema"],
                "an-kla/revision-v3",
            )
            self.assertEqual(
                refute_store.snapshot(refuted["revision"]).records["facts"][0][
                    "subject_ref"
                ],
                subject_ref,
            )

            bundle2 = Path(root) / "bundle2"
            exported2 = create_export(refute_store, bundle2)
            proposal2 = {
                "schema": "an-kla/compaction-proposal-v1",
                "base_revision": refuted["revision"],
                "epoch_id": str(uuid.uuid4()),
                "transaction_id": str(uuid.uuid4()),
                "export_manifest_sha256": exported2["manifest_sha256"],
            }
            planning2 = plan_compaction(refute_store, proposal2, bundle2)
            self.assertEqual(len(planning2["catalog"]["previous_catalogs"]), 1)
            second = commit_compaction(
                refute_store, planning2, refuted["revision"], bundle2
            )
            self.assertEqual(second["state"], "committed")
            self.assertEqual(
                [row["id"] for row in refute_store.snapshot().records["facts"]],
                ["f-after"],
            )
            self.assertEqual(
                verify_revision(refute_store, refuted["revision"])["availability"],
                "archived_by_compaction",
            )
            self.assertEqual(
                refute_store.inspect_transaction(source_txid)["state"],
                "transaction_archived_by_compaction",
            )
            first_catalog = planning["plan"]["core"]["catalog_sha256"]
            refute_store._path_for("compaction/catalogs", first_catalog).unlink()
            with self.assertRaisesRegex(
                Exception, "(?:compaction_catalog|compaction_epoch)"
            ):
                refute_store.verify()

    def test_cleanup_retry_uses_same_candidate_without_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            project = Path(root) / "project"
            project.mkdir()
            store = MemoryStore(project)
            initial = store.initialize()
            source = store.commit(
                expected_current_hash=initial, checkpoint_patch={},
                facts=[{"id": "f-1", "text": "one"}],
            )
            bundle = Path(root) / "bundle"
            exported = create_export(store, bundle)
            proposal = {
                "schema": "an-kla/compaction-proposal-v1",
                "base_revision": source,
                "epoch_id": str(uuid.uuid4()),
                "transaction_id": str(uuid.uuid4()),
                "export_manifest_sha256": exported["manifest_sha256"],
            }
            planning = plan_compaction(store, proposal, bundle)
            with patch("an_kla.compaction.delete_exact", side_effect=CompactionError("injected")):
                first = commit_compaction(store, planning, source, bundle)
            self.assertEqual(first["state"], "committed_cleanup_incomplete")
            candidate = first["candidate_revision"]
            with patch(
                "an_kla.compaction.policy_fingerprint",
                return_value="sha256:" + "9" * 64,
            ):
                self.assertEqual(
                    store.snapshot().manifest["schema"], "an-kla/revision-v3"
                )
                retry = commit_compaction(store, planning, source)
            self.assertEqual(retry["state"], "committed")
            self.assertEqual(retry["candidate_revision"], candidate)
            self.assertEqual(store.read_current(), candidate)

    def test_historical_policy_survives_installed_policy_drift(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            project = Path(root) / "project"
            project.mkdir()
            store = MemoryStore(project)
            initial = store.initialize()
            source = store.commit(
                expected_current_hash=initial, checkpoint_patch={},
                facts=[{"id": "f-policy", "text": "historical policy"}],
            )
            bundle = Path(root) / "bundle"
            exported = create_export(store, bundle)
            proposal = {
                "schema": "an-kla/compaction-proposal-v1",
                "base_revision": source,
                "epoch_id": str(uuid.uuid4()),
                "transaction_id": str(uuid.uuid4()),
                "export_manifest_sha256": exported["manifest_sha256"],
            }
            planning = plan_compaction(store, proposal, bundle)
            with patch("an_kla.compaction.delete_exact", side_effect=CompactionError("pause")):
                first = commit_compaction(store, planning, source, bundle)
            self.assertEqual(first["state"], "committed_cleanup_incomplete")

            from an_kla import compaction_contracts

            with patch.dict(
                compaction_contracts._POLICY_V1,
                {"segmenting": "future-installed-segmenting"},
            ):
                self.assertEqual(store.snapshot().manifest["schema"], "an-kla/revision-v3")
                retry = commit_compaction(store, planning, source)
            self.assertEqual(retry["state"], "committed")

    def test_missing_candidate_receipt_blocks_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            project = Path(root) / "project"
            project.mkdir()
            store = MemoryStore(project)
            initial = store.initialize()
            source = store.commit(
                expected_current_hash=initial, checkpoint_patch={},
                facts=[{"id": "f-receipt", "text": "receipt"}],
            )
            bundle = Path(root) / "bundle"
            exported = create_export(store, bundle)
            proposal = {
                "schema": "an-kla/compaction-proposal-v1",
                "base_revision": source,
                "epoch_id": str(uuid.uuid4()),
                "transaction_id": str(uuid.uuid4()),
                "export_manifest_sha256": exported["manifest_sha256"],
            }
            planning = plan_compaction(store, proposal, bundle)
            with patch("an_kla.compaction.delete_exact", side_effect=CompactionError("pause")):
                first = commit_compaction(store, planning, source, bundle)
            self.assertEqual(first["state"], "committed_cleanup_incomplete")
            journal_path = store.root / "transactions" / f"{proposal['transaction_id']}.json"
            journal = json.loads(journal_path.read_bytes())
            receipt = store._path_for(
                f"transactions/{proposal['transaction_id']}/receipts",
                journal["candidate_receipt"],
            )
            receipt.unlink()
            remaining = first["cleanup_remaining"]
            retry = commit_compaction(store, planning, source)
            self.assertEqual(retry["state"], "committed_cleanup_incomplete")
            self.assertEqual(retry["cleanup_remaining"], remaining)

    def test_missing_current_receipt_cannot_be_rebuilt_to_authorize_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            project = Path(root) / "project"
            project.mkdir()
            store = MemoryStore(project)
            initial = store.initialize()
            source = store.commit(
                expected_current_hash=initial, checkpoint_patch={},
                facts=[{"id": "f-current-receipt", "text": "receipt authority"}],
            )
            bundle = Path(root) / "bundle"
            exported = create_export(store, bundle)
            proposal = {
                "schema": "an-kla/compaction-proposal-v1",
                "base_revision": source,
                "epoch_id": str(uuid.uuid4()),
                "transaction_id": str(uuid.uuid4()),
                "export_manifest_sha256": exported["manifest_sha256"],
            }
            planning = plan_compaction(store, proposal, bundle)
            with patch("an_kla.compaction.delete_exact", side_effect=CompactionError("pause")):
                first = commit_compaction(store, planning, source, bundle)
            self.assertEqual(first["state"], "committed_cleanup_incomplete")
            journal_path = store.root / "transactions" / f"{proposal['transaction_id']}.json"
            journal = json.loads(journal_path.read_bytes())
            receipt = store._path_for(
                f"transactions/{proposal['transaction_id']}/receipts",
                journal["current_receipt"],
            )
            receipt.unlink()
            journal["current_receipt"] = None
            store._write_transaction(proposal["transaction_id"], journal)

            with patch("an_kla.compaction.delete_exact") as delete_mock:
                retry = commit_compaction(store, planning, source)
            self.assertEqual(retry["state"], "committed_cleanup_incomplete")
            self.assertEqual(retry["cleanup_remaining"], first["cleanup_remaining"])
            delete_mock.assert_not_called()

    def test_post_current_error_never_invents_cleanup_authority(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            project = Path(root) / "project"
            project.mkdir()
            store = MemoryStore(project)
            initial = store.initialize()
            source = store.commit(
                expected_current_hash=initial, checkpoint_patch={},
                facts=[{"id": "f-current-fault", "text": "fault"}],
            )
            bundle = Path(root) / "bundle"
            exported = create_export(store, bundle)
            proposal = {
                "schema": "an-kla/compaction-proposal-v1",
                "base_revision": source,
                "epoch_id": str(uuid.uuid4()),
                "transaction_id": str(uuid.uuid4()),
                "export_manifest_sha256": exported["manifest_sha256"],
            }
            planning = plan_compaction(store, proposal, bundle)
            original = store._replace_current

            def publish_then_fail(candidate: str) -> None:
                original(candidate)
                raise OSError("injected-after-current")

            with patch.object(store, "_replace_current", side_effect=publish_then_fail):
                first = commit_compaction(store, planning, source, bundle)
            self.assertEqual(first["state"], "committed_cleanup_incomplete")
            with patch("an_kla.compaction.delete_exact") as delete_mock:
                retry = commit_compaction(store, planning, source)
            self.assertEqual(retry["state"], "committed_cleanup_incomplete")
            self.assertGreater(retry["cleanup_remaining"], 0)
            delete_mock.assert_not_called()
            self.assertEqual(store.read_current(), planning["plan"]["core"]["candidate_revision"])

    def test_unknown_publication_outcome_is_not_reported_false(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            project = Path(root) / "project"
            project.mkdir()
            store = MemoryStore(project)
            initial = store.initialize()
            source = store.commit(
                expected_current_hash=initial, checkpoint_patch={},
                facts=[{"id": "f-unknown", "text": "unknown"}],
            )
            bundle = Path(root) / "bundle"
            exported = create_export(store, bundle)
            proposal = {
                "schema": "an-kla/compaction-proposal-v1",
                "base_revision": source,
                "epoch_id": str(uuid.uuid4()),
                "transaction_id": str(uuid.uuid4()),
                "export_manifest_sha256": exported["manifest_sha256"],
            }
            planning = plan_compaction(store, proposal, bundle)
            original = store._replace_current

            def publish_corrupt_and_fail(candidate: str) -> None:
                original(candidate)
                store.current_path.write_bytes(b"broken")
                raise OSError("injected-unknown")

            with patch.object(store, "_replace_current", side_effect=publish_corrupt_and_fail):
                result = commit_compaction(store, planning, source, bundle)
            self.assertEqual(result["state"], "outcome_unknown")
            self.assertIsNone(result["committed"])

    def test_altered_cleanup_target_fails_closed_after_authority_moves(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            project = Path(root) / "project"
            project.mkdir()
            store = MemoryStore(project)
            initial = store.initialize()
            source = store.commit(
                expected_current_hash=initial, checkpoint_patch={},
                facts=[{"id": "f-altered", "text": "altered"}],
            )
            bundle = Path(root) / "bundle"
            exported = create_export(store, bundle)
            proposal = {
                "schema": "an-kla/compaction-proposal-v1",
                "base_revision": source,
                "epoch_id": str(uuid.uuid4()),
                "transaction_id": str(uuid.uuid4()),
                "export_manifest_sha256": exported["manifest_sha256"],
            }
            planning = plan_compaction(store, proposal, bundle)
            with patch("an_kla.compaction.delete_exact", side_effect=CompactionError("pause")):
                first = commit_compaction(store, planning, source, bundle)
            self.assertEqual(first["state"], "committed_cleanup_incomplete")
            target = store.root / planning["delete_set"][0]["path"]
            target.write_bytes(b"altered-after-current")
            retry = commit_compaction(store, planning, source)
            self.assertEqual(retry["state"], "committed_cleanup_incomplete")
            self.assertTrue(target.exists())

    def test_current_drift_creates_no_compaction_objects(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            project = Path(root) / "project"
            project.mkdir()
            store = MemoryStore(project)
            initial = store.initialize()
            source = store.commit(
                expected_current_hash=initial, checkpoint_patch={},
                facts=[{"id": "f-drift", "text": "drift"}],
            )
            bundle = Path(root) / "bundle"
            exported = create_export(store, bundle)
            proposal = {
                "schema": "an-kla/compaction-proposal-v1",
                "base_revision": source,
                "epoch_id": str(uuid.uuid4()),
                "transaction_id": str(uuid.uuid4()),
                "export_manifest_sha256": exported["manifest_sha256"],
            }
            planning = plan_compaction(store, proposal, bundle)
            with patch(
                "an_kla.compaction.policy_fingerprint",
                return_value="sha256:" + "8" * 64,
            ), self.assertRaisesRegex(
                CompactionError, "compaction_policy_fingerprint_mismatch"
            ):
                commit_compaction(store, planning, source, bundle)
            self.assertEqual(store.read_current(), source)
            self.assertFalse(
                (store.root / "transactions" / f"{proposal['transaction_id']}.json").exists()
            )
            child = store.commit(
                expected_current_hash=source, checkpoint_patch={},
                facts=[{"id": "f-drift-child", "text": "changed"}],
            )
            with self.assertRaisesRegex(CompactionError, "compaction_base_changed"):
                commit_compaction(store, planning, source, bundle)
            self.assertEqual(store.read_current(), child)
            self.assertFalse(
                (store.root / "transactions" / f"{proposal['transaction_id']}.json").exists()
            )
            self.assertFalse((store.root / "compaction").exists())

    def test_inventory_rejects_symlink_and_hardlink_targets(self) -> None:
        for attack in ("symlink", "hardlink"):
            with self.subTest(attack=attack), tempfile.TemporaryDirectory() as root:
                project = Path(root) / "project"
                project.mkdir()
                store = MemoryStore(project)
                initial = store.initialize()
                source = store.commit(
                    expected_current_hash=initial, checkpoint_patch={},
                    facts=[{"id": f"f-{attack}", "text": attack}],
                )
                bundle = Path(root) / "bundle"
                exported = create_export(store, bundle)
                proposal = {
                    "schema": "an-kla/compaction-proposal-v1",
                    "base_revision": source,
                    "epoch_id": str(uuid.uuid4()),
                    "transaction_id": str(uuid.uuid4()),
                    "export_manifest_sha256": exported["manifest_sha256"],
                }
                planning = plan_compaction(store, proposal, bundle)
                target = store.root / planning["delete_set"][0]["path"]
                payload = target.read_bytes()
                target.unlink()
                external = Path(root) / "external"
                external.write_bytes(payload)
                if attack == "symlink":
                    target.symlink_to(external)
                else:
                    os.link(external, target)
                with self.assertRaisesRegex(
                    CompactionError, "compaction_(?:inventory|namespace)_unsafe"
                ):
                    commit_compaction(store, planning, source, bundle)
                self.assertEqual(store.read_current(), source)
                self.assertFalse(
                    (store.root / "transactions" / f"{proposal['transaction_id']}.json").exists()
                )

    def test_compaction_namespace_symlink_cannot_escape_store(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            project = Path(root) / "project"
            project.mkdir()
            store = MemoryStore(project)
            initial = store.initialize()
            source = store.commit(
                expected_current_hash=initial, checkpoint_patch={},
                facts=[{"id": "f-escape", "text": "escape"}],
            )
            bundle = Path(root) / "bundle"
            exported = create_export(store, bundle)
            proposal = {
                "schema": "an-kla/compaction-proposal-v1",
                "base_revision": source,
                "epoch_id": str(uuid.uuid4()),
                "transaction_id": str(uuid.uuid4()),
                "export_manifest_sha256": exported["manifest_sha256"],
            }
            planning = plan_compaction(store, proposal, bundle)
            outside = Path(root) / "outside"
            outside.mkdir()
            (store.root / "compaction").symlink_to(outside)
            with self.assertRaisesRegex(CompactionError, "compaction_namespace_unsafe"):
                commit_compaction(store, planning, source, bundle)
            self.assertEqual(list(outside.rglob("*")), [])

    def test_cli_plan_commit_and_historical_verify(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            project = Path(root) / "project"
            project.mkdir()
            store = MemoryStore(project)
            initial = store.initialize()
            source = store.commit(
                expected_current_hash=initial, checkpoint_patch={},
                facts=[{"id": "f-cli", "text": "cli"}],
            )
            bundle = Path(root) / "bundle"
            exported = create_export(store, bundle)
            proposal = {
                "schema": "an-kla/compaction-proposal-v1",
                "base_revision": source,
                "epoch_id": str(uuid.uuid4()),
                "transaction_id": str(uuid.uuid4()),
                "export_manifest_sha256": exported["manifest_sha256"],
            }
            proposal_path = Path(root) / "proposal.json"
            proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
            planned = subprocess.run(
                [sys.executable, "-m", "an_kla", "--project-root", str(project),
                 "--no-update-check", "compact", "plan", "--proposal",
                 str(proposal_path), "--bundle", str(bundle)],
                capture_output=True, check=True,
            )
            planning_path = Path(root) / "planning.json"
            planning_path.write_bytes(planned.stdout)
            committed = subprocess.run(
                [sys.executable, "-m", "an_kla", "--project-root", str(project),
                 "--no-update-check", "compact", "commit", "--planning-result",
                 str(planning_path), "--expected-current", source, "--bundle", str(bundle)],
                capture_output=True, check=True,
            )
            self.assertEqual(json.loads(committed.stdout)["state"], "committed")
            verified = subprocess.run(
                [sys.executable, "-m", "an_kla", "--project-root", str(project),
                 "--no-update-check", "verify", "--revision", source],
                capture_output=True, check=True,
            )
            self.assertEqual(
                json.loads(verified.stdout)["availability"],
                "archived_by_compaction",
            )


if __name__ == "__main__":
    unittest.main()
