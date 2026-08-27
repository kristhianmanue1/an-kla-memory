"""Tests de disponibilidad del perfil sellado — esqueleto T1 (issue #46).

Fijan el contrato de fail-closed sin el extra ``[sealed]``:

1. ``sealed_available`` es ``False`` cuando ``cryptography`` no está
   instalada en el intérprete que corre la suite (entorno canónico del
   proyecto: el extra se declara pero NO se instala).
2. Todo comando sellado (``sealed_export``/``sealed_restore``) falla
   cerrado con ``SealedExtraNotInstalledError`` — código canónico
   ``sealing_extra_not_installed`` — y sin degradarse a texto claro.
3. El core sigue siendo importable stdlib-only: importar ``an_kla``
   (y ``an_kla.sealed``) jamás importa ``cryptography`` a nivel top-level.

La suite NO declara ``cryptography`` como dependencia de test (sólo
``jsonschema`` vía el extra ``test``): si alguien la instala en el entorno
de CI, estos tests de disponibilidad se saltan (skip) en vez de mentir
en rojo — la señal de ausencia del extra es una propiedad del entorno.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
import unittest


def _cryptography_importable() -> bool:
    try:
        import cryptography  # noqa: F401
    except ImportError:
        return False
    return True


class TestSealedAvailability(unittest.TestCase):
    def setUp(self):
        import an_kla.sealed as sealed

        self.sealed = sealed

    def test_sealed_available_false_without_extra(self):
        """Sin el extra instalado, sealed_available es exactamente False."""
        if _cryptography_importable():
            self.skipTest("cryptography presente en el intérprete; "
                          "la señal de ausencia no es observable aquí")
        self.assertIs(self.sealed.sealed_available, False)

    def test_sealed_available_is_bool(self):
        """El tipo del flag es bool en cualquier entorno (contrato estable)."""
        self.assertIsInstance(self.sealed.sealed_available, bool)

    def test_canonical_error_code_is_stable(self):
        """El código canónico no cambia entre fases (T2+ lo reutilizan)."""
        self.assertEqual(self.sealed.SEALED_EXTRA_ERROR_CODE,
                         "sealing_extra_not_installed")

    def test_error_class_is_runtime_error(self):
        """El error canónico es RuntimeError: terminal, no de validación."""
        self.assertTrue(issubclass(
            self.sealed.SealedExtraNotInstalledError, RuntimeError))


class TestSealedFailClosed(unittest.TestCase):
    """Todo comando sellado falla cerrado sin el extra."""

    COMMANDS = ("sealed_export", "sealed_restore")

    def test_commands_fail_closed_without_extra(self):
        import an_kla.sealed as sealed

        for command in self.COMMANDS:
            with self.subTest(command=command):
                if sealed.sealed_available:
                    self.skipTest(
                        "extra [sealed] presente: el fail-closed por "
                        "ausencia no es observable en este intérprete")
                with self.assertRaises(sealed.SealedExtraNotInstalledError):
                    getattr(sealed, command)([])
                # Ningún comando devuelve éxito silencioso (fallback claro).
                self.assertIs(
                    getattr(sealed, command, None).__doc__ is not None, True)

    def test_error_message_names_extra(self):
        """El error dice cómo remediarlo: instalar el extra [sealed]."""
        import an_kla.sealed as sealed

        if sealed.sealed_available:
            self.skipTest("extra [sealed] presente")
        with self.assertRaises(sealed.SealedExtraNotInstalledError) as ctx:
            sealed.sealed_export([])
        self.assertIn("sealed", str(ctx.exception))


class TestCoreStdlibOnly(unittest.TestCase):
    """El core no adquiere dependencias por el esqueleto sellado."""

    def test_import_an_kla_does_not_import_cryptography(self):
        """Importar el core en un intérprete limpio no toca cryptography."""
        code = (
            "import sys\n"
            "[sys.modules.pop(m, None) for m in list(sys.modules)\n"
            " if m.startswith('cryptography')]\n"
            "import an_kla\n"
            "assert not any(m == 'cryptography' or m.startswith("
            "'cryptography.')\n"
            "               for m in sys.modules), 'core imported cryptography'\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True,
            cwd=__file__.rsplit("/tests/", 1)[0] or ".",
        )
        self.assertEqual(
            result.returncode, 0,
            msg=f"stderr: {result.stderr}\nstdout: {result.stdout}")

    def test_import_sealed_submodule_survives_missing_cryptography(self):
        """an_kla.sealed es importable aunque cryptography falte por completo.

        Se fuerza el fallo del import de cryptography con un bloqueador en
        meta_path: el esqueleto debe degradarse a sealed_available=False,
        nunca a ImportError del submódulo.
        """
        code = (
            "import sys\n"
            "class _Block:\n"
            "    def find_spec(self, name, path=None, target=None):\n"
            "        if name == 'cryptography' or name.startswith("
            "'cryptography.'):\n"
            "            raise ImportError('blocked for test')\n"
            "        return None\n"
            "sys.meta_path.insert(0, _Block())\n"
            "sys.modules.pop('cryptography', None)\n"
            "import an_kla.sealed as s\n"
            "assert s.sealed_available is False, s.sealed_available\n"
            "try:\n"
            "    s.sealed_export([])\n"
            "except s.SealedExtraNotInstalledError:\n"
            "    pass\n"
            "else:\n"
            "    raise AssertionError('sealed_export did not fail closed')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True,
            cwd=__file__.rsplit("/tests/", 1)[0] or ".",
        )
        self.assertEqual(
            result.returncode, 0,
            msg=f"stderr: {result.stderr}\nstdout: {result.stdout}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
