"""Smoke tests de la batería P0 de escala (issue #149, Fase 0).

Validan el cableado de cada escenario en escala diminuta vía el CLI propio
de la batería (`--smoke`): umbrales reales, N reducido. Añade ~25 s a la
suite; la corrida oficial vive fuera de unittest, en
`benchmarks/scale/results/`.
"""
from __future__ import annotations

import unittest

from benchmarks.scale.battery import SCENARIOS, main


class ScaleBatterySmokeTests(unittest.TestCase):
    def test_smoke_all_scenarios(self) -> None:
        for name in SCENARIOS:
            with self.subTest(scenario=name):
                rc = main(["--scenario", name, "--smoke"])
                self.assertEqual(rc, 0, f"{name} terminó en error")

    def test_fingerprint_reports_env(self) -> None:
        from benchmarks.scale.core import env_fingerprint

        env = env_fingerprint()
        self.assertTrue(env["python"].startswith("3."))
        self.assertIn("fts5", env)
        self.assertIn("git_head", env)


if __name__ == "__main__":
    unittest.main()
