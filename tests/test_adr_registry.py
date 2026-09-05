from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_adr_registry.py"
SPEC = importlib.util.spec_from_file_location("check_adr_registry", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AdrRegistryTests(unittest.TestCase):
    def test_state_requires_a_complete_canonical_word(self) -> None:
        self.assertEqual(MODULE.canonical_state("Aceptada."), "Aceptada")
        self.assertIsNone(MODULE.canonical_state("Aceptadaz"))

    def test_repository_registry_is_consistent(self) -> None:
        errors, states = MODULE.check_registry(ROOT)
        self.assertEqual(errors, [])
        self.assertEqual(states["Aceptada"], 43)
        # 0045 aceptada 2026-09-01 (orden explícita del dueño: adoptar
        # Skevi); 0046 aceptada en el ciclo beta.21 (S2 implementado,
        # ed64994); 0044 propuesta (tarjeta ankla-h1c-formalizacion-anclaje)
        # y 0047 host-hooks propuesta (#56/G2, F2 2026-09-05, sesión del
        # maintainer) — las 4 Propuestas vigentes son posteriores a 0043.
        self.assertEqual(states["Propuesta"], 4)

    def test_detects_gap_and_state_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            architecture = root / "docs" / "architecture"
            architecture.mkdir(parents=True)
            (architecture / "0001-first.md").write_text(
                "# ADR-0001: first\n\n- **Estado:** Aceptada\n",
                encoding="utf-8",
            )
            (architecture / "0003-third.md").write_text(
                "# ADR-0003: third\n\n- **Estado:** Propuesta\n",
                encoding="utf-8",
            )
            (root / "docs" / "README.md").write_text(
                "| # | ADR | Tema | Estado | Vigencia o evidencia |\n"
                "|---|---|---|---|---|\n"
                "| 0001 | [first](architecture/0001-first.md) | x | Propuesta | x |\n"
                "| 0003 | [third](architecture/0003-third.md) | x | Propuesta | "
                "[missing](releases/missing.md) |\n",
                encoding="utf-8",
            )

            errors, _states = MODULE.check_registry(root)

        self.assertTrue(any("faltan: [2]" in error for error in errors))
        self.assertTrue(any("ADR-0001: estado del registro" in error for error in errors))
        self.assertIn(
            "referencia local ausente en registro: releases/missing.md", errors
        )


if __name__ == "__main__":
    unittest.main()
