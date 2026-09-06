"""test_ci_local_matriz.py — unidad del paso matriz de ci_local (#111/P5).

Con mocks de ``shutil.which`` y del intérprete: resolución de
intérpretes (binario dedicado, fallback al intérprete actual, ausencia
-> SKIP), sin correr suite alguna. La pierna anidada real quedó fuera
de ``test_ci_local_both_modes`` (escape ``AN_KLA_CI_LOCAL_MATRIX=0``)
para no multiplicar corridas completas.
"""

from __future__ import annotations

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys_path = str(Path(__file__).resolve().parents[1] / "scripts")
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

import ci_local  # noqa: E402

#: Hermeticidad: los tests de unidad fuerzan la AUSENCIA del escape,
#: sea cual sea el entorno del proceso que los ejecute (suite anidada,
#: shell del operador, etc.). Se toma snapshot con patch.dict(os.environ)
#: y se elimina la clave a mano: os.environ rechaza valores None.
_SIN_ESCAPE = "AN_KLA_CI_LOCAL_MATRIX"


def _sin_matriz_escape():
    return mock.patch.dict(os.environ)


class InterpreteParaTests(unittest.TestCase):
    def test_prefers_dedicated_binary(self) -> None:
        with mock.patch.object(
            ci_local.shutil, "which", return_value="/opt/bin/python3.12"
        ):
            self.assertEqual(
                ci_local._interprete_para("3.12"), "/opt/bin/python3.12"
            )

    def test_falls_back_to_running_interpreter(self) -> None:
        with mock.patch.object(
            ci_local.shutil, "which", return_value=None
        ), mock.patch.object(ci_local.sys, "version_info", (3, 9, 6, "final", 0)):
            self.assertEqual(
                ci_local._interprete_para("3.9"), ci_local.sys.executable
            )

    def test_absent_version_returns_none(self) -> None:
        with mock.patch.object(
            ci_local.shutil, "which", return_value=None
        ), mock.patch.object(ci_local.sys, "version_info", (3, 12, 0, "final", 0)):
            self.assertIsNone(ci_local._interprete_para("3.9"))


class PasoMatrizTests(unittest.TestCase):
    def _run(self, which_map, executable="/actual/python3"):
        captured = io.StringIO()
        with _sin_matriz_escape(), mock.patch.object(
            ci_local.shutil,
            "which",
            side_effect=lambda name: which_map.get(name),
        ), mock.patch.object(ci_local, "PYTHON", executable), \
           mock.patch.object(ci_local.sys, "executable", executable), \
           mock.patch.object(ci_local.sys, "version_info",
                             (3, 12, 0, "final", 0)), \
           mock.patch.object(ci_local, "subprocess") as sub, \
           redirect_stdout(captured):
            os.environ.pop(_SIN_ESCAPE, None)
            sub.run.return_value = mock.Mock(returncode=0)
            estado = ci_local.paso_matriz()
        return estado, sub, captured.getvalue()

    def test_current_interpreter_covered_without_nested_runs(self) -> None:
        # Sólo 3.12 disponible y coincide con el intérprete actual:
        # cubierto por el paso unittest, cero subprocess de suite.
        estado, sub, salida = self._run({"python3.12": "/actual/python3"})
        self.assertEqual(estado, "OK")
        self.assertIn("cubierto", salida)
        self.assertIn("python3.9: SKIP", salida)
        self.assertIn("python3.13: SKIP", salida)
        sub.run.assert_not_called()

    def test_escape_flag_reports_skip(self) -> None:
        with mock.patch.dict("os.environ", {"AN_KLA_CI_LOCAL_MATRIX": "0"}):
            captured = io.StringIO()
            with redirect_stdout(captured):
                self.assertEqual(ci_local.paso_matriz(), "SKIP")
        self.assertIn("AN_KLA_CI_LOCAL_MATRIX=0", captured.getvalue())

    def test_missing_binary_is_skip_and_foreign_leg_runs_suite(self) -> None:
        estado, sub, salida = self._run(
            {"python3.12": "/opt/py312/bin/python3.12"},
            executable="/actual/python3",
        )
        self.assertEqual(estado, "OK")
        self.assertIn("python3.9: SKIP", salida)
        self.assertIn("python3.13: SKIP", salida)
        sub.run.assert_called_once()  # pierna 3.12 = suite anidada


if __name__ == "__main__":
    unittest.main()
