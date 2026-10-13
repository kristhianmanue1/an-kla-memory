"""G3 R2a: governed relocate plan/commit, crash points and concurrency
(ADR-0048 §3).  Every failure leaves an identifiable state with a recovery
path; the origin is deleted only after the pointer exists."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from an_kla import relocate
from an_kla.attest import attest_run
from an_kla.custody import custody_fingerprint, pointer_path, read_pointer
from an_kla.identity import read_binding
from an_kla.relocation_receipts import load_relocation_receipt
from an_kla.relocate import (
    RelocateError, SimulatedCrash, commit_relocation, inspect_relocation,
    plan_relocation, reconcile_relocation,
)
from an_kla.store import MemoryStore
from tests.test_custody_root import _commit_fact

ROOT = Path(__file__).resolve().parents[1]
_POINTS = ("journal_staging", "before_publish", "after_rename", "after_publish", "after_pointer")


def _crash_at(point: str):
    def fault(name: str) -> None:
        if name == point:
            raise SimulatedCrash(name)

    return fault


class RelocateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name).resolve()
        self.project = self.base / "project"
        self.project.mkdir()
        self.vault = self.base / "vaults" / "vault"
        self.store = MemoryStore(self.project)
        self.store.initialize()
        self.revision = _commit_fact(self.store, "f-before")
        attest_run(self.project, ["git", "diff"])
        self.fingerprint = custody_fingerprint(read_binding(self.store))
        self.addCleanup(setattr, relocate, "_fault", None)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _plan(self) -> dict:
        return plan_relocation(self.store, self.vault)

    def _assert_relocated(self, result: dict) -> None:
        self.assertEqual(result["stage"], "cleaned")
        destination = MemoryStore(self.project, store_root=self.vault)
        verified = destination.verify()
        self.assertEqual(verified["revision"], self.revision)
        self.assertEqual(verified["identity_status"], "complete")
        self.assertEqual(custody_fingerprint(read_binding(destination)), self.fingerprint)
        pointer = read_pointer(self.project)
        self.assertEqual(pointer["store_root"], str(self.vault))
        self.assertEqual(pointer["custody_fingerprint"], self.fingerprint)
        receipt = load_relocation_receipt(destination, result["relocation_receipt"])
        self.assertEqual(receipt["kind"], "store_root")
        self.assertEqual(receipt["to_root_observed"], str(self.vault))
        self.assertTrue((self.vault / "attest.key").exists())
        anchor = self.project / ".an-kla"
        for gone in ("project-identity.json", "attest.key", "memory/refs/CURRENT", "memory/identity.json"):
            self.assertFalse((anchor / gone).exists(), gone)
        self.assertEqual(result["cleanup"]["residue"], [])
        self.assertFalse(any(path.name.startswith(".staging-") for path in self.vault.parent.iterdir()))

    def _assert_origin_intact(self) -> None:
        self.assertIsNone(read_pointer(self.project))
        self.assertEqual(MemoryStore(self.project).verify()["revision"], self.revision)
        self.assertFalse(self.vault.exists())
        self.assertFalse(any(path.name.startswith(".staging-") for path in self.vault.parent.iterdir()))

    def test_plan_commit_moves_the_exact_set_and_writes_the_pointer(self) -> None:
        plan = self._plan()
        paths = {entry["path"] for entry in plan["core"]["entries"]}
        self.assertIn("anchor/attest.key", paths)
        self.assertIn("anchor/memory/refs/CURRENT", paths)
        self.assertTrue(any(path.startswith("anchor/receipts/receipts/") for path in paths))
        self.assertFalse(any("indexes/" in path or path.endswith(".lock") for path in paths))
        result = commit_relocation(self.store, plan, self.revision)
        self._assert_relocated(result)
        # The relocated vault keeps working through the pointer.
        destination = MemoryStore(self.project, store_root=self.vault)
        after = _commit_fact(destination, "f-after")
        self.assertEqual(destination.verify()["revision"], after)
        # A timed-out caller repeating the commit gets the same result.
        replay = commit_relocation(destination, plan, self.revision)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["relocation_receipt"], result["relocation_receipt"])

    def test_fail_closed_cases_keep_the_origin(self) -> None:
        plan = self._plan()
        with self.assertRaises(RelocateError) as caught:
            commit_relocation(self.store, plan, "sha256:" + "0" * 64)
        self.assertEqual(str(caught.exception), "relocate_expected_current_mismatch")
        tampered = json.loads(json.dumps(plan))
        tampered["core"]["destination_store_root"] = str(self.base / "elsewhere")
        with self.assertRaises(RelocateError) as caught:
            commit_relocation(self.store, tampered, self.revision)
        self.assertEqual(str(caught.exception), "relocate_plan_digest_mismatch")

        self.vault.mkdir(parents=True)
        with self.assertRaises(RelocateError) as caught:
            commit_relocation(self.store, plan, self.revision)
        self.assertEqual(str(caught.exception), "relocate_destination_exists")
        self.vault.rmdir()
        self._assert_origin_intact()

        whitelist = self.project / ".an-kla" / "attest-whitelist.json"
        original = whitelist.read_bytes()
        whitelist.write_bytes(original + b" ")
        with self.assertRaises(RelocateError) as caught:
            commit_relocation(self.store, plan, self.revision)
        self.assertEqual(str(caught.exception), "relocate_source_changed")
        self.assertEqual(inspect_relocation(self.project, plan["core"]["transaction_id"])["stage"], "aborted")
        whitelist.write_bytes(original)
        self._assert_origin_intact()
        with self.assertRaises(RelocateError) as caught:
            commit_relocation(self.store, plan, self.revision)
        self.assertEqual(str(caught.exception), "relocate_transaction_aborted")

        plan = self._plan()
        self.revision = _commit_fact(self.store, "f-moved-on")
        with self.assertRaises(RelocateError) as caught:
            commit_relocation(self.store, plan, plan["core"]["base_revision"])
        self.assertEqual(str(caught.exception), "relocate_base_changed")
        self._assert_origin_intact()

    def test_late_lock_free_evidence_stays_in_origin_and_is_reported(self) -> None:
        plan = self._plan()
        late = attest_run(self.project, ["git", "diff"])
        result = commit_relocation(self.store, plan, self.revision)
        late_path = late["receipt_path"].removeprefix(".an-kla/")
        self.assertEqual(result["lock_free_residue"], ["anchor/" + late_path])
        self.assertIn(late_path, result["cleanup"]["residue"])
        self.assertTrue((self.project / ".an-kla" / late_path).exists())
        self.assertFalse((self.vault / late_path).exists())
        destination = MemoryStore(self.project, store_root=self.vault)
        self.assertEqual(destination.doctor()["custody_divergence"]["project_local_residue"], 1)

    def test_crash_points_have_an_identifiable_recovery(self) -> None:
        for point in _POINTS:
            with self.subTest(point=point):
                self.tearDown()
                self.setUp()
                plan = self._plan()
                txid = plan["core"]["transaction_id"]
                relocate._fault = _crash_at(point)
                with self.assertRaises(SimulatedCrash):
                    commit_relocation(self.store, plan, self.revision)
                relocate._fault = None
                inspected = inspect_relocation(self.project, txid)
                expected_stage = {
                    "journal_staging": "staging", "before_publish": "staging",
                    "after_rename": "staging", "after_publish": "published",
                    "after_pointer": "pointer_written",
                }[point]
                self.assertEqual(inspected["stage"], expected_stage)
                self.assertEqual(
                    inspected["observed"]["destination_present"],
                    point not in {"journal_staging", "before_publish"},
                )
                with self.assertRaises(RelocateError) as caught:
                    commit_relocation(self.store, plan, self.revision)
                self.assertEqual(str(caught.exception), "relocate_reconcile_required")
                result = reconcile_relocation(self.project, txid)
                if point in {"journal_staging", "before_publish"}:
                    self.assertEqual(result["stage"], "aborted")
                    self._assert_origin_intact()
                else:
                    self._assert_relocated(result)
                again = reconcile_relocation(self.project, txid)
                self.assertTrue(again["replayed"])

    def test_abort_before_pointer_and_too_late_after(self) -> None:
        plan = self._plan()
        txid = plan["core"]["transaction_id"]
        relocate._fault = _crash_at("after_publish")
        with self.assertRaises(SimulatedCrash):
            commit_relocation(self.store, plan, self.revision)
        relocate._fault = None
        # The origin moved on after the crash: the copy is stale.
        self.revision = _commit_fact(MemoryStore(self.project), "f-after-crash")
        with self.assertRaises(RelocateError) as caught:
            reconcile_relocation(self.project, txid)
        self.assertEqual(str(caught.exception), "relocate_source_advanced")
        self.assertEqual(reconcile_relocation(self.project, txid, abort=True)["stage"], "aborted")
        self._assert_origin_intact()

        plan = self._plan()
        relocate._fault = _crash_at("after_pointer")
        with self.assertRaises(SimulatedCrash):
            commit_relocation(self.store, plan, self.revision)
        relocate._fault = None
        with self.assertRaises(RelocateError) as caught:
            reconcile_relocation(self.project, plan["core"]["transaction_id"], abort=True)
        self.assertEqual(str(caught.exception), "relocate_abort_too_late")
        self._assert_relocated(reconcile_relocation(self.project, plan["core"]["transaction_id"]))

    def test_foreign_destination_is_never_adopted_or_deleted(self) -> None:
        plan = self._plan()
        relocate._fault = _crash_at("journal_staging")
        with self.assertRaises(SimulatedCrash):
            commit_relocation(self.store, plan, self.revision)
        relocate._fault = None
        other = self.base / "other"
        other.mkdir()
        MemoryStore(other, store_root=self.vault).initialize()
        result = reconcile_relocation(self.project, plan["core"]["transaction_id"])
        self.assertEqual(result["stage"], "aborted")
        self.assertIsNone(read_pointer(self.project))
        self.assertTrue((self.vault / "memory" / "refs" / "CURRENT").exists())

    def test_reader_holding_the_gate_defers_cleanup_to_reconcile(self) -> None:
        plan = self._plan()
        ready = self.base / "ready"
        release = self.base / "release"
        reader = subprocess.Popen(
            [sys.executable, "-c", (
                "import sys, time\n"
                "from pathlib import Path\n"
                "from an_kla.reader_gate import shared_reader_gate\n"
                "from an_kla.store import MemoryStore\n"
                "store = MemoryStore(sys.argv[1])\n"
                "with shared_reader_gate(store):\n"
                "    Path(sys.argv[2]).touch()\n"
                "    while not Path(sys.argv[3]).exists():\n"
                "        time.sleep(0.01)\n"
            ), str(self.project), str(ready), str(release)],
            cwd=str(ROOT), env=dict(os.environ, PYTHONPATH=str(ROOT)),
        )
        self.addCleanup(reader.wait)
        self.addCleanup(lambda: release.parent.exists() and release.touch())
        while not ready.exists():
            self.assertIsNone(reader.poll())
        original = relocate._GATE_TIMEOUT
        relocate._GATE_TIMEOUT = 0.2
        self.addCleanup(setattr, relocate, "_GATE_TIMEOUT", original)
        with self.assertRaises(RelocateError) as caught:
            commit_relocation(self.store, plan, self.revision)
        self.assertEqual(str(caught.exception), "relocate_cleanup_readers_active")
        txid = plan["core"]["transaction_id"]
        self.assertEqual(inspect_relocation(self.project, txid)["stage"], "pointer_written")
        # The reader still sees the whole origin while it holds the gate.
        self.assertTrue((self.project / ".an-kla" / "memory" / "refs" / "CURRENT").exists())
        release.touch()
        self.assertEqual(reader.wait(), 0)
        self._assert_relocated(reconcile_relocation(self.project, txid))

    def test_stale_writer_and_concurrent_commit_fail_closed(self) -> None:
        plan = self._plan()
        stale = MemoryStore(self.project)
        results: list[object] = []

        def run() -> None:
            try:
                results.append(commit_relocation(MemoryStore(self.project), plan, self.revision))
            except Exception as exc:  # pragma: no cover - reported below
                results.append(exc)

        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertTrue(all(isinstance(item, dict) for item in results), results)
        self.assertEqual(sorted(item["replayed"] for item in results), [False, True])
        self._assert_relocated(next(item for item in results if not item["replayed"]))
        # A process that opened the origin before the pointer cannot write
        # into the dead tree, and the vault does not move.
        with self.assertRaises(Exception):
            _commit_fact(stale, "f-stale")
        destination = MemoryStore(self.project, store_root=self.vault)
        self.assertEqual(destination.verify()["revision"], self.revision)
        self.assertFalse((self.project / ".an-kla" / "memory" / "refs" / "CURRENT").exists())

    def test_destination_before_pointer_is_inert_and_abort_checks_every_file(self) -> None:
        # Adversarial round M1 (forward side) and m3.
        plan = self._plan()
        txid = plan["core"]["transaction_id"]
        relocate._fault = _crash_at("after_publish")
        with self.assertRaises(SimulatedCrash):
            commit_relocation(self.store, plan, self.revision)
        relocate._fault = None
        early = MemoryStore(self.project, store_root=self.vault)
        with self.assertRaises(Exception) as caught:
            _commit_fact(early, "f-early")
        self.assertEqual(str(caught.exception), "store_root_divergence")
        foreign = self.vault / "memory" / "indexes" / "foreign.bin"
        foreign.parent.mkdir(parents=True)
        foreign.write_bytes(b"not ours")
        with self.assertRaises(RelocateError) as caught:
            reconcile_relocation(self.project, txid, abort=True)
        self.assertEqual(str(caught.exception), "relocate_destination_unrecognized")
        self.assertTrue(foreign.exists())
        foreign.unlink()
        self.assertEqual(reconcile_relocation(self.project, txid, abort=True)["stage"], "aborted")
        self._assert_origin_intact()

    def test_cli_plan_commit_inspect(self) -> None:
        env = {key: value for key, value in os.environ.items() if key != "AN_KLA_STORE_ROOT"}
        env["AN_KLA_NO_UPDATE_CHECK"] = "1"

        def cli(*args: str) -> dict:
            completed = subprocess.run(
                [sys.executable, "-m", "an_kla", "--project-root", str(self.project), *args],
                capture_output=True, text=True, cwd=str(ROOT), env=env,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            return json.loads(completed.stdout)

        plan = cli("relocate", "plan", "--to", str(self.vault))
        plan_file = self.base / "plan.json"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")
        result = cli("relocate", "commit", "--plan", str(plan_file), "--expected-current", self.revision)
        self.assertEqual(result["stage"], "cleaned")
        self.assertEqual(cli("status")["revision"], self.revision)
        inspected = cli("relocate", "inspect", "--transaction-id", plan["core"]["transaction_id"])
        self.assertEqual(inspected["observed"]["pointer"], "matches")
        self.assertTrue(pointer_path(self.project).exists())
        back = cli("relocate", "plan", "--back")
        plan_file.write_text(json.dumps(back), encoding="utf-8")
        self.assertEqual(
            cli("relocate", "commit", "--plan", str(plan_file), "--expected-current", self.revision)["stage"],
            "cleaned",
        )
        self.assertFalse(pointer_path(self.project).exists())
        self.assertEqual(cli("status")["revision"], self.revision)


if __name__ == "__main__":
    unittest.main()
