from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from an_kla import VERSION
from an_kla.canonical import canonical_json, exact_sized_payload
from an_kla.context import ASSEMBLY_PROFILE
from an_kla.mcp import PROTOCOL_VERSION, ReadOnlyMcp, _safe_error
from an_kla.retrieval import retrieve
from an_kla.store import MemoryStore, StoreError
from an_kla.temporal import FRESHNESS_PROFILE, FRESHNESS_PROJECTION_KEYS


class McpProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        store = MemoryStore(self.temp.name)
        root = store.initialize()
        store.commit(expected_current_hash=root, checkpoint_patch={}, facts=[
            {
                "id": "f-001",
                "verified_at": "2026-08-01T00:00:00Z",
                "payload": {"text": "memoria ágil"},
            },
            {"id": "f-002", "payload": {"text": "distractor"}},
        ])
        self.server = ReadOnlyMcp(self.temp.name)
        self._initialize(self.server)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _call(self, name: str, arguments: object) -> tuple[dict, dict]:
        response = self.server.handle({
            "jsonrpc": "2.0",
            "id": name,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        })
        return response, json.loads(response["result"]["content"][0]["text"])

    @staticmethod
    def _initialize(server: ReadOnlyMcp, version: str = PROTOCOL_VERSION) -> dict:
        response = server.handle({"jsonrpc":"2.0", "id":1, "method":"initialize", "params":{"protocolVersion":version}})
        server.handle({"jsonrpc":"2.0", "method":"notifications/initialized"})
        return response

    def test_initialize_negotiates_the_supported_protocol(self) -> None:
        server = ReadOnlyMcp(self.temp.name)
        ok = self._initialize(server)
        self.assertEqual(ok["result"]["protocolVersion"], PROTOCOL_VERSION)
        self.assertEqual(ok["result"]["serverInfo"]["version"], VERSION)
        fallback_server = ReadOnlyMcp(self.temp.name)
        fallback = self._initialize(fallback_server, "1999-01-01")
        self.assertEqual(fallback["result"]["protocolVersion"], PROTOCOL_VERSION)

    def test_tools_are_gated_until_initialized_notification(self) -> None:
        server = ReadOnlyMcp(self.temp.name)
        before = server.handle({"jsonrpc":"2.0", "id":1, "method":"tools/list"})
        self.assertEqual(before["error"]["message"], "server_not_initialized")
        response = server.handle({"jsonrpc":"2.0", "id":2, "method":"initialize", "params":{"protocolVersion":"1999-01-01"}})
        self.assertEqual(response["result"]["protocolVersion"], PROTOCOL_VERSION)
        negotiated_only = server.handle({"jsonrpc":"2.0", "id":3, "method":"tools/list"})
        self.assertEqual(negotiated_only["error"]["message"], "server_not_initialized")
        server.handle({"jsonrpc":"2.0", "method":"notifications/initialized"})
        listed = server.handle({"jsonrpc":"2.0", "id":4, "method":"tools/list"})
        self.assertIn("tools", listed["result"])

    def test_lists_only_read_tools_and_ignores_all_notifications(self) -> None:
        listed = self.server.handle({"jsonrpc":"2.0", "id":1, "method":"tools/list"})
        names = {tool["name"] for tool in listed["result"]["tools"]}
        self.assertIn("an_kla_retrieve", names)
        self.assertIn("an_kla_assemble_context", names)
        self.assertFalse(any("write" in name or "commit" in name for name in names))
        self.assertIsNone(self.server.handle({"jsonrpc":"2.0", "method":"notifications/cancelled"}))
        self.assertIsNone(self.server.handle({"jsonrpc":"2.0", "method":"unknown_without_id"}))

    def test_temporal_tool_input_schemas_are_closed_and_exact(self) -> None:
        listed = self.server.handle({"jsonrpc":"2.0", "id":1, "method":"tools/list"})
        by_name = {tool["name"]: tool for tool in listed["result"]["tools"]}
        retrieve_schema = by_name["an_kla_retrieve"]["inputSchema"]
        context_schema = by_name["an_kla_assemble_context"]["inputSchema"]
        self.assertFalse(retrieve_schema["additionalProperties"])
        self.assertFalse(context_schema["additionalProperties"])
        self.assertEqual(
            set(retrieve_schema["properties"]),
            {"query", "budget_bytes", "freshness_profile", "now", "stale_after_days"},
        )
        self.assertEqual(
            set(context_schema["properties"]),
            {"query", "budget_bytes", "new_information", "freshness_profile", "now", "stale_after_days"},
        )
        self.assertEqual(
            retrieve_schema["properties"]["freshness_profile"]["enum"],
            [FRESHNESS_PROFILE],
        )

    def test_empty_tool_schemas_are_enforced_at_runtime(self) -> None:
        for name in (
            "an_kla_status",
            "an_kla_verify",
            "an_kla_doctor",
            "an_kla_get_checkpoint",
        ):
            with self.subTest(name=name):
                response, payload = self._call(name, {"unexpected": True})
                self.assertTrue(response["result"]["isError"])
                self.assertEqual(payload, {"error": "invalid_tool_arguments"})

    def test_tool_dispatch_measures_model_content_not_jsonrpc_transport(self) -> None:
        response = self.server.handle({"jsonrpc":"2.0", "id":3, "method":"tools/call", "params":{"name":"an_kla_retrieve", "arguments":{"query":"memoria", "budget_bytes":400}}})
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertLessEqual(len(response["result"]["content"][0]["text"].encode("utf-8")), 400)
        self.assertEqual(payload["used_bytes"], len(response["result"]["content"][0]["text"].encode("utf-8")))
        self.assertTrue(payload["host_framing_unmeasured"])

    def test_mcp_retrieve_v2_preserves_projection_and_exact_budget(self) -> None:
        response, payload = self._call(
            "an_kla_retrieve",
            {
                "query": "memoria",
                "budget_bytes": 900,
                "freshness_profile": FRESHNESS_PROFILE,
                "now": "2026-08-08T00:00:00Z",
                "stale_after_days": 3,
            },
        )
        self.assertFalse(response["result"]["isError"])
        text = response["result"]["content"][0]["text"]
        self.assertEqual(payload["schema"], "an-kla/mcp-retrieve-v2")
        self.assertEqual(payload["freshness_profile"], FRESHNESS_PROFILE)
        self.assertEqual(payload["freshness"]["semantics"], "self_asserted_timestamp")
        self.assertEqual(payload["freshness"]["source_field"], "record.verified_at")
        self.assertEqual(payload["used_bytes"], len(text.encode("utf-8")))
        self.assertLessEqual(payload["used_bytes"], 900)
        record = next(item for item in payload["records"] if item["id"] == "f-001")
        self.assertEqual(record["verified_at"], "2026-08-01T00:00:00Z")
        self.assertEqual(record["days_since_verified"], 7)
        self.assertTrue(record["stale"])

    def test_mcp_context_v2_remains_untrusted_and_preserves_projection(self) -> None:
        response, payload = self._call(
            "an_kla_assemble_context",
            {
                "query": "memoria",
                "budget_bytes": 1200,
                "freshness_profile": FRESHNESS_PROFILE,
                "now": "2026-08-08T00:00:00Z",
            },
        )
        self.assertFalse(response["result"]["isError"])
        self.assertEqual(payload["schema"], "an-kla/context-assembly-v2")
        self.assertTrue(payload["untrusted_memory_data"])
        record = payload["sections"]["retrieved_records"][0]
        self.assertEqual(record["verified_at"], "2026-08-01T00:00:00Z")
        self.assertEqual(record["days_since_verified"], 7)

    def test_mcp_v1_payloads_have_no_temporal_keys(self) -> None:
        _response, retrieved = self._call(
            "an_kla_retrieve", {"query": "memoria", "budget_bytes": 700}
        )
        self.assertEqual(retrieved["schema"], "an-kla/mcp-retrieve-v1")
        self.assertNotIn("freshness", retrieved)
        self.assertNotIn("freshness_profile", retrieved)
        self.assertFalse(any("verified_at" in item for item in retrieved["records"]))
        _response, assembled = self._call(
            "an_kla_assemble_context", {"query": "memoria", "budget_bytes": 900}
        )
        self.assertEqual(assembled["schema"], "an-kla/context-assembly-v1")
        self.assertNotIn("freshness", assembled)
        self.assertNotIn("freshness_profile", assembled)

    def test_v1_wrapper_payloads_are_byte_golden_and_never_read_clock(self) -> None:
        class ClockBomb:
            @classmethod
            def now(cls, _zone):
                raise AssertionError("v1_wrapper_must_not_read_clock")

        with tempfile.TemporaryDirectory() as root:
            store = MemoryStore(root)
            initial = store.initialize()
            revision = store.commit(
                expected_current_hash=initial,
                checkpoint_patch={},
                facts=[
                    {"id": "f-invalid", "verified_at": "opaque", "payload": {"text": "needle invalid"}},
                    {"id": "f-nonstr", "verified_at": 7, "payload": {"text": "needle number"}},
                    {"id": "f-null", "verified_at": None, "payload": {"text": "needle null"}},
                    {"id": "f-valid", "verified_at": "2026-08-01T00:00:00Z", "payload": {"text": "needle valid"}},
                ],
            )
            server = ReadOnlyMcp(root)
            records = [
                {"id": "f-invalid", "text": "needle invalid", "score": 1},
                {"id": "f-nonstr", "text": "needle number", "score": 1},
                {"id": "f-null", "text": "needle null", "score": 1},
                {"id": "f-valid", "text": "needle valid", "score": 1},
            ]

            def expected_mcp(used: int = 0) -> dict:
                return {
                    "schema": "an-kla/mcp-retrieve-v1",
                    "untrusted_memory_data": True,
                    "host_framing_unmeasured": True,
                    "revision": revision,
                    "budget_bytes": 10_000,
                    "used_bytes": used,
                    "excluded_summary": {},
                    "records": records,
                }

            expected_retrieved, _size = exact_sized_payload(expected_mcp)

            context_records = [dict(item) for item in records]

            def expected_context(used: int = 0) -> dict:
                return {
                    "schema": "an-kla/context-assembly-v1",
                    "profile": ASSEMBLY_PROFILE,
                    "canonicalization": "canonical-json/v1",
                    "untrusted_memory_data": True,
                    "host_framing_unmeasured": True,
                    "revision": revision,
                    "budget_bytes": 10_000,
                    "used_bytes": used,
                    "section_provenance": {
                        "working_state": "memory_store",
                        "new_information": "caller",
                        "retrieved_records": "memory_store",
                    },
                    "sections": {
                        "working_state": {
                            "blockers": [],
                            "decisions": [],
                            "goal": None,
                            "next": None,
                            "revision": 0,
                            "schema": "an-kla/checkpoint-v1",
                        },
                        "new_information": None,
                        "retrieved_records": context_records,
                    },
                    "excluded_summary": {},
                }

            expected_assembled, _size = exact_sized_payload(expected_context)
            with patch("an_kla.retrieval.datetime", ClockBomb):
                retrieved = server.call(
                    "an_kla_retrieve", {"query": "needle", "budget_bytes": 10_000}
                )
                assembled = server.call(
                    "an_kla_assemble_context",
                    {"query": "needle", "budget_bytes": 10_000},
                )
            self.assertEqual(canonical_json(retrieved), canonical_json(expected_retrieved))
            self.assertEqual(canonical_json(assembled), canonical_json(expected_assembled))

    def test_v2_mcp_evicts_projected_candidate_without_residual_fields(self) -> None:
        now = "2026-08-08T00:00:00Z"
        found = None
        for budget in range(300, 1001):
            try:
                v1 = self.server.call(
                    "an_kla_retrieve", {"query": "ágil", "budget_bytes": budget}
                )
                v2 = self.server.call(
                    "an_kla_retrieve",
                    {
                        "query": "ágil",
                        "budget_bytes": budget,
                        "freshness_profile": FRESHNESS_PROFILE,
                        "now": now,
                    },
                )
            except ValueError:
                continue
            if v1["records"] and not v2["records"]:
                found = (budget, v2)
                break
        self.assertIsNotNone(found)
        budget, v2 = found
        self.assertEqual(v2["schema"], "an-kla/mcp-retrieve-v2")
        self.assertIn("freshness", v2)
        self.assertEqual(v2["records"], [])
        self.assertEqual(v2["excluded_summary"]["budget"], 1)
        self.assertFalse(
            any(key in v2 for key in FRESHNESS_PROJECTION_KEYS)
        )
        self.assertEqual(v2["used_bytes"], len(canonical_json(v2)))
        self.assertLessEqual(v2["used_bytes"], budget)

    def test_mcp_projection_equals_retrieval_projection_for_common_item(self) -> None:
        now = "2026-08-08T00:00:00Z"
        direct = retrieve(
            self.server.store,
            "memoria",
            10_000,
            freshness_profile=FRESHNESS_PROFILE,
            now=datetime.fromisoformat("2026-08-08T00:00:00+00:00"),
            stale_after_days=3,
        )
        wrapped = self.server.call(
            "an_kla_retrieve",
            {
                "query": "memoria",
                "budget_bytes": 10_000,
                "freshness_profile": FRESHNESS_PROFILE,
                "now": now,
                "stale_after_days": 3,
            },
        )
        direct_item = next(item for item in direct["selected"] if item["id"] == "f-001")
        wrapped_item = next(item for item in wrapped["records"] if item["id"] == "f-001")
        self.assertEqual(
            {key: direct_item[key] for key in FRESHNESS_PROJECTION_KEYS if key in direct_item},
            {key: wrapped_item[key] for key in FRESHNESS_PROJECTION_KEYS if key in wrapped_item},
        )

    def test_temporal_argument_error_precedence_is_stable_and_safe(self) -> None:
        cases = [
            ({"query": "x", "budget_bytes": 100, "extra": 1}, "invalid_retrieve_arguments"),
            ({"query": "x", "budget_bytes": True}, "invalid_retrieve_arguments"),
            ({"query": "x", "budget_bytes": 100, "freshness_profile": 1}, "invalid_retrieve_arguments"),
            ({"query": "x", "budget_bytes": 100, "now": None}, "freshness_profile_required"),
            ({"query": "x", "budget_bytes": 100, "stale_after_days": -1}, "freshness_profile_required"),
            ({"query": "x", "budget_bytes": 100, "freshness_profile": "unknown", "now": None}, "unsupported_freshness_profile"),
            ({"query": "x", "budget_bytes": 100, "freshness_profile": FRESHNESS_PROFILE, "now": None}, "invalid_freshness_now"),
            ({"query": "x", "budget_bytes": 100, "freshness_profile": FRESHNESS_PROFILE, "now": "2026-08-08T00:00:00"}, "invalid_freshness_now"),
            ({"query": "x", "budget_bytes": 100, "freshness_profile": FRESHNESS_PROFILE, "stale_after_days": True}, "invalid_stale_after_days"),
            ({"query": "x", "budget_bytes": 100, "freshness_profile": FRESHNESS_PROFILE, "stale_after_days": -1}, "invalid_stale_after_days"),
        ]
        for arguments, expected in cases:
            with self.subTest(arguments=arguments):
                response, payload = self._call("an_kla_retrieve", arguments)
                self.assertTrue(response["result"]["isError"])
                self.assertEqual(payload, {"error": expected})

    def test_context_temporal_argument_errors_are_surface_specific(self) -> None:
        cases = [
            ({"query": "x", "budget_bytes": 100, "new_information": None}, "invalid_context_arguments"),
            ({"query": "x", "budget_bytes": 100, "extra": 1}, "invalid_context_arguments"),
            ({"query": "x", "budget_bytes": 100, "now": "bad"}, "freshness_profile_required"),
            ({"query": "x", "budget_bytes": 100, "freshness_profile": "unknown"}, "unsupported_freshness_profile"),
            ({"query": "x", "budget_bytes": 100, "freshness_profile": FRESHNESS_PROFILE, "stale_after_days": None}, "invalid_stale_after_days"),
        ]
        for arguments, expected in cases:
            with self.subTest(arguments=arguments):
                response, payload = self._call("an_kla_assemble_context", arguments)
                self.assertTrue(response["result"]["isError"])
                self.assertEqual(payload, {"error": expected})

    def test_unknown_tool_is_tool_error_and_errors_are_fail_closed(self) -> None:
        response = self.server.handle({"jsonrpc":"2.0", "id":4, "method":"tools/call", "params":{"name":"evil", "arguments":{}}})
        self.assertTrue(response["result"]["isError"])
        self.assertEqual(json.loads(response["result"]["content"][0]["text"])["error"], "unknown_tool")
        self.assertEqual(_safe_error(StoreError("/Users/name/private")), "internal_error")

    def test_context_assembly_measures_the_complete_model_content(self) -> None:
        response = self.server.handle({"jsonrpc":"2.0", "id":5, "method":"tools/call", "params":{"name":"an_kla_assemble_context", "arguments":{"query":"memoria", "budget_bytes":700, "new_information":"dato ñ"}}})
        self.assertFalse(response["result"]["isError"])
        text = response["result"]["content"][0]["text"]
        payload = json.loads(text)
        self.assertEqual(payload["used_bytes"], len(text.encode("utf-8")))
        self.assertLessEqual(payload["used_bytes"], 700)
        self.assertEqual(payload["sections"]["new_information"], "dato ñ")
        self.assertEqual(payload["section_provenance"]["new_information"], "caller")
        self.assertEqual(payload["section_provenance"]["working_state"], "memory_store")

    def test_context_assembly_budget_failure_is_a_stable_tool_error(self) -> None:
        response = self.server.handle({"jsonrpc":"2.0", "id":6, "method":"tools/call", "params":{"name":"an_kla_assemble_context", "arguments":{"query":"memoria", "budget_bytes":1}}})
        self.assertTrue(response["result"]["isError"])
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(payload["error"], "budget_too_small_for_required_context")

    def test_all_mcp_reads_leave_the_memory_tree_byte_identical(self) -> None:
        def files() -> dict[str, bytes]:
            root = Path(self.temp.name)
            return {
                str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }

        before = files()
        calls = [
            ("an_kla_status", {}),
            ("an_kla_verify", {}),
            ("an_kla_doctor", {}),
            ("an_kla_get_checkpoint", {}),
            ("an_kla_retrieve", {"query": "memoria", "budget_bytes": 500}),
            ("an_kla_assemble_context", {"query": "memoria", "budget_bytes": 900}),
        ]
        for name, arguments in calls:
            response = self.server.handle({
                "jsonrpc": "2.0",
                "id": name,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            })
            self.assertFalse(response["result"]["isError"], name)
        self.assertEqual(files(), before)


if __name__ == "__main__":
    unittest.main()
