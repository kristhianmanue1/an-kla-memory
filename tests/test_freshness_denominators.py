"""G-FRESH (#50 / ADR-0037): denominadores del bloque freshness."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from types import SimpleNamespace
import tempfile
import unittest

from an_kla.canonical import canonical_json, exact_sized_payload
from an_kla.context import assemble_context
from an_kla.mcp import ReadOnlyMcp
from an_kla.retrieval import retrieve
from an_kla.store import MemoryStore
from an_kla.temporal import (
    FRESHNESS_PROFILE,
    TemporalError,
    summarize_freshness,
)
from an_kla.schemas import schema_bytes, schema_names


REVISION = "sha256:" + "a" * 64
NOW = datetime(2026, 8, 8, tzinfo=timezone.utc)


class StubStore:
    """Five records: 1 evaluated, 1 unparseable, 3 not evaluable."""

    def __init__(self) -> None:
        self.records = (
            {"id": "f-valid", "indexable_text": "needle valid", "verified_at": "2026-08-01T00:00:00Z"},
            {"id": "f-invalid", "indexable_text": "needle invalid", "verified_at": "opaque-beta8"},
            {"id": "f-null", "indexable_text": "needle null", "verified_at": None},
            {"id": "f-nonstr", "indexable_text": "needle number", "verified_at": 7},
            {"id": "f-missing", "indexable_text": "needle missing"},
        )

    def snapshot(self) -> SimpleNamespace:
        return SimpleNamespace(
            revision_id=REVISION,
            records={"facts": self.records, "events": (), "episodes": ()},
        )


class SummarizeFreshnessTests(unittest.TestCase):
    def test_states_are_total_and_mutually_exclusive(self) -> None:
        items = [
            {"days_since_verified": 7},
            {"days_since_verified": 0, "stale": False},
            {"freshness_error": "unparseable_verified_at"},
            {"freshness_error": "unrepresentable_verified_at"},
            {},
        ]
        self.assertEqual(
            summarize_freshness(items),
            {"evaluated": 2, "not_evaluable": 1, "unparseable": 2, "stale": 0},
        )

    def test_stale_is_subset_of_evaluated(self) -> None:
        items = [
            {"days_since_verified": 9, "stale": True},
            {"days_since_verified": 1},
            {},
        ]
        summary = summarize_freshness(items)
        self.assertEqual(summary["stale"], 1)
        self.assertLessEqual(summary["stale"], summary["evaluated"])
        self.assertEqual(
            summary["evaluated"] + summary["not_evaluable"] + summary["unparseable"],
            len(items),
        )

    def test_empty_population_counts_zero(self) -> None:
        self.assertEqual(
            summarize_freshness([]),
            {"evaluated": 0, "not_evaluable": 0, "unparseable": 0, "stale": 0},
        )


class RetrieveDenominatorTests(unittest.TestCase):
    def test_counts_describe_full_selection(self) -> None:
        result = retrieve(
            StubStore(),  # type: ignore[arg-type]
            "needle",
            10_000,
            freshness_profile=FRESHNESS_PROFILE,
            now=NOW,
            stale_after_days=6,
        )
        self.assertEqual(
            result["freshness"],
            {
                "semantics": "self_asserted_timestamp",
                "source_field": "record.verified_at",
                "computed_at": "2026-08-08T00:00:00.000000Z",
                "stale_after_days": 6,
                "evaluated": 1,
                "not_evaluable": 3,
                "unparseable": 1,
                "stale": 1,
            },
        )
        self.assertEqual(len(result["selected"]), 5)

    def test_counts_describe_final_selection_after_budget_cut(self) -> None:
        # Budget that only admits a prefix of the alphabetical ranking:
        # f-invalid, f-missing, ... (score 1, id order).
        result = retrieve(
            StubStore(),  # type: ignore[arg-type]
            "needle",
            30,
            freshness_profile=FRESHNESS_PROFILE,
            now=NOW,
            stale_after_days=6,
        )
        selected_ids = [item["id"] for item in result["selected"]]
        self.assertLess(len(selected_ids), 5)
        freshness = result["freshness"]
        self.assertEqual(
            freshness["evaluated"]
            + freshness["not_evaluable"]
            + freshness["unparseable"],
            len(result["selected"]),
        )
        # The counts must reflect only what was served.
        expected = summarize_freshness(result["selected"])
        for key in ("evaluated", "not_evaluable", "unparseable", "stale"):
            self.assertEqual(freshness[key], expected[key], key)

    def test_v1_payloads_remain_unchanged(self) -> None:
        result = retrieve(StubStore(), "needle", 10_000)  # type: ignore[arg-type]
        self.assertNotIn("freshness", result)
        self.assertEqual(result["schema"], "an-kla/retrieval-result-v1")

    def test_empty_selection_counts_zero(self) -> None:
        result = retrieve(
            StubStore(),  # type: ignore[arg-type]
            "no-matching-term",
            10_000,
            freshness_profile=FRESHNESS_PROFILE,
            now=NOW,
        )
        self.assertEqual(result["selected"], [])
        self.assertEqual(
            result["freshness"],
            {
                "semantics": "self_asserted_timestamp",
                "source_field": "record.verified_at",
                "computed_at": "2026-08-08T00:00:00.000000Z",
                "stale_after_days": None,
                "evaluated": 0,
                "not_evaluable": 0,
                "unparseable": 0,
                "stale": 0,
            },
        )

    def test_all_unparseable_corpus_declares_itself(self) -> None:
        class UnparseableStore(StubStore):
            def __init__(self) -> None:
                super().__init__()
                self.records = tuple(
                    {**record, "verified_at": "opaque-beta8"}
                    for record in self.records
                )

        result = retrieve(
            UnparseableStore(),  # type: ignore[arg-type]
            "needle",
            10_000,
            freshness_profile=FRESHNESS_PROFILE,
            now=NOW,
        )
        self.assertEqual(len(result["selected"]), 5)
        self.assertEqual(result["freshness"]["unparseable"], 5)
        self.assertEqual(result["freshness"]["evaluated"], 0)
        self.assertEqual(result["freshness"]["stale"], 0)

    def test_minimum_v2_envelope_boundary_is_pinned(self) -> None:
        # The four count integers enlarge the freshness block; pin the
        # minimum envelope so silent growth fails loudly (ADR-0037 limit).
        result = retrieve(
            StubStore(),  # type: ignore[arg-type]
            "no-matching-term",
            10_000,
            freshness_profile=FRESHNESS_PROFILE,
            now=NOW,
        )
        _payload, measured = exact_sized_payload(lambda used=0: result)
        self.assertLessEqual(measured, 800)
        self.assertGreaterEqual(measured, 720)


class _TempStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        store = MemoryStore(self.temp.name)
        root = store.initialize()
        store.commit(
            expected_current_hash=root,
            checkpoint_patch={},
            facts=[
                {
                    "id": "f-001",
                    "verified_at": "2026-08-01T00:00:00Z",
                    "payload": {"text": "memoria ágil"},
                },
                {"id": "f-002", "payload": {"text": "memoria sin fecha"}},
                {"id": "f-003", "payload": {"text": "memoria también sin fecha"}},
            ],
        )
        self.store = store

    def tearDown(self) -> None:
        self.temp.cleanup()


class ContextDenominatorTests(_TempStoreTest):
    def test_assembly_recomputes_counts_after_global_budget_cut(self) -> None:
        payload = assemble_context(
            self.store,
            "memoria",
            10_000,
            freshness_profile=FRESHNESS_PROFILE,
            now=NOW,
            stale_after_days=3,
        )
        served = payload["sections"]["retrieved_records"]
        self.assertEqual(len(served), 3)
        self.assertEqual(
            payload["freshness"],
            {
                "semantics": "self_asserted_timestamp",
                "source_field": "record.verified_at",
                "computed_at": "2026-08-08T00:00:00.000000Z",
                "stale_after_days": 3,
                "evaluated": 1,
                "not_evaluable": 2,
                "unparseable": 0,
                "stale": 1,
            },
        )

    def test_tight_budget_counts_only_served_records(self) -> None:
        # Force the assembly to drop records: budget barely above the
        # required sections.
        probe = assemble_context(
            self.store,
            "memoria",
            10_000,
            freshness_profile=FRESHNESS_PROFILE,
            now=NOW,
        )
        full_size = exact_sized_payload(lambda used=0: probe)[1]
        tight = full_size - 60
        payload = assemble_context(
            self.store,
            "memoria",
            tight,
            freshness_profile=FRESHNESS_PROFILE,
            now=NOW,
        )
        served = payload["sections"]["retrieved_records"]
        self.assertLess(len(served), 3)
        freshness = payload["freshness"]
        self.assertEqual(
            freshness["evaluated"]
            + freshness["not_evaluable"]
            + freshness["unparseable"],
            len(served),
        )
        expected = summarize_freshness(served)
        for key in ("evaluated", "not_evaluable", "unparseable", "stale"):
            self.assertEqual(freshness[key], expected[key], key)


class McpDenominatorTests(_TempStoreTest):
    def setUp(self) -> None:
        super().setUp()
        self.server = ReadOnlyMcp(self.temp.name)
        self.server.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-11-25"},
            }
        )
        self.server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _retrieve(self, budget: int) -> dict:
        response = self.server.handle(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "an_kla_retrieve",
                    "arguments": {
                        "query": "memoria",
                        "budget_bytes": budget,
                        "freshness_profile": FRESHNESS_PROFILE,
                        "now": "2026-08-08T00:00:00Z",
                        "stale_after_days": 3,
                    },
                },
            }
        )
        self.assertFalse(response["result"]["isError"])
        return json.loads(response["result"]["content"][0]["text"])

    def test_mcp_counts_cover_served_records(self) -> None:
        payload = self._retrieve(4_000)
        self.assertEqual(len(payload["records"]), 3)
        self.assertEqual(
            payload["freshness"],
            {
                "semantics": "self_asserted_timestamp",
                "source_field": "record.verified_at",
                "computed_at": "2026-08-08T00:00:00.000000Z",
                "stale_after_days": 3,
                "evaluated": 1,
                "not_evaluable": 2,
                "unparseable": 0,
                "stale": 1,
            },
        )

    def test_mcp_recomputes_counts_after_envelope_cut(self) -> None:
        payload = self._retrieve(4_000)
        tight = len(canonical_json(payload)) - 70
        cut = self._retrieve(tight)
        self.assertLess(len(cut["records"]), 3)
        freshness = cut["freshness"]
        self.assertEqual(
            freshness["evaluated"]
            + freshness["not_evaluable"]
            + freshness["unparseable"],
            len(cut["records"]),
        )
        expected = summarize_freshness(cut["records"])
        for key in ("evaluated", "not_evaluable", "unparseable", "stale"):
            self.assertEqual(freshness[key], expected[key], key)


class SchemaContractTests(unittest.TestCase):
    @staticmethod
    def _freshness_schema(document: dict) -> dict | None:
        defs = document.get("$defs", {})
        node = defs.get("freshness") if isinstance(defs, dict) else None
        if isinstance(node, dict):
            return node
        node = document.get("properties", {}).get("freshness")
        if isinstance(node, dict) and "$ref" not in node and "oneOf" not in node:
            return node
        return None

    def test_freshness_blocks_validate_against_packaged_schemas(self) -> None:
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema unavailable")
        freshness = {
            "semantics": "self_asserted_timestamp",
            "source_field": "record.verified_at",
            "computed_at": "2026-08-08T00:00:00.000000Z",
            "stale_after_days": 3,
            "evaluated": 1,
            "not_evaluable": 2,
            "unparseable": 0,
            "stale": 1,
        }
        counted_contracts = {
            "retrieval-result-v2",
            "context-assembly-v2",
            "mcp-retrieve-v2",
        }
        for name in counted_contracts:
            document = json.loads(schema_bytes(name))
            freshness_schema = self._freshness_schema(document)
            self.assertIsInstance(freshness_schema, dict, name)
            with self.subTest(schema=name):
                Draft202012Validator(freshness_schema).validate(freshness)

    def test_view_contract_keeps_denominator_free_freshness(self) -> None:
        # ADR-0037 defers view denominators: its freshness block must keep
        # rejecting the count fields until a dedicated decision extends it.
        try:
            from jsonschema import Draft202012Validator
            from jsonschema.exceptions import ValidationError
        except ImportError:
            self.skipTest("jsonschema unavailable")
        document = json.loads(schema_bytes("context-view-v1"))
        freshness_schema = self._freshness_schema(document)
        self.assertIsInstance(freshness_schema, dict)
        with self.assertRaises(ValidationError):
            Draft202012Validator(freshness_schema).validate(
                {
                    "semantics": "self_asserted_timestamp",
                    "source_field": "record.verified_at",
                    "computed_at": "2026-08-08T00:00:00.000000Z",
                    "stale_after_days": None,
                    "evaluated": 0,
                }
            )

    def test_missing_counts_fail_schema_validation(self) -> None:
        try:
            from jsonschema import Draft202012Validator
            from jsonschema.exceptions import ValidationError
        except ImportError:
            self.skipTest("jsonschema unavailable")
        document = json.loads(schema_bytes("retrieval-result-v2"))
        freshness_schema = document["properties"]["freshness"]
        validator = Draft202012Validator(freshness_schema)
        with self.assertRaises(ValidationError):
            validator.validate(
                {
                    "semantics": "self_asserted_timestamp",
                    "source_field": "record.verified_at",
                    "computed_at": "2026-08-08T00:00:00.000000Z",
                    "stale_after_days": None,
                }
            )


if __name__ == "__main__":
    unittest.main()
