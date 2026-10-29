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
        # 0045 aceptada 2026-09-01 (orden explícita del dueño: adoptar
        # Skevi); 0046 aceptada en el ciclo beta.21 (S2 implementado,
        # ed64994); 0047 aceptada 2026-09-05 (orden del dueño, G2 #56);
        # 0048 aceptada 2026-09-05 (orden del dueño, G3 #57); 0049
        # aceptada 2026-09-11 (orden del dueño, ciclo zero_score #118/#133)
        # — las 3 Propuestas vigentes (0029, 0030, 0044) son posteriores a
        # 0028. 0050 (descubrimiento de stores, #134) propuesta 2026-10-13
        # por D0 del plan G3 y aceptada el mismo día por el dueño. 0051
        # (rediseño de attach) propuesta 2026-10-13 por la regla de corte.
        # 0052/0053/0054 (resolver del host, watermark incremental, lote
        # gobernado) propuestas 2026-10-14 por la mesa de diseño del plan
        # de escalado (#140/#149), PRs #155-#157; aceptadas por orden del
        # maintainer (2026-10-15). 0055 (poda de índices) aceptada e
        # implementada 2026-10-15; 0056 (caché de segmentos) propuesta
        # con tradeoff de tamper-evidence pendiente de decisión. 0057
        # (lectura sin re-canonicalización) aceptada e implementada el
        # mismo día tras spike de perfilado. 0058 (paginación de
        # context_view en el origen, #149 P2b/#165) propuesta 2026-10-15
        # tras spike pre-implementación; aceptada e implementada el mismo
        # día por orden del maintainer ("ADELANTE CON PENDIENTES") tras
        # absorber la ronda adversarial fix-and-retry. 0059/0060 (gate del
        # escritor acotado y planificación coherente, #186/#187) propuestas
        # 2026-10-29 con ronda externa fix-and-retry→proceed; aceptadas e
        # implementadas por orden del maintainer ("aceptada").
        self.assertEqual(states["Propuesta"], 5)
        self.assertEqual(states["Aceptada"], 55)

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
