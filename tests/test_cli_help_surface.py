"""Superficie de ayuda del CLI: todo comando de primer nivel documentado.

Alcance declarado (no-goal): subcomandos anidados; sólo se fijan los
comandos de primer nivel y los flags con texto distintivo. Un comando sin
help aparece en el metavar pero NO tiene fila propia en la sección
detallada: este test exige esa fila (técnica de la ronda adversarial
P3-2026-08-20).
"""

from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _help(argv: list[str]) -> str:
    completed = subprocess.run(
        [sys.executable, "-m", "an_kla", "--no-update-check", *argv, "--help"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    return completed.stdout


def _documented_rows(text: str) -> set[str]:
    """Commands with their own row in the detailed section: either the
    description follows on the same line, or the name wraps alone and the
    description starts on the next indented line (argparse wraps long
    names). The comma-separated metavar never matches: names there are
    not at line start."""

    detailed = text.split("positional arguments:", 1)[1]
    same_line = re.findall(r"^\s{2,}([a-z][a-z0-9-]+)\s{2,}\S", detailed, re.MULTILINE)
    wrapped = re.findall(r"^\s{2,}([a-z][a-z0-9-]+)\s*$", detailed, re.MULTILINE)
    return set(same_line) | set(wrapped)


class CliHelpSurfaceTests(unittest.TestCase):
    def test_every_top_level_command_has_a_help_row(self) -> None:
        text = _help([])
        listed = text.split("{", 1)[1].split("}", 1)[0].split(",")
        self.assertGreater(len(listed), 25)
        documented = _documented_rows(text)
        missing = sorted(set(listed) - documented)
        self.assertEqual(missing, [], f"comandos sin help: {missing}")

    def test_help_row_requirement_actually_detects_missing_help(self) -> None:
        # Guard the guard: a bare-name row (no description) must not count.
        self.assertNotIn("barecommand", _documented_rows("positional arguments:\n  {a,barecommand}\n  a    described\n"))

    def test_retrieve_flags_explain_distinctive_semantics(self) -> None:
        text = _help(["retrieve"])
        for fragment in ("bytes UTF-8", "denominadores", "ISO-8601", "stale"):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, text)

    def test_assemble_context_flags_explain_distinctive_semantics(self) -> None:
        text = _help(["assemble-context"])
        for fragment in (
            "sección indivisible",
            "framing del host no se mide",
            "ISO-8601",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, text)

    def test_mutating_and_versioned_surfaces_are_flagged(self) -> None:
        # Subparser help= appears in the parent listing (discovery surface).
        self.assertIn("MUTATIVO", _help(["transaction"]))
        self.assertIn("sha256", _help(["verify"]))
        self.assertIn("plan_fingerprint", _help(["upgrade", "apply"]))
        self.assertIn("Evaluar recuperación (v1)", _help([]))


if __name__ == "__main__":
    unittest.main()
