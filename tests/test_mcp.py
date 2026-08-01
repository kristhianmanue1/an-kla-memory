from __future__ import annotations

import json
import tempfile
import unittest

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

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_initialize_requires_supported_protocol(self) -> None:
        ok = self.server.handle({"jsonrpc":"2.0", "id":1, "method":"initialize", "params":{"protocolVersion":PROTOCOL_VERSION}})
        self.assertEqual(ok["result"]["protocolVersion"], PROTOCOL_VERSION)
        rejected = self.server.handle({"jsonrpc":"2.0", "id":2, "method":"initialize", "params":{"protocolVersion":"1999-01-01"}})
        self.assertEqual(rejected["error"]["message"], "unsupported_protocol_version")

    def test_lists_only_read_tools_and_ignores_all_notifications(self) -> None:
        listed = self.server.handle({"jsonrpc":"2.0", "id":1, "method":"tools/list"})
        names = {tool["name"] for tool in listed["result"]["tools"]}
        self.assertIn("an_kla_retrieve", names)
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


if __name__ == "__main__":
    unittest.main()
