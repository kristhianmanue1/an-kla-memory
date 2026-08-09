from __future__ import annotations

from datetime import datetime, timezone
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

from an_kla.canonical import canonical_json, digest_json
from an_kla.checkpoint_policy import CheckpointPolicyError, FIELDS, build_plan
from an_kla.checkpoints import commit_checkpoint, plan_checkpoint, show_checkpoint
from an_kla.resume import _snapshot, resume
from an_kla.store import MemoryStore


def _state(parent: str, marker: str = "continue") -> dict:
    return {
        "schema": "an-kla/working-state-v2",
        "objective": {"value": marker, "provenance": "caller_asserted"},
        "phase": {"value": "implementation", "provenance": "caller_asserted"},
        "next_step": {"value": "test", "provenance": "caller_asserted"},
        "decisions": [],
        "blockers": [],
        "evidence": [],
        "source_state": {
            "profile": "none/v1",
            "head": {"value": None, "provenance": "unavailable"},
            "branch": {"value": None, "provenance": "unavailable"},
            "dirty_digest": {"value": None, "provenance": "unavailable"},
        },
        "captured_at": {
            "value": "2026-08-08T00:00:00.000000Z",
            "provenance": "caller_asserted",
        },
        "supersedes_checkpoint": parent,
    }


def _authority(store: MemoryStore, state: dict, authority_class: str = "model_derived") -> dict:
    current = store.read_current()
    parent = store.snapshot(current).manifest["checkpoint"]
    proposal = {
        "schema": "an-kla/checkpoint-proposal-v1",
        "base_revision": current,
        "parent_checkpoint": parent,
        "working_state": state,
    }
    kinds = {
        "model_derived": "model",
        "unresolved": "unknown",
        "tool_observed": "tool",
    }
    return {
        "schema": "an-kla/checkpoint-authority-v1",
        "proposal_sha256": digest_json(proposal),
        "base_revision": current,
        "authority_class": authority_class,
        "issuer": {
            "kind": kinds[authority_class],
            "id": "checkpoint-test",
            "configuration_fingerprint": "sha256:" + "1" * 64,
        },
        "evidence": [],
        "scope": {"operation": "checkpoint", "fields": sorted(FIELDS)},
    }


class CheckpointContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(self.temp.name)
        self.root = self.store.initialize()
        self.parent_checkpoint = self.store.snapshot().manifest["checkpoint"]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _planning(self, marker: str = "continue") -> dict:
        state = _state(self.store.snapshot().manifest["checkpoint"], marker)
        return plan_checkpoint(self.store, state, _authority(self.store, state))

    def test_plan_is_deterministic_and_rejects_spoofed_tool_observation(self) -> None:
        state = _state(self.parent_checkpoint)
        authority = _authority(self.store, state)
        first = plan_checkpoint(self.store, state, authority)
        second = plan_checkpoint(self.store, state, authority)
        self.assertEqual(canonical_json(first), canonical_json(second))
        spoofed = dict(state)
        spoofed["objective"] = {
            "value": "claimed observation",
            "provenance": "tool_observed",
        }
        with self.assertRaisesRegex(
            CheckpointPolicyError, "tool_observed_requires_adapter"
        ):
            plan_checkpoint(self.store, spoofed, _authority(self.store, spoofed))

    def test_planner_rejects_boolean_revision(self) -> None:
        planning = self._planning()
        with self.assertRaisesRegex(CheckpointPolicyError, "invalid_checkpoint_plan"):
            build_plan(
                planning["proposal"],
                planning["authority"],
                planning["decision"],
                revision=True,
            )

    def test_invalid_provenance_timestamp_and_verified_evidence_fail(self) -> None:
        invalid_unavailable = _state(self.parent_checkpoint)
        invalid_unavailable["objective"] = {
            "value": "not-null",
            "provenance": "unavailable",
        }
        with self.assertRaisesRegex(
            CheckpointPolicyError, "invalid_checkpoint_provenance"
        ):
            plan_checkpoint(
                self.store,
                invalid_unavailable,
                _authority(self.store, invalid_unavailable),
            )
        invalid_time = _state(self.parent_checkpoint)
        invalid_time["captured_at"]["value"] = "not-a-time"
        with self.assertRaisesRegex(CheckpointPolicyError, "invalid_working_state"):
            plan_checkpoint(
                self.store, invalid_time, _authority(self.store, invalid_time)
            )
        state = _state(self.parent_checkpoint)
        authority = _authority(self.store, state)
        authority["evidence"] = [
            {"kind": "artifact", "id": "missing-digest", "resolution": "verified"}
        ]
        with self.assertRaisesRegex(
            CheckpointPolicyError, "invalid_checkpoint_authority"
        ):
            plan_checkpoint(self.store, state, authority)
        mismatched = _authority(self.store, state)
        mismatched["issuer"]["kind"] = "tool"
        with self.assertRaisesRegex(
            CheckpointPolicyError, "invalid_checkpoint_authority"
        ):
            plan_checkpoint(self.store, state, mismatched)

    def test_commit_transitions_v1_to_v2_and_links_parent(self) -> None:
        planning = self._planning()
        result = commit_checkpoint(
            self.store,
            planning,
            self.root,
            transaction_id=str(uuid.uuid4()),
        )
        self.assertTrue(result["committed"])
        snapshot = self.store.snapshot(result["revision"])
        self.assertEqual(snapshot.checkpoint["schema"], "an-kla/checkpoint-v2")
        self.assertEqual(
            snapshot.checkpoint["working_state"]["supersedes_checkpoint"],
            self.parent_checkpoint,
        )
        self.assertEqual(snapshot.checkpoint["revision"], snapshot.manifest["revision"])
        shown = show_checkpoint(self.store)
        self.assertTrue(shown["untrusted_memory_data"])
        self.assertEqual(shown["checkpoint_digest"], result["checkpoint"])

    def test_write_requires_preassigned_transaction_id_before_store_io(self) -> None:
        planning = self._planning()
        before = set((self.store.root / "transactions").glob("**/*"))
        with patch.object(
            self.store,
            "read_current",
            side_effect=AssertionError("store_io_must_not_run"),
        ), self.assertRaisesRegex(
            CheckpointPolicyError, "^checkpoint_transaction_id_required$"
        ):
            commit_checkpoint(self.store, planning, self.root)
        self.assertEqual(set((self.store.root / "transactions").glob("**/*")), before)

    def test_ordinary_write_reuses_checkpoint_digest_and_is_not_lexical(self) -> None:
        planning = self._planning("needle-only-in-working-state")
        checkpointed = commit_checkpoint(
            self.store, planning, self.root, transaction_id=str(uuid.uuid4())
        )
        checkpoint_digest = checkpointed["checkpoint"]
        child = self.store.commit(
            expected_current_hash=checkpointed["revision"],
            checkpoint_patch={},
            facts=[{"id": "f-other", "payload": {"text": "unrelated"}}],
        )
        self.assertEqual(self.store.snapshot(child).manifest["checkpoint"], checkpoint_digest)
        projected = resume(self.store, 4096, query="needle-only-in-working-state")
        self.assertEqual(projected["retrieved_evidence"], [])

    def test_stale_plan_fails_before_transaction_bytes(self) -> None:
        planning = self._planning()
        advanced = self.store.commit(
            expected_current_hash=self.root,
            checkpoint_patch={},
            facts=[{"id": "f-advance", "payload": {"text": "advance"}}],
        )
        before = set((self.store.root / "transactions").glob("*.json"))
        with self.assertRaisesRegex(
            CheckpointPolicyError, "checkpoint_plan_base_changed"
        ):
            commit_checkpoint(
                self.store, planning, self.root, transaction_id=str(uuid.uuid4())
            )
        self.assertEqual(set((self.store.root / "transactions").glob("*.json")), before)
        self.assertEqual(self.store.read_current(), advanced)

    def test_checkpoint_object_failure_is_not_committed_and_retry_converges(self) -> None:
        planning = self._planning()
        txid = str(uuid.uuid4())
        original = self.store._write_json_object

        def fail_checkpoint(kind, value):
            if kind == "checkpoints":
                raise OSError("checkpoint-EIO")
            return original(kind, value)

        with patch.object(self.store, "_write_json_object", side_effect=fail_checkpoint):
            failed = commit_checkpoint(
                self.store, planning, self.root, transaction_id=txid
            )
        self.assertFalse(failed["committed"])
        self.assertEqual(self.store.read_current(), self.root)
        retried = commit_checkpoint(
            self.store, planning, self.root, transaction_id=txid
        )
        self.assertTrue(retried["committed"])

    def test_success_and_post_current_retry_return_same_candidate(self) -> None:
        for fail_journal in (False, True):
            with self.subTest(fail_journal=fail_journal), tempfile.TemporaryDirectory() as project:
                store = MemoryStore(project)
                root = store.initialize()
                state = _state(store.snapshot().manifest["checkpoint"])
                planning = plan_checkpoint(store, state, _authority(store, state))
                txid = str(uuid.uuid4())
                original = store._write_transaction

                def maybe_fail(tx, body):
                    if fail_journal and body.get("stage") == "committed":
                        raise OSError("journal-EIO")
                    return original(tx, body)

                with patch.object(store, "_write_transaction", side_effect=maybe_fail):
                    first = commit_checkpoint(
                        store, planning, root, transaction_id=txid
                    )
                self.assertTrue(first["committed"])
                retried = commit_checkpoint(
                    store, planning, root, transaction_id=txid
                )
                self.assertTrue(retried["committed"])
                self.assertEqual(retried["revision"], first["revision"])
                self.assertEqual(store.snapshot().manifest["revision"], 1)

    def test_ordinary_write_rejects_checkpoint_patch_before_objects(self) -> None:
        before = set((self.store.root / "transactions").glob("*.json"))
        with self.assertRaisesRegex(
            RuntimeError, "governed_checkpoint_update_required"
        ):
            self.store.commit(
                expected_current_hash=self.root,
                checkpoint_patch={"goal": "legacy mutation"},
            )
        self.assertEqual(set((self.store.root / "transactions").glob("*.json")), before)
        self.assertEqual(self.store.read_current(), self.root)

    def test_resume_legacy_and_v2_have_exact_budget_and_provenance(self) -> None:
        legacy = resume(self.store, 4096)
        self.assertIn("legacy_checkpoint_v1", legacy["warnings"])
        self.assertEqual(legacy["used_bytes"], len(canonical_json(legacy)))
        self.assertEqual(legacy["retrieved_evidence"], [])
        self.assertEqual(legacy["provenance"]["retrieval"]["source"], "disabled")
        planning = self._planning()
        commit_checkpoint(
            self.store, planning, self.root, transaction_id=str(uuid.uuid4())
        )
        current = resume(self.store, 4096)
        self.assertEqual(current["warnings"], [])
        self.assertEqual(current["snapshot"]["checkpoint_schema"], "an-kla/checkpoint-v2")
        self.assertEqual(current["used_bytes"], len(canonical_json(current)))
        with self.assertRaisesRegex(ValueError, "budget_too_small_for_resume_snapshot"):
            resume(self.store, 1)

    def test_resume_rejects_invalid_or_future_checkpoint_revision(self) -> None:
        parent = "sha256:" + "2" * 64
        state = _state(parent)
        for checkpoint_revision in (-1, 0, 2, True):
            with self.subTest(checkpoint_revision=checkpoint_revision):
                forged = SimpleNamespace(
                    checkpoint={
                        "schema": "an-kla/checkpoint-v2",
                        "revision": checkpoint_revision,
                        "working_state": state,
                    },
                    manifest={"checkpoint": parent, "revision": 1},
                )
                with self.assertRaisesRegex(
                    CheckpointPolicyError, "invalid_working_state"
                ):
                    _snapshot(forged)
        reused = SimpleNamespace(
            checkpoint={
                "schema": "an-kla/checkpoint-v2",
                "revision": 1,
                "working_state": state,
            },
            manifest={"checkpoint": parent, "revision": 3},
        )
        projected, warnings = _snapshot(reused)
        self.assertEqual(projected["checkpoint"]["revision"], 1)
        self.assertEqual(warnings, [])

    def test_resume_freezes_revision_across_concurrent_advance(self) -> None:
        checkpointed = commit_checkpoint(
            self.store,
            self._planning(),
            self.root,
            transaction_id=str(uuid.uuid4()),
        )
        self.store.commit(
            expected_current_hash=checkpointed["revision"],
            checkpoint_patch={},
            facts=[{"id": "f-before", "payload": {"text": "target"}}],
        )
        frozen_revision = self.store.read_current()
        from an_kla import resume as resume_module

        original = resume_module.retrieve
        advanced = None

        def advance_then_retrieve(*args, **kwargs):
            nonlocal advanced
            advanced = self.store.commit(
                expected_current_hash=frozen_revision,
                checkpoint_patch={},
                facts=[{"id": "f-after", "payload": {"text": "target"}}],
            )
            return original(*args, **kwargs)

        with patch("an_kla.resume.retrieve", side_effect=advance_then_retrieve):
            result = resume(self.store, 4096, query="target")
        self.assertEqual(result["revision"], frozen_revision)
        self.assertEqual(
            {item["id"] for item in result["retrieved_evidence"]}, {"f-before"}
        )
        self.assertEqual(self.store.read_current(), advanced)

    def test_resume_reconsiders_evidence_when_budget_counter_grows(self) -> None:
        selected = [
            {
                "id": "f-small",
                "stream": "facts",
                "score": 1,
                "render": "x",
                "cost_bytes": 1,
            }
        ] + [
            {
                "id": f"f-large-{index}",
                "stream": "facts",
                "score": 1,
                "render": "x" * 1000,
                "cost_bytes": 1000,
            }
            for index in range(10)
        ]
        fake = {
            "profile": "scan-fallback/v1",
            "degradation": "none",
            "selected": selected,
            "excluded_summary": {},
        }
        with patch("an_kla.resume.retrieve", return_value=fake):
            result = resume(self.store, 1227, query="x")
        self.assertLessEqual(result["used_bytes"], 1227)
        self.assertEqual(result["used_bytes"], len(canonical_json(result)))
        self.assertGreaterEqual(result["excluded_summary"]["budget"], 10)


if __name__ == "__main__":
    unittest.main()
