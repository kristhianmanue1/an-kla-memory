"""test_rc_pending_contract.py — la matriz comando→rc=3 es contrato (issue #188).

rc 0 queda reservado al estado terminal firme; rc 3 significa «ejecutado sin
estado terminal firme, payload completo en stdout». La decisión vive en
`an_kla.__main__.pending_outcome_reason` (testeable unitariamente), se
publica en `capabilities` (`cli_error_surface.pending_outcome`) y se anuncia
con una línea en stderr que nombra el caso sin duplicar el payload.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from an_kla.__main__ import pending_outcome_reason
from an_kla.capabilities import capabilities
from an_kla.canonical import canonical_json

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_CASES = [
    "transaction inspect",
    "compact commit",
    "export restore",
    "refute commit",
    "init",
    "commit-write-plan",
    "subject namespace",
]


def _ns(command: str, sub: str | None = None) -> argparse.Namespace:
    return argparse.Namespace(
        command=command,
        transaction_command=sub,
        compact_command=sub,
        export_command=sub,
        refute_command=sub,
        subject_command=sub,
    )


class PendingOutcomeMatrixTests(unittest.TestCase):
    def test_seven_cases_name_their_pending(self) -> None:
        cases = [
            (_ns("transaction", "inspect"), {"committed": False}, "transaction_inspect_outcome_not_firm"),
            (_ns("transaction", "inspect"), {"state": "outcome_unknown", "committed": None}, "transaction_inspect_outcome_not_firm"),
            (_ns("compact", "commit"), {"state": "cleanup_incomplete"}, "compact_commit_outcome_not_firm"),
            (_ns("export", "restore"), {"state": "staged"}, "export_restore_outcome_not_firm"),
            (_ns("refute", "commit"), {"outcome": {"committed": False}}, "refute_commit_outcome_not_firm"),
            (_ns("init"), {"outcome": {"committed": False}}, "init_outcome_not_firm"),
            (_ns("commit-write-plan"), {"outcome": {"committed": None}}, "commit_write_plan_outcome_not_firm"),
            (_ns("subject", "namespace"), {"result": "namespace_unavailable"}, "subject_namespace_unavailable"),
        ]
        for args, result, expected in cases:
            with self.subTest(command=args.command):
                self.assertEqual(pending_outcome_reason(args, result), expected)

    def test_terminal_states_keep_rc_zero(self) -> None:
        cases = [
            (_ns("transaction", "inspect"), {"committed": True, "state": "committed"}),
            (_ns("transaction", "inspect"), {"state": "transaction_archived_by_compaction"}),
            (_ns("transaction", "repair"), {"committed": False}),
            (_ns("compact", "commit"), {"state": "committed"}),
            (_ns("export", "restore"), {"state": "published"}),
            (_ns("refute", "commit"), {"outcome": {"committed": True}}),
            (_ns("init"), {"outcome": {"committed": True}}),
            (_ns("commit-write-plan"), {"outcome": {"committed": True}}),
            (_ns("subject", "namespace"), {"result": "ok"}),
            (_ns("status"), {"ok": True}),
        ]
        for args, result in cases:
            with self.subTest(command=args.command):
                self.assertIsNone(pending_outcome_reason(args, result))

    def test_non_dict_result_is_tolerated(self) -> None:
        self.assertEqual(
            pending_outcome_reason(_ns("compact", "commit"), None),
            "compact_commit_outcome_not_firm",
        )
        self.assertIsNone(pending_outcome_reason(_ns("status"), None))


class PendingOutcomeCapabilitiesTests(unittest.TestCase):
    def test_capabilities_publish_the_matrix(self) -> None:
        pending = capabilities()["cli_error_surface"]["pending_outcome"]
        self.assertEqual(pending["exit_code"], 3)
        self.assertEqual(pending["stdout"], "result_payload_complete")
        self.assertEqual(pending["source_of_truth"], "an_kla.__main__.pending_outcome_reason")
        self.assertEqual(list(pending["cases"]), EXPECTED_CASES)

    def test_capabilities_stay_deterministic(self) -> None:
        self.assertEqual(canonical_json(capabilities()), canonical_json(capabilities()))


class PendingOutcomeCliTests(unittest.TestCase):
    def test_transaction_inspect_unknown_keeps_stderr_empty_with_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "proj"
            from an_kla.store import MemoryStore

            MemoryStore(root).initialize()
            completed = subprocess.run(
                [sys.executable, "-m", "an_kla", "--no-update-check",
                 "--project-root", str(root), "transaction", "inspect",
                 str(uuid.uuid4())],
                capture_output=True, text=True, cwd=str(ROOT),
            )
        self.assertEqual(completed.returncode, 3)
        # stderr vacío es contrato (tests congelados de subject namespace):
        # el caso se documenta, no se anuncia en stderr.
        self.assertEqual(completed.stderr, "")
        parsed = json.loads(completed.stdout)
        self.assertEqual(parsed["state"], "outcome_unknown")
        self.assertEqual(completed.stdout, canonical_json(parsed).decode())


if __name__ == "__main__":
    unittest.main()
