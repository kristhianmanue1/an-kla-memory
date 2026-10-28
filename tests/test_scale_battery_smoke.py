"""Smoke tests de la batería de escala (issue #149 Fase 0 + #167 v2).

Validan el cableado de cada escenario en escala diminuta vía el CLI propio
de la batería (`--smoke`): umbrales reales, N reducido. Añade ~25 s (v1) y
~15 s (v2) a la suite; la corrida oficial vive fuera de unittest, en
`benchmarks/scale/results/`.
"""
from __future__ import annotations

import unittest

from benchmarks.scale.battery import SCENARIOS, SCENARIOS_V2, main


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


class ScaleBatteryV2SmokeTests(unittest.TestCase):
    """Cableado v2 (issue #167) en escala diminuta: las cinco familias."""

    def test_smoke_v2_scenarios(self) -> None:
        for name in SCENARIOS_V2:
            with self.subTest(scenario=name):
                rc = main(["--scenario", name, "--smoke"])
                self.assertEqual(rc, 0, f"{name} terminó en error")

    def test_v2_scenarios_in_all(self) -> None:
        from benchmarks.scale.battery import SCENARIO_CHOICES

        for name in SCENARIOS_V2:
            self.assertIn(name, SCENARIO_CHOICES)
        self.assertIn("all-v2", SCENARIO_CHOICES)

    def test_thresholds_v2_loads(self) -> None:
        from benchmarks.scale.core import REPO_ROOT, load_thresholds

        th = load_thresholds(REPO_ROOT / "benchmarks/scale/thresholds-v2.json")
        for key in (
            "ingest_cli",
            "concurrency_v2",
            "rare_query",
            "crash_mid_commit",
            "compaction_large",
            "battery",
        ):
            self.assertIn(key, th)
        # Las secciones v1 siguen presentes para que `--scenario all` funcione.
        for key in ("ingest_governed", "concurrency", "crash", "compaction"):
            self.assertIn(key, th)


if __name__ == "__main__":
    unittest.main()
