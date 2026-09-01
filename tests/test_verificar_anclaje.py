from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verificar_anclaje.py"

REGISTRY_HEADER = """# Registro de anclas (tmp de test)

| Fecha (UTC) | Digest sha256 (refs/) | Commit/origen | Comparación |
|---|---|---|---|
"""


def run_script(refs_root: Path, registry: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--refs-root",
            str(refs_root),
            "--registry",
            str(registry),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


class VerificarAnclajeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        # Layout canónico: <tmp>/.an-kla/memory/refs — el script detecta el
        # patrón y reproduce el pipeline relativo del protocolo.
        self.refs = (
            self.base / ".an-kla" / "memory" / "refs"
        )
        self.refs.mkdir(parents=True)
        self.registry = self.base / "registro.md"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def digest_of_refs(self) -> str:
        """Digest con el comando EXACTO del protocolo (misma forma que el script)."""
        result = subprocess.run(
            "find .an-kla/memory/refs -type f -exec shasum -a 256 {} + "
            "| sort -k2 | shasum -a 256",
            shell=True,
            capture_output=True,
            text=True,
            check=True,
            cwd=self.base,
        )
        return result.stdout.split()[0]

    def write_registry_with_anchor(self, digest: str) -> None:
        self.registry.write_text(
            REGISTRY_HEADER
            + f"| 2026-08-31T00:00:00Z | `{digest}` | test | primera |\n",
            encoding="utf-8",
        )

    def test_match_returns_0(self) -> None:
        (self.refs / "CURRENT").write_text("sha256:abc", encoding="utf-8")
        self.write_registry_with_anchor(self.digest_of_refs())

        result = run_script(self.refs, self.registry)

        self.assertEqual(result.returncode, 0)
        self.assertIn("anchor_match", result.stdout)

    def test_divergence_returns_1_with_canonical_message(self) -> None:
        (self.refs / "CURRENT").write_text("sha256:abc", encoding="utf-8")
        self.write_registry_with_anchor(self.digest_of_refs())
        # Mutación del store tras el anclaje: CURRENT cambia.
        (self.refs / "CURRENT").write_text("sha256:forged", encoding="utf-8")

        result = run_script(self.refs, self.registry)

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "anchor_divergence: stop fail-closed + escalar al dueño",
            result.stderr,
        )
        self.assertIn("refs_sha256", result.stderr)
        self.assertIn("anchor_sha256", result.stderr)

    def test_registry_without_parsable_row_returns_2(self) -> None:
        (self.refs / "CURRENT").write_text("sha256:abc", encoding="utf-8")
        self.registry.write_text(
            "# Registro sin filas\n\nnada parseable aquí\n", encoding="utf-8"
        )

        result = run_script(self.refs, self.registry)

        self.assertEqual(result.returncode, 2)
        self.assertIn("sin fila de ancla parseable", result.stderr)

    def test_missing_registry_returns_4(self) -> None:
        (self.refs / "CURRENT").write_text("sha256:abc", encoding="utf-8")

        result = run_script(self.refs, self.base / "no-existe.md")

        self.assertEqual(result.returncode, 4)
        self.assertIn("AUSENTE", result.stderr)

    def test_uses_last_parsable_anchor(self) -> None:
        (self.refs / "CURRENT").write_text("sha256:abc", encoding="utf-8")
        digest = self.digest_of_refs()
        old = "0" * 64
        self.registry.write_text(
            REGISTRY_HEADER
            + f"| 2026-08-30T00:00:00Z | `{old}` | viejo | ok |\n"
            + f"| 2026-08-31T00:00:00Z | `{digest}` | nuevo | ok |\n",
            encoding="utf-8",
        )

        result = run_script(self.refs, self.registry)

        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
