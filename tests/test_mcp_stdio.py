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
            env["PYTHONPYCACHEPREFIX"] = "/tmp/an-kla-pycache"
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
            self.assertEqual(process.stderr, "")


if __name__ == "__main__":
    unittest.main()
