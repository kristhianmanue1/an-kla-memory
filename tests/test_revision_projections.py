"""Discovery must rehash bytes and keep uncached/orphan candidates visible."""
from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from unittest.mock import patch

from an_kla.canonical import canonical_json, digest_json
from an_kla.identity import _mutation_preflight_with_context
from an_kla.revision_walk import _OperationContext
from an_kla.store import MemoryStore
from an_kla.transactions import _manifest_candidates, candidate_relation
from tests.test_revision_walk import SyntheticChain, identifier

try:
    import fcntl  # noqa: F401
    _COMPACT_CAPABLE = True
except ImportError:
    _COMPACT_CAPABLE = False


class RevisionProjectionTests(unittest.TestCase):
    def fixture(self, root):
        store = MemoryStore(root)
        head = store.initialize()
        head = store.commit(expected_current_hash=head, checkpoint_patch={}, facts=[{"id": "f"}])
        preflight = _mutation_preflight_with_context(store)
        manifest = store._read_json_object("revisions", head)
        return store, head, manifest, preflight.context

    def test_projected_scan_matches_full_scan_without_redecoding(self):
        with tempfile.TemporaryDirectory() as root:
            store, head, manifest, context = self.fixture(root)
            txid = manifest["transaction_id"]
            expected = _manifest_candidates(store, txid)
            with patch("an_kla.transactions.canonical_json", side_effect=AssertionError("redecode")):
                self.assertEqual(_manifest_candidates(store, txid, _context=context), expected)
            self.assertEqual(expected, [head])
            # An arbitrary dictionary cannot act as a validated projection.
            self.assertEqual(_manifest_candidates(store, txid, _context={head: ("fake", txid)}), expected)

    def test_cached_object_modified_deleted_or_replaced_is_not_served(self):
        for mutation in ("modified", "deleted", "replaced"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as root:
                store, head, manifest, context = self.fixture(root)
                path = store._path_for("revisions", head)
                if mutation == "deleted":
                    path.unlink()
                elif mutation == "modified":
                    path.write_bytes(path.read_bytes() + b" ")
                else:
                    changed = dict(manifest, transaction_id=str(uuid.uuid4()))
                    path.write_bytes(canonical_json(changed))
                full = _manifest_candidates(store, manifest["transaction_id"])
                self.assertEqual(_manifest_candidates(store, manifest["transaction_id"], _context=context), full)
                self.assertEqual(full, [])

    def test_orphans_still_expose_ambiguous_candidates(self):
        with tempfile.TemporaryDirectory() as root:
            store, head, manifest, context = self.fixture(root)
            orphan = store._write_json_object("revisions", dict(manifest, checkpoint="sha256:"+"0"*64))
            txid = manifest["transaction_id"]
            self.assertEqual(set(_manifest_candidates(store, txid, _context=context)), {head, orphan})
            self.assertEqual(_manifest_candidates(store, txid, _context=context), _manifest_candidates(store, txid))
            self.assertEqual(store.inspect_transaction(txid)["operation_error_code"], "transaction_candidate_ambiguous")

    def test_new_revision_has_no_projection_in_previous_operation(self):
        with tempfile.TemporaryDirectory() as root:
            store, head, manifest, context = self.fixture(root)
            new = store.commit(expected_current_hash=head, checkpoint_patch={}, facts=[{"id": "g"}])
            self.assertIsNone(context._candidate(new))
            latest = _mutation_preflight_with_context(store).context
            self.assertIsNot(context, latest)
            txid = store._read_json_object("revisions", new)["transaction_id"]
            self.assertEqual(_manifest_candidates(store, txid, _context=context), [new])
            self.assertEqual(_manifest_candidates(store, txid, _context=latest), [new])

    def test_unbounded_fields_are_ineligible_without_normalization(self):
        key = identifier(0)
        for schema, txid in (
            ("an-kla/revision-v1", ["x"]*10000),
            ({"nested": ["x"]*10000}, str(uuid.uuid4())),
            ("an-kla/revision-v1", "x"*100000),
            ("an-kla/revision-v1", None),
        ):
            with self.subTest(schema_type=type(schema).__name__, txid_type=type(txid).__name__):
                context = _OperationContext()
                context._remember(key, {"schema": schema, "transaction_id": txid})
                self.assertIsNone(context._candidate(key))

    def test_fallback_keeps_malformed_field_results_and_errors(self):
        with tempfile.TemporaryDirectory() as root:
            store, head, manifest, context = self.fixture(root)
            txid = manifest["transaction_id"]
            store._write_json_object("revisions", dict(manifest, transaction_id=["x"]*1000))
            self.assertEqual(_manifest_candidates(store, txid, _context=context), _manifest_candidates(store, txid))
            store._write_json_object("revisions", dict(manifest, schema={"bad": []}))
            for ctx in (None, context):
                with self.assertRaises(TypeError):
                    _manifest_candidates(store, txid, _context=ctx)


class VirtualCanonicalChain:
    """Hash-consistent manifests in memory; no disk/CAS scale claim."""
    def __init__(self, length):
        self.objects = {}
        parent = None
        self.ids = []
        for n in range(length+1):
            manifest = {
                "schema": "an-kla/revision-v1", "revision": n, "parent": parent,
                "facts_segments": [], "events_segments": [], "episodes_segments": [],
                "checkpoint": "sha256:"+"0"*64,
                "transaction_id": str(uuid.UUID(int=n, version=4)) if n else "root",
                "canonicalization": "canonical-json/v1",
                "integrity_claim": "content_identity_not_truth_or_authorship",
            }
            parent = digest_json(manifest)
            self.objects[parent] = manifest
            self.ids.append(parent)

    def _read_json_object(self, kind, key):
        return self.objects[key]


class CandidateRelationHorizonTests(unittest.TestCase):
    def test_long_ancestor_orphan_and_invalid_chain(self):
        store = VirtualCanonicalChain(20000)
        for n in (9999, 10000, 20000):
            with self.subTest(n=n):
                self.assertEqual(candidate_relation(store, store.ids[0], store.ids[n]), "ancestor")
        self.assertEqual(candidate_relation(store, identifier(20001), store.ids[-1]), "orphan")
        self.assertEqual(candidate_relation(store, store.ids[1], store.ids[1]), "current")
        self.assertEqual(candidate_relation(SyntheticChain({1: {"revision": True}}),
                                           identifier(0), identifier(2)), "unknown")

    def test_real_foreign_binding_is_not_reported_as_ancestor(self):
        with tempfile.TemporaryDirectory() as root:
            store = MemoryStore(root)
            base = store.initialize()
            head = store.commit(expected_current_hash=base, checkpoint_patch={}, facts=[{"id": "f"}])
            manifest = store._read_json_object("revisions", head)
            bad = store._write_json_object("revisions", dict(manifest, store_identity="sha256:"+"e"*64))
            self.assertEqual(candidate_relation(store, base, head), "ancestor")
            self.assertEqual(candidate_relation(store, base, bad), "unknown")

    @unittest.skipUnless(_COMPACT_CAPABLE, "compactación no soportada (ADR-0028)")
    def test_v3_epoch_schema_and_root_proof_cannot_be_skipped(self):
        from pathlib import Path
        from an_kla.compaction import plan_compaction, commit_compaction
        from an_kla.export_restore import create_export
        with tempfile.TemporaryDirectory() as root:
            store = MemoryStore(Path(root)/"project")
            source = store.initialize()
            source = store.commit(expected_current_hash=source, checkpoint_patch={}, facts=[{"id": "f"}])
            bundle = Path(root)/"bundle"
            exported = create_export(store, bundle)
            proposal = {"schema": "an-kla/compaction-proposal-v1", "base_revision": source,
                        "epoch_id": str(uuid.uuid4()), "transaction_id": str(uuid.uuid4()),
                        "export_manifest_sha256": exported["manifest_sha256"]}
            compacted = commit_compaction(store, plan_compaction(store, proposal, bundle), source, bundle)
            epoch_root = compacted["candidate_revision"]
            first = store.commit(expected_current_hash=epoch_root, checkpoint_patch={}, facts=[{"id": "g"}])
            head = store.commit(expected_current_hash=first, checkpoint_patch={}, facts=[{"id": "h"}])
            self.assertEqual(candidate_relation(store, first, head), "ancestor")
            self.assertEqual(candidate_relation(store, source, head), "orphan")
            manifest = store._read_json_object("revisions", head)
            epoch = dict(manifest["compaction_epoch"], epoch_id=str(uuid.uuid4()))
            bad_epoch = store._write_json_object("revisions", dict(manifest, compaction_epoch=epoch))
            self.assertEqual(candidate_relation(store, first, bad_epoch), "unknown")
            downgraded = {k:v for k,v in manifest.items()
                          if k not in {"features", "refutations_map", "compaction_epoch"}}
            downgraded["schema"] = "an-kla/revision-v1"
            bad_schema = store._write_json_object("revisions", downgraded)
            self.assertEqual(candidate_relation(store, first, bad_schema), "unknown")
            catalog = store._path_for("compaction/catalogs", manifest["compaction_epoch"]["tombstone_catalog"])
            catalog.write_bytes(catalog.read_bytes()+b" ")
            # Candidate is before the corrupted root on the walk. An early
            # return would hide this failure even though the head is genuine.
            self.assertEqual(candidate_relation(store, first, head), "unknown")
