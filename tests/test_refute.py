from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

from an_kla.canonical import digest_json
from an_kla.capabilities import capabilities
from an_kla.index import INDEX_PROFILE, build_index
from an_kla.receipt_validation import required_candidate_files
from an_kla.refute_contracts import RefutePolicyError
from an_kla.retrieval import retrieve
from an_kla.store import IntegrityError, MemoryStore
from an_kla.transaction_attempts import begin_transaction


class Resolver:
    descriptor = {
        "profile": "test-resolver/v1",
        "subject_sha256": "sha256:" + "a" * 64,
        "configuration_fingerprint": "sha256:" + "b" * 64,
    }

    def resolve(self, proposal, claim, observations):
        kind = "tool" if claim["requested_authority_class"] == "tool_observed" else "channel"
        return {
            "schema": "an-kla/refute-authority-attestation-v1",
            "proposal_sha256": digest_json(proposal),
            "authority_claim_sha256": digest_json(claim),
            "base_revision": proposal["base_revision"],
            "resolver": deepcopy(self.descriptor),
            "authority_class": claim["requested_authority_class"],
            "issuer": {
                "kind": kind,
                "subject_sha256": "sha256:" + "c" * 64,
                "configuration_fingerprint": "sha256:" + "d" * 64,
            },
            "observations_sha256": digest_json(observations),
            "evidence_resolutions": [
                {
                    **deepcopy(evidence),
                    "resolution": "verified",
                    "observation_sha256": digest_json(observation),
                }
                for evidence, observation in zip(claim["evidence"], observations["items"])
            ],
            "scope": deepcopy(claim["scope"]),
            "proof": {
                "profile": self.descriptor["profile"],
                "proof_sha256": "sha256:" + "e" * 64,
            },
        }

    def verify(self, attestation, proposal, claim, observations):
        return attestation == self.resolve(proposal, claim, observations)


def proposal_and_claim(store: MemoryStore, target_sha: str) -> tuple[dict, dict]:
    base = store.read_current()
    proposal = {
        "schema": "an-kla/refute-proposal-v1",
        "base_revision": base,
        "stream": "facts",
        "target_record_sha256": target_sha,
        "reason": "evidence_contradicts_record",
    }
    claim = {
        "schema": "an-kla/refute-authority-claim-v1",
        "proposal_sha256": digest_json(proposal),
        "base_revision": base,
        "requested_authority_class": "tool_observed",
        "issuer_claim": {
            "kind": "tool",
            "subject_sha256": "sha256:" + "1" * 64,
            "configuration_fingerprint": "sha256:" + "2" * 64,
        },
        "evidence": [{"kind": "revision", "revision_sha256": base}],
        "scope": {
            "operation": "refute",
            "stream": "facts",
            "target_record_sha256": target_sha,
        },
    }
    return proposal, claim


class RefuteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(self.temp.name, refute_authority_resolver=Resolver())
        root = self.store.initialize()
        self.record = {"id": "f-legacy\u0001-id", "payload": {"text": "claim"}}
        self.base = self.store.commit(
            expected_current_hash=root, checkpoint_patch={}, facts=[self.record]
        )
        self.target_sha = digest_json(self.record)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_plan_and_commit_project_refuted_without_rewriting_segment(self) -> None:
        proposal, claim = proposal_and_claim(self.store, self.target_sha)
        planning = self.store.plan_refute(proposal, claim)
        self.assertEqual(planning["decision"]["decision"], "refute")
        parent_segments = self.store.snapshot().manifest["facts_segments"]
        result = self.store.commit_refute_plan(
            expected_current=self.base,
            planning_result=planning,
            transaction_id=str(uuid.uuid4()),
        )
        self.assertTrue(result["committed"])
        child = self.store.snapshot(result["revision"])
        self.assertEqual(child.manifest["schema"], "an-kla/revision-v2")
        self.assertEqual(child.manifest["facts_segments"], parent_segments)
        self.assertEqual(child.records["facts"][0]["status"], "refutada")
        self.assertNotIn("status", self.store.snapshot(self.base).records["facts"][0])
        inspected = self.store.inspect_refute(
            stream="facts", target_record_sha256=self.target_sha
        )
        self.assertEqual(inspected["state"], "refuted")
        self.assertTrue(inspected["untrusted_memory_data"])
        self.assertNotIn(self.record["id"], str(inspected))
        self.assertEqual(inspected["authority_claim"], claim)
        self.assertEqual(retrieve(self.store, "claim", 4096)["selected"], [])
        build_index(self.store, revision_id=result["revision"])
        self.assertEqual(
            retrieve(self.store, "claim", 4096, profile=INDEX_PROFILE)["selected"],
            [],
        )

    def test_unprivileged_or_missing_resolver_skips_without_transaction(self) -> None:
        proposal, claim = proposal_and_claim(self.store, self.target_sha)
        claim["requested_authority_class"] = "model_derived"
        planning = self.store.plan_refute(proposal, claim)
        self.assertEqual(planning["decision"]["reason_codes"], ["refute_requires_privileged_authority"])
        before = set((self.store.root / "transactions").rglob("*"))
        result = self.store.commit_refute_plan(
            expected_current=self.base, planning_result=planning
        )
        self.assertFalse(result["committed"])
        self.assertIsNone(result["outcome"])
        self.assertEqual(set((self.store.root / "transactions").rglob("*")), before)

        proposal, claim = proposal_and_claim(self.store, self.target_sha)
        without = MemoryStore(self.temp.name)
        skipped = without.plan_refute(proposal, claim)
        self.assertEqual(
            skipped["decision"]["reason_codes"],
            ["refute_authority_resolver_unavailable"],
        )

    def test_claim_base_mismatch_is_a_committable_safe_skip(self) -> None:
        proposal, claim = proposal_and_claim(self.store, self.target_sha)
        claim["base_revision"] = "sha256:" + "9" * 64
        planning = self.store.plan_refute(proposal, claim)
        self.assertEqual(
            planning["decision"]["reason_codes"], ["authority_scope_mismatch"]
        )
        before = set((self.store.root / "transactions").rglob("*"))
        result = self.store.commit_refute_plan(
            expected_current=self.base, planning_result=planning
        )
        self.assertFalse(result["committed"])
        self.assertEqual(set((self.store.root / "transactions").rglob("*")), before)

    def test_commit_refute_plan_requires_same_resolver_before_prepared(self) -> None:
        proposal, claim = proposal_and_claim(self.store, self.target_sha)
        planning = self.store.plan_refute(proposal, claim)
        without = MemoryStore(self.temp.name)
        txid = str(uuid.uuid4())
        with self.assertRaisesRegex(RefutePolicyError, "invalid_refute_attestation") as raised:
            without.commit_refute_plan(
                expected_current=self.base, planning_result=planning,
                transaction_id=txid,
            )
        self.assertEqual(raised.exception.detail, "resolver_unavailable_at_commit")
        self.assertFalse((self.store.root / "transactions" / f"{txid}.json").exists())

    def test_refute_requires_preassigned_txid_before_store_io(self) -> None:
        proposal, claim = proposal_and_claim(self.store, self.target_sha)
        planning = self.store.plan_refute(proposal, claim)
        with patch.object(
            self.store, "read_current", side_effect=AssertionError("store_io")
        ), self.assertRaisesRegex(RefutePolicyError, "invalid_refute_planning_result") as raised:
            self.store.commit_refute_plan(
                expected_current=self.base, planning_result=planning
            )
        self.assertEqual(raised.exception.detail, "transaction_id_required")

    def test_missing_target_is_terminal_with_zero_transaction_objects(self) -> None:
        missing = "sha256:" + "9" * 64
        proposal, claim = proposal_and_claim(self.store, missing)
        planning = self.store.plan_refute(proposal, claim)
        txid = str(uuid.uuid4())
        with self.assertRaisesRegex(RefutePolicyError, "invalid_refute_target") as raised:
            self.store.commit_refute_plan(
                expected_current=self.base, planning_result=planning,
                transaction_id=txid,
            )
        self.assertEqual(raised.exception.detail, "target_missing")
        self.assertFalse((self.store.root / "transactions" / f"{txid}.json").exists())
        self.assertEqual(list((self.store.root / "refutations" / "sha256").glob("*.json")), [])

    def test_retry_and_v2_heredity(self) -> None:
        proposal, claim = proposal_and_claim(self.store, self.target_sha)
        planning = self.store.plan_refute(proposal, claim)
        txid = str(uuid.uuid4())
        first = self.store.commit_refute_plan(
            expected_current=self.base, planning_result=planning, transaction_id=txid
        )
        child = self.store.commit(
            expected_current_hash=first["revision"], checkpoint_patch={},
            facts=[{"id": "f-child", "payload": {"text": "next"}}],
        )
        self.assertEqual(self.store.snapshot(child).manifest["schema"], "an-kla/revision-v2")
        retry = self.store.commit_refute_plan(
            expected_current=self.base, planning_result=planning, transaction_id=txid
        )
        self.assertTrue(retry["committed"])
        self.assertEqual(retry["revision"], first["revision"])
        self.assertEqual(self.store.read_current(), child)

    def test_committed_replay_survives_installed_policy_drift(self) -> None:
        from an_kla import refute_policy

        proposal, claim = proposal_and_claim(self.store, self.target_sha)
        planning = self.store.plan_refute(proposal, claim)
        txid = str(uuid.uuid4())
        first = self.store.commit_refute_plan(
            expected_current=self.base, planning_result=planning,
            transaction_id=txid,
        )
        original = deepcopy(refute_policy._CONFIG)
        refute_policy._CONFIG["terminal_error_codes"].append("future_code")
        try:
            retry = self.store.commit_refute_plan(
                expected_current=self.base, planning_result=planning,
                transaction_id=txid,
            )
            self.assertTrue(retry["committed"])
            self.assertEqual(retry["revision"], first["revision"])
            self.store._replace_current(self.base)
            with self.assertRaisesRegex(
                RefutePolicyError, "refute_policy_fingerprint_mismatch"
            ):
                self.store.commit_refute_plan(
                    expected_current=self.base, planning_result=planning,
                    transaction_id=str(uuid.uuid4()),
                )
        finally:
            refute_policy._CONFIG.clear()
            refute_policy._CONFIG.update(original)

    def test_candidate_receipt_covers_exact_refute_objects(self) -> None:
        proposal, claim = proposal_and_claim(self.store, self.target_sha)
        planning = self.store.plan_refute(proposal, claim)
        txid = str(uuid.uuid4())
        result = self.store.commit_refute_plan(
            expected_current=self.base, planning_result=planning, transaction_id=txid
        )
        journal = __import__("json").loads(
            (self.store.root / "transactions" / f"{txid}.json").read_text()
        )
        receipt = self.store._read_json_object(
            f"transactions/{txid}/receipts", journal["candidate_receipt"]
        )
        files = {
            item["path"] for item in receipt["protected"]
            if item["operation"] == "file_fsync"
        }
        self.assertEqual(
            files,
            required_candidate_files(
                self.store, txid, result["revision"], journal["attempt"]
            ),
        )
        self.assertEqual(
            sum(path.startswith("authority-") or path.startswith("refutations/") for path in files),
            3,
        )

    def test_claim_write_fault_returns_outcome_and_retry_converges(self) -> None:
        proposal, claim = proposal_and_claim(self.store, self.target_sha)
        planning = self.store.plan_refute(proposal, claim)
        txid = str(uuid.uuid4())
        original = self.store._write_json_object

        def fail_claim(kind, value):
            if kind == "authority-claims":
                raise OSError("claim-EIO")
            return original(kind, value)

        with patch.object(self.store, "_write_json_object", side_effect=fail_claim):
            failed = self.store.commit_refute_plan(
                expected_current=self.base, planning_result=planning,
                transaction_id=txid,
            )
        self.assertFalse(failed["committed"])
        self.assertEqual(self.store.read_current(), self.base)
        retried = self.store.commit_refute_plan(
            expected_current=self.base, planning_result=planning, transaction_id=txid
        )
        self.assertTrue(retried["committed"])

    def test_mapping_cannot_be_resolver_capability(self) -> None:
        with self.assertRaisesRegex(RefutePolicyError, "invalid_refute_attestation"):
            MemoryStore(self.temp.name, refute_authority_resolver={"resolve": True})
        advertised = capabilities()["storage"]["refute"]
        self.assertTrue(advertised["python_host_resolver_injection"])
        self.assertFalse(advertised["bundled_resolver"])
        self.assertFalse(advertised["provider_adapter"])

    def test_cli_plan_is_safe_skip_and_inspect_is_canonical(self) -> None:
        proposal, claim = proposal_and_claim(self.store, self.target_sha)
        proposal_path = Path(self.temp.name) / "proposal.json"
        claim_path = Path(self.temp.name) / "claim.json"
        proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
        claim_path.write_text(json.dumps(claim), encoding="utf-8")
        planned = subprocess.run(
            [
                sys.executable, "-m", "an_kla", "--project-root", self.temp.name,
                "--no-update-check", "refute", "plan", "--proposal",
                str(proposal_path), "--authority-claim", str(claim_path),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(planned.returncode, 0, planned.stderr)
        self.assertEqual(
            json.loads(planned.stdout)["decision"]["reason_codes"],
            ["refute_authority_resolver_unavailable"],
        )
        planning_path = Path(self.temp.name) / "planning.json"
        planning_path.write_text(planned.stdout, encoding="utf-8")
        skipped = subprocess.run(
            [
                sys.executable, "-m", "an_kla", "--project-root", self.temp.name,
                "--no-update-check", "refute", "commit", "--expected-current",
                self.base, "--planning-result", str(planning_path),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(skipped.returncode, 0, skipped.stderr)
        self.assertFalse(json.loads(skipped.stdout)["committed"])
        inspected = subprocess.run(
            [
                sys.executable, "-m", "an_kla", "--project-root", self.temp.name,
                "--no-update-check", "refute", "inspect", "--stream", "facts",
                "--record-sha256", self.target_sha,
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(inspected.returncode, 0, inspected.stderr)
        payload = json.loads(inspected.stdout)
        self.assertEqual(inspected.stdout, __import__("an_kla.canonical", fromlist=["canonical_json"]).canonical_json(payload).decode("utf-8"))
        self.assertEqual(payload["state"], "active")
        self.assertNotIn(self.record["id"], inspected.stdout)

    def test_faults_across_new_objects_retry_to_one_candidate(self) -> None:
        for point in (
            "authority-claims", "authority-attestations", "refutations",
            "revisions", "candidate-stage", "candidate-receipt", "current",
        ):
            with self.subTest(point=point), tempfile.TemporaryDirectory() as project:
                store = MemoryStore(project, refute_authority_resolver=Resolver())
                root = store.initialize()
                record = {"id": "f-fault", "payload": {"text": point}}
                base = store.commit(
                    expected_current_hash=root, checkpoint_patch={}, facts=[record]
                )
                proposal, claim = proposal_and_claim(store, digest_json(record))
                planning = store.plan_refute(proposal, claim)
                txid = str(uuid.uuid4())
                original_object = store._write_json_object
                original_receipt = __import__("an_kla.transactions", fromlist=["write_receipt"]).write_receipt
                original_replace = store._replace_current

                def object_fault(kind, value):
                    wanted = f"transactions/{txid}/stages" if point == "candidate-stage" else point
                    if kind == wanted:
                        raise OSError(f"{point}-EIO")
                    return original_object(kind, value)

                def receipt_fault(*args, **kwargs):
                    if kwargs.get("kind") == "candidate-data-durable":
                        raise OSError("receipt-EIO")
                    return original_receipt(*args, **kwargs)

                def current_fault(identifier):
                    raise OSError("current-EIO")

                patches = []
                if point in {"authority-claims", "authority-attestations", "refutations", "revisions", "candidate-stage"}:
                    patches.append(patch.object(store, "_write_json_object", side_effect=object_fault))
                elif point == "candidate-receipt":
                    patches.append(patch("an_kla.transactions.write_receipt", side_effect=receipt_fault))
                else:
                    patches.append(patch.object(store, "_replace_current", side_effect=current_fault))
                with patches[0]:
                    failed = store.commit_refute_plan(
                        expected_current=base, planning_result=planning,
                        transaction_id=txid,
                    )
                self.assertIsNot(failed["committed"], True)
                retried = store.commit_refute_plan(
                    expected_current=base, planning_result=planning,
                    transaction_id=txid,
                )
                self.assertTrue(retried["committed"])
                candidates = [
                    path for path in (store.root / "revisions" / "sha256").glob("*.json")
                    if json.loads(path.read_text()).get("transaction_id") == txid
                ]
                self.assertEqual(len(candidates), 1)

    def test_post_current_fault_is_reported_committed_and_retry_is_stable(self) -> None:
        for point in ("replace-returned-error", "current-receipt"):
            with self.subTest(point=point), tempfile.TemporaryDirectory() as project:
                store = MemoryStore(project, refute_authority_resolver=Resolver())
                root = store.initialize()
                record = {"id": "f-post-current", "payload": {"text": point}}
                base = store.commit(
                    expected_current_hash=root, checkpoint_patch={}, facts=[record]
                )
                proposal, claim = proposal_and_claim(store, digest_json(record))
                planning = store.plan_refute(proposal, claim)
                txid = str(uuid.uuid4())
                if point == "replace-returned-error":
                    original = store._replace_current

                    def replace(identifier):
                        original(identifier)
                        raise OSError("post-replace-EIO")

                    context = patch.object(store, "_replace_current", side_effect=replace)
                else:
                    from an_kla import transactions

                    original_receipt = transactions.write_receipt

                    def receipt(*args, **kwargs):
                        if kwargs.get("kind") == "current-durable":
                            raise OSError("current-receipt-EIO")
                        return original_receipt(*args, **kwargs)

                    context = patch("an_kla.transactions.write_receipt", side_effect=receipt)
                with context:
                    first = store.commit_refute_plan(
                        expected_current=base, planning_result=planning,
                        transaction_id=txid,
                    )
                self.assertTrue(first["committed"])
                candidate = first["revision"]
                self.assertEqual(store.read_current(), candidate)
                retry = store.commit_refute_plan(
                    expected_current=base, planning_result=planning,
                    transaction_id=txid,
                )
                self.assertTrue(retry["committed"])
                self.assertEqual(retry["revision"], candidate)

    def test_refute_durability_repair_reprotects_all_dependencies(self) -> None:
        proposal, claim = proposal_and_claim(self.store, self.target_sha)
        planning = self.store.plan_refute(proposal, claim)
        txid = str(uuid.uuid4())
        committed = self.store.commit_refute_plan(
            expected_current=self.base, planning_result=planning,
            transaction_id=txid,
        )
        receipt_dir = self.store.root / "transactions" / txid / "receipts" / "sha256"
        for path in receipt_dir.glob("*.json"):
            path.unlink()
        degraded = self.store.inspect_transaction(txid)
        self.assertTrue(degraded["committed"])
        self.assertEqual(degraded["durability_state"], "incomplete")
        repaired = self.store.repair_transaction_durability(txid)
        self.assertTrue(repaired["committed"])
        self.assertEqual(repaired["durability_state"], "complete")
        self.assertEqual(repaired["candidate_revision"], committed["revision"])

    def test_tampered_journal_map_and_attestation_fail_closed(self) -> None:
        proposal, claim = proposal_and_claim(self.store, self.target_sha)
        planning = self.store.plan_refute(proposal, claim)
        txid = str(uuid.uuid4())
        committed = self.store.commit_refute_plan(
            expected_current=self.base, planning_result=planning,
            transaction_id=txid,
        )
        journal_path = self.store.root / "transactions" / f"{txid}.json"
        journal = json.loads(journal_path.read_text())
        journal["refute_policy"]["reason"] = "source_retracted"
        journal_path.write_text(json.dumps(journal), encoding="utf-8")
        with self.assertRaisesRegex(Exception, "refute_content_hash_mismatch"):
            self.store.inspect_transaction(txid)

        manifest = dict(self.store.snapshot(committed["revision"]).manifest)
        manifest["refutations_map"] = [
            {**manifest["refutations_map"][0], "target_record_sha256": "sha256:" + "8" * 64}
        ]
        forged = self.store._write_json_object("revisions", manifest)
        with self.assertRaisesRegex(IntegrityError, "revision_transition_invalid"):
            self.store.snapshot(forged)

        current_manifest = self.store.snapshot(committed["revision"]).manifest
        refutation = self.store._read_json_object(
            "refutations", current_manifest["refutations_map"][0]["refutation_id"]
        )
        self.store._path_for(
            "authority-attestations", refutation["authority_attestation_id"]
        ).unlink()
        with self.assertRaisesRegex(IntegrityError, "object_missing:authority-attestations"):
            self.store.snapshot(committed["revision"])

    def test_v2_downgrade_and_tampered_map_fail_closed(self) -> None:
        proposal, claim = proposal_and_claim(self.store, self.target_sha)
        planning = self.store.plan_refute(proposal, claim)
        result = self.store.commit_refute_plan(
            expected_current=self.base, planning_result=planning,
            transaction_id=str(uuid.uuid4()),
        )
        child = self.store.commit(
            expected_current_hash=result["revision"], checkpoint_patch={},
            facts=[{"id": "f-after", "payload": {"text": "after"}}],
        )
        manifest = dict(self.store.snapshot(child).manifest)
        manifest["schema"] = "an-kla/revision-v1"
        manifest.pop("features")
        manifest.pop("refutations_map")
        forged = self.store._write_json_object("revisions", manifest)
        with self.assertRaisesRegex(IntegrityError, "revision_schema_downgrade"):
            self.store.snapshot(forged)

    def test_revision_edges_cannot_drop_legacy_supersedes_overlay(self) -> None:
        successor = {"id": "f-successor", "payload": {"text": "successor"}}
        both = self.store.commit(
            expected_current_hash=self.base, checkpoint_patch={}, facts=[successor]
        )
        parent = dict(self.store.snapshot(both).manifest)
        parent["supersedes_map"] = [{
            "stream": "facts", "target_id": self.record["id"],
            "sustituida_por": successor["id"],
        }]
        parent_id = self.store._write_json_object("revisions", parent)
        self.store.snapshot(parent_id)
        child = dict(parent)
        child["revision"] += 1
        child["parent"] = parent_id
        child["transaction_id"] = str(uuid.uuid4())
        child.pop("supersedes_map")
        child_id = self.store._write_json_object("revisions", child)
        with self.assertRaisesRegex(IntegrityError, "revision_transition_invalid"):
            self.store.snapshot(child_id)

    def test_refutation_delta_requires_immutable_refute_attempt(self) -> None:
        proposal, claim = proposal_and_claim(self.store, self.target_sha)
        planning = self.store.plan_refute(proposal, claim)
        txid = str(uuid.uuid4())
        result = self.store.commit_refute_plan(
            expected_current=self.base, planning_result=planning,
            transaction_id=txid,
        )
        stage_dir = self.store.root / "transactions" / txid / "stages" / "sha256"
        original_path = next(stage_dir.glob("*.json"))
        stage = json.loads(original_path.read_text())
        stage["attempt"] = begin_transaction(
            "write", transaction_id=txid, base_revision=self.base,
            plan_fingerprint=planning["plan"]["plan_fingerprint"],
        )
        self.store._write_json_object(f"transactions/{txid}/stages", stage)
        original_path.unlink()
        with self.assertRaisesRegex(IntegrityError, "revision_transition_invalid"):
            self.store.snapshot(result["revision"])

    def test_legacy_root_transaction_id_is_only_valid_at_root(self) -> None:
        root_manifest = {
            "schema": "an-kla/revision-v1",
            "revision": 0,
            "parent": None,
            "facts_segments": [],
            "events_segments": [],
            "episodes_segments": [],
            "checkpoint": "sha256:" + "0" * 64,
            "transaction_id": "root",
            "canonicalization": "canonical-json/v1",
            "integrity_claim": "content_identity_not_truth_or_authorship",
        }
        self.store._validate_manifest(root_manifest)
        root_manifest["revision"] = 1
        with self.assertRaisesRegex(IntegrityError, "manifest_identifier_missing|manifest_transaction_id_invalid"):
            self.store._validate_manifest(root_manifest)


if __name__ == "__main__":
    unittest.main()
