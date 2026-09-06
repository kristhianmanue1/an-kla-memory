"""Absorción beta.22 de los issues #113 (R1), #114 (A1/A2) y #115 (T2).

Auditoría externa sobre beta.21 (4d651d2), revalidada en main antes de
corregir. R1 fue reproducido por el ejecutor: escritura gobernada con
`status: []` commits y después tumba a retrieve/index/evaluation con
TypeError (pertenencia en set sobre un no-hashable).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from an_kla import attest
from an_kla.canonical import digest_json
from an_kla.index import build_index
from an_kla.retrieval import retrieve
from an_kla.store import MemoryStore
from an_kla.vigency import is_active

ROOT = Path(__file__).resolve().parents[1]


class WriteSideRejectsNonScalarTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="ankla-r1-write-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = MemoryStore(self.root)
        self.store.initialize()

    def _candidate(self, extra_record: dict) -> dict:
        return {
            "schema": "an-kla/write-proposal-v1",
            "base_revision": self.store.read_current(),
            "stream": "facts",
            "operation": "add",
            "requested_representation": "summary",
            "record": {
                "id": "f-r1",
                "payload": {"text": "texto indexable"},
                **extra_record,
            },
            "lineage": {"derived_from_retrieval": False, "refs": []},
        }

    def test_policy_rejects_non_scalar_status_and_nu(self) -> None:
        for extra in ({"status": []}, {"status": {}}, {"nu": []},
                      {"status": ["vigente"]}):
            with self.subTest(extra=extra):
                with self.assertRaises(Exception) as ctx:
                    self.store.plan_write(self._candidate(extra), {
                        "schema": "an-kla/write-authority-v1",
                        "proposal_sha256": digest_json(self._candidate(extra)),
                        "base_revision": self.store.read_current(),
                        "authority_class": "model_derived",
                        "issuer": {"kind": "model", "id": "t",
                                   "configuration_fingerprint": "sha256:" + "0"*64},
                        "evidence": [],
                        "scope": {"streams": ["facts"],
                                  "representations": ["summary"],
                                  "operations": ["add"]},
                    })
            del ctx


class ReadSideDegradesTests(unittest.TestCase):
    """Registro envenenado YA persistido: los lectores no se tumban."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="ankla-r1-read-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = MemoryStore(self.root)
        self.root_revision = self.store.initialize()
        self.store.commit(
            expected_current_hash=self.root_revision,
            checkpoint_patch={},
            facts=[
                {"id": "f-veneno", "payload": {"text": "registro envenenado"},
                 "status": []},
                {"id": "f-sano", "payload": {"text": "memoria sana revalidar"}},
            ],
        )

    def test_vigency_predicate_is_fail_closed(self) -> None:
        self.assertFalse(is_active({"status": []}))
        self.assertFalse(is_active({"status": {}}))
        self.assertFalse(is_active({"nu": ["vigente"]}))
        self.assertTrue(is_active({"status": "vigente"}))
        self.assertTrue(is_active({}))
        self.assertTrue(is_active({"status": None}))

    def test_retrieve_serves_healthy_and_excludes_poisoned(self) -> None:
        result = retrieve(self.store, "memoria sana", 2000)
        served = {item["id"] for item in result["selected"]}
        self.assertIn("f-sano", served)
        self.assertNotIn("f-veneno", served)

    def test_rebuild_index_does_not_crash(self) -> None:
        build_index(self.store)  # no debe lanzar TypeError


class AttestPartialWriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="ankla-a1-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / ".an-kla").mkdir(parents=True)

    def test_partial_os_write_still_yields_complete_key(self) -> None:
        # Issue #114/A1: os.write que escribe de a 1 byte; el bucle de
        # _write_exclusive debe completar los 32 bytes de la clave.
        real_write = os.write

        def one_byte_write(fd, data):
            return real_write(fd, data[:1])

        with mock.patch("an_kla.attest.os.write", side_effect=one_byte_write):
            result = attest.ensure_attest_files(self.root)
        self.assertEqual(result["created"], ["attest.key", "attest-whitelist.json"])
        key = attest._load_key(self.root)
        self.assertEqual(len(key), 32)


class AttestContentAddressTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="ankla-a2-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = MemoryStore(self.root)
        self.store.initialize()
        attest.ensure_attest_files(self.root)

    def _receipt_result(self) -> dict:
        whitelist = {
            "schema": "an-kla/attest-whitelist-v1",
            "entries": [
                {"argv_prefix": [sys.executable, "-c"], "deny_flags": []},
            ],
        }
        (self.root / ".an-kla" / "attest-whitelist.json").write_text(
            json.dumps(whitelist, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        return attest.attest_run(
            self.root, [sys.executable, "-c", "print('hola')"],
        )

    def _authority(self, receipt_result: dict, sha: str | None = None) -> dict:
        receipt = receipt_result["receipt"]
        return {
            "schema": "an-kla/write-authority-v2",
            "proposal_sha256": digest_json({"k": "c"}),
            "base_revision": "sha256:" + "0" * 64,
            "authority_class": "tool_observed",
            "issuer": {"kind": "tool", "id": "an-kla-attest",
                       "configuration_fingerprint": "sha256:" + "b" * 64},
            "evidence": [{
                "kind": "attestation_receipt",
                "id": receipt["receipt_id"],
                "sha256": sha or receipt_result["receipt_digest"],
                "resolution": "verified",
            }],
            "scope": {"streams": ["facts"], "representations": ["summary"],
                      "operations": ["add"]},
        }

    def test_rewritten_receipt_file_is_rejected(self) -> None:
        # Issue #114/A2: un receipt válido reescrito con otro contenido
        # bajo la misma dirección content-addressed se rechaza.
        receipt_result = self._receipt_result()
        receipt_path = self.root / ".an-kla" / "receipts" / "receipts" / "sha256" / (
            receipt_result["receipt_digest"][len("sha256:"):] + ".json"
        )
        minted = json.loads(receipt_path.read_text(encoding="utf-8"))
        minted["command"] = ["/bin/otro-comando"]  # mentira con la firma vieja
        receipt_path.write_text(json.dumps(minted), encoding="utf-8")
        with self.assertRaises(attest.AttestError) as ctx:
            attest.verify_receipt_for_authority(
                self.store, self._authority(receipt_result))
        self.assertEqual(ctx.exception.code, "receipt_invalid")
        self.assertEqual(ctx.exception.detail, "receipt_digest_mismatch")


class InitOutcomePreservedTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="ankla-t2-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = MemoryStore(self.root)

    def test_attest_oserror_after_commit_keeps_init_outcome(self) -> None:
        # Issue #115/T2: un fallo operacional de attest tras el bootstrap
        # no puede ocultar un init ya comprometido.
        from an_kla import store as store_module

        with mock.patch.object(
            store_module.attest_module, "ensure_attest_files",
            side_effect=OSError(28, "No space left on device"),
        ):
            result = self.store.initialize_with_outcome()
        self.assertIs(result["outcome"]["committed"], True)
        self.assertEqual(
            result["attestation"].get("error"), "attest_init_unwritable"
        )


if __name__ == "__main__":
    unittest.main()
