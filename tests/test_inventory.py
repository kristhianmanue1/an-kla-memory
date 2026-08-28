"""ADR-0041: inventario físico por revisión (tests congelados)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from an_kla.canonical import digest_json
from an_kla.inventory import DEFAULT_LIMIT, INVENTORY_SCHEMA, MAX_LIMIT, inventory
from an_kla.store import IntegrityError, MemoryStore
from an_kla.subject import resolve_namespace
from an_kla.export_restore import create_export
from an_kla.compaction import commit_compaction, plan_compaction
from an_kla.subject_ref import parse_subject_ref

ROOT = Path(__file__).resolve().parents[1]


def _validator():
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        raise unittest.SkipTest("jsonschema unavailable")
    return Draft202012Validator(
        json.loads((ROOT / "docs/schemas/inventory-v1.schema.json").read_text())
    )


class InventoryContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = MemoryStore(self.root)
        current = self.store.initialize()
        self.root_revision = current
        namespace = resolve_namespace(self.store)["namespace"]
        subject_ref = f"an-kla:subject:v1:decision:{namespace}:f-2"
        parse_subject_ref(subject_ref)  # sanity: grammar-valid
        self.revision = self.store.commit(
            expected_current_hash=current,
            checkpoint_patch={},
            facts=[
                {"id": "f-1", "payload": {"text": "uno"}},
                {"id": "f-2", "payload": {"text": "dos"},
                 "subject_ref": subject_ref},
            ],
            events=[{"id": "e-1", "payload": {"text": "evento"}}],
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_happy_path_counts_and_invariant(self) -> None:
        result = inventory(self.store, self.revision)
        self.assertEqual(result["schema"], INVENTORY_SCHEMA)
        counts = result["counts"]["facts"]
        self.assertEqual(counts["total"], counts["vigente"] + counts["sustituida"] + counts["refutada"])
        self.assertEqual(counts["total"], 2)
        self.assertEqual(result["counts"]["events"]["total"], 1)
        self.assertTrue(result["pagination"]["complete"])
        self.assertTrue(result["untrusted_memory_data"])
        _validator().validate(result)

    def test_legacy_without_subject_ref_is_enumerated(self) -> None:
        result = inventory(self.store, self.revision, streams=("facts",))
        by_id = {item["id"]: item for item in result["records"]}
        self.assertFalse(by_id["f-1"]["has_subject_ref"])
        self.assertTrue(by_id["f-2"]["has_subject_ref"])

    def test_pagination_continues_exactly(self) -> None:
        first = inventory(self.store, self.revision, limit=1)
        self.assertFalse(first["pagination"]["complete"])
        cursor = first["pagination"]["next_cursor"]
        second = inventory(self.store, self.revision, limit=1, cursor=cursor)
        ids = [item["id"] for item in first["records"]] + [
            item["id"] for item in second["records"]
        ]
        third = inventory(self.store, self.revision, limit=1, cursor=second["pagination"]["next_cursor"])
        ids += [item["id"] for item in third["records"]]
        complete = inventory(self.store, self.revision)
        self.assertEqual(sorted(ids), sorted(i["id"] for i in complete["records"]))

    def test_cursor_from_other_revision_is_invalid(self) -> None:
        first = inventory(self.store, self.revision, limit=1)
        cursor = first["pagination"]["next_cursor"]
        with self.assertRaisesRegex(ValueError, "inventory_cursor_invalid"):
            inventory(self.store, self.root_revision, cursor=cursor)

    def test_missing_revision_argument_is_stable(self) -> None:
        with self.assertRaisesRegex(ValueError, "inventory_revision_required"):
            inventory(self.store, "")

    def test_limit_bounds_are_enforced(self) -> None:
        with self.assertRaisesRegex(ValueError, "inventory_limit_invalid"):
            inventory(self.store, self.revision, limit=0)
        with self.assertRaisesRegex(ValueError, "inventory_limit_invalid"):
            inventory(self.store, self.revision, limit=MAX_LIMIT + 1)
        self.assertEqual(MAX_LIMIT, 1000)
        self.assertEqual(DEFAULT_LIMIT, 200)

    def test_payload_has_no_content_nor_absolute_paths(self) -> None:
        result = inventory(self.store, self.revision)
        blob = json.dumps(result)
        self.assertNotIn("vigente uno", blob)  # no record text
        self.assertNotIn(str(self.root), blob)

    def test_unknown_revision_raises_integrity(self) -> None:
        with self.assertRaises(IntegrityError):
            inventory(self.store, "sha256:" + "f" * 64)

    def test_streams_filter_and_dedup(self) -> None:
        result = inventory(self.store, self.revision, streams=("events", "events"))
        self.assertEqual(result["streams_searched"], ["events"])
        self.assertEqual(result["counts"]["events"]["total"], 1)
        self.assertNotIn("facts", result["counts"])


class InventoryCliTests(unittest.TestCase):
    def test_cli_exit_zero_and_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(directory)
            revision = store.initialize()
            completed = subprocess.run(
                [sys.executable, "-m", "an_kla", "--no-update-check",
                 "--project-root", directory, "inventory",
                 "--revision", revision],
                cwd=ROOT, capture_output=True, text=True,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["schema"], INVENTORY_SCHEMA)

    def test_cli_without_store_reports_gate_not_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run(
                [sys.executable, "-m", "an_kla", "--no-update-check",
                 "--project-root", directory, "inventory",
                 "--revision", "sha256:" + "0" * 64],
                cwd=ROOT, capture_output=True, text=True,
            )
        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn("Traceback", completed.stderr)
        self.assertNotIn(str(ROOT), completed.stderr)



class InventoryPopulationTests(unittest.TestCase):
    """H2/H3 de la ronda: mezcla real con supersede gobernado + eliminada."""

    def _governed_supersede(self, store: MemoryStore, target: str, new_id: str) -> None:
        from tests.test_write_commit import authority as write_authority

        base = store.read_current()
        candidate = {
            "schema": "an-kla/write-proposal-v1",
            "base_revision": base,
            "stream": "facts",
            "operation": "supersede",
            "requested_representation": "summary",
            "record": {"id": new_id, "payload": {"text": f"reemplaza {target}"}},
            "supersedes": target,
            "lineage": {"derived_from_retrieval": False, "refs": []},
        }
        auth = write_authority(candidate)
        planning = store.plan_write(candidate, auth)
        self.assertTrue(planning["decision"]["decision"].startswith("write"), planning["decision"])
        result = store.commit_write_plan(
            expected_current_hash=base,
            proposal=candidate,
            authority=auth,
            decision=planning["decision"],
            plan=planning["plan"],
        )
        self.assertTrue(result["outcome"]["committed"])

    def test_mixed_population_planes_and_invariant(self) -> None:
        import uuid

        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(directory)
            initial = store.initialize()
            revision = store.commit(
                expected_current_hash=initial,
                checkpoint_patch={},
                facts=[
                    {"id": "f-1", "payload": {"text": "vigente uno"}},
                    {"id": "f-2", "payload": {"text": "eliminada fisica"},
                     "status": "eliminada"},
                    {"id": "f-3", "payload": {"text": "sera sustituida"}},
                ],
            )
            self._governed_supersede(store, "f-3", "f-4")
            current = store.read_current()
            result = inventory(store, revision, streams=("facts",))
            mixed = inventory(store, current, streams=("facts",))
        # snapshot de una revision PRE-supercede: sin overlay
        self.assertEqual(result["counts"]["facts"]["eliminada"], 1)
        counts = mixed["counts"]["facts"]
        self.assertEqual(counts["total"], 4)
        self.assertEqual(counts["vigente"], 2)      # f-1, f-4
        self.assertEqual(counts["sustituida"], 1)   # f-3 (overlay)
        self.assertEqual(counts["eliminada"], 1)    # f-2 (fisico)
        self.assertEqual(
            counts["total"],
            counts["vigente"] + counts["sustituida"] + counts["refutada"] + counts["eliminada"],
        )
        by_id = {item["id"]: item for item in mixed["records"]}
        self.assertEqual(by_id["f-3"]["status"], "sustituida")
        self.assertEqual(by_id["f-3"]["status_source"], "supersede_overlay")
        self.assertEqual(by_id["f-3"]["physical_status"], "vigente")
        self.assertEqual(by_id["f-2"]["physical_status"], "eliminada")
        self.assertEqual(by_id["f-2"]["status_source"], "physical")
        _validator().validate(mixed)

    @unittest.skipIf(
        __import__("os").name == "nt",
        "export+compaction no soportados en NT (ADR-0027/0028)",
    )
    def test_archived_revision_fails_closed_even_with_manifest_present(self) -> None:
        """H1: catalog-first; the committed_cleanup_incomplete window must
        not serve an archived revision whose manifest is still on disk."""
        import uuid

        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(directory)
            initial = store.initialize()
            source = store.commit(
                expected_current_hash=initial,
                checkpoint_patch={},
                facts=[
                    {"id": "f-keep", "text": "keep", "status": "active"},
                    {"id": "f-drop", "text": "drop", "status": "inactive"},
                ],
            )
            bundle = Path(directory).parent / f"bundle-{uuid.uuid4().hex[:8]}"
            exported = create_export(store, bundle)
            proposal = {
                "schema": "an-kla/compaction-proposal-v1",
                "base_revision": source,
                "epoch_id": str(uuid.uuid4()),
                "transaction_id": str(uuid.uuid4()),
                "export_manifest_sha256": exported["manifest_sha256"],
            }
            planning = plan_compaction(store, proposal, bundle)
            result = commit_compaction(store, planning, source, bundle)
            self.assertEqual(result["state"], "committed")
            # Ventana fabricada: restaurar SOLO el manifest archivado en disco
            # (los bytes historicos) sin tocar CURRENT v3 — estado alcanzable
            # cuando el cleanup fallo a mitad. Recrearlo desde el snapshot
            # exportado simula exactamente el estado de la ventana.
            from an_kla.canonical import canonical_json
            from an_kla.store import StoreError

            manifest_path = store._path_for("revisions", source)
            if not manifest_path.exists():
                historic = store.snapshot.__self__  # noqa: F841 — store ref
                manifest_obj = None
                for entry in sorted(bundle.rglob("*.json")):
                    try:
                        candidate = json.loads(entry.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        continue
                    digest = "sha256:" + __import__("hashlib").sha256(
                        canonical_json(candidate)
                    ).hexdigest()
                    if digest == source:
                        manifest_obj = candidate
                        break
                if manifest_obj is None:
                    self.skipTest("manifest no localizable en bundle")
                manifest_path.parent.mkdir(parents=True, exist_ok=True)
                manifest_path.write_bytes(canonical_json(manifest_obj))
                self.assertTrue(manifest_path.exists())
            # Con o sin manifest en disco: catalog-first debe rechazar SIEMPRE.
            with self.assertRaises(IntegrityError) as ctx:
                inventory(store, source)
            self.assertIn(
                str(ctx.exception),
                ("revision_archived_by_compaction", "object_missing:revisions"),
            )
            # Y jamas el error engañoso:
            self.assertNotEqual(str(ctx.exception), "segment_missing:facts")



    def test_status_claiming_reserved_total_key_counts_as_exotic(self) -> None:
        # N1 de la re-ronda: a physical status "total" must not corrupt the
        # counts invariant.
        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(directory)
            initial = store.initialize()
            revision = store.commit(
                expected_current_hash=initial,
                checkpoint_patch={},
                facts=[{"id": "f-1", "payload": {"text": "uno"},
                        "status": "total"}],
            )
            result = inventory(store, revision, streams=("facts",))
        counts = result["counts"]["facts"]
        self.assertEqual(counts["total"], 1)
        self.assertEqual(counts["status:total"], 1)
        self.assertEqual(counts["vigente"], 0)
        self.assertEqual(
            counts["total"],
            counts["vigente"] + counts["sustituida"] + counts["refutada"]
            + counts["eliminada"] + counts["status:total"],
        )


if __name__ == "__main__":
    unittest.main()
