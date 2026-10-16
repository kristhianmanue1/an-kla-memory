"""test_issue179_vigencia_no_escalar.py — lectores tolerantes a status/nu no escalares (#179).

Hasta beta.32 el lote `write-proposal-v2` sólo validaba `records[0]`, así que
pudieron persistirse records con `status`/`nu` no escalares. beta.33 ya no los
escribe; estos tests siembran ese estado con el `commit` interno (sin
política) y fijan que los lectores fallan cerrado sin `TypeError`:

- supersede (plan y commit) y refute los tratan como no vigentes;
- `refute inspect` y la proyección de compactación los clasifican `inactive`;
- `inventory` los cuenta como `no_canonica` (no `vigente` ni su repr);
- `verify` (y `doctor`) informan `noncanonical_vigency` sin perder `ok`.
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
from an_kla.compaction_projection import project_snapshot
from an_kla.inventory import NONCANONICAL_STATUS, inventory
from an_kla.store import MemoryStore
from an_kla.vigency import is_canonical_vigency

ROOT = Path(__file__).resolve().parents[1]
POISONED = {"f-nu": {"nu": ["x"]}, "f-st": {"status": 7}, "f-sd": {"status": {"a": 1}}}


class NonScalarVigencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="ankla-179-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "proj"
        self.work = Path(self._tmp.name) / "work"
        self.root.mkdir()
        self.work.mkdir()
        self.store = MemoryStore(self.root)
        base = self.store.initialize()
        facts = [{"id": "f-ok", "payload": {"text": "registro sano"}}]
        facts += [dict({"id": rid, "payload": {"text": "registro de lote antiguo"}}, **extra)
                  for rid, extra in POISONED.items()]
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

    def test_canonical_predicate(self) -> None:
        self.assertTrue(is_canonical_vigency({"id": "x"}))
        self.assertTrue(is_canonical_vigency({"status": None}))
        self.assertTrue(is_canonical_vigency({"nu": "vigente"}))
        for extra in POISONED.values():
            with self.subTest(extra=extra):
                self.assertFalse(is_canonical_vigency(extra))

    def test_verify_and_doctor_report_without_losing_ok(self) -> None:
        verified = self.store.verify()
        self.assertTrue(verified["ok"])
        self.assertEqual(verified["noncanonical_vigency"],
                         {"facts": 3, "events": 0, "episodes": 0})
        self.assertEqual(self.store.doctor()["status"]["noncanonical_vigency"]["facts"], 3)

    def test_clean_store_verify_output_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            clean = MemoryStore(Path(temp))
            clean.initialize()
            self.assertNotIn("noncanonical_vigency", clean.verify())

    def test_inventory_counts_noncanonical_honestly(self) -> None:
        result = inventory(self.store, self.store.read_current())
        by_id = {r["id"]: r for r in result["records"]}
        for rid in POISONED:
            with self.subTest(record=rid):
                self.assertEqual(by_id[rid]["physical_status"], NONCANONICAL_STATUS)
                self.assertEqual(by_id[rid]["status"], NONCANONICAL_STATUS)
                self.assertEqual(by_id[rid]["status_source"], "physical")
        counts = result["counts"]["facts"]
        self.assertEqual(counts[NONCANONICAL_STATUS], 3)
        self.assertEqual(counts["vigente"], 1)
        self.assertNotIn("7", counts)
        self.assertEqual(by_id["f-ok"]["status"], "vigente")

    def test_compaction_projection_tolerates_and_tombstones(self) -> None:
        projection = project_snapshot(self.store.snapshot())
        text = json.dumps(projection, default=str)
        self.assertIn("inactive", text)
        for rid in POISONED:
            with self.subTest(record=rid):
                self.assertIn(digest_json(self._raw(rid)), text)

    def test_refute_inspect_classifies_inactive(self) -> None:
        for rid in POISONED:
            with self.subTest(record=rid):
                result = self._cli(["refute", "inspect", "--stream", "facts",
                                    "--record-sha256", digest_json(self._raw(rid))])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["state"], "inactive")

    def test_supersede_fails_closed_without_type_error(self) -> None:
        rev = self.store.read_current()
        for rid in POISONED:
            with self.subTest(record=rid):
                proposal = {
                    "schema": "an-kla/write-proposal-v1", "base_revision": rev,
                    "stream": "facts", "operation": "supersede",
                    "requested_representation": "summary", "supersedes": rid,
                    "record": {"id": rid + "-v2", "text": "corrección"},
                    "lineage": {"derived_from_retrieval": False, "refs": []},
                }
                path = self.work / f"{rid}.json"
                path.write_text(json.dumps(proposal), encoding="utf-8")
                emitted = self._cli(["plan-write", "--proposal", str(path),
                                     "--emit-authority-template"])
                self.assertEqual(emitted.returncode, 0, emitted.stderr)
                auth = self.work / f"{rid}-auth.json"
                auth.write_text(emitted.stdout, encoding="utf-8")
                planned = self._cli(["plan-write", "--proposal", str(path),
                                     "--authority", str(auth)])
                self.assertNotEqual(planned.returncode, 0)
                self.assertIn("plan_supersede_target_not_vigente", planned.stderr)
                self.assertNotIn("cli_unexpected_failure", planned.stderr)

    def test_batch_supersede_guard_fails_closed(self) -> None:
        rev = self.store.read_current()
        proposal = {
            "schema": "an-kla/write-proposal-v2", "base_revision": rev,
            "stream": "facts", "operation": "supersede",
            "requested_representation": "summary",
            "records": [{"id": "f-nu-v2", "text": "corrección"}],
            "supersedes": {"f-nu-v2": "f-nu"},
            "lineage": {"derived_from_retrieval": False, "refs": []},
        }
        path = self.work / "batch.json"
        path.write_text(json.dumps(proposal), encoding="utf-8")
        emitted = self._cli(["plan-write", "--proposal", str(path), "--emit-authority-template"])
        self.assertEqual(emitted.returncode, 0, emitted.stderr)
        auth = self.work / "batch-auth.json"
        auth.write_text(emitted.stdout, encoding="utf-8")
        planned = self._cli(["plan-write", "--proposal", str(path), "--authority", str(auth)])
        self.assertNotEqual(planned.returncode, 0)
        self.assertIn("plan_supersede_target_not_vigente", planned.stderr)
        self.assertNotIn("cli_unexpected_failure", planned.stderr)


if __name__ == "__main__":
    unittest.main()
