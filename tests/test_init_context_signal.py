"""#87: init señala el estado del bloque de contexto (patrón ADR-0020)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from an_kla.context_package import apply_context_plan, plan_context_change
from an_kla.store import MemoryStore


class InitContextDiagnosticsTests(unittest.TestCase):
    def test_bare_init_surfaces_installed_false(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(directory)
            result = store.initialize_with_outcome()
        self.assertTrue(result["outcome"]["committed"])
        diagnostics = result["context_diagnostics"]
        self.assertEqual(diagnostics["schema"], "an-kla/context-status/v1")
        self.assertFalse(diagnostics["installed"])
        self.assertEqual(diagnostics["diagnostics"], [])

    def test_init_after_context_install_surfaces_installed_true(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = plan_context_change(directory, "install", "AGENTS.md")
            apply_context_plan(directory, plan)
            store = MemoryStore(directory)
            result = store.initialize_with_outcome()
        self.assertTrue(
            result["outcome"] is None or result["outcome"]["committed"] is True
        )
        self.assertTrue(result["context_diagnostics"]["installed"])

    def test_context_status_failure_degrades_to_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(directory)
            with patch(
                "an_kla.store.context_status",
                side_effect=RuntimeError("boom"),
            ):
                result = store.initialize_with_outcome()
        diagnostics = result["context_diagnostics"]
        self.assertEqual(diagnostics["ok"], None)
        self.assertIn("context_status_unavailable", diagnostics["diagnostics"])

    def test_result_shape_is_additive_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(directory)
            result = store.initialize_with_outcome()
        self.assertEqual(
            set(result),
            {
                "revision",
                "outcome",
                "identity",
                "attestation",
                "context_diagnostics",
            },
        )


    def test_corrupt_managed_block_surfaces_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "AGENTS.md").write_text(
                "# broken\n<!-- an-kla:managed-begin {\"id\":\"agent-context\"} -->\n"
                "sin end marker\n",
                encoding="utf-8",
            )
            store = MemoryStore(directory)
            result = store.initialize_with_outcome()
        diagnostics = result["context_diagnostics"]
        self.assertFalse(diagnostics["installed"])
        self.assertIn(
            "managed_block_structure_invalid",
            diagnostics["diagnostics"],
        )

    def test_cli_e2e_prints_context_diagnostics(self) -> None:
        import json
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run(
                [
                    sys.executable, "-m", "an_kla", "--no-update-check",
                    "--project-root", directory, "init",
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True, text=True,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["outcome"]["committed"])
        self.assertFalse(payload["context_diagnostics"]["installed"])


class InitCapabilitiesContractTests(unittest.TestCase):
    def test_capabilities_declares_the_init_surface(self) -> None:
        from an_kla.capabilities import capabilities

        payload = capabilities()
        self.assertTrue(
            payload["write_policy"]["context_diagnostics_in_init_result"]
        )


if __name__ == "__main__":
    unittest.main()
