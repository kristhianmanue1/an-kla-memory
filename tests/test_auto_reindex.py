"""Tests for P4 (ADR-0016): auto-reindex after commit_write_plan/commit."""

from __future__ import annotations

import tempfile
import unittest
from unittest import mock

from an_kla.index import build_index, index_resolution
from an_kla.retrieval import INDEX_PROFILE, retrieve
from an_kla.store import MemoryStore


def _governed_commit(store: MemoryStore, expected: str, record_id: str) -> str:
    """Drive the governed write path with model_derived authority."""

    import json
    from an_kla.canonical import digest_json
    from pathlib import Path

    proposal = {
        "schema": "an-kla/write-proposal-v1",
        "base_revision": expected,
        "stream": "episodes",
        "operation": "add",
        "requested_representation": "summary",
        "record": {
            "schema": "an-kla/episode-v1",
            "id": record_id,
            "type": "lesson",
            "timestamp": "2026-08-03T22:00:00Z",
            "payload": {"text": f"leccion {record_id} para reindex inmediato"},
        },
        "lineage": {"derived_from_retrieval": False, "refs": []},
    }
    authority = {
        "schema": "an-kla/write-authority-v1",
        "proposal_sha256": "sha256:" + "0" * 64,
        "base_revision": expected,
        "authority_class": "model_derived",
        "issuer": {
            "kind": "model",
            "id": "test",
            "configuration_fingerprint": "sha256:" + "0" * 64,
        },
        "evidence": [],
        "scope": {
            "streams": ["episodes"],
            "representations": ["summary"],
            "operations": ["add"],
        },
    }
    authority["proposal_sha256"] = digest_json(proposal)
    plan = store.plan_write(proposal, authority)
    result = store.commit_write_plan(
        expected_current_hash=expected,
        proposal=proposal,
        authority=authority,
        decision=plan["decision"],
        plan=plan["plan"],
    )
    assert result["committed"], result
    return result["revision"]


class AutoReindexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(self.temp.name)
        self.base = self.store.initialize()
        # Bootstrap the parent index so _maybe_reindex has something to detect.
        build_index(self.store, revision_id=self.base)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_commit_write_plan_reindexes_without_manual_rebuild(self):
        new_revision = _governed_commit(
            self.store, self.base, "ep-auto-reindex-1"
        )
        resolution = index_resolution(self.store, new_revision)
        self.assertEqual(resolution.status, "none")
        self.assertIsNotNone(resolution.path)
        out = retrieve(
            self.store,
            "reindex inmediato",
            5000,
            profile=INDEX_PROFILE,
            streams=("episodes",),
        )
        self.assertEqual(out["profile"], INDEX_PROFILE)
        self.assertEqual(out["degradation"], "none")
        ids = [s["id"] for s in out["selected"]]
        self.assertEqual(ids, ["ep-auto-reindex-1"])

    def test_legacy_commit_also_triggers_reindex(self):
        new_revision = self.store.commit(
            expected_current_hash=self.base,
            checkpoint_patch={},
            facts=[{"id": "f-auto-1", "payload": {"text": "facto legacy reindex"}}],
        )
        resolution = index_resolution(self.store, new_revision)
        self.assertEqual(resolution.status, "none")

    def test_reindex_failure_does_not_break_commit(self):
        with mock.patch(
            "an_kla.index.build_index", side_effect=RuntimeError("simulated")
        ) as _mock:
            new_revision = _governed_commit(
                self.store, self.base, "ep-reindex-fail"
            )
        # The commit is still authoritative.
        self.assertEqual(self.store.read_current(), new_revision)
        # Retrieval degrades silently to scan because no index exists for the
        # new revision (the build was mocked to fail).
        out = retrieve(
            self.store,
            "reindex",
            5000,
            profile=INDEX_PROFILE,
            streams=("episodes",),
        )
        self.assertEqual(out["profile"], "scan-fallback/v1")
        self.assertIn(out["degradation"], {"index_unavailable", "none"})

    def test_first_commit_without_parent_index_does_not_build(self):
        # Fresh memory without a bootstrapped index: no auto-build happens
        # because the parent has no index to mirror.
        temp = tempfile.TemporaryDirectory()
        try:
            store = MemoryStore(temp.name)
            base = store.initialize()
            new_revision = _governed_commit(store, base, "ep-cold-start")
            resolution = index_resolution(store, new_revision)
            self.assertEqual(resolution.status, "index_unavailable")
            self.assertIsNone(resolution.path)
        finally:
            temp.cleanup()

    def test_skip_decision_does_not_reindex(self):
        # An unresolved authority leads to skip; _maybe_reindex is never
        # reached. We assert by patching build_index and observing it is not
        # called.
        with mock.patch("an_kla.index.build_index") as mock_build:
            from an_kla.canonical import digest_json
            proposal = {
                "schema": "an-kla/write-proposal-v1",
                "base_revision": self.base,
                "stream": "episodes",
                "operation": "add",
                "requested_representation": "summary",
                "record": {
                    "schema": "an-kla/episode-v1",
                    "id": "ep-skip-attempt",
                    "type": "lesson",
                    "timestamp": "2026-08-03T22:00:00Z",
                    "payload": {"text": "intentando escribir sin autoridad"},
                },
                "lineage": {"derived_from_retrieval": False, "refs": []},
            }
            authority = {
                "schema": "an-kla/write-authority-v1",
                "proposal_sha256": "sha256:" + "0" * 64,
                "base_revision": self.base,
                "authority_class": "unresolved",
                "issuer": {
                    "kind": "unknown",
                    "id": "test",
                    "configuration_fingerprint": "sha256:" + "0" * 64,
                },
                "evidence": [],
                "scope": {
                    "streams": ["episodes"],
                    "representations": ["summary"],
                    "operations": ["add"],
                },
            }
            authority["proposal_sha256"] = digest_json(proposal)
            plan = self.store.plan_write(proposal, authority)
            result = self.store.commit_write_plan(
                expected_current_hash=self.base,
                proposal=proposal,
                authority=authority,
                decision=plan["decision"],
                plan=plan["plan"],
            )
        self.assertFalse(result["committed"])
        self.assertEqual(result["decision"], "skip")
        mock_build.assert_not_called()


if __name__ == "__main__":
    unittest.main()
