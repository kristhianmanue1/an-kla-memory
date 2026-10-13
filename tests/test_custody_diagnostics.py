"""G3 R1b: custody observability — startup-diagnostic-v3, integration-status-v3
and doctor.custody_divergence (ADR-0048 §4, Enmienda 1)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from an_kla.canonical import canonical_json
from an_kla.custody import custody_fingerprint, pointer_path
from an_kla.identity import read_binding
from an_kla.integration import integration_status, integration_status_v3
from an_kla.schemas import schema_document
from an_kla.startup import startup_diagnostic
from an_kla.store import MemoryStore
from tests.test_custody_root import _commit_fact

ROOT = Path(__file__).resolve().parents[1]

try:
    from jsonschema import Draft202012Validator

    _HAS_JSONSCHEMA = True
except Exception:  # pragma: no cover
    _HAS_JSONSCHEMA = False


def _validate(test: unittest.TestCase, name: str, payload: dict) -> None:
    if not _HAS_JSONSCHEMA:
        return
    errors = list(Draft202012Validator(schema_document(name)).iter_errors(payload))
    test.assertEqual(errors, [], [error.message for error in errors])


class CustodyDiagnosticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name).resolve()
        self.base = base
        self.project = base / "project"
        self.project.mkdir()
        self.vault = base / "vaults" / "vault"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _external(self) -> MemoryStore:
        store = MemoryStore(self.project, store_root=self.vault)
        store.initialize()
        return store

    def _assert_no_paths(self, payload: dict) -> None:
        text = canonical_json(payload).decode("utf-8")
        self.assertNotIn(str(self.base), text)

    def test_default_layout_keeps_v1_and_v2_ids(self) -> None:
        store = MemoryStore(self.project)
        self.assertEqual(startup_diagnostic(store)["schema"], "an-kla/startup-diagnostic-v1")
        store.initialize()
        _commit_fact(store, "f-vocab")
        result = startup_diagnostic(store)
        self.assertEqual(result["schema"], "an-kla/startup-diagnostic-v2")
        self.assertNotIn("custody", result)
        self.assertIs(result["external_memory_evaluated"], False)
        _validate(self, "startup-diagnostic-v2", result)

    def test_opt_in_v3_on_default_layout_preserves_vocabulary(self) -> None:
        store = MemoryStore(self.project)
        store.initialize()
        _commit_fact(store, "f-vocab")
        result = startup_diagnostic(store, custody=True)
        self.assertEqual(result["schema"], "an-kla/startup-diagnostic-v3")
        self.assertIn("vocabulary", result)
        self.assertEqual(
            result["custody"],
            {
                "store_external": False,
                "custody_fingerprint": custody_fingerprint(read_binding(store)),
                "pointer": "absent",
                "divergence": "none",
            },
        )
        _validate(self, "startup-diagnostic-v3", result)
        absent = startup_diagnostic(MemoryStore(self.base / "empty"), custody=True)
        self.assertNotIn("vocabulary", absent)
        self.assertIsNone(absent["custody"]["custody_fingerprint"])
        _validate(self, "startup-diagnostic-v3", absent)

    def test_external_custody_emits_v3_without_paths(self) -> None:
        store = self._external()
        _commit_fact(store, "f-external")
        result = startup_diagnostic(store)
        self.assertEqual(result["schema"], "an-kla/startup-diagnostic-v3")
        self.assertIs(result["external_memory_evaluated"], True)
        self.assertEqual(result["store_integrity"], "verified")
        self.assertEqual(result["custody"]["divergence"], "none")
        self.assertIs(result["custody"]["store_external"], True)
        self.assertEqual(result["custody"]["pointer"], "present")
        self.assertIn("vocabulary", result)
        self._assert_no_paths(result)
        _validate(self, "startup-diagnostic-v3", result)

    def _divergence(self, store: MemoryStore) -> str:
        result = startup_diagnostic(store)
        _validate(self, "startup-diagnostic-v3", result)
        self._assert_no_paths(result)
        return result["custody"]["divergence"]

    def test_divergence_codes(self) -> None:
        store = self._external()
        local = MemoryStore(self.project)
        self.assertEqual(self._divergence(local), "project_local_with_pointer")

        moved = self.vault.parent / "moved"
        shutil.move(str(self.vault), str(moved))
        self.assertEqual(
            self._divergence(MemoryStore(self.project, store_root=moved)),
            "pointer_stale_locator",
        )
        self.assertEqual(
            self._divergence(MemoryStore(self.project, store_root=self.vault)),
            "custody_identity_unreadable",
        )
        shutil.move(str(moved), str(self.vault))

        other_project = self.base / "other"
        other_project.mkdir()
        foreign = self.base / "foreign"
        MemoryStore(other_project, store_root=foreign).initialize()
        self.assertEqual(
            self._divergence(MemoryStore(self.project, store_root=foreign)),
            "pointer_fingerprint_mismatch",
        )

        pointer = pointer_path(self.project).read_bytes()
        pointer_path(self.project).write_bytes(b"{}")
        self.assertEqual(self._divergence(store), "pointer_invalid")
        pointer_path(self.project).unlink()
        self.assertEqual(self._divergence(store), "external_without_pointer")
        pointer_path(self.project).write_bytes(pointer)
        self.assertEqual(self._divergence(store), "none")

    def test_doctor_custody_axis(self) -> None:
        store = MemoryStore(self.project)
        store.initialize()
        axis = store.doctor()["custody_divergence"]
        self.assertEqual(
            axis,
            {
                "code": "none",
                "store_external": False,
                "pointer": "absent",
                "project_root_relocated_since_init": False,
                "project_local_residue": None,
            },
        )
        shutil.rmtree(self.project / ".an-kla")
        external = self._external()
        self.assertEqual(external.doctor()["custody_divergence"]["code"], "none")
        self.assertEqual(external.doctor()["custody_divergence"]["project_local_residue"], 0)
        shutil.copytree(self.vault, self.project / ".an-kla", dirs_exist_ok=True)
        local = MemoryStore(self.project)
        report = local.doctor()
        self.assertEqual(report["current_error"], "store_root_divergence")
        self.assertEqual(
            report["custody_divergence"]["code"], "project_local_with_pointer"
        )

    def test_integration_v3_and_frozen_v1(self) -> None:
        store = MemoryStore(self.project)
        store.initialize()
        result = integration_status_v3(store)
        self.assertEqual(result["schema"], "an-kla/integration-status-v3")
        self.assertEqual(result["store"]["custody"]["divergence"], "none")
        self.assertEqual(result["host_hooks"]["declaration_custody"], "project_local")
        self.assertEqual(result["host_hooks"]["runs_custody"], "project_local")
        _validate(self, "integration-status-v3", result)
        self.assertIs(
            integration_status(store)["store"]["external_memory_evaluated"], False
        )

    def test_cli_schema_version_flags(self) -> None:
        MemoryStore(self.project).initialize()
        env = dict(os.environ, AN_KLA_NO_UPDATE_CHECK="1")
        for args, expected in (
            (["startup-diagnostic"], "an-kla/startup-diagnostic-v2"),
            (["startup-diagnostic", "--schema-version", "v3"], "an-kla/startup-diagnostic-v3"),
            (["integration", "status", "--schema-version", "v3"], "an-kla/integration-status-v3"),
        ):
            completed = subprocess.run(
                [sys.executable, "-m", "an_kla", "--project-root", str(self.project)]
                + args,
                capture_output=True, text=True, cwd=str(ROOT), env=env,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["schema"], expected)


if __name__ == "__main__":
    unittest.main()
