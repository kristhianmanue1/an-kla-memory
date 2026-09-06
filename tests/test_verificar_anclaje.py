"""test_verificar_anclaje.py — regresión de #116/C1 (beta.22).

compute_refs_digest: quoting de rutas con espacios (sin falsos
anchor_match), fail-closed ante refs/ vacío o ausente, y determinismo
del digest para el layout canónico.
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import verificar_anclaje  # noqa: E402


class ComputeRefsDigestTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="ankla-anclaje-")
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)

    def _write_ref(self, refs_root: Path, name: str, content: bytes) -> None:
        (refs_root / "sha256").mkdir(parents=True, exist_ok=True)
        (refs_root / "sha256" / name).write_bytes(content)

    def test_layout_con_espacios_computa_digest_real(self) -> None:
        # #116/C1: antes, find sin quoting fallaba y la última etapa del
        # pipeline enmascaraba el error -> exit 0 con anchor_match falso.
        refs = self.base / "refs with spaces"
        self._write_ref(refs, "a.txt", b"contenido-anclaje")
        digest = verificar_anclaje.compute_refs_digest(refs)
        self.assertNotEqual(digest, hashlib.sha256(b"").hexdigest())
        self.assertEqual(len(digest), 64)
        # Determinismo.
        self.assertEqual(digest, verificar_anclaje.compute_refs_digest(refs))

    def test_canonical_layout_is_stable(self) -> None:
        refs = self.base / "proyecto" / ".an-kla" / "memory" / "refs"
        self._write_ref(refs, "a.txt", b"contenido")
        digest = verificar_anclaje.compute_refs_digest(refs)
        self.assertEqual(len(digest), 64)
        self.assertNotEqual(digest, hashlib.sha256(b"").hexdigest())

    def test_empty_refs_fails_closed(self) -> None:
        refs = self.base / "refs vacío"
        refs.mkdir(parents=True)
        with self.assertRaises(SystemExit) as ctx:
            verificar_anclaje.compute_refs_digest(refs)
        self.assertEqual(ctx.exception.code, 3)

    def test_missing_refs_fails_closed(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            verificar_anclaje.compute_refs_digest(self.base / "no-existe")
        self.assertEqual(ctx.exception.code, 3)


if __name__ == "__main__":
    unittest.main()
