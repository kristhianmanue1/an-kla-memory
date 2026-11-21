"""ADR-0074 §6: ``scripts/measure_suite.py`` clasifica por ``argv[0]``, apunta quién pide cada ``git`` y se niega a medir la suite completa por descuido.

Sólo mide un módulo de muestra (``tests/measure_sample_fixture.py``, tres procesos): nunca la suite.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from tests import proc_support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import measure_suite  # noqa: E402


class ClassifyTests(unittest.TestCase):
    def test_by_argv0_not_by_dash_m(self) -> None:
        kind = measure_suite.kind_of
        self.assertEqual(kind(["git", "commit", "-m", "base"]), "git")  # `-m base` es un mensaje de commit, no un módulo (el error del medidor de c74)
        self.assertEqual(kind(["/usr/bin/git", "-C", "x", "init"]), "git")
        self.assertEqual(kind(["/v/bin/python", "-m", "an_kla", "--project-root", "."]), "python -m an_kla")
        self.assertEqual(kind(["python3.12", "-m", "an_kla.mcp"]), "python -m an_kla")
        self.assertEqual(kind([sys.executable, "-m", "unittest", "discover"]), "python -m unittest")
        self.assertEqual(kind([sys.executable, "-c", "pass"]), "python -c")
        self.assertEqual(kind([sys.executable, "script.py"]), "python script")
        self.assertEqual(kind(["tar", "-x"]), "tar")
        self.assertEqual(kind("ps"), "ps")


class MeasureOneModuleTests(unittest.TestCase):
    def test_it_counts_the_spawns_of_a_sample_module_and_names_who_asks_for_git(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            done = proc_support.run(
                [sys.executable, "-B", str(ROOT / "scripts" / "measure_suite.py"), "--out", temp, "tests.measure_sample_fixture"],
                timeout=300, cwd=str(ROOT), capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            data = json.loads((Path(temp) / "medicion.json").read_text())
            self.assertEqual((data["tests_run"], data["ok"]), (1, True))
            self.assertEqual(data["spawns_by_kind"]["git"], 2)
            self.assertEqual(data["spawns_by_kind"]["python -c"], 1)
            self.assertEqual(data["git_by_caller"], {"tests/measure_sample_fixture.py:ask_git_version": 2})  # la función de la pila que lo pide
            row = data["modules"]["tests.measure_sample_fixture"]
            self.assertEqual((row["tests"], row["git"], row["other"]), (1, 2, 1))
            self.assertTrue((Path(temp) / "medicion.md").read_text().startswith("# Medición"))

    def test_it_refuses_to_measure_the_full_suite_by_accident(self) -> None:
        done = proc_support.run([sys.executable, "-B", str(ROOT / "scripts" / "measure_suite.py"), "--out", tempfile.gettempdir()],
                                timeout=60, cwd=str(ROOT), capture_output=True, text=True)
        self.assertEqual(done.returncode, 2)
        self.assertIn("módulos o --full", done.stderr)


if __name__ == "__main__":
    unittest.main()
