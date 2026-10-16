"""test_issue171_template.py — plantilla gestionada y runtime viejo (#171, PR B).

- Un consumidor en la plantilla beta.26 publicada se ve como desactualizado
  (no modificado) y actualiza con el flujo conocido.
- Un runtime más antiguo que la plantilla del proyecto lo declara
  (`runtime_older_than_context_template`), nunca da `ok:true` y nunca degrada
  el contexto con `update`/`install`.
- La etiqueta `version` del bloque es dato no confiable: una versión inflada
  no silencia la detección de un contrato editado.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from an_kla.context_package import (
    ContextPackageError,
    apply_context_plan,
    context_status,
    plan_context_change,
)
from an_kla.context_text import DETAILED_CONTRACT, TEMPLATE_VERSION
from an_kla.version import VERSION, compare_template_versions

ROOT = Path(__file__).resolve().parents[1]


def _relabel(agents: Path, version: str) -> None:
    """Rewrite only the block's declared version (an untrusted label)."""

    lines = agents.read_text(encoding="utf-8").splitlines(keepends=True)
    for index, line in enumerate(lines):
        prefix = "<!-- an-kla:managed-begin "
        if line.startswith(prefix):
            metadata = json.loads(line[len(prefix):].rsplit(" -->", 1)[0])
            metadata["version"] = version
            body = json.dumps(metadata, ensure_ascii=True, sort_keys=True,
                              separators=(",", ":"))
            lines[index] = prefix + body + " -->\n"
    agents.write_text("".join(lines), encoding="utf-8")


class TemplateVersionOrderingTests(unittest.TestCase):
    def test_orders_release_labels_and_rejects_others(self) -> None:
        self.assertEqual(compare_template_versions("0.1.0-beta.10", "0.1.0-beta.9"), 1)
        self.assertEqual(compare_template_versions("0.1.0-beta.26", "0.1.0-beta.26"), 0)
        self.assertEqual(compare_template_versions("0.1.0-beta.99", "0.1.0"), -1)
        for bad in ("x", "99", "v0.1.0", "0.1.0-gamma.1", "", None,
                    "0.1.0-beta.\u0669\u0669", "00.1.0-beta.99", "0.1.0-beta.0099"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    compare_template_versions(bad, TEMPLATE_VERSION)


class PublishedConsumerTests(unittest.TestCase):
    def test_published_templates_are_outdated_not_modified_and_update(self) -> None:
        # Cada plantilla publicada (bytes del tag) migra sin falsos
        # managed_contract_modified: beta.26 (#171) y beta.32.
        for version in ("0.1.0-beta.26", "0.1.0-beta.32"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                fixture = ROOT / "tests" / "fixtures" / f"context-v{version}"
                for name in ("AGENTS.md", "AN-KLA.md"):
                    shutil.copyfile(fixture / name, root / name)
                self.assertNotEqual(TEMPLATE_VERSION, version)
                before = context_status(root)
                self.assertEqual(before["template_version"], version)
                self.assertEqual(before["diagnostics"], ["context_template_outdated"])
                self.assertEqual(before["runtime_version"], VERSION)
                plan = plan_context_change(root, "update")
                self.assertEqual(apply_context_plan(root, plan)["action"], "replace")
                after = context_status(root)
                self.assertTrue(after["ok"], after)
                self.assertEqual(
                    (root / "AN-KLA.md").read_text(encoding="utf-8"), DETAILED_CONTRACT)

    def test_contract_documents_new_signals(self) -> None:
        for needle in ("minimum_budget_bytes", "runtime_older_than_context_template",
                       "managed_contract_unverifiable_by_runtime",
                       "runtime.package_version", "invalid_transaction_id",
                       "uv tool"):
            with self.subTest(needle=needle):
                self.assertIn(needle, DETAILED_CONTRACT)


class OlderRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        apply_context_plan(self.root, plan_context_change(self.root, "install"))
        self.agents = self.root / "AGENTS.md"
        self.contract = self.root / "AN-KLA.md"

    def _edit_contract(self) -> None:
        self.contract.write_text(
            DETAILED_CONTRACT + "\nInstrucción inyectada.\n", encoding="utf-8")

    def test_newer_template_is_reported_not_ok(self) -> None:
        _relabel(self.agents, "0.1.0-beta.99")
        status = context_status(self.root)
        self.assertFalse(status["ok"])
        self.assertIn("runtime_older_than_context_template", status["diagnostics"])
        self.assertNotIn("context_template_outdated", status["diagnostics"])
        self.assertEqual(status["template_version"], "0.1.0-beta.99")

    def test_inflated_label_never_silences_contract_edit(self) -> None:
        for label in ("0.1.0-beta.99", "99.0.0"):
            with self.subTest(label=label):
                _relabel(self.agents, label)
                self._edit_contract()
                status = context_status(self.root)
                self.assertFalse(status["ok"])
                self.assertIn("managed_contract_unverifiable_by_runtime",
                              status["diagnostics"])

    def test_historical_labels_are_never_newer(self) -> None:
        # "0.1.0" fue la primera plantilla: ordena por encima de las betas
        # pero está congelada como histórica.
        _relabel(self.agents, "0.1.0")
        self._edit_contract()
        status = context_status(self.root)
        self.assertNotIn("runtime_older_than_context_template", status["diagnostics"])
        self.assertIn("managed_contract_modified", status["diagnostics"])

    def test_malformed_label_keeps_previous_diagnostics(self) -> None:
        _relabel(self.agents, "x")
        self._edit_contract()
        status = context_status(self.root)
        self.assertFalse(status["ok"])
        self.assertIn("context_template_outdated", status["diagnostics"])
        self.assertIn("managed_contract_modified", status["diagnostics"])
        self.assertNotIn("runtime_older_than_context_template", status["diagnostics"])

    def test_newer_label_never_hides_missing_contract(self) -> None:
        _relabel(self.agents, "0.1.0-beta.99")
        self.contract.unlink()
        status = context_status(self.root)
        self.assertFalse(status["ok"])
        self.assertIn("managed_contract_missing", status["diagnostics"])

    def test_refusal_precedes_contract_check(self) -> None:
        # Caso real: el contrato es el de la plantilla más nueva, que este
        # runtime no reconoce; debe responder runtime_older, no "modified".
        _relabel(self.agents, "0.1.0-beta.99")
        self._edit_contract()
        for operation in ("update", "install"):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(
                    ContextPackageError, "^runtime_older_than_context_template$"
                ):
                    plan_context_change(self.root, operation, allow_target_drift=True)

    def test_older_runtime_refuses_to_downgrade(self) -> None:
        _relabel(self.agents, "0.1.0-beta.99")
        agents_before = self.agents.read_bytes()
        contract_before = self.contract.read_bytes()
        for operation in ("update", "install"):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(
                    ContextPackageError, "runtime_older_than_context_template"
                ):
                    plan_context_change(
                        self.root, operation, allow_target_drift=True)
        self.assertEqual(self.agents.read_bytes(), agents_before)
        self.assertEqual(self.contract.read_bytes(), contract_before)
        # uninstall no depende de verificar la plantilla.
        plan_context_change(self.root, "uninstall", allow_target_drift=True)


if __name__ == "__main__":
    unittest.main()
