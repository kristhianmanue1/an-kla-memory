"""Compatibilidad de lectura: un store de la beta.35 da las mismas salidas (ADR-0063, criterio 5).

Los goldens se generaron con el código de `main` (beta.35) antes de tocar nada.
Aquí se recalculan sobre el store versionado y se comparan; un cambio aditivo
(D2 sin llamante) no puede mover ninguno.
"""

from __future__ import annotations

import json
import unittest

from legacy_store_goldens import GOLDENS, STORE_TAR, compute_fresh, sha256_hex


class LegacyStoreByteIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.expected = json.loads(GOLDENS.read_text(encoding="utf-8"))
        cls.actual = compute_fresh()

    def test_fixture_tar_is_the_one_the_goldens_were_made_from(self) -> None:
        self.assertEqual(sha256_hex(STORE_TAR.read_bytes()), self.expected["store_tar_sha256"])

    def test_every_golden_is_recomputed_identically(self) -> None:
        goldens = self.expected["goldens"]
        self.assertEqual(sorted(self.actual), sorted(goldens))
        for name, digest in goldens.items():
            with self.subTest(golden=name):
                self.assertEqual(self.actual[name], digest)

    def test_goldens_cover_the_surfaces_the_adr_names(self) -> None:
        names = set(self.expected["goldens"])
        for required in (
            "cli.status", "cli.verify", "cli.inventory", "cli.retrieve", "cli.resume",
            "cli.assemble_context", "export.manifest_sha256", "export.entries_sha256",
            "policy_fingerprint", "mcp.tools_list", "mcp.an_kla_retrieve",
        ):
            self.assertIn(required, names)


if __name__ == "__main__":
    unittest.main()
