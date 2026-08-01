from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from an_kla.mcp import PROTOCOL_VERSION
from an_kla.store import MemoryStore


class McpStdioTests(unittest.TestCase):
    @staticmethod
    def _send(process: subprocess.Popen, message: dict) -> dict:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()
        return json.loads(process.stdout.readline())

    def test_stdio_round_trip_does_not_reply_to_notification(self) -> None:
        with tempfile.TemporaryDirectory() as project_root:
            store = MemoryStore(project_root)
            root = store.initialize()
            store.commit(expected_current_hash=root, checkpoint_patch={}, facts=[
                {"id": "f-001", "payload": {"text": "memoria por stdio"}},
            ])
            messages = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": PROTOCOL_VERSION}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "an_kla_retrieve", "arguments": {"query": "memoria", "budget_bytes": 400}}},
            ]
            env = dict(os.environ)
            env["PYTHONPYCACHEPREFIX"] = str(Path(tempfile.gettempdir()) / "an-kla-pycache")
            process = subprocess.run(
                [sys.executable, "-m", "an_kla.mcp", "--project-root", project_root],
                cwd=Path(__file__).resolve().parents[1],
                input="".join(json.dumps(message) + "\n" for message in messages),
                text=True,
                capture_output=True,
                env=env,
                check=True,
                timeout=10,
            )
            replies = [json.loads(line) for line in process.stdout.splitlines()]
            self.assertEqual([reply["id"] for reply in replies], [1, 2, 3])
            self.assertEqual(replies[0]["result"]["protocolVersion"], PROTOCOL_VERSION)
            self.assertIn("an_kla_retrieve", [tool["name"] for tool in replies[1]["result"]["tools"]])
            payload = json.loads(replies[2]["result"]["content"][0]["text"])
            self.assertLessEqual(payload["used_bytes"], payload["budget_bytes"])
            self.assertNotIn("Traceback", process.stderr)

    def test_live_reader_does_not_block_current_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as project_root:
            store = MemoryStore(project_root)
            root = store.initialize()
            store.commit(expected_current_hash=root, checkpoint_patch={}, facts=[
                {"id": "f-001", "payload": {"text": "memoria persistente"}},
            ])
            expected = store.read_current()
            env = dict(os.environ)
            env["PYTHONPYCACHEPREFIX"] = str(Path(tempfile.gettempdir()) / "an-kla-pycache")
            process = subprocess.Popen(
                [sys.executable, "-m", "an_kla.mcp", "--project-root", project_root],
                cwd=Path(__file__).resolve().parents[1], text=True,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
            )
            try:
                initialized = self._send(process, {"jsonrpc":"2.0", "id":1, "method":"initialize", "params":{"protocolVersion":PROTOCOL_VERSION}})
                self.assertIn("result", initialized)
                retrieved = self._send(process, {"jsonrpc":"2.0", "id":2, "method":"tools/call", "params":{"name":"an_kla_retrieve", "arguments":{"query":"memoria", "budget_bytes":400}}})
                self.assertFalse(retrieved["result"]["isError"])
                replacement = store.commit(expected_current_hash=expected, checkpoint_patch={"goal":"replaced while reader alive"})
                self.assertEqual(store.read_current(), replacement)
            finally:
                assert process.stdin is not None
                process.stdin.close()
                process.wait(timeout=10)
                assert process.stderr is not None
                self.assertNotIn("Traceback", process.stderr.read())
                process.stderr.close()
                assert process.stdout is not None
                process.stdout.close()


if __name__ == "__main__":
    unittest.main()
