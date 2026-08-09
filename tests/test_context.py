from __future__ import annotations

import json
from datetime import datetime, timezone
import tempfile
import unittest
from unittest.mock import patch

from an_kla.canonical import canonical_json
from an_kla.context import ASSEMBLY_PROFILE, ASSEMBLY_PROFILE_V2, assemble_context
from an_kla.retrieval import retrieve
from an_kla.store import MemoryStore


class ContextAssemblyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(self.temp.name)
        root = self.store.initialize()
        self.revision = self.store.commit(
            expected_current_hash=root,
            checkpoint_patch={},
            facts=[
                {
                    "id": "f-001",
                    "payload": {"text": "memoria ágil"},
                    "verified_at": "2026-08-01T00:00:00Z",
                },
                {"id": "f-002", "payload": {"text": "memoria extensa " * 20}},
                {"id": "f-003", "payload": {"text": "distractor"}},
            ],
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_global_budget_measures_the_complete_utf8_envelope(self) -> None:
        result = assemble_context(
            self.store,
            "memoria",
            700,
            new_information="entrada nueva ñ",
        )
        encoded = canonical_json(result)
        self.assertEqual(result["profile"], ASSEMBLY_PROFILE)
        self.assertEqual(result["canonicalization"], "canonical-json/v1")
        self.assertEqual(result["used_bytes"], len(encoded))
        self.assertLessEqual(len(encoded), 700)
        self.assertEqual(
            result["sections"]["working_state"], self.store.snapshot().checkpoint
        )
        self.assertEqual(result["sections"]["new_information"], "entrada nueva ñ")
        self.assertTrue(result["host_framing_unmeasured"])
        self.assertEqual(result["section_provenance"]["working_state"], "memory_store")
        self.assertEqual(result["section_provenance"]["new_information"], "caller")

    def test_assembly_is_bound_to_one_immutable_revision(self) -> None:
        result = assemble_context(self.store, "memoria", 1000)
        self.assertEqual(result["revision"], self.revision)
        self.assertEqual(
            result["sections"]["working_state"],
            self.store.snapshot(result["revision"]).checkpoint,
        )

    def test_current_move_does_not_mix_revisions(self) -> None:
        original_retrieve = retrieve

        def retrieve_then_commit(store, query, budget):
            result = original_retrieve(store, query, budget)
            store.commit(
                expected_current_hash=result["revision"],
                checkpoint_patch={},
                facts=[{"id": "f-later", "payload": {"text": "memoria posterior"}}],
            )
            return result

        with patch("an_kla.context.retrieve", side_effect=retrieve_then_commit):
            result = assemble_context(self.store, "memoria", 1000)
        self.assertEqual(result["revision"], self.revision)
        self.assertEqual(
            result["sections"]["working_state"],
            self.store.snapshot(result["revision"]).checkpoint,
        )
        self.assertNotIn(
            "f-later",
            {record["id"] for record in result["sections"]["retrieved_records"]},
        )

    def test_required_sections_fail_closed_instead_of_truncating(self) -> None:
        with self.assertRaisesRegex(ValueError, "budget_too_small_for_required_context"):
            assemble_context(self.store, "memoria", 100, new_information="ñ" * 100)

    def test_diagnostic_growth_does_not_evict_without_reconsideration(self) -> None:
        lengths = [
            39,
            102,
            167,
            13,
            19,
            211,
            138,
            25,
            94,
            150,
            15,
            233,
            130,
            55,
            10,
            23,
            112,
            108,
        ]
        with tempfile.TemporaryDirectory() as root:
            store = MemoryStore(root)
            initial = store.initialize()
            store.commit(
                expected_current_hash=initial,
                checkpoint_patch={},
                facts=[
                    {
                        "id": f"f-{index:03}",
                        "payload": {"text": "memoria " + "x" * length},
                    }
                    for index, length in enumerate(lengths)
                ],
            )
            result = assemble_context(store, "memoria", 667)
        selected = {
            item["id"] for item in result["sections"]["retrieved_records"]
        }
        self.assertIn("f-014", selected)
        self.assertLessEqual(result["used_bytes"], 667)

    def test_output_is_canonical_json_serializable(self) -> None:
        result = assemble_context(self.store, "memoria", 900)
        self.assertEqual(json.loads(canonical_json(result)), result)

    def test_v2_copies_retrieval_projection_and_measures_complete_payload(self) -> None:
        now = datetime(2026, 8, 8, tzinfo=timezone.utc)
        result = assemble_context(
            self.store,
            "memoria ágil",
            1200,
            freshness_profile="computed-age/v1",
            now=now,
            stale_after_days=6,
        )
        self.assertEqual(result["schema"], "an-kla/context-assembly-v2")
        self.assertEqual(result["profile"], ASSEMBLY_PROFILE_V2)
        self.assertTrue(result["untrusted_memory_data"])
        self.assertEqual(result["used_bytes"], len(canonical_json(result)))
        records = result["sections"]["retrieved_records"]
        projected = next(item for item in records if item["id"] == "f-001")
        self.assertEqual(projected["verified_at"], "2026-08-01T00:00:00Z")
        self.assertEqual(projected["days_since_verified"], 7)
        self.assertTrue(projected["stale"])

    def test_v2_budget_can_evict_record_without_residual_projection(self) -> None:
        found = None
        for budget in range(400, 1201):
            try:
                v1 = assemble_context(self.store, "ágil", budget)
                v2 = assemble_context(
                    self.store,
                    "ágil",
                    budget,
                    freshness_profile="computed-age/v1",
                    now=datetime(2026, 8, 8, tzinfo=timezone.utc),
                )
            except ValueError:
                continue
            if v1["sections"]["retrieved_records"] and not v2["sections"]["retrieved_records"]:
                found = (budget, v2)
                break
        self.assertIsNotNone(found)
        budget, v2 = found
        self.assertIn("freshness", v2)
        self.assertEqual(v2["sections"]["retrieved_records"], [])
        self.assertEqual(v2["excluded_summary"]["budget"], 1)
        self.assertFalse(any(key in v2 for key in (
            "verified_at", "days_since_verified", "stale", "freshness_error"
        )))
        self.assertEqual(v2["used_bytes"], len(canonical_json(v2)))
        self.assertLessEqual(v2["used_bytes"], budget)


if __name__ == "__main__":
    unittest.main()
