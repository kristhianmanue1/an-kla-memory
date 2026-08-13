from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch

from an_kla.canonical import canonical_json
from an_kla.context_view import context_view
from an_kla.mcp import PROTOCOL_VERSION, ReadOnlyMcp
from an_kla.store import STREAMS, MemoryStore


REVISION = "sha256:" + "a" * 64
SUBJECT = "an-kla:subject:v1:service:p-" + "b" * 32 + ":billing"


class McpContextViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(self.temp.name)
        self.revision = self.store.initialize()
        self.server = ReadOnlyMcp(self.temp.name)
        self.server.handle({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": PROTOCOL_VERSION},
        })
        self.server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _call(self, arguments: object) -> tuple[dict, dict]:
        response = self.server.handle({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "an_kla_view_context", "arguments": arguments},
        })
        payload = json.loads(response["result"]["content"][0]["text"])
        return response, payload

    def test_tool_schema_is_closed_and_declares_all_core_inputs(self) -> None:
        tools = {item["name"]: item for item in self.server.tools()}
        schema = tools["an_kla_view_context"]["inputSchema"]
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["required"], ["revision"])
        self.assertEqual(
            set(schema["properties"]),
            {
                "revision", "streams", "subject_filter", "projection", "limit",
                "budget_bytes", "cursor", "now", "stale_after_days",
            },
        )
        self.assertEqual(schema["properties"]["streams"]["items"]["enum"], list(STREAMS))
        self.assertEqual(schema["properties"]["projection"]["enum"], ["metadata", "text", "full"])

    def test_input_schema_rejects_trailing_newlines_like_runtime(self) -> None:
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema unavailable")
        tools = {item["name"]: item for item in self.server.tools()}
        validator = Draft202012Validator(tools["an_kla_view_context"]["inputSchema"])
        self.assertFalse(validator.is_valid({"revision": self.revision + "\n"}))
        self.assertFalse(validator.is_valid({"revision": self.revision, "subject_filter": SUBJECT + "\n"}))

    def test_call_forwards_all_arguments_to_the_shared_core(self) -> None:
        success = {"schema": "an-kla/context-view-v1"}
        arguments = {
            "revision": REVISION,
            "streams": ["episodes", "facts"],
            "subject_filter": SUBJECT,
            "projection": "full",
            "limit": 7,
            "budget_bytes": 9000,
            "cursor": "opaque",
            "now": "2026-08-12T00:00:00Z",
            "stale_after_days": 30,
        }
        with patch("an_kla.mcp.context_view", return_value=success) as view:
            self.assertEqual(self.server.call("an_kla_view_context", arguments), success)
        self.assertEqual(view.call_args.kwargs, arguments)

    def test_success_has_exact_canonical_text_and_is_error_false(self) -> None:
        response, payload = self._call({"revision": self.revision})
        text = response["result"]["content"][0]["text"]
        self.assertFalse(response["result"]["isError"])
        self.assertNotIn("structuredContent", response["result"])
        self.assertEqual(payload["schema"], "an-kla/context-view-v1")
        self.assertEqual(text.encode("utf-8"), canonical_json(payload))
        self.assertTrue(payload["host_framing_unmeasured"])

    def test_core_errors_remain_exact_payloads_and_set_is_error_true(self) -> None:
        for arguments, code in (
            ({}, "view_invalid_inputs"),
            ({"revision": REVISION}, "view_revision_not_available"),
            ({"revision": self.revision, "projection": "full"}, "view_invalid_inputs"),
        ):
            with self.subTest(code=code, arguments=arguments):
                response, payload = self._call(arguments)
                text = response["result"]["content"][0]["text"]
                self.assertTrue(response["result"]["isError"])
                self.assertEqual(payload["schema"], "an-kla/view-error-v1")
                self.assertEqual(payload["code"], code)
                self.assertEqual(text.encode("utf-8"), canonical_json(payload))

    def test_mcp_payload_has_byte_parity_with_direct_core(self) -> None:
        arguments = {"revision": self.revision, "budget_bytes": 4096}
        direct = context_view(self.store, **arguments)
        response, payload = self._call(arguments)
        self.assertFalse(response["result"]["isError"])
        self.assertEqual(canonical_json(payload), canonical_json(direct))

    def test_requested_stream_subset_and_text_conflict_are_not_rejected(self) -> None:
        revision = self.store.commit(
            expected_current_hash=self.revision,
            checkpoint_patch={},
            facts=[
                {"id": "f-1", "subject_ref": SUBJECT, "payload": {"text": "same", "version": 1}},
                {"id": "f-2", "subject_ref": SUBJECT, "payload": {"text": "same", "version": 2}},
            ],
        )
        response, payload = self._call({"revision": revision, "streams": ["facts"]})
        self.assertFalse(response["result"]["isError"])
        self.assertEqual(set(payload["subjects_without_subject_ref"]), {"facts"})
        self.assertTrue(payload["subjects"][0]["content_differs_beyond_text"])

    def test_transport_rejects_unknown_arguments_without_leaking_them(self) -> None:
        response, payload = self._call({"revision": self.revision, "secret": "do not echo"})
        self.assertTrue(response["result"]["isError"])
        self.assertEqual(payload, {"error": "invalid_tool_arguments"})

    def test_transport_fails_closed_for_malformed_core_results(self) -> None:
        malformed = (
            {"schema": "an-kla/view-error-v1", "private": "do not leak"},
            {"schema": "unexpected", "private": "do not leak"},
            {"schema": "an-kla/context-view-v1", "private": "do not leak"},
        )
        for value in malformed:
            with self.subTest(schema=value["schema"]), patch(
                "an_kla.mcp.context_view", return_value=value
            ):
                response, payload = self._call({"revision": self.revision})
            self.assertTrue(response["result"]["isError"])
            self.assertEqual(payload, {"error": "internal_error"})
            self.assertNotIn("do not leak", json.dumps(response))

    def test_transport_fails_closed_for_malformed_values_in_known_fields(self) -> None:
        valid = context_view(self.store, revision=self.revision)
        malformed_success = dict(valid)
        malformed_success["consumer_action_required"] = "/private/SECRET"
        malformed_error = {
            "schema": "an-kla/view-error-v1",
            "ok": False,
            "code": "view_invalid_subject_ref_in_revision",
            "retryable": False,
            "untrusted_memory_data": True,
            "detail": {"stream": "/private/SECRET", "record_sha256": REVISION},
        }
        for value in (malformed_success, malformed_error):
            with patch("an_kla.mcp.context_view", return_value=value):
                response, payload = self._call({"revision": self.revision})
            self.assertTrue(response["result"]["isError"])
            self.assertEqual(payload, {"error": "internal_error"})
            self.assertNotIn("/private/SECRET", json.dumps(response))


if __name__ == "__main__":
    unittest.main()
