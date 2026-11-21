"""test_ci_local_matriz.py — unidad del paso matriz de ci_local y de la cuenta de corridas completas (ADR-0074 §3).

Sin correr suite alguna: el paso pesado (``load_guard.run_guarded``) se simula y se cuentan sus llamadas.
"""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys_path = str(Path(__file__).resolve().parents[1] / "scripts")
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

import ci_local  # noqa: E402


def outcome(rc: int = 0) -> mock.Mock:
    return mock.Mock(rc=rc, aborted=False, left=[], reason={})


class PasoMatrizTests(unittest.TestCase):
    def run_paso(self, matriz: bool, *, es_39: bool = True):
        captured = io.StringIO()
        with mock.patch.object(ci_local, "_es_39", return_value=es_39), \
                mock.patch.object(ci_local.load_guard, "run_guarded", return_value=outcome()) as guarded, redirect_stdout(captured):
            estado = ci_local.paso_matriz(matriz)
        return estado, guarded, captured.getvalue()

    def test_without_matrix_it_is_skip_and_runs_nothing(self) -> None:
        estado, guarded, salida = self.run_paso(False)
        self.assertEqual(estado, "SKIP")
        self.assertIn("SKIP (usa --matrix)", salida)
        guarded.assert_not_called()

    def test_with_matrix_it_runs_the_discover_with_the_39_of_usr_bin(self) -> None:
        estado, guarded, salida = self.run_paso(True)
        self.assertEqual(estado, "OK")
        argv = guarded.call_args.args[0]
        self.assertEqual((argv[0], argv[1:3], "discover" in argv), ("/usr/bin/python3", ["-m", "unittest"], True))
        self.assertIn("python3.9: OK", salida)

    def test_with_matrix_but_no_39_it_is_a_declared_skip(self) -> None:
        estado, guarded, salida = self.run_paso(True, es_39=False)
        self.assertEqual(estado, "SKIP")
        self.assertIn("no es Python 3.9", salida)
        guarded.assert_not_called()

    def test_a_failing_39_is_fail(self) -> None:
        with mock.patch.object(ci_local, "_es_39", return_value=True), redirect_stdout(io.StringIO()):
            with mock.patch.object(ci_local.load_guard, "run_guarded", return_value=outcome(1)):
                self.assertEqual(ci_local.paso_matriz(True), "FAIL")

    def test_es_39_requires_an_existing_python_39(self) -> None:
        self.assertFalse(ci_local._es_39("/no/existe/python"))
        with mock.patch.object(ci_local.Path, "exists", return_value=True), \
                mock.patch.object(ci_local.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="3.12\n")):
            self.assertFalse(ci_local._es_39("/x/python3"))
        with mock.patch.object(ci_local.Path, "exists", return_value=True), \
                mock.patch.object(ci_local.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="3.9\n")):
            self.assertTrue(ci_local._es_39("/x/python3"))


class UnaSolaCorridaTests(unittest.TestCase):
    """Aceptación 6: ``ci_local --simulate-ci`` lanza un solo ``discover`` completo (se cuenta); ``--matrix`` lanza además el del 3.9."""

    def count(self, argv: list[str], *, es_39: bool = True) -> list[list[str]]:
        calls: list[list[str]] = []

        def guarded(cmd, **kw):
            calls.append(list(cmd))
            return outcome()

        quiet = [mock.patch.object(ci_local, name, return_value="OK") for name in ("paso_import", "paso_redteam_selftest", "paso_sizes", "paso_plans", "paso_adrs")]
        patches = quiet + [mock.patch.object(ci_local.load_guard, "run_guarded", side_effect=guarded),
                           mock.patch.object(ci_local, "_es_39", return_value=es_39),
                           mock.patch.object(sys, "argv", ["ci_local.py", *argv])]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(ci_local.main(), 0)
        return [cmd for cmd in calls if "discover" in cmd]

    def test_simulate_ci_launches_one_full_discover(self) -> None:
        discovers = self.count(["--simulate-ci"])
        self.assertEqual(len(discovers), 1)
        self.assertEqual(discovers[0][0], sys.executable)

    def test_matrix_adds_the_discover_of_the_39(self) -> None:
        discovers = self.count(["--simulate-ci", "--matrix"])
        self.assertEqual([cmd[0] for cmd in discovers], [sys.executable, "/usr/bin/python3"])

    def test_matrix_without_a_39_adds_nothing(self) -> None:
        self.assertEqual(len(self.count(["--matrix"], es_39=False)), 1)


if __name__ == "__main__":
    unittest.main()
