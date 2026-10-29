"""Traversal controls are separate from a real 20k-revision scale run."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from an_kla.canonical import canonical_json, digest_bytes
from an_kla.identity import _read_intent, identity_status, read_binding
from an_kla.identity_evidence import (
    _is_ancestor, validate_bound_descendants, valid_identity_receipt,
    write_identity_receipt, IdentityEvidenceError,
)
from an_kla.revision_walk import _LineageSummary, RevisionWalkError
from an_kla.store import MemoryStore

IDENTITY = "sha256:" + "f" * 64


def identifier(n):
    return f"sha256:{n:064x}"


class SyntheticChain:
    """No CAS/filesystem claim: supplies a virtual chain to the walker."""
    def __init__(self, changes=None):
        self.changes = changes or {}

    def _read_json_object(self, kind, key):
        n = int(key[7:], 16)
        manifest = {"revision": n, "schema": "an-kla/revision-v1",
                    "parent": identifier(n-1) if n else None,
                    "store_identity": IDENTITY}
        manifest.update(self.changes.get(n, {}))
        return manifest


class RevisionWalkTests(unittest.TestCase):
    def test_long_conforming_chains_do_not_truncate_at_10k(self):
        for n in (9999, 10000, 20000):
            with self.subTest(n=n):
                store = SyntheticChain()
                self.assertTrue(_is_ancestor(store, identifier(0), identifier(n)))
                validate_bound_descendants(store, identifier(n), identifier(0), IDENTITY)
                self.assertTrue(_LineageSummary(store, identifier(n), IDENTITY).bound(identifier(0)))

    def test_cycles_non_decreasing_boolean_and_missing_parents_fail_closed(self):
        for changes in (
            {1: {"parent": identifier(2)}},
            {1: {"revision": 2}},
            {1: {"revision": True}},
            {1: {"parent": "missing"}},
        ):
            with self.subTest(changes=changes):
                store = SyntheticChain(changes)
                self.assertFalse(_is_ancestor(store, identifier(0), identifier(2)))
                with self.assertRaises(IdentityEvidenceError):
                    validate_bound_descendants(store, identifier(2), identifier(0), IDENTITY)
                with self.assertRaises((RevisionWalkError, ValueError)):
                    _LineageSummary(store, identifier(2), IDENTITY)

    def test_legacy_exception_is_local_to_captured_node(self):
        good = SyntheticChain({0: {"store_identity": None}})
        summary = _LineageSummary(good, identifier(2), IDENTITY)
        self.assertFalse(summary.bound(identifier(0)))
        self.assertTrue(summary.bound(identifier(0), allow_legacy=True))
        bad = SyntheticChain({0: {"store_identity": None}, 1: {"store_identity": None}})
        self.assertFalse(_LineageSummary(bad, identifier(2), IDENTITY).bound(
            identifier(0), allow_legacy=True))
        alien = SyntheticChain({0: {"store_identity": "sha256:" + "a" * 64}})
        self.assertFalse(_LineageSummary(alien, identifier(2), IDENTITY).bound(
            identifier(0), allow_legacy=True))


class ConsolidatedIdentityTests(unittest.TestCase):
    def test_status_reads_ancestors_once_and_preserves_receipt_selection(self):
        with tempfile.TemporaryDirectory() as root:
            store = MemoryStore(root)
            current = store.initialize()
            for i in range(6):
                current = store.commit(expected_current_hash=current,
                                       checkpoint_patch={}, facts=[{"id": f"f-{i}"}])
            intent = _read_intent(store)
            write_identity_receipt(store, intent, "repair", current)
            receipt_dir = store.store_root / "identity-receipts/sha256"
            valid_ids = ["sha256:" + p.stem for p in receipt_dir.glob("*.json")]
            value = json.loads(next(receipt_dir.glob("*.json")).read_bytes())
            value["protected"][0]["content_sha256"] = "sha256:" + "0" * 64
            raw = canonical_json(value)
            (receipt_dir/(digest_bytes(raw)[7:]+".json")).write_bytes(raw)
            with patch.object(store, "_read_json_object", wraps=store._read_json_object) as read:
                self.assertEqual(identity_status(store)["identity_status"], "complete")
            counts = Counter(call.args[1] for call in read.call_args_list
                             if call.args[0] == "revisions")
            self.assertEqual(len(counts), 7)
            self.assertTrue(all(n == 1 for key, n in counts.items() if key != current))
            self.assertLessEqual(counts[current], 2)
            self.assertEqual(valid_identity_receipt(store, intent, current), max(valid_ids))

    def test_receipt_observes_advanced_current_without_certifying_old_head(self):
        with tempfile.TemporaryDirectory() as root:
            store = MemoryStore(root)
            old = store.initialize()
            intent = _read_intent(store)
            summary = _LineageSummary(store, old, read_binding(store)["store_identity"])
            new = store.commit(expected_current_hash=old, checkpoint_patch={}, facts=[{"id": "f"}])
            with patch.object(store, "_read_json_object", wraps=store._read_json_object) as read:
                self.assertIsNotNone(valid_identity_receipt(store, intent, old, _lineage=summary))
            self.assertTrue(any(call.args == ("revisions", new) for call in read.call_args_list))
