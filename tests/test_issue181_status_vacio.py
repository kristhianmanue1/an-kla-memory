"""test_issue181_status_vacio.py — status/nu cadena vacía: coherencia de lectores.

Un record con `status: ""` (o `nu: ""`) es escribible por la política v1.
`is_active` lo trata como no vigente desde siempre, pero hasta beta.34
`inventory` lo contaba como `vigente` (la cadena vacía heredaba el default)
y `verify` no lo informaba como vigencia no canónica. Desde #181 la cadena
vacía no es canónica: inventory la cuenta en `no_canonica`, verify/doctor la
informan sin perder `ok`, y refute/supersede/retrieve siguen excluyéndola
(issue #181, opción 1: bucket coherente con `is_active`; la política de
escritura v1 no cambia).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from an_kla.canonical import digest_json
from an_kla.inventory import NONCANONICAL_STATUS, inventory
from an_kla.retrieval import retrieve
from an_kla.store import MemoryStore
from an_kla.vigency import is_active, is_canonical_vigency

ROOT = Path(__file__).resolve().parents[1]
EMPTY_VIGENCY = {"f-empty-status": {"status": ""}, "f-empty-nu": {"nu": ""}}


class EmptyVigencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="ankla-181-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "proj"
        self.work = Path(self._tmp.name) / "work"
        self.root.mkdir()
        self.work.mkdir()
        self.store = MemoryStore(self.root)
        base = self.store.initialize()
        facts = [
            {"id": "f-ok", "payload": {"text": "registro sano"}},
            {"id": "f-none", "payload": {"text": "status None sigue vigente"},
             "status": None},
        ]
        facts += [dict({"id": rid, "payload": {"text": f"texto raro {rid}"}}, **extra)
                  for rid, extra in EMPTY_VIGENCY.items()]
        self.store.commit(expected_current_hash=base, checkpoint_patch={}, facts=facts)
        self.env = {"PATH": os.environ["PATH"], "AN_KLA_NO_UPDATE_CHECK": "1",
                    "PYTHONPATH": str(ROOT)}

    def _cli(self, args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "an_kla", "--project-root", str(self.root)] + args,
            capture_output=True, text=True, env=self.env, cwd=str(self.work))

    def _raw(self, record_id: str) -> dict:
        snapshot = self.store.snapshot()
        return next(r for r in snapshot.raw_records["facts"] if r.get("id") == record_id)

    def test_predicate_and_is_active_coherence(self) -> None:
        self.assertTrue(is_canonical_vigency({"id": "x"}))
        self.assertTrue(is_canonical_vigency({"status": None}))
        self.assertTrue(is_active({"id": "x"}))
        for extra in EMPTY_VIGENCY.values():
            with self.subTest(extra=extra):
                self.assertFalse(is_canonical_vigency(extra))
                self.assertFalse(is_active(extra))
        # La cadena no vacía sigue siendo canónica y decide su bucket.
        self.assertTrue(is_canonical_vigency({"status": "refutada"}))
        self.assertFalse(is_active({"status": "refutada"}))

    def test_inventory_buckets_empty_as_noncanonical(self) -> None:
        result = inventory(self.store, self.store.read_current())
        by_id = {r["id"]: r for r in result["records"]}
        for rid in EMPTY_VIGENCY:
            with self.subTest(record=rid):
                self.assertEqual(by_id[rid]["physical_status"], NONCANONICAL_STATUS)
                self.assertEqual(by_id[rid]["status"], NONCANONICAL_STATUS)
                self.assertEqual(by_id[rid]["status_source"], "physical")
        # f-none (status None) sigue contando vigente: None es canónico.
        self.assertEqual(by_id["f-none"]["status"], "vigente")
        self.assertEqual(by_id["f-none"]["physical_status"], "vigente")
        counts = result["counts"]["facts"]
        self.assertEqual(counts[NONCANONICAL_STATUS], 2)
        self.assertEqual(counts["vigente"], 2)  # f-ok y f-none
        self.assertNotIn("", counts)
        self.assertEqual(
            counts["total"],
            counts["vigente"] + counts["sustituida"] + counts["refutada"]
            + counts["eliminada"] + counts[NONCANONICAL_STATUS],
        )
        self._validate_schema(result)

    def _validate_schema(self, result: dict) -> None:
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            raise unittest.SkipTest("jsonschema unavailable")
        schema_path = ROOT / "docs/schemas/inventory-v1.schema.json"
        validator = Draft202012Validator(json.loads(schema_path.read_text()))
        validator.validate(result)

    def test_verify_and_doctor_report_empty_vigency(self) -> None:
        verified = self.store.verify()
        self.assertTrue(verified["ok"])
        self.assertEqual(verified["noncanonical_vigency"],
                         {"facts": 2, "events": 0, "episodes": 0})
        self.assertEqual(self.store.doctor()["status"]["noncanonical_vigency"]["facts"], 2)

    def test_clean_store_verify_output_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            clean = MemoryStore(Path(temp))
            clean.initialize()
            self.assertNotIn("noncanonical_vigency", clean.verify())

    def test_retrieve_excludes_empty_vigency(self) -> None:
        result = retrieve(self.store, "texto raro f-empty-status", 4096)
        self.assertNotIn("f-empty-status",
                         [item["id"] for item in result["selected"]])
        healthy = retrieve(self.store, "registro sano", 4096)
        self.assertIn("f-ok", [item["id"] for item in healthy["selected"]])

    def test_refute_inspect_classifies_inactive(self) -> None:
        for rid in EMPTY_VIGENCY:
            with self.subTest(record=rid):
                result = self._cli(["refute", "inspect", "--stream", "facts",
                                    "--record-sha256", digest_json(self._raw(rid))])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["state"], "inactive")

    def test_supersede_fails_closed_without_type_error(self) -> None:
        rev = self.store.read_current()
        proposal = {
            "schema": "an-kla/write-proposal-v1", "base_revision": rev,
            "stream": "facts", "operation": "supersede",
            "requested_representation": "summary", "supersedes": "f-empty-status",
            "record": {"id": "f-empty-status-v2", "text": "corrección"},
            "lineage": {"derived_from_retrieval": False, "refs": []},
        }
        path = self.work / "supersede.json"
        path.write_text(json.dumps(proposal), encoding="utf-8")
        emitted = self._cli(["plan-write", "--proposal", str(path),
                             "--emit-authority-template"])
        self.assertEqual(emitted.returncode, 0, emitted.stderr)
        auth = self.work / "supersede-auth.json"
        auth.write_text(emitted.stdout, encoding="utf-8")
        planned = self._cli(["plan-write", "--proposal", str(path),
                             "--authority", str(auth)])
        self.assertNotEqual(planned.returncode, 0)
        self.assertIn("plan_supersede_target_not_vigente", planned.stderr)
        self.assertNotIn("cli_unexpected_failure", planned.stderr)


if __name__ == "__main__":
    unittest.main()
