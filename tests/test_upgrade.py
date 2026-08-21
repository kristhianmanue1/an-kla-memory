from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from an_kla import VERSION
from an_kla.canonical import canonical_json, digest_json
from an_kla.context_package import ContextConcurrentUpdate
from an_kla.store import MemoryStore
from an_kla.upgrade import apply_upgrade, inspect_upgrade, verify_upgrade


ROOT = Path(__file__).resolve().parents[1]
TARGET = f"v{VERSION.replace('b', '-beta.')}"


class UpgradeContractTests(unittest.TestCase):
    def test_inspect_is_deterministic_non_mutating_and_content_addressed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = inspect_upgrade(root, TARGET)
            second = inspect_upgrade(root, TARGET)
            self.assertEqual(canonical_json(first), canonical_json(second))
            self.assertEqual(first["core"]["installed_version"], VERSION)
            self.assertEqual(first["core"]["package_action"], "already_installed")
            self.assertEqual(first["core"]["context_operation"], "install")
            self.assertEqual(
                first["core"]["context_plan_sha256"],
                digest_json(first["context_plan"]),
            )
            self.assertEqual(first["plan_fingerprint"], digest_json(first["core"]))
            self.assertFalse((root / ".an-kla").exists())
            self.assertFalse((root / "AGENTS.md").exists())

    def test_apply_requires_exact_plan_and_verifies_without_initializing_memory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = inspect_upgrade(root, TARGET)
            result = apply_upgrade(root, plan, plan["plan_fingerprint"])
            self.assertTrue(result["ok"])
            self.assertTrue((root / "AGENTS.md").is_file())
            self.assertTrue((root / "AN-KLA.md").is_file())
            self.assertTrue((root / ".an-kla" / "context" / "manifest.json").is_file())
            self.assertFalse((root / ".an-kla" / "memory").exists())
            self.assertEqual(
                result["verification"]["memory"]["status"], "not_initialized"
            )

    def test_tampering_fingerprint_and_wrong_installed_target_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = inspect_upgrade(root, TARGET)
            with self.assertRaisesRegex(ValueError, "invalid_upgrade_plan"):
                apply_upgrade(root, plan, "sha256:" + "0" * 64)
            plan["context_plan"]["result_target_sha256"] = "sha256:" + "0" * 64
            with self.assertRaisesRegex(ValueError, "invalid_upgrade_plan"):
                apply_upgrade(root, plan, plan["plan_fingerprint"])
            self.assertFalse((root / ".an-kla").exists())
            with self.assertRaisesRegex(ValueError, "upgrade_target_not_installed"):
                inspect_upgrade(root, "v9.9.9")
            with self.assertRaisesRegex(ValueError, "unsupported_upgrade_target"):
                inspect_upgrade(root, "latest")

    def test_context_change_after_inspection_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "AGENTS.md").write_text("original\n", encoding="utf-8")
            plan = inspect_upgrade(root, TARGET)
            (root / "AGENTS.md").write_text("concurrente\n", encoding="utf-8")
            with self.assertRaises(ContextConcurrentUpdate):
                apply_upgrade(root, plan, plan["plan_fingerprint"])
            self.assertEqual(
                (root / "AGENTS.md").read_text(encoding="utf-8"), "concurrente\n"
            )

    def test_verify_checks_existing_memory_but_does_not_require_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = inspect_upgrade(root, TARGET)
            apply_upgrade(root, plan, plan["plan_fingerprint"])
            absent = verify_upgrade(root, TARGET)
            self.assertTrue(absent["ok"])
            self.assertEqual(absent["memory"]["status"], "not_initialized")
            MemoryStore(root).initialize()
            present = verify_upgrade(root, TARGET)
            self.assertTrue(present["ok"])
            self.assertEqual(present["memory"]["status"], "verified")
            self.assertTrue(present["memory"]["verification"]["ok"])

    def test_cli_inspect_apply_verify_are_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path = root / "upgrade-plan.json"
            inspected = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "an_kla",
                    "--project-root",
                    directory,
                    "upgrade",
                    "inspect",
                    "--target",
                    TARGET,
                ],
                cwd=ROOT,
                capture_output=True,
                check=True,
            )
            plan = json.loads(inspected.stdout)
            self.assertEqual(inspected.stdout, canonical_json(plan))
            plan_path.write_bytes(inspected.stdout)
            applied = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "an_kla",
                    "--project-root",
                    directory,
                    "upgrade",
                    "apply",
                    plan["plan_fingerprint"],
                    "--plan",
                    str(plan_path),
                ],
                cwd=ROOT,
                capture_output=True,
                check=True,
            )
            self.assertEqual(applied.stdout, canonical_json(json.loads(applied.stdout)))
            verified = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "an_kla",
                    "--project-root",
                    directory,
                    "upgrade",
                    "verify",
                    "--target",
                    TARGET,
                ],
                cwd=ROOT,
                capture_output=True,
                check=True,
            )
            self.assertTrue(json.loads(verified.stdout)["ok"])

    def test_cli_rejects_moving_target_without_creating_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "an_kla",
                    "--project-root",
                    directory,
                    "upgrade",
                    "inspect",
                    "--target",
                    "latest",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(completed.stdout, "")
            self.assertIn("an-kla error: unsupported_upgrade_target", completed.stderr)
            self.assertNotIn(str(root), completed.stderr)
            self.assertFalse((root / ".an-kla").exists())


class TargetDriftTests(unittest.TestCase):
    """ADR-0017: target drift transparency in upgrade flow (issue #12)."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        # Install context first so a manifest baseline exists.
        plan = inspect_upgrade(self.root, TARGET)
        apply_upgrade(self.root, plan, plan["plan_fingerprint"])

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_inspect_reports_no_drift_when_target_unchanged(self) -> None:
        plan = inspect_upgrade(self.root, TARGET)
        drift = plan["core"]["target_drift"]
        self.assertFalse(drift["outside_managed_block"])
        self.assertFalse(drift["will_be_absorbed_by_apply"])
        self.assertEqual(
            drift["manifest_target_sha256_at_baseline"],
            drift["observed_target_sha256"],
        )

    def test_inspect_reports_target_drift_when_target_changed(self) -> None:
        # Edit AGENTS.md outside the managed block.
        agents = self.root / "AGENTS.md"
        agents.write_bytes(agents.read_bytes() + b"\n## Mis notas internas\n\nnota\n")
        plan = inspect_upgrade(self.root, TARGET)
        drift = plan["core"]["target_drift"]
        self.assertTrue(drift["outside_managed_block"])
        self.assertTrue(drift["will_be_absorbed_by_apply"])
        self.assertNotEqual(
            drift["manifest_target_sha256_at_baseline"],
            drift["observed_target_sha256"],
        )

    def test_apply_fails_closed_without_confirm_flag_on_drift(self) -> None:
        agents = self.root / "AGENTS.md"
        agents.write_bytes(agents.read_bytes() + b"\n## notas\n")
        plan = inspect_upgrade(self.root, TARGET)
        with self.assertRaises(ValueError) as ctx:
            apply_upgrade(self.root, plan, plan["plan_fingerprint"])
        self.assertIn("target_drift_requires_confirmation", str(ctx.exception))

    def test_apply_declares_target_drift_absorbed_with_confirm(self) -> None:
        agents = self.root / "AGENTS.md"
        original_sha = agents.read_bytes()
        agents.write_bytes(original_sha + b"\n## notas fuera del bloque\n\ncontenido\n")
        plan = inspect_upgrade(self.root, TARGET)
        result = apply_upgrade(
            self.root,
            plan,
            plan["plan_fingerprint"],
            confirm_target_drift=True,
        )
        self.assertTrue(result["ok"])
        self.assertIn(
            "target_drift_absorbed_into_new_baseline",
            result.get("warnings", []),
        )
        self.assertTrue(result["target_drift"]["outside_managed_block"])
        self.assertNotEqual(
            result["target_drift"]["manifest_target_sha256_at_baseline"],
            result["target_drift"]["observed_target_sha256"],
        )

    def test_inspect_emits_v3_schema_with_target_drift_field(self) -> None:
        plan = inspect_upgrade(self.root, TARGET)
        self.assertEqual(plan["schema"], "an-kla/upgrade-plan-v3")
        self.assertIn("target_drift", plan["core"])


if __name__ == "__main__":
    unittest.main()
