"""G1 (#55 / ADR-0039): contrato observable de la integración."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from an_kla.integration import INTEGRATION_SCHEMA, integration_status
from an_kla.schemas import schema_bytes
from an_kla.store import MemoryStore


ROOT = Path(__file__).resolve().parents[1]


def _validator():
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        raise unittest.SkipTest("jsonschema unavailable")
    return Draft202012Validator(json.loads(schema_bytes("integration-status-v1")))


class IntegrationStatusTests(unittest.TestCase):
    def test_absent_store_and_context_is_a_valid_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(directory)
            result = integration_status(store)
        self.assertEqual(result["schema"], INTEGRATION_SCHEMA)
        self.assertEqual(result["store"]["store_presence"], "absent")
        self.assertEqual(result["store"]["store_integrity"], "not_evaluated")
        self.assertEqual(result["managed_context"]["presence"], "absent")
        self.assertEqual(result["integration"]["observed_profile"], "unspecified")
        self.assertEqual(result["integration"]["agent_binding"], "unverified")
        self.assertEqual(
            result["integration"]["sharing_boundary"],
            "filesystem-access/unverified",
        )
        self.assertFalse(result["integration"]["host_hooks_evaluated"])
        _validator().validate(result)

    def test_initialized_store_reported_verified_without_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(directory)
            store.initialize()
            result = integration_status(store)
        self.assertEqual(result["store"]["store_presence"], "present")
        self.assertEqual(result["store"]["store_integrity"], "verified")
        self.assertEqual(result["managed_context"]["presence"], "absent")
        _validator().validate(result)

    def test_installed_context_reported_present(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(directory)
            store.initialize()
            from an_kla.context_package import (
                apply_context_plan,
                plan_context_change,
            )

            plan = plan_context_change(directory, "install", "AGENTS.md")
            apply_context_plan(directory, plan)
            result = integration_status(store)
        self.assertEqual(result["managed_context"]["presence"], "present")
        self.assertEqual(
            result["managed_context"]["template_version"], "0.1.0-beta.21"
        )
        self.assertTrue(result["managed_context"]["ok"])
        _validator().validate(result)

    def test_query_does_not_create_store_or_mutate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(directory)
            integration_status(store)
            self.assertFalse((Path(directory) / ".an-kla" / "memory").exists())

    def test_unreadable_context_target_is_a_diagnosable_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            real = Path(directory) / "REAL.md"
            real.write_text("# real\n", encoding="utf-8")
            target = Path(directory) / "AGENTS.md"
            target.symlink_to(real)
            store = MemoryStore(directory)
            result = integration_status(store)
        self.assertEqual(result["managed_context"]["presence"], "unreadable")
        self.assertFalse(result["managed_context"]["ok"])
        self.assertEqual(
            result["managed_context"]["observation_error"],
            "context_target_symlink_forbidden",
        )
        _validator().validate(result)

    def test_permission_denied_context_reports_stable_code(self) -> None:
        import os
        import sys as _sys

        if _sys.platform == "win32" or os.geteuid() == 0:
            self.skipTest("permission bits not enforceable here")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "AGENTS.md"
            target.write_text("# x\n", encoding="utf-8")
            target.chmod(0o000)
            try:
                store = MemoryStore(directory)
                result = integration_status(store)
            finally:
                target.chmod(0o644)
        self.assertEqual(result["managed_context"]["presence"], "unreadable")
        self.assertEqual(
            result["managed_context"]["observation_error"],
            "context_target_unreadable",
        )
        _validator().validate(result)

    def test_corrupt_managed_block_still_diagnoses_with_exit_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "AGENTS.md").write_text(
                "# broken\n<!-- an-kla:managed-begin {\"id\":\"agent-context\"} -->\n"
                "content without end marker\n",
                encoding="utf-8",
            )
            store = MemoryStore(directory)
            result = integration_status(store)
        self.assertEqual(result["managed_context"]["presence"], "absent")
        self.assertIn(
            "managed_block_structure_invalid",
            result["managed_context"]["diagnostics"],
        )
        _validator().validate(result)


class IntegrationCliTests(unittest.TestCase):
    def _run(self, project_root: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "an_kla", "--no-update-check",
             "--project-root", project_root, "integration", "status"],
            cwd=ROOT, capture_output=True, text=True,
        )

    def test_cli_succeeds_on_empty_project_with_valid_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = self._run(directory)
            leftovers = sorted(
                str(path.relative_to(directory))
                for path in Path(directory).rglob("*")
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(leftovers, [])
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["schema"], INTEGRATION_SCHEMA)
        self.assertEqual(payload["store"]["store_presence"], "absent")
        _validator().validate(payload)


if __name__ == "__main__":
    unittest.main()
