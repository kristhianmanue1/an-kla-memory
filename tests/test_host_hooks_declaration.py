"""test_host_hooks_declaration.py — F3-A de ADR-0047 (#56).

Cubre la lectura/validación de `.an-kla/host-hooks.json`: eje
`declaration` (absent | invalid | well_formed), límites congelados,
códigos estables sin filtrar rutas, pureza (sin escritura) y paridad
estructural con el schema publicado `an-kla/host-hooks-v1` (la
verificación cruzada de `required`/ids duplicados es sólo del módulo).
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from an_kla import host_hooks

try:
    from jsonschema import Draft202012Validator
    import json as _json
    from importlib.resources import files as _files

    _SCHEMA = _json.loads(
        _files("an_kla.schemas").joinpath("host-hooks-v1.schema.json")
        .read_text(encoding="utf-8")
    )
    _HAS_JSONSCHEMA = True
except Exception:  # pragma: no cover
    _HAS_JSONSCHEMA = False


def _well_formed() -> dict:
    return {
        "schema": "an-kla/host-hooks-v1",
        "adapter": {
            "name": "cline",
            "version": "1.0.0",
            "configuration_fingerprint": "sha256:" + "a" * 64,
        },
        "declared_profile": "host-managed/v1",
        "hooks": [
            {"id": "before-task-retrieve", "trigger": "before_task",
             "action": "assemble-context", "budget_bytes": 4096},
            {"id": "material-close-checkpoint",
             "trigger": "material_close_or_handoff", "action": "checkpoint",
             "required": True},
        ],
    }


class DeclarationAxisTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="ankla-host-hooks-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.path = host_hooks.declaration_path(self.root)

    def write(self, payload) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(payload, (dict, list)):
            self.path.write_text(json.dumps(payload), encoding="utf-8")
        else:
            self.path.write_text(payload, encoding="utf-8")

    def test_absent_when_no_file_and_creates_nothing(self) -> None:
        before = sorted(str(p) for p in self.root.rglob("*"))
        result = host_hooks.load_declaration(self.root)
        self.assertEqual(result["declaration"], "absent")
        self.assertEqual(result["reason_codes"], ["host_hooks_absent"])
        self.assertEqual(result["hooks"], [])
        after = sorted(str(p) for p in self.root.rglob("*"))
        self.assertEqual(before, after)

    def test_invalid_json_is_diagnosticable(self) -> None:
        self.write("{no es json")
        result = host_hooks.load_declaration(self.root)
        self.assertEqual(result["declaration"], "invalid")
        self.assertEqual(result["reason_codes"], ["host_hooks_invalid_json"])

    def test_unreadable_file_is_diagnosticable_without_paths(self) -> None:
        if os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0):
            self.skipTest("permisos POSIX no aplicables")
        self.write(_well_formed())
        self.path.chmod(0o000)
        try:
            result = host_hooks.load_declaration(self.root)
        finally:
            self.path.chmod(0o644)
        self.assertEqual(result["declaration"], "invalid")
        self.assertEqual(result["reason_codes"], ["host_hooks_unreadable"])

    def test_well_formed_returns_hooks_verbatim(self) -> None:
        candidate = _well_formed()
        self.write(candidate)
        result = host_hooks.load_declaration(self.root)
        self.assertEqual(result["declaration"], "well_formed")
        self.assertEqual(result["reason_codes"], [])
        self.assertEqual(result["adapter"], candidate["adapter"])
        self.assertEqual(result["declared_profile"], "host-managed/v1")
        self.assertEqual(result["hooks"], candidate["hooks"])

    def test_reason_codes_never_leak_paths(self) -> None:
        self.write("{roto")
        result = host_hooks.load_declaration(self.root)
        self.assertNotIn(str(self.root), json.dumps(result))
        self.assertNotIn(str(self.path), json.dumps(result))


class FrozenLimitsTests(unittest.TestCase):
    """Cada límite congelado de ADR-0047 §1, violado uno a uno."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="ankla-host-hooks-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.path = host_hooks.declaration_path(self.root)

    def verdict(self, payload) -> str:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        return host_hooks.load_declaration(self.root)["declaration"]

    def assert_invalid(self, payload, expected_code: str | None = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        result = host_hooks.load_declaration(self.root)
        self.assertEqual(result["declaration"], "invalid")
        self.assertNotEqual(result["reason_codes"], [])
        if expected_code is not None:
            self.assertIn(expected_code, result["reason_codes"])

    def test_not_an_object(self) -> None:
        self.assert_invalid([1, 2], "host_hooks_not_an_object")

    def test_schema_unknown(self) -> None:
        candidate = _well_formed()
        candidate["schema"] = "an-kla/host-hooks-v99"
        self.assert_invalid(candidate, "host_hooks_schema_unknown")

    def test_adapter_shapes(self) -> None:
        candidate = _well_formed()
        candidate["adapter"] = {"name": "x", "version": "1"}
        self.assert_invalid(candidate, "host_hooks_adapter_invalid")
        candidate = _well_formed()
        candidate["adapter"]["name"] = ""
        self.assert_invalid(candidate, "host_hooks_adapter_name_invalid")
        candidate = _well_formed()
        candidate["adapter"]["configuration_fingerprint"] = "sha256:zz"
        self.assert_invalid(candidate, "host_hooks_adapter_fingerprint_invalid")

    def test_profile_unknown(self) -> None:
        candidate = _well_formed()
        candidate["declared_profile"] = "host-managed/v99"
        self.assert_invalid(candidate, "host_hooks_profile_unknown")

    def test_hooks_not_a_list(self) -> None:
        candidate = _well_formed()
        candidate["hooks"] = {}
        self.assert_invalid(candidate, "host_hooks_hooks_invalid")

    def test_hooks_count_exceeds_limit(self) -> None:
        candidate = _well_formed()
        candidate["hooks"] = [
            {"id": f"hook-{i}", "trigger": "before_task", "action": "status"}
            for i in range(17)
        ]
        self.assert_invalid(candidate, "host_hooks_hooks_count_exceeds_limit")

    def test_hook_id_limits_and_uniqueness(self) -> None:
        candidate = _well_formed()
        candidate["hooks"][0]["id"] = "a" * 129
        self.assert_invalid(candidate, "hook_0_id_invalid")
        candidate = _well_formed()
        candidate["hooks"][0]["id"] = "mal carácteres"
        self.assert_invalid(candidate, "hook_0_id_invalid")
        candidate = _well_formed()
        candidate["hooks"][1]["id"] = candidate["hooks"][0]["id"]
        self.assert_invalid(candidate, "duplicate_hook_id")

    def test_trigger_and_action_dictionaries(self) -> None:
        candidate = _well_formed()
        candidate["hooks"][0]["trigger"] = "whenever"
        self.assert_invalid(candidate, "hook_0_trigger_unknown")
        candidate = _well_formed()
        candidate["hooks"][0]["action"] = "rm -rf"
        self.assert_invalid(candidate, "hook_0_action_unknown")

    def test_budget_bytes_frozen_range(self) -> None:
        for malo in (0, 1048577, "5", 3.5, True):
            with self.subTest(budget=malo):
                candidate = _well_formed()
                candidate["hooks"][0]["budget_bytes"] = malo
                self.assert_invalid(candidate, "hook_0_budget_bytes_out_of_range")

    def test_required_only_on_checkpoint(self) -> None:
        candidate = _well_formed()
        candidate["hooks"][0]["required"] = True
        self.assert_invalid(candidate, "hook_0_required_on_non_checkpoint")
        candidate = _well_formed()
        candidate["hooks"][1]["required"] = "sí"
        self.assert_invalid(candidate, "hook_1_required_not_boolean")

    def test_hook_extra_field(self) -> None:
        candidate = _well_formed()
        candidate["hooks"][0]["shell"] = "/bin/sh"
        self.assert_invalid(candidate, "hook_0_shape_invalid")


@unittest.skipUnless(_HAS_JSONSCHEMA, "jsonschema unavailable")
class SchemaParityTests(unittest.TestCase):
    """El módulo y el schema publicado acuerdan el veredicto estructural."""

    def _schema_rejects(self, payload) -> bool:
        errors = sorted(
            Draft202012Validator(_SCHEMA).iter_errors(payload),
            key=lambda e: list(e.path),
        )
        return bool(errors)

    def test_module_and_schema_agree(self) -> None:
        candidate = _well_formed()
        self.assertFalse(host_hooks.validate(candidate))
        self.assertFalse(self._schema_rejects(candidate))
        for mutador, estructural in (
            (lambda c: c.update(schema="an-kla/host-hooks-v99"), True),
            (lambda c: c["hooks"].append("no-soy-objeto"), True),
            (lambda c: c["hooks"][0].update(trigger="whenever"), True),
            (lambda c: c["hooks"][0].pop("id"), True),
            # Cruzadas: sólo el módulo las ve (el schema las permite).
            (lambda c: c["hooks"][0].update(required=True), False),
            (lambda c: c["hooks"].append(dict(c["hooks"][0])), False),
        ):
            with self.subTest(mutacion=mutador.__doc__ or mutador):
                copia = _well_formed()
                mutador(copia)
                modulada = bool(host_hooks.validate(copia))
                self.assertEqual(modulada, self._schema_rejects(copia)
                                 or not estructural)


if __name__ == "__main__":
    unittest.main()
