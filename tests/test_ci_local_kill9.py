"""test_ci_local_kill9.py — unidad del paso `kill -9` de la bandeja en ci_local (ADR-0063, criterio 3).

La matriz real es lenta y se salta en ``unittest discover`` sin ``AN_KLA_SLOW_KILL9=1``; ci_local
la corre en un paso propio con esa variable (decisión del orquestador: fuera de cada push, dentro
de ci_local). Aquí sólo se comprueba el paso, sin lanzar la matriz.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ci_local  # noqa: E402


class KillNinePassTests(unittest.TestCase):
    def test_skip_with_the_escape_variable_and_without_running_anything(self) -> None:
        with mock.patch.dict(os.environ, {"AN_KLA_CI_LOCAL_KILL9": "0"}), mock.patch.object(
            ci_local, "subprocess"
        ) as sub:
            self.assertEqual(ci_local.paso_kill9_bandeja(), "SKIP")
        sub.run.assert_not_called()

    def test_runs_the_matrix_with_the_slow_variable_and_maps_the_exit_code(self) -> None:
        for code, expected in ((0, "OK"), (1, "FAIL")):
            with self.subTest(code=code):
                env = {k: v for k, v in os.environ.items() if k != "AN_KLA_CI_LOCAL_KILL9"}
                with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(ci_local, "subprocess") as sub:
                    sub.run.return_value.returncode = code
                    self.assertEqual(ci_local.paso_kill9_bandeja(), expected)
                args, kwargs = sub.run.call_args
                self.assertEqual(args[0][-1], "tests.test_inbox_crash.Kill9MatrixTests")
                self.assertEqual(kwargs["env"]["AN_KLA_SLOW_KILL9"], "1")
                self.assertEqual(kwargs["cwd"], ci_local.ROOT)

    def test_is_part_of_the_summary_and_the_slow_test_skips_without_the_variable(self) -> None:
        source = (ROOT / "scripts" / "ci_local.py").read_text()
        self.assertIn('"kill9_bandeja": paso_kill9_bandeja()', source)
        crash = (ROOT / "tests" / "test_inbox_crash.py").read_text()
        self.assertIn('@unittest.skipUnless(SLOW, "prueba lenta', crash)
        self.assertIn('os.environ.get("AN_KLA_SLOW_KILL9") == "1"', crash)


if __name__ == "__main__":
    unittest.main()
