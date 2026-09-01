"""Tests del guard mecánico y del ataque de reescritura consistente (G-3).

Cubre el check guard_store_canonico de la tarjeta ankla-g1-g3:
(a) el script rechaza ejecutar sobre un root con .git/ o docs/architecture/;
(b) el rechazo tiene exit code y mensaje canónicos;
(c) el ataque corre sobre copia desechable y su resultado tiene forma válida.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "redteam_consistent_rewrite.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("redteam_consistent_rewrite", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GuardTests(unittest.TestCase):
    def test_rejects_repository_root(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--target-root", str(REPO_ROOT)],
            capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("redteam_refused: target root looks like a repository checkout", completed.stderr)

    def test_rejects_fake_root_with_git_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "repo-like"
            (fake / ".git").mkdir(parents=True)
            (fake / ".an-kla" / "memory").mkdir(parents=True)
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--target-root", str(fake)],
                capture_output=True, text=True,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("redteam_refused", completed.stderr)

    def test_rejects_fake_root_with_architecture_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "docs-like"
            (fake / "docs" / "architecture").mkdir(parents=True)
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--target-root", str(fake)],
                capture_output=True, text=True,
            )
            self.assertEqual(completed.returncode, 2)

    def test_no_target_root_refuses(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT)],
            capture_output=True, text=True,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("redteam_refused", completed.stderr)

    def test_missing_memory_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty"
            empty.mkdir()
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--target-root", str(empty)],
                capture_output=True, text=True,
            )
            self.assertEqual(completed.returncode, 3)


class AttackShapeTests(unittest.TestCase):
    """El ataque completo requiere un .an-kla real; se prueba vía selftest.

    El selftest ejercita guard + copia desechable + ataque + verificación y
    es el camino canónico; aquí validamos la forma del módulo cargado para
    no duplicar la corrida costosa.
    """

    def test_result_schema_constant(self) -> None:
        module = _load_script()
        # Sin fallback hasattr: si el atributo desaparece o cambia de nombre,
        # el test debe FALLAR, no comparar el literal contra sí mismo.
        self.assertEqual(
            module.RESULT_SCHEMA,
            "an-kla/redteam-consistent-rewrite-result/v1",
        )

    def test_forged_record_id_is_stable(self) -> None:
        module = _load_script()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = {
                "id": "f-adversarial-consistent-rewrite-v1",
                "payload": {"text": "x", "topic": "adversarial-redteam"},
                "provenance": {
                    "kind": "git_document",
                    "repository": "r",
                    "commit": "0" * 40,
                    "path": "p",
                    "sha256": "0" * 64,
                },
                "schema": "an-kla/fact-v1",
                "status": "active",
            }
            segment_id = module.write_segment(root, "facts", [record])
            self.assertTrue(segment_id.startswith("sha256:"))
            stored = (
                root / ".an-kla" / "memory" / "segments" / "facts" / "sha256" /
                (segment_id[7:] + ".jsonl")
            )
            self.assertIn("f-adversarial-consistent-rewrite-v1", stored.read_text())


if __name__ == "__main__":
    unittest.main()
