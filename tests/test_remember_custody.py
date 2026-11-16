"""Criterios 6 y 7 (ADR-0063) con ``remember`` real: lecturas puras con entradas pendientes y bandeja frente a la custodia."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from an_kla import inbox, relocate
from an_kla.relocate import commit_relocation, plan_relocation
from an_kla.store import MemoryStore
from tests.inbox_support import InboxCase, hold_flock
from tests.remember_support import ROOT, cli, cli_env, remember
import tests.test_inbox_custody as base


def inbox_listing(store: MemoryStore) -> list[tuple[str, int, int, str]]:
    """``(ruta, tamaño, mtime_ns, sha256)`` de todo lo que hay bajo ``memory/inbox/``."""

    root = inbox.inbox_paths(store).root
    rows = []
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() and not path.is_symlink() else ""
        rows.append((str(path.relative_to(root)), info.st_size, info.st_mtime_ns, digest))
    return rows


class QueuedByRememberCase(base.CustodyCase):
    def queue_with_remember(self, text: str = "pendiente de remember") -> dict:
        holder = hold_flock(Path(self.store.root) / ".write.lock")
        try:
            rc, result = remember(self.project, text)
        finally:
            InboxCase.release(holder)
        self.assertEqual((rc, result["state"]), (0, "queued"), result)
        return result


class PureReadsTests(QueuedByRememberCase):
    def test_criterion_6_reads_do_not_move_current_nor_touch_the_inbox(self) -> None:
        queued = self.queue_with_remember("palabraclave en cola")
        revision = self.store.read_current()
        before = inbox_listing(self.store)
        self.assertTrue(any(queued["entry"] in row[0] for row in before))
        reads = [
            ("status",), ("verify",), ("doctor",), ("inventory", "--revision", revision),
            ("retrieve", "--query", "palabraclave", "--budget", "2000"), ("resume", "--budget", "4000"),
            ("assemble-context", "--query", "palabraclave", "--budget", "800"), ("inbox", "status"),
            ("disputes", "list"), ("export", "verify", "--bundle", str(self.scratch / "no-hay")),
        ]
        for args in reads:
            with self.subTest(read=args[0]):
                cli(self.project, *args)
                self.assertEqual(self.store.read_current(), revision)
                self.assertEqual(inbox_listing(self.store), before)
        self.assertNotIn("palabraclave", cli(self.project, "retrieve", "--query", "palabraclave", "--budget", "2000").stdout)


class CustodyWithRememberTests(QueuedByRememberCase):
    def test_criterion_7_pending_stops_export_and_relocate_commit_until_drained(self) -> None:
        self.queue_with_remember()
        bundle = self.scratch / "bundle"
        done = cli(self.project, "export", "create", "--bundle", str(bundle))
        self.assertIn("inbox_pending", done.stderr)
        self.assertFalse(bundle.exists())
        plan_file = self.scratch / "plan.json"
        planned = cli(self.project, "relocate", "plan", "--to", str(self.vault))
        self.assertEqual(planned.returncode, 0, planned.stderr)  # `relocate plan` pasa con la bandeja no vacía
        plan_file.write_text(planned.stdout)
        done = cli(self.project, "relocate", "commit", "--plan", str(plan_file), "--expected-current", self.revision)
        self.assertIn("inbox_pending", done.stderr)
        self.assertFalse(self.vault.exists())
        drained = cli(self.project, "inbox", "drain")
        self.assertEqual(json.loads(drained.stdout)["committed"]["count"], 1)
        done = cli(self.project, "export", "create", "--bundle", str(bundle))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse([p for p in bundle.rglob("*") if "inbox" in p.relative_to(bundle).parts])

    def test_criterion_7_remember_racing_relocate_commit_never_lands_in_the_abandoned_anchor(self) -> None:
        plan = plan_relocation(self.store, self.vault)
        spawned: dict = {}

        def fault(name: str) -> None:
            if name == "journal_staging" and "proc" not in spawned:
                spawned["proc"] = subprocess.Popen(
                    [os.sys.executable, "-m", "an_kla", "--project-root", str(self.project), "remember", "--text-file", "-"],
                    cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=cli_env(),
                )
                spawned["proc"].stdin.write("concurrente con relocate")
                spawned["proc"].stdin.close()
                try:
                    spawned["proc"].wait(1.5)
                except subprocess.TimeoutExpired:
                    pass

        relocate._fault = fault
        self.addCleanup(setattr, relocate, "_fault", None)
        relocation = commit_relocation(self.store, plan, self.revision)
        proc = spawned["proc"]
        proc.wait(timeout=60)
        out, err = proc.stdout.read(), proc.stderr.read()
        proc.stdout.close()
        proc.stderr.close()
        self.assertEqual(relocation["stage"], "cleaned")
        print("\nREMEMBER-RACE " + json.dumps({"stdout_state": json.loads(out)["state"] if out.strip() else None, "stderr": err.strip()[:120]}))
        allowed = {"inbox_busy", "store_root_divergence", "store_identity_changed", "identity_lock_busy"}
        landed = json.loads(out)["state"] if out.strip() else None
        self.assertTrue(landed in ("committed", "queued") or any(code in err for code in allowed), (out, err))
        old = self.project / ".an-kla" / "memory" / "inbox"
        self.assertEqual(list(old.rglob("*.json")), [], (out, err))
        destination = MemoryStore(self.project, store_root=self.vault)
        residue = base.RelocateCustodyTests.residue_of(destination.doctor())
        self.assertEqual(residue, 0)
        self.assertEqual(destination.verify()["ok"], True)


if __name__ == "__main__":
    unittest.main()
