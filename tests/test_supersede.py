"""Characterization tests for the supersede resolution block (issue #59 Fase 0).

These tests freeze the observable behavior of the supersede target resolution
that lives in ``MemoryStore.commit_write_plan`` and is extracted unchanged into
``an_kla.supersede.resolve_supersede_targets``. They are written BEFORE the
extraction against the inline ``store.py`` block, and must stay green after the
extraction.

Behavior coverage (per docs/planning/issue-59-subject-ref-implementation-2026-08-11.md
§5):

* error code ``invalid_supersede_target`` + exact details (``self_reference``,
  ``target_missing``, ``target_not_vigente``);
* failure order under ``write_lock``: CAS/identity/policy BEFORE supersede, and
  supersede BEFORE pending construction (zero effects on failure);
* ``snapshot(observed)`` is called by the resolution block only when at least
  one item has ``operation=supersede``;
* stable observable effects of a valid supersede (revision, vigencia, snapshot,
  objects, journal, CURRENT).

The ``target_missing`` and ``target_not_vigente`` details are reachable through
``commit_write_plan``; the store-level ``self_reference`` check is a
defense-in-depth that the policy core (``verify_write_plan``) already rejects
first (``records[]:supersedes:self_reference_forbidden``), so it is only
exercised through the extracted unit (new surface): that subcase is red before
the extraction (function absent) and green after, by design.

The snapshot-call test stubs ``_maybe_reindex`` because the derived FTS refresh
(``index_resolution`` in ``an_kla/index.py``) also calls ``store.snapshot``
after a successful commit; isolating the resolution block's own call is what the
Fase 0 invariant freezes.
"""

from __future__ import annotations

from copy import deepcopy
import tempfile
import unittest
from unittest.mock import patch

from an_kla.canonical import digest_json
from an_kla.store import MemoryStore
from an_kla.write_policy import WritePolicyError


def proposal(base: str, record_id: str = "f-policy", *, representation: str = "summary") -> dict:
    return {
        "schema": "an-kla/write-proposal-v1",
        "base_revision": base,
        "stream": "facts",
        "operation": "add",
        "requested_representation": representation,
        "record": {"id": record_id, "payload": {"text": "memoria durable"}},
        "lineage": {"derived_from_retrieval": False, "refs": []},
    }


def authority(candidate: dict, *, authority_class: str = "model_derived") -> dict:
    issuer_kind = {
        "channel_confirmed": "channel",
        "model_derived": "model",
        "unresolved": "unknown",
    }[authority_class]
    return {
        "schema": "an-kla/write-authority-v1",
        "proposal_sha256": digest_json(candidate),
        "base_revision": candidate["base_revision"],
        "authority_class": authority_class,
        "issuer": {
            "kind": issuer_kind,
            "id": "test-authority",
            "configuration_fingerprint": "sha256:" + "b" * 64,
        },
        "evidence": [],
        "scope": {
            "streams": [candidate["stream"]],
            "representations": [candidate["requested_representation"]],
            "operations": [candidate["operation"]],
        },
    }


def _supersede_proposal(base: str, new_id: str, target_id: str) -> dict:
    return {
        "schema": "an-kla/write-proposal-v1",
        "base_revision": base,
        "stream": "facts",
        "operation": "supersede",
        "requested_representation": "summary",
        "record": {"id": new_id, "indexable_text": new_id, "summary": new_id},
        "lineage": {"derived_from_retrieval": False, "refs": []},
        "supersedes": target_id,
    }


class SupersedeCharacterizationTests(unittest.TestCase):
    """Freeze the supersede resolution contract across the Fase 0 extraction."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(self.temp.name)
        self.root_revision = self.store.initialize()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _add(self, base: str, record_id: str) -> str:
        candidate = proposal(base, record_id, representation="summary")
        candidate["record"]["indexable_text"] = record_id
        auth = authority(candidate)
        planning = self.store.plan_write(candidate, auth)
        result = self.store.commit_write_plan(
            expected_current_hash=base,
            plan=planning["plan"],
            proposal=candidate,
            authority=auth,
            decision=planning["decision"],
        )
        return result["revision"]

    def _supersede_planning(self, base: str, new_id: str, target_id: str):
        candidate = _supersede_proposal(base, new_id, target_id)
        auth = authority(candidate)
        return candidate, auth, self.store.plan_write(candidate, auth)

    def _commit(self, base, candidate, auth, planning):
        return self.store.commit_write_plan(
            expected_current_hash=base,
            plan=planning["plan"],
            proposal=candidate,
            authority=auth,
            decision=planning["decision"],
        )

    def test_supersede_resolution_freezes_error_codes_and_details(self) -> None:
        rev1 = self._add(self.root_revision, "f-old")

        # target_missing: target id does not exist in the resolved stream.
        candidate, auth, planning = self._supersede_planning(rev1, "f-new", "f-ghost")
        with self.assertRaises(WritePolicyError) as caught:
            self._commit(rev1, candidate, auth, planning)
        self.assertEqual(caught.exception.code, "invalid_supersede_target")
        self.assertEqual(caught.exception.detail, "target_missing")

        # target_not_vigente: target already marked sustituida by a prior supersede.
        self._commit(rev1, *self._supersede_planning(rev1, "f-new", "f-old"))
        rev2 = self.store.read_current()
        candidate, auth, planning = self._supersede_planning(rev2, "f-newer", "f-old")
        with self.assertRaises(WritePolicyError) as caught:
            self._commit(rev2, candidate, auth, planning)
        self.assertEqual(caught.exception.code, "invalid_supersede_target")
        self.assertEqual(caught.exception.detail, "target_not_vigente")

        # self_reference: defense-in-depth at the store layer. The policy core
        # (verify_write_plan) rejects self-ref first, so this is only reachable
        # via the extracted unit directly (new surface). Lazy import keeps the
        # other subcases green against inline store.py before the extraction.
        from an_kla.supersede import resolve_supersede_targets

        rev3 = self._add(self.store.read_current(), "f-seed")
        self_reference_plan = {
            "records": [
                {
                    "operation": "supersede",
                    "stream": "facts",
                    "supersedes": "f-self",
                    "record": {"id": "f-self"},
                }
            ]
        }
        with self.assertRaises(WritePolicyError) as caught:
            resolve_supersede_targets(self.store, self_reference_plan, rev3)
        self.assertEqual(caught.exception.code, "invalid_supersede_target")
        self.assertEqual(caught.exception.detail, "self_reference")

    def test_supersede_resolution_order_under_lock(self) -> None:
        rev1 = self._add(self.root_revision, "f-old")
        # Probe plan: a supersede whose target does not exist. If the supersede
        # block ran, it would raise invalid_supersede_target.
        candidate, auth, planning = self._supersede_planning(rev1, "f-new", "f-ghost")
        journals_before = set((self.store.root / "transactions").glob("*.json"))
        objects_before = set(
            path
            for path in (self.store.root / "objects").rglob("*")
            if path.is_file()
        )

        # (1) CAS before supersede: a stale expected_current_hash yields
        # write_plan_base_changed, not invalid_supersede_target.
        with self.assertRaises(WritePolicyError) as caught:
            self.store.commit_write_plan(
                expected_current_hash="sha256:" + "0" * 64,
                plan=planning["plan"],
                proposal=candidate,
                authority=auth,
                decision=planning["decision"],
            )
        self.assertEqual(caught.exception.code, "write_plan_base_changed")
        self.assertEqual(self.store.read_current(), rev1)

        # (2) Policy (verify_write_plan) before supersede: a corrupted
        # plan_fingerprint yields write_plan_hash_mismatch, not
        # invalid_supersede_target.
        corrupted = deepcopy(planning)
        corrupted["plan"] = deepcopy(planning["plan"])
        corrupted["plan"]["plan_fingerprint"] = "sha256:" + "a" * 64
        with self.assertRaises(WritePolicyError) as caught:
            self._commit(rev1, candidate, auth, corrupted)
        self.assertEqual(caught.exception.code, "write_plan_hash_mismatch")
        self.assertEqual(self.store.read_current(), rev1)

        # (3) Supersede before pending: the probe reaches the supersede block
        # and fails with invalid_supersede_target and zero side effects (no new
        # journal, CURRENT unchanged).
        with self.assertRaises(WritePolicyError) as caught:
            self._commit(rev1, candidate, auth, planning)
        self.assertEqual(caught.exception.code, "invalid_supersede_target")
        self.assertEqual(caught.exception.detail, "target_missing")
        self.assertEqual(self.store.read_current(), rev1)
        journals_after = set((self.store.root / "transactions").glob("*.json"))
        objects_after = set(
            path
            for path in (self.store.root / "objects").rglob("*")
            if path.is_file()
        )
        self.assertEqual(journals_before, journals_after)
        self.assertEqual(objects_before, objects_after)

    def test_snapshot_called_only_when_supersede_present(self) -> None:
        real_snapshot = self.store.snapshot

        # commit_locked (an_kla/transactions.py) always calls snapshot(observed)
        # once to build the child revision, and the post-commit FTS reindex adds
        # further calls. Stub _maybe_reindex to remove that variance and isolate
        # the resolution block, which must contribute exactly one extra
        # snapshot(observed) call iff a supersede item is present.
        with patch.object(self.store, "_maybe_reindex"):
            with patch.object(self.store, "snapshot", side_effect=real_snapshot) as spy:
                self._add(self.root_revision, "f-lone")
                add_only_calls = spy.call_count
            self.assertEqual(add_only_calls, 1)

            rev1 = self.store.read_current()
            candidate, auth, planning = self._supersede_planning(rev1, "f-new", "f-lone")
            with patch.object(self.store, "snapshot", side_effect=real_snapshot) as spy:
                self._commit(rev1, candidate, auth, planning)
                supersede_calls = spy.call_count
            self.assertEqual(supersede_calls, 2)

        # The resolution block adds exactly one snapshot(observed) call, and
        # only when a supersede item is present.
        self.assertEqual(supersede_calls - add_only_calls, 1)

    def test_supersede_commit_effects_stable_across_refactor(self) -> None:
        rev1 = self._add(self.root_revision, "f-old")
        journals_before = list((self.store.root / "transactions").glob("*.json"))

        rev2 = self._commit(rev1, *self._supersede_planning(rev1, "f-new", "f-old"))["revision"]

        self.assertNotEqual(rev2, rev1)
        self.assertEqual(self.store.read_current(), rev2)

        snapshot = self.store.snapshot(rev2)
        facts = {row["id"]: row for row in snapshot.records["facts"]}
        self.assertEqual(facts["f-old"].get("status"), "sustituida")
        self.assertNotIn("status", facts["f-new"])
        self.assertEqual(
            snapshot.manifest["supersedes_map"],
            [{"stream": "facts", "target_id": "f-old", "sustituida_por": "f-new"}],
        )

        # A new transaction journal was produced by the supersede commit.
        journals_after = list((self.store.root / "transactions").glob("*.json"))
        new_journals = set(journals_after) - set(journals_before)
        self.assertEqual(len(new_journals), 1)


if __name__ == "__main__":
    unittest.main()
