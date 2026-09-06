from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest
import uuid
from unittest.mock import patch

from an_kla.canonical import canonical_json, digest_json
from an_kla.identity import (
    IdentityError,
    adopt,
    identity_status,
    plan_adoption,
    read_binding,
    repair,
    mutation_preflight,
)
from an_kla.initialization import initialize_locked
from an_kla.store import MemoryStore


def _proposal(base: str, record_id: str) -> dict:
    return {
        "schema": "an-kla/write-proposal-v1",
        "base_revision": base,
        "stream": "facts",
        "operation": "add",
        "requested_representation": "summary",
        "record": {"id": record_id, "payload": {"text": "identity test"}},
        "lineage": {"derived_from_retrieval": False, "refs": []},
    }


def _authority(proposal: dict) -> dict:
    return {
        "schema": "an-kla/write-authority-v1",
        "proposal_sha256": digest_json(proposal),
        "base_revision": proposal["base_revision"],
        "authority_class": "model_derived",
        "issuer": {
            "kind": "model",
            "id": "identity-test",
            "configuration_fingerprint": "sha256:" + "1" * 64,
        },
        "evidence": [],
        "scope": {
            "streams": ["facts"],
            "representations": ["summary"],
            "operations": ["add"],
        },
    }


def _legacy_store(project: str) -> tuple[MemoryStore, str]:
    store = MemoryStore(project)
    store._make_layout()
    with store.write_lock():
        root, outcome = initialize_locked(store, transaction_id=str(uuid.uuid4()))
    if root is None or outcome["committed"] is not True:
        raise AssertionError("legacy fixture failed")
    return store, root


class IdentityContractTests(unittest.TestCase):
    def test_new_init_links_exact_canonical_identity(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            store = MemoryStore(project)
            result = store.initialize_with_outcome(transaction_id=str(uuid.uuid4()))
            binding = read_binding(store)
            manifest = store.snapshot().manifest
            self.assertEqual(manifest["store_identity"], binding["store_identity"])
            self.assertEqual(result["identity"]["identity_state"], "complete")
            self.assertEqual(identity_status(store)["identity_status"], "complete")
            for path in (
                Path(project) / ".an-kla" / "project-identity.json",
                store.root / "identity.json",
            ):
                value = json.loads(path.read_bytes())
                self.assertEqual(path.read_bytes(), canonical_json(value))

    def test_relocation_preserves_identity_and_is_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            original = Path(parent) / "original"
            relocated = Path(parent) / "relocated"
            store = MemoryStore(original)
            store.initialize()
            expected = read_binding(store)["store_identity"]
            shutil.copytree(original, relocated)
            moved = MemoryStore(relocated)
            self.assertEqual(read_binding(moved)["store_identity"], expected)
            self.assertTrue(moved.verify()["root_relocated"])

    def test_legacy_requires_explicit_adoption_then_child_is_linked(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            store, root = _legacy_store(project)
            self.assertEqual(identity_status(store)["identity_status"], "legacy_unadopted")
            with self.assertRaisesRegex(
                IdentityError, "legacy_store_identity_adoption_required"
            ):
                store.initialize()
            self.assertFalse((Path(project) / ".an-kla" / "identity-intent.json").exists())

            plan = plan_adoption(store)
            adopted = adopt(store, plan, root)
            self.assertEqual(adopted["identity_state"], "complete")
            self.assertTrue(store.verify()["ok"])
            proposal = _proposal(root, "f-adopted")
            authority = _authority(proposal)
            planning = store.plan_write(proposal, authority)
            committed = store.commit_write_plan(
                expected_current_hash=root,
                proposal=proposal,
                authority=authority,
                decision=planning["decision"],
                plan=planning["plan"],
            )
            self.assertEqual(
                store.snapshot(committed["revision"]).manifest["store_identity"],
                read_binding(store)["store_identity"],
            )

    def test_identity_change_between_preflight_and_lock_creates_no_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            store = MemoryStore(project)
            root = store.initialize()
            proposal = _proposal(root, "f-toctou")
            authority = _authority(proposal)
            planning = store.plan_write(proposal, authority)
            transactions_before = set((store.root / "transactions").glob("*.json"))
            from an_kla import store as store_module

            original = store_module.assert_unchanged

            def mutate_then_check(target, before, parent):
                path = target.project_root / ".an-kla" / "project-identity.json"
                value = json.loads(path.read_bytes())
                value["created_by_version"] = "tampered"
                path.write_bytes(canonical_json(value))
                return original(target, before, parent)

            with patch("an_kla.write_commit.assert_unchanged", side_effect=mutate_then_check):
                with self.assertRaisesRegex(IdentityError, "store_identity_changed"):
                    store.commit_write_plan(
                        expected_current_hash=root,
                        proposal=proposal,
                        authority=authority,
                        decision=planning["decision"],
                        plan=planning["plan"],
                    )
            self.assertEqual(
                set((store.root / "transactions").glob("*.json")),
                transactions_before,
            )
            self.assertEqual(store.read_current(), root)

    def test_status_hides_ids_unless_requested(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            store = MemoryStore(project)
            store.initialize()
            public = identity_status(store)
            local = identity_status(store, include_ids=True)
            self.assertNotIn("project_uuid", public)
            self.assertIn("project_uuid", local)
            self.assertIn("store_uuid", local)

    def test_store_copied_under_different_project_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            first = Path(parent) / "first"
            second = Path(parent) / "second"
            combined = Path(parent) / "combined"
            MemoryStore(first).initialize()
            MemoryStore(second).initialize()
            (combined / ".an-kla").mkdir(parents=True)
            shutil.copy2(
                second / ".an-kla" / "project-identity.json",
                combined / ".an-kla" / "project-identity.json",
            )
            shutil.copytree(
                first / ".an-kla" / "memory",
                combined / ".an-kla" / "memory",
            )
            mixed = MemoryStore(combined)
            self.assertEqual(identity_status(mixed)["identity_status"], "conflict")
            with self.assertRaisesRegex(IdentityError, "project_identity_mismatch"):
                read_binding(mixed)

    def test_live_identity_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            store = MemoryStore(project)
            store.initialize()
            project_path = Path(project) / ".an-kla" / "project-identity.json"
            copy = Path(project) / ".an-kla" / "project-copy.json"
            copy.write_bytes(project_path.read_bytes())
            project_path.unlink()
            project_path.symlink_to(copy.name)
            with self.assertRaisesRegex(IdentityError, "store_identity_invalid"):
                read_binding(store)

    def test_adoption_plan_is_bound_to_root_and_exact_candidate_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            store, root = _legacy_store(project)
            plan = plan_adoption(store)
            tampered = dict(plan)
            tampered["canonical_project_root_observed"] = project + "-elsewhere"
            core = {key: tampered[key] for key in tampered if key != "plan_fingerprint"}
            tampered["plan_fingerprint"] = digest_json(core)
            with self.assertRaisesRegex(IdentityError, "identity_adoption_base_changed"):
                adopt(store, tampered, root)
            self.assertEqual(identity_status(store)["identity_status"], "legacy_unadopted")

    def test_interrupted_init_resumes_from_exact_intent(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            store = MemoryStore(project)
            with patch(
                "an_kla.initialization.initialize_locked", side_effect=OSError("EIO")
            ):
                with self.assertRaises(OSError):
                    store.initialize()
            self.assertEqual(
                identity_status(store)["identity_status"],
                "identities_ready_root_pending",
            )
            intent = json.loads(
                (Path(project) / ".an-kla" / "identity-intent.json").read_bytes()
            )
            repaired = repair(store, intent)
            self.assertEqual(repaired["identity_state"], "complete")
            self.assertTrue(store.verify()["ok"])

    def test_retry_after_identity_receipt_failure_reuses_root_and_uuids(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            store = MemoryStore(project)
            txid = str(uuid.uuid4())
            with patch(
                "an_kla.identity.write_identity_receipt", side_effect=OSError("EIO")
            ):
                with self.assertRaises(OSError):
                    store.initialize_with_outcome(transaction_id=txid)
            first_current = store.read_current()
            first_binding = read_binding(store)
            retried = store.initialize_with_outcome(transaction_id=txid)
            self.assertEqual(retried["revision"], first_current)
            self.assertEqual(
                read_binding(store)["store_identity"], first_binding["store_identity"]
            )
            self.assertEqual(identity_status(store)["identity_status"], "complete")

    def test_invalid_init_txid_writes_zero_identity_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            store = MemoryStore(project)
            with self.assertRaisesRegex(IdentityError, "invalid_transaction_id"):
                store.initialize_with_outcome(transaction_id="bad")
            self.assertFalse((Path(project) / ".an-kla").exists())

    def test_adoption_receipt_removed_after_preflight_blocks_first_child(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            store, root = _legacy_store(project)
            adopted = adopt(store, plan_adoption(store), root)
            self.assertEqual(adopted["durability_state"], "complete")
            proposal = _proposal(root, "f-receipt-race")
            authority = _authority(proposal)
            planning = store.plan_write(proposal, authority)
            transactions_before = set((store.root / "transactions").glob("*.json"))
            from an_kla import write_commit as write_commit_module

            original = write_commit_module.assert_unchanged

            def remove_receipt_then_check(target, before, parent):
                for path in (
                    target.project_root / ".an-kla" / "identity-receipts" / "sha256"
                ).glob("*.json"):
                    path.unlink()
                return original(target, before, parent)

            with patch(
                "an_kla.write_commit.assert_unchanged",
                side_effect=remove_receipt_then_check,
            ):
                with self.assertRaisesRegex(
                    IdentityError, "legacy_store_identity_adoption_required"
                ):
                    store.commit_write_plan(
                        expected_current_hash=root,
                        proposal=proposal,
                        authority=authority,
                        decision=planning["decision"],
                        plan=planning["plan"],
                    )
            self.assertEqual(
                set((store.root / "transactions").glob("*.json")),
                transactions_before,
            )

    def test_init_retry_reports_only_semantically_valid_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            store = MemoryStore(project)
            first = store.initialize_with_outcome()
            valid = first["identity"]["receipt"]
            receipts = Path(project) / ".an-kla" / "identity-receipts" / "sha256"
            (receipts / ("f" * 64 + ".json")).write_bytes(b"{}")
            retried = store.initialize_with_outcome()
            self.assertEqual(retried["identity"]["receipt"], valid)
            self.assertEqual(retried["identity"]["durability_state"], "complete")

    def test_init_repair_rejects_unrelated_unlinked_root(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            store = MemoryStore(project)
            with patch(
                "an_kla.initialization.initialize_locked", side_effect=OSError("EIO")
            ):
                with self.assertRaises(OSError):
                    store.initialize()
            intent_path = Path(project) / ".an-kla" / "identity-intent.json"
            intent = json.loads(intent_path.read_bytes())
            with store.write_lock():
                unrelated, outcome = initialize_locked(
                    store, transaction_id=str(uuid.uuid4()), store_identity=None
                )
            self.assertTrue(outcome["committed"])
            with self.assertRaisesRegex(IdentityError, "identity_bootstrap_conflict"):
                repair(store, intent)
            self.assertEqual(store.read_current(), unrelated)
            self.assertNotEqual(identity_status(store)["identity_status"], "complete")

    def test_adoption_rejects_cross_uuid_plan_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            store, root = _legacy_store(project)
            plan = plan_adoption(store)
            tampered = json.loads(json.dumps(plan))
            tampered["store_identity"]["project_uuid"] = str(uuid.uuid4())
            core = {key: tampered[key] for key in tampered if key != "plan_fingerprint"}
            tampered["plan_fingerprint"] = digest_json(core)
            with self.assertRaisesRegex(IdentityError, "identity_adoption_plan_invalid"):
                adopt(store, tampered, root)
            self.assertFalse((Path(project) / ".an-kla" / "identity-intent.json").exists())
            self.assertFalse((Path(project) / ".an-kla" / "project-identity.json").exists())
            self.assertFalse((store.root / "identity.json").exists())

    def test_intent_publication_failure_reuses_single_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            store = MemoryStore(project)
            from an_kla import identity as identity_module

            original = identity_module.atomic_write
            failed = False

            def fail_first_replace(*args, **kwargs):
                nonlocal failed
                if not failed:
                    failed = True
                    raise OSError("EIO")
                return original(*args, **kwargs)

            with patch("an_kla.identity.atomic_write", side_effect=fail_first_replace):
                with self.assertRaises(OSError):
                    store.initialize()
            intent_path = Path(project) / ".an-kla" / "identity-intent.json"
            first = json.loads(intent_path.read_bytes())
            immutable = Path(project) / ".an-kla" / "identity-intents" / "sha256"
            self.assertEqual(len(list(immutable.glob("*.json"))), 1)
            store.initialize()
            retried = json.loads(intent_path.read_bytes())
            self.assertEqual(retried["project_identity"], first["project_identity"])
            self.assertEqual(retried["store_identity"], first["store_identity"])
            self.assertEqual(len(list(immutable.glob("*.json"))), 1)

    def test_symlinked_intent_receipt_and_lock_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            store = MemoryStore(project)
            store.initialize()
            anchor = Path(project) / ".an-kla"
            intent = anchor / "identity-intent.json"
            intent_copy = anchor / "intent-copy.json"
            intent_copy.write_bytes(intent.read_bytes())
            intent.unlink()
            intent.symlink_to(intent_copy.name)
            self.assertEqual(identity_status(store)["identity_status"], "conflict")

        with tempfile.TemporaryDirectory() as project:
            store = MemoryStore(project)
            store.initialize()
            receipts = Path(project) / ".an-kla" / "identity-receipts" / "sha256"
            receipt = next(receipts.glob("*.json"))
            copy = Path(project) / ".an-kla" / "receipt-copy.json"
            copy.write_bytes(receipt.read_bytes())
            receipt.unlink()
            receipt.symlink_to(copy)
            self.assertEqual(
                identity_status(store)["identity_status"], "partial_consistent"
            )

        with tempfile.TemporaryDirectory() as project:
            anchor = Path(project) / ".an-kla"
            anchor.mkdir()
            target = anchor / "lock-target"
            target.write_bytes(b"")
            (anchor / ".identity.lock").symlink_to(target.name)
            with self.assertRaisesRegex(IdentityError, "store_identity_invalid"):
                MemoryStore(project).initialize()
            self.assertFalse((anchor / "identity-intent.json").exists())

    def test_symlinked_evidence_parent_is_not_followed(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            store = MemoryStore(project)
            store.initialize()
            anchor = Path(project) / ".an-kla"
            receipts = anchor / "identity-receipts" / "sha256"
            relocated = anchor / "receipt-directory-copy"
            receipts.rename(relocated)
            receipts.symlink_to(relocated)
            self.assertEqual(
                identity_status(store)["identity_status"], "partial_consistent"
            )

        with tempfile.TemporaryDirectory() as project:
            anchor = Path(project) / ".an-kla"
            anchor.mkdir()
            outside = Path(project) / "outside-intents"
            outside.mkdir()
            (anchor / "identity-intents").symlink_to(outside)
            with self.assertRaisesRegex(IdentityError, "store_identity_invalid"):
                MemoryStore(project).initialize()
            self.assertEqual(list(outside.rglob("*.json")), [])

    def test_repair_after_child_restores_init_and_adoption_evidence(self) -> None:
        for operation in ("initialize", "adopt"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as project:
                store = MemoryStore(project)
                if operation == "initialize":
                    captured = store.initialize()
                else:
                    store, captured = _legacy_store(project)
                    adopt(store, plan_adoption(store), captured)
                child = store.commit(
                    expected_current_hash=captured,
                    checkpoint_patch={},
                    facts=[
                        {
                            "id": "f-repair-child-" + operation,
                            "payload": {"text": "child"},
                        }
                    ],
                )
                receipts = (
                    Path(project) / ".an-kla" / "identity-receipts" / "sha256"
                )
                for path in receipts.glob("*.json"):
                    path.unlink()
                self.assertEqual(
                    identity_status(store)["identity_status"], "partial_consistent"
                )
                intent = json.loads(
                    (Path(project) / ".an-kla" / "identity-intent.json").read_bytes()
                )
                result = repair(store, intent)
                self.assertEqual(result["current_observed"], child)
                self.assertEqual(result["durability_state"], "complete")
                self.assertEqual(identity_status(store)["identity_status"], "complete")

    def test_foreign_or_missing_identity_descendant_blocks_status_and_mutation(self) -> None:
        for linked in (None, "sha256:" + "0" * 64):
            with self.subTest(linked=linked), tempfile.TemporaryDirectory() as project:
                store = MemoryStore(project)
                root = store.initialize()
                child = store.commit(
                    expected_current_hash=root,
                    checkpoint_patch={},
                    facts=[{"id": "f-valid-child", "payload": {"text": "valid"}}],
                )
                forged = dict(store.snapshot(child).manifest)
                forged["revision"] = int(forged["revision"]) + 1
                forged["parent"] = child
                if linked is None:
                    forged.pop("store_identity", None)
                else:
                    forged["store_identity"] = linked
                forged_id = store._write_json_object("revisions", forged)
                store._replace_current(forged_id)
                self.assertEqual(identity_status(store)["identity_status"], "conflict")
                with self.assertRaisesRegex(IdentityError, "store_identity_invalid"):
                    mutation_preflight(store)


if __name__ == "__main__":
    unittest.main()
