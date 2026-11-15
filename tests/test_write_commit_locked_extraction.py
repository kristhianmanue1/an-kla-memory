"""Neutralidad de la extracción de ``_commit_write_plan_locked`` (ADR-0063).

Los goldens de ``tests/fixtures/write-commit-goldens/`` se generaron con el
código previo a la extracción; aquí se recalculan y se exige igualdad byte a
byte (resultado o error, y árbol del store).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests import write_commit_scenarios as scenarios

GOLDENS = Path(__file__).parent / "fixtures" / "write-commit-goldens"


class WriteCommitGoldenTests(unittest.TestCase):
    def setUp(self) -> None:
        recorded = json.loads((GOLDENS / "_meta.json").read_text(encoding="utf-8"))
        try:
            actual = scenarios.resolved_base_dir()
        except OSError as exc:
            self.skipTest(f"sin directorio fijo de goldens: {exc}")
        if actual != recorded["base_dir_resolved"]:
            self.skipTest(
                "los digests dependen de la ruta resuelta del proyecto: "
                f"{actual} != {recorded['base_dir_resolved']}"
            )

    def test_every_scenario_has_a_golden_and_vice_versa(self) -> None:
        on_disk = {
            path.stem for path in GOLDENS.glob("*.json") if path.stem != "_meta"
        }
        self.assertEqual(on_disk, set(scenarios.SCENARIOS))

    def test_scenarios_match_goldens_byte_for_byte(self) -> None:
        for name in scenarios.SCENARIOS:
            with self.subTest(scenario=name):
                actual = scenarios.canonical_bytes(
                    scenarios.run_scenario(name, scenarios.default_base_dir())
                )
                expected = (GOLDENS / f"{name}.json").read_bytes()
                self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
