"""test_integration_status_v2.py — F3-B de ADR-0047 (#56).

Goldens de `integration-status-v2`: el bloque `host_hooks`, el enum de
`observed_profile` (calculado, nunca persistido), la emisión opt-in
(`--schema-version v2`) con v1 byte-idéntico por defecto, y la pureza
read-only. La lectura de `.an-kla/hook-runs/` llega en F3-C: aquí la
evidencia no puede existir (no hay escritor) y `hook_invoked` es [].
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

try:
    from jsonschema import Draft202012Validator
    import json as _json
    from importlib.resources import files as _files

    _SCHEMA = _json.loads(
        _files("an_kla.schemas").joinpath("integration-status-v2.schema.json")
        .read_text(encoding="utf-8")
    )
    _HAS_JSONSCHEMA = True
except Exception:  # pragma: no cover
    _HAS_JSONSCHEMA = False


def _cli(args: list, root: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, AN_KLA_NO_UPDATE_CHECK="1")
    return subprocess.run(
        [sys.executable, "-m", "an_kla", "--project-root", str(root)] + args,
        capture_output=True, text=True, cwd=str(ROOT), env=env,
    )


def _declaration(well_formed: bool = True, invalid: bool = False) -> dict:
    if invalid:
        return {"schema": "an-kla/host-hooks-v1", "hooks": "no-soy-lista"}
    return {
        "schema": "an-kla/host-hooks-v1",
        "adapter": {
            "name": "cline", "version": "1.0.0",
            "configuration_fingerprint": "sha256:" + "a" * 64,
        },
        "declared_profile": "host-managed/v1",
        "hooks": ([] if not well_formed else [
            {"id": "before-task-retrieve", "trigger": "before_task",
             "action": "assemble-context", "budget_bytes": 4096},
            {"id": "material-close-checkpoint",
             "trigger": "material_close_or_handoff", "action": "checkpoint",
             "required": True},
        ]),
    }


class EmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="ankla-itstatus-v2-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.path = self.root / ".an-kla" / "host-hooks.json"

    def write(self, payload) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload), encoding="utf-8")

    def test_default_emission_is_frozen_v1(self) -> None:
        self.write(_declaration())
        completed = _cli(["integration", "status"], self.root)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["schema"], "an-kla/integration-status-v1")
        self.assertEqual(payload["integration"]["observed_profile"], "unspecified")
        self.assertFalse(payload["integration"]["host_hooks_evaluated"])
        self.assertNotIn("host_hooks", payload)

    @unittest.skipUnless(_HAS_JSONSCHEMA, "jsonschema unavailable")
    def test_v2_absent_declaration(self) -> None:
        completed = _cli(["integration", "status", "--schema-version", "v2"], self.root)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        Draft202012Validator(_SCHEMA).validate(payload)
        self.assertEqual(payload["schema"], "an-kla/integration-status-v2")
        self.assertEqual(payload["integration"]["observed_profile"], "unspecified")
        self.assertTrue(payload["integration"]["host_hooks_evaluated"])
        self.assertEqual(payload["host_hooks"]["declaration"], "absent")
        self.assertEqual(payload["host_hooks"]["pending_continuity"], "none")
        self.assertEqual(payload["host_hooks"]["hook_invoked"], [])

    @unittest.skipUnless(_HAS_JSONSCHEMA, "jsonschema unavailable")
    def test_v2_well_formed_is_declared_not_invoked_with_pending_required(self) -> None:
        self.write(_declaration())
        completed = _cli(["integration", "status", "--schema-version", "v2"], self.root)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        Draft202012Validator(_SCHEMA).validate(payload)
        self.assertEqual(payload["integration"]["observed_profile"], "declared-not-invoked")
        self.assertEqual(
            payload["host_hooks"]["hook_declared"],
            ["before-task-retrieve", "material-close-checkpoint"],
        )
        self.assertEqual(payload["host_hooks"]["pending_continuity"], "required")

    @unittest.skipUnless(_HAS_JSONSCHEMA, "jsonschema unavailable")
    def test_v2_well_formed_without_required_hook_has_pending_none(self) -> None:
        self.write(_declaration(well_formed=False))
        completed = _cli(["integration", "status", "--schema-version", "v2"], self.root)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        Draft202012Validator(_SCHEMA).validate(payload)
        self.assertEqual(payload["integration"]["observed_profile"], "declared-not-invoked")
        self.assertEqual(payload["host_hooks"]["pending_continuity"], "none")

    def test_v2_invalid_declaration_is_diagnosticable_without_paths(self) -> None:
        self.write(_declaration(invalid=True))
        completed = _cli(["integration", "status", "--schema-version", "v2"], self.root)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["integration"]["observed_profile"], "unspecified")
        self.assertEqual(payload["host_hooks"]["declaration"], "invalid")
        self.assertNotEqual(payload["host_hooks"]["reason_codes"], [])
        self.assertNotIn(str(self.root), json.dumps(payload))

    def test_v2_accepts_injected_now_and_writes_nothing(self) -> None:
        before = sorted(str(p) for p in self.root.rglob("*"))
        completed = _cli([
            "integration", "status", "--schema-version", "v2",
            "--now", "2026-09-05T00:00:00Z",
        ], self.root)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        after = sorted(str(p) for p in self.root.rglob("*"))
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
