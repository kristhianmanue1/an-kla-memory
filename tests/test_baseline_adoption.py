"""ADR-0040: adopción explícita de baseline (tests congelados §9)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from an_kla.baseline_adoption import (
    apply_baseline_adoption,
    plan_baseline_adoption,
)
from an_kla.context_package import (
    ContextConcurrentUpdate,
    ContextPackageError,
    MANIFEST_RELATIVE,
    apply_context_plan,
    context_status,
    plan_context_change,
)

ROOT = Path(__file__).resolve().parents[1]


class AdoptionProject:
    """Fresh consumer with project-owned content outside the block."""

    def __init__(self, root: Path) -> None:
        self.root = root
        apply_context_plan(root, plan_context_change(root, "install"))

    def edit_project_owned(self, text: str = "\nRegla nueva del proyecto.\n") -> None:
        target = self.root / "AGENTS.md"
        target.write_text(
            target.read_text(encoding="utf-8") + text, encoding="utf-8"
        )

    def manifest(self) -> dict:
        return json.loads((self.root / MANIFEST_RELATIVE).read_text(encoding="utf-8"))


class AdoptionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.project = AdoptionProject(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    # 1. Smoke before → after.
    def test_edit_warns_then_adoption_clears_it(self) -> None:
        self.project.edit_project_owned()
        self.assertIn(
            "context_target_changed_outside_managed_block",
            context_status(self.project.root)["warnings"],
        )
        result = apply_baseline_adoption(
            self.project.root, plan_baseline_adoption(self.project.root)
        )
        self.assertEqual(result["action"], "adopted")
        self.assertEqual(context_status(self.project.root)["warnings"], [])
        self.assertEqual(
            self.project.manifest()["target_sha256"],
            result["manifest_target_sha256_after"],
        )

    # 2. CAS: editar tras planificar.
    def test_target_edit_after_plan_fails_cas_without_mutation(self) -> None:
        self.project.edit_project_owned()
        plan = plan_baseline_adoption(self.project.root)
        before = self.project.manifest()
        self.project.edit_project_owned("\nOtra edición tardía.\n")
        with self.assertRaisesRegex(
            ContextConcurrentUpdate, "context_file_concurrent_update"
        ):
            apply_baseline_adoption(self.project.root, plan)
        self.assertEqual(self.project.manifest(), before)

    # 3. Bloque corrupto → fail-closed sin adopción.
    def test_corrupt_block_never_adopts(self) -> None:
        self.project.edit_project_owned()
        target = self.project.root / "AGENTS.md"
        target.write_text(
            "# roto\n<!-- an-kla:managed-begin {\"id\":\"agent-context\"} -->\nsin fin\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            ContextPackageError, "managed_block_structure_invalid"
        ):
            plan_baseline_adoption(self.project.root)

    # 4. Hash falso bien formado → corrupción, no drift.
    def test_fake_wellformed_manifest_hash_is_corruption(self) -> None:
        self.project.edit_project_owned()
        path = self.project.root / MANIFEST_RELATIVE
        manifest = self.project.manifest()
        manifest["managed_content_sha256"] = "sha256:" + "a" * 64
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(
            ContextPackageError, "context_baseline_semantic_mismatch"
        ):
            plan_baseline_adoption(self.project.root)

    # 5. Sin fuga: plan/result no llevan texto ni rutas absolutas.
    def test_plan_and_result_leak_nothing(self) -> None:
        self.project.edit_project_owned("\n## Referencia confidencial X-Y-Z\n")
        plan = plan_baseline_adoption(self.project.root)
        blob = json.dumps(plan)
        self.assertNotIn("Referencia", blob)
        self.assertNotIn(str(self.project.root), blob)
        result = apply_baseline_adoption(self.project.root, plan)
        self.assertNotIn("Referencia", json.dumps(result))

    # 6. Noop idempotente (sin drift).
    def test_noop_without_drift(self) -> None:
        plan = plan_baseline_adoption(self.project.root)
        self.assertFalse(plan["will_update_manifest"])
        result = apply_baseline_adoption(self.project.root, plan)
        self.assertEqual(result["action"], "noop")
        self.assertEqual(
            result["manifest_target_sha256_before"],
            result["manifest_target_sha256_after"],
        )

    # 7. Doble proceso: manifiesto cambió tras el plan.
    def test_second_adoption_under_lock_fails_manifest_cas(self) -> None:
        self.project.edit_project_owned()
        plan = plan_baseline_adoption(self.project.root)
        first = apply_baseline_adoption(self.project.root, plan)
        self.assertEqual(first["action"], "adopted")
        # El plan viejo ya no es válido: la baseline se movió.
        with self.assertRaisesRegex(
            ContextConcurrentUpdate, "context_manifest_concurrent_update"
        ):
            apply_baseline_adoption(self.project.root, plan)

    # 8. update fail-closed ante drift; sanos siguen igual.
    def test_update_fails_closed_on_drift_and_healthy_update_still_works(self) -> None:
        # Con drift: fail-closed (ADR-0040 §6).
        self.project.edit_project_owned()
        with self.assertRaisesRegex(
            ContextPackageError, "context_target_drift_adoption_required"
        ):
            plan_context_change(self.project.root, "update")
        # Sin drift (proyecto fresco): update conserva su noop.
        fresh = tempfile.TemporaryDirectory()
        self.addCleanup(fresh.cleanup)
        fresh_root = Path(fresh.name)
        apply_context_plan(
            fresh_root, plan_context_change(fresh_root, "install")
        )
        result = apply_context_plan(
            fresh_root, plan_context_change(fresh_root, "update")
        )
        self.assertEqual(result["action"], "noop")

    # 9. Re-drift tras editar de nuevo.
    def test_post_adoption_edit_reactivates_warning(self) -> None:
        self.project.edit_project_owned()
        apply_baseline_adoption(
            self.project.root, plan_baseline_adoption(self.project.root)
        )
        self.assertEqual(context_status(self.project.root)["warnings"], [])
        self.project.edit_project_owned("\nMás cambios.\n")
        self.assertIn(
            "context_target_changed_outside_managed_block",
            context_status(self.project.root)["warnings"],
        )

    # 10. Target ausente jamás adopta baseline inválida.
    def test_missing_target_is_never_adopted(self) -> None:
        self.project.edit_project_owned()
        (self.project.root / "AGENTS.md").unlink()
        with self.assertRaisesRegex(
            ContextPackageError, "context_baseline_target_missing"
        ):
            plan_baseline_adoption(self.project.root)

    # 11. Manifest ausente remite a install.
    def test_missing_manifest_points_to_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "AGENTS.md").write_text("proyecto sin contexto\n", encoding="utf-8")
            with self.assertRaisesRegex(
                ContextPackageError, "context_manifest_missing"
            ):
                plan_baseline_adoption(root)


class UpgradeAdoptionFlowTests(unittest.TestCase):
    """ADR-0017 regression + v3 plan contract (§9)."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = AdoptionProject(self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_confirm_target_drift_flow_survives(self) -> None:
        from an_kla.upgrade import apply_upgrade, inspect_upgrade

        self.project.edit_project_owned()
        plan = inspect_upgrade(self.root, "v0.1.0-beta.16")
        self.assertEqual(plan["schema"], "an-kla/upgrade-plan-v3")
        self.assertTrue(plan["core"]["target_drift"]["outside_managed_block"])
        # Sin flag falla cerrado.
        with self.assertRaisesRegex(ValueError, "target_drift_requires_confirmation"):
            apply_upgrade(self.root, plan, plan["plan_fingerprint"])
        # Con flag absorbe y lo declara.
        result = apply_upgrade(
            self.root, plan, plan["plan_fingerprint"], confirm_target_drift=True
        )
        self.assertEqual(
            result["warnings"], ["target_drift_absorbed_into_new_baseline"]
        )

    def test_v3_plan_names_baseline_not_install(self) -> None:
        from an_kla.upgrade import inspect_upgrade

        plan = inspect_upgrade(self.root, "v0.1.0-beta.16")
        drift = plan["core"]["target_drift"]
        self.assertIn("manifest_target_sha256_at_baseline", drift)
        self.assertNotIn("manifest_target_sha256_at_install", drift)

    def test_adopted_bytes_do_not_ask_confirmation_on_next_upgrade(self) -> None:
        from an_kla.upgrade import inspect_upgrade

        self.project.edit_project_owned()
        apply_baseline_adoption(
            self.root, plan_baseline_adoption(self.root)
        )
        plan = inspect_upgrade(self.root, "v0.1.0-beta.16")
        self.assertFalse(plan["core"]["target_drift"]["outside_managed_block"])

    def test_plan_and_result_schemas_validate(self) -> None:
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema unavailable")
        self.project.edit_project_owned()
        plan = plan_baseline_adoption(self.root)
        result = apply_baseline_adoption(self.root, plan)
        plan_schema = json.loads(
            (ROOT / "docs/schemas/context-baseline-adoption-plan-v1.schema.json")
            .read_text(encoding="utf-8")
        )
        result_schema = json.loads(
            (ROOT / "docs/schemas/context-baseline-adoption-result-v1.schema.json")
            .read_text(encoding="utf-8")
        )
        Draft202012Validator(plan_schema).validate(plan)
        Draft202012Validator(result_schema).validate(result)


class AdoptionCliTests(unittest.TestCase):
    def test_cli_shortcut_plan_and_apply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            AdoptionProject(Path(directory))
            target = Path(directory) / "AGENTS.md"
            target.write_text(
                target.read_text(encoding="utf-8") + "\nRefs locales.\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable, "-m", "an_kla", "--no-update-check",
                    "--project-root", directory, "context", "adopt-baseline",
                ],
                cwd=ROOT, capture_output=True, text=True,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(
            payload["result"]["schema"],
            "an-kla/context-baseline-adoption-result/v1",
        )
        self.assertEqual(payload["result"]["action"], "adopted")



class FrozenListGapTests(unittest.TestCase):
    """Los 4 ítems §9 que la ronda post-code halló sin test (H6)."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = AdoptionProject(self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_known_outdated_template_adopts_then_updates(self) -> None:
        # Real historical state: v0.1.0 block AND contract from the fixture,
        # manifest coherent with that old version, drift outside the block.
        fixture = ROOT / "tests" / "fixtures" / "context-v0.1.0"
        (self.root / "AGENTS.md").write_text(
            (fixture / "AGENTS.md").read_text(encoding="utf-8")
            + "\nReferencia local del proyecto.\n",
            encoding="utf-8",
        )
        (self.root / "AN-KLA.md").write_text(
            (fixture / "AN-KLA.md").read_text(encoding="utf-8"), encoding="utf-8"
        )
        from an_kla.context_package import _KNOWN_CONTEXT_TEMPLATES, _sha
        from an_kla.context_package import parse_managed_block

        fixture_text = (fixture / "AGENTS.md").read_text(encoding="utf-8")
        block = parse_managed_block(fixture_text)
        self.assertIsNotNone(block)
        old_version = str(block.metadata.get("version"))
        self.assertIn(old_version, _KNOWN_CONTEXT_TEMPLATES)
        manifest_path = self.root / MANIFEST_RELATIVE
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["template_version"] = old_version
        contract_bytes = (self.root / "AN-KLA.md").read_bytes()
        manifest["contract_sha256"] = _sha(contract_bytes)
        manifest["managed_content_sha256"] = _sha(block.payload.encode("utf-8"))
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        # ADR-0040 §4: known-outdated IS adoptable (adopt -> update path).
        from an_kla.context_package import (
            _known_template_equivalent,
            _project_root,
            _read_utf8,
            _target_path,
        )
        _, target_text = _read_utf8(_target_path(_project_root(self.root), "AGENTS.md"))
        _, contract_text = _read_utf8(self.root / "AN-KLA.md")
        block = parse_managed_block(target_text or "")
        self.assertTrue(
            _known_template_equivalent(block, contract_text),
            "el fixture debe ejercer la rama known-outdated",
        )
        plan = plan_baseline_adoption(self.root)
        result = apply_baseline_adoption(self.root, plan)
        self.assertEqual(result["action"], "adopted")

    def test_contract_edit_after_plan_fails_cas(self) -> None:
        self.project.edit_project_owned()
        plan = plan_baseline_adoption(self.root)
        contract = self.root / "AN-KLA.md"
        contract.write_text(
            contract.read_text(encoding="utf-8").replace("\n", "\r\n"),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            ContextConcurrentUpdate, "context_contract_concurrent_update"
        ):
            apply_baseline_adoption(self.root, plan)

    def test_hand_modified_contract_fails_closed(self) -> None:
        self.project.edit_project_owned()
        contract = self.root / "AN-KLA.md"
        contract.write_text(
            contract.read_text(encoding="utf-8") + "\nTexto ajeno al contrato.\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            ContextPackageError, "context_baseline_managed_state_invalid"
        ):
            plan_baseline_adoption(self.root)

    def test_v2_plan_created_before_adoption_fails_cas_after(self) -> None:
        from an_kla.upgrade import apply_upgrade, inspect_upgrade

        self.project.edit_project_owned()
        v3_plan = inspect_upgrade(self.root, "v0.1.0-beta.16")
        # Forjar un v2 a partir del v3 (como lo haría un binario viejo).
        v2_plan = {
            **v3_plan,
            "schema": "an-kla/upgrade-plan-v2",
            "core": {
                **v3_plan["core"],
                "target_drift": {
                    **v3_plan["core"]["target_drift"],
                    "manifest_target_sha256_at_install": v3_plan["core"][
                        "target_drift"
                    ]["manifest_target_sha256_at_baseline"],
                },
            },
        }
        del v2_plan["core"]["target_drift"]["manifest_target_sha256_at_baseline"]
        # Adoptar mueve la baseline: el plan v2 previo ya no puede aplicar.
        apply_baseline_adoption(
            self.root, plan_baseline_adoption(self.root)
        )
        with self.assertRaises(ValueError):
            apply_upgrade(self.root, v2_plan, v2_plan["plan_fingerprint"])

    def test_reinstall_with_drift_also_fails_closed(self) -> None:
        # H4 de la ronda: install sobre manifiesto existente no absorbe.
        self.project.edit_project_owned()
        with self.assertRaisesRegex(
            ContextPackageError, "context_target_drift_adoption_required"
        ):
            plan_context_change(self.root, "install")


if __name__ == "__main__":
    unittest.main()
