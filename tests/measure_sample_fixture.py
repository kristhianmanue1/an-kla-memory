"""Módulo de muestra para ``tests/test_measure_suite.py``: lanza unos pocos procesos conocidos y nada más. No se descubre (no empieza por ``test_``)."""

from __future__ import annotations

import subprocess
import sys
import unittest


def ask_git_version() -> None:
    subprocess.run(["git", "--version"], capture_output=True, check=True)


class SampleTests(unittest.TestCase):
    def test_spawns_two_git_and_one_python(self) -> None:
        ask_git_version()
        ask_git_version()
        subprocess.run([sys.executable, "-c", "pass"], check=True)
