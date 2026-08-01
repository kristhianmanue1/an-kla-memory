from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch

from an_kla.canonical import canonical_json
from an_kla.context import ASSEMBLY_PROFILE, assemble_context
from an_kla.retrieval import retrieve
from an_kla.store import MemoryStore


class ContextAssemblyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(self.temp.name)
        root = self.store.initialize()
        self.revision = self.store.commit(
            expected_current_hash=root,
            checkpoint_patch={"goal": "decidir ágilmente", "next": "validar"},
            facts=[
                {"id": "f-001", "payload": {"text": "memoria ágil"}},
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
        self.assertEqual(result["used_bytes"], len(encoded))
        self.assertLessEqual(len(encoded), 700)
        self.assertEqual(result["sections"]["working_state"]["goal"], "decidir ágilmente")
        self.assertEqual(result["sections"]["new_information"], "entrada nueva ñ")
        self.assertTrue(result["host_framing_unmeasured"])

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
                checkpoint_patch={"goal": "objetivo posterior"},
                facts=[{"id": "f-later", "payload": {"text": "memoria posterior"}}],
            )
            return result

        with patch("an_kla.context.retrieve", side_effect=retrieve_then_commit):
            result = assemble_context(self.store, "memoria", 1000)
        self.assertEqual(result["revision"], self.revision)
        self.assertEqual(
            result["sections"]["working_state"]["goal"], "decidir ágilmente"
        )
        self.assertNotIn(
            "f-later",
            {record["id"] for record in result["sections"]["retrieved_records"]},
        )

    def test_required_sections_fail_closed_instead_of_truncating(self) -> None:
        with self.assertRaisesRegex(ValueError, "budget_too_small_for_required_context"):
            assemble_context(self.store, "memoria", 100, new_information="ñ" * 100)

    def test_output_is_canonical_json_serializable(self) -> None:
        result = assemble_context(self.store, "memoria", 900)
        self.assertEqual(json.loads(canonical_json(result)), result)


if __name__ == "__main__":
    unittest.main()
