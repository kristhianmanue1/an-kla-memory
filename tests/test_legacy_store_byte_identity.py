"""Compatibilidad de lectura: un store de la beta.35 da las mismas salidas (ADR-0063, criterio 5).

Los goldens se generaron con el código de `main` (beta.35) antes de tocar nada.
Aquí se recalculan sobre el store versionado y se comparan; un cambio aditivo
(D2 sin llamante) no puede mover ninguno.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import tests.legacy_store_goldens as legacy_store_goldens
from tests.legacy_store_goldens import GOLDENS, STORE_TAR, _cli, compute_fresh, extract_store, sha256_hex


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

    def test_goldens_do_not_inherit_the_developer_store_environment(self) -> None:
        env = {"AN_KLA_STORE_ROOT": "/var/tmp/no-existe", "AN_KLA_PROJECT_ROOT": "/var/tmp/no-existe",
               "AN_KLA_AGENT_CLI": "claude-code"}
        with mock.patch.dict(os.environ, env):
            leaked = legacy_store_goldens._env()
            actual = compute_fresh()
        self.assertEqual(sorted(k for k in leaked if k.startswith("AN_KLA_")),
                         ["AN_KLA_NO_UPDATE_CHECK"])
        self.assertEqual(actual, self.actual)

    def test_tampered_tar_is_rejected_before_it_is_opened(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tampered = Path(tmp) / "store.tar"
            tampered.write_bytes(STORE_TAR.read_bytes() + b"\0")
            project = Path(tmp) / "project"
            with mock.patch.object(legacy_store_goldens, "STORE_TAR", tampered):
                with self.assertRaisesRegex(ValueError, "store_tar_digest_mismatch"):
                    extract_store(project)
            self.assertFalse(project.exists())


class NativeRootTests(unittest.TestCase):
    """The goldens always open the store relocated; this covers the other branch (no goldens)."""

    def test_store_opened_at_its_registered_root_is_not_relocated(self) -> None:
        with tempfile.TemporaryDirectory(prefix="native-root-") as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            self.assertIn(b"rc=0", _cli(project, "init")[0])
            status = json.loads(_cli(project, "status")[1])
            self.assertIs(status["root_relocated"], False)

    def test_the_fixture_store_is_opened_relocated(self) -> None:
        with tempfile.TemporaryDirectory(prefix="relocated-root-") as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            extract_store(project)
            self.assertIs(json.loads(_cli(project, "status")[1])["root_relocated"], True)


if __name__ == "__main__":
    unittest.main()
