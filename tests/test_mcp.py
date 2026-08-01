from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from an_kla import VERSION
from an_kla.mcp import PROTOCOL_VERSION, ReadOnlyMcp, _safe_error
from an_kla.store import MemoryStore, StoreError


class McpProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        store = MemoryStore(self.temp.name)
        root = store.initialize()
        store.commit(expected_current_hash=root, checkpoint_patch={}, facts=[
            {"id": "f-001", "payload": {"text": "memoria ágil"}},
            {"id": "f-002", "payload": {"text": "distractor"}},
        ])
        self.server = ReadOnlyMcp(self.temp.name)
        self._initialize(self.server)

    def tearDown(self) -> None:
        self.temp.cleanup()

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

    def test_tool_dispatch_measures_model_content_not_jsonrpc_transport(self) -> None:
        response = self.server.handle({"jsonrpc":"2.0", "id":3, "method":"tools/call", "params":{"name":"an_kla_retrieve", "arguments":{"query":"memoria", "budget_bytes":400}}})
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertLessEqual(len(response["result"]["content"][0]["text"].encode("utf-8")), 400)
        self.assertEqual(payload["used_bytes"], len(response["result"]["content"][0]["text"].encode("utf-8")))
        self.assertTrue(payload["host_framing_unmeasured"])

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
