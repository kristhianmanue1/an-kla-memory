"""ADR-0071, acceptance 5 and 7: a store written by beta.38 reads byte for byte the same until its first audit, and the way back.

``git archive v0.1.0-beta.38`` in a scratch folder and ``PYTHONPATH`` (nothing is installed).  **5:** a store whose ``document``
anchors are v1 (beta.38 wrote them) is read by beta.38 and by this tree with the same bytes; the first ``anchors verify`` stores
its annotations (also without a custodian) and from then on the anchors serve what is stored.  **7:** a store with ``document``
v2 anchors, read by beta.38, breaks neither ``anchors verify`` nor the reads; what beta.38 does with them is declared below.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.inbox_support import run_git
from tests.remember_support import ROOT, cli, cli_env, remember
from tests.scope_support import ScopeCase
from tests.test_document_v2_write import DERIVATION, DOC_SHA, MANIFEST, QUOTE, shortcut
from tests.test_scope_compat import BASELINE_TAG, baseline_tree

V1_DOCUMENT = {
    "schema": "memoria/ancla/v1", "quote": QUOTE,
    "source": {"kind": "document", "document_sha256": DOC_SHA, "locator": "unknown",
               "derivation": {"custodian": "skopos", "derivation_id": DERIVATION, "manifest_sha256": MANIFEST, "modality": "native_text"}},
}


class BetaCase(ScopeCase):
    def setUp(self) -> None:
        super().setUp()
        scratch = tempfile.TemporaryDirectory(prefix="beta38-")
        self.addCleanup(scratch.cleanup)
        tree = baseline_tree(Path(scratch.name))
        if tree is None:
            self.skipTest(f"la etiqueta {BASELINE_TAG} no está en este clon")
        self.tree = tree
        self.env_a = self.env("orq-plano")

    def run_tree(self, tree: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        done = subprocess.run(
            [sys.executable, "-m", "an_kla", "--project-root", str(self.project), *args], cwd=tree,
            env={**cli_env(self.env_a), "PYTHONPATH": str(tree)}, capture_output=True, text=True,
        )
        if check:
            self.assertEqual(done.returncode, 0, done.stderr[-400:])
        return done


class CompatibilityTests(BetaCase):
    """Acceptance 5."""

    def setUp(self) -> None:
        super().setUp()
        (self.project / "anclas-v1.json").write_text(json.dumps([V1_DOCUMENT]))
        done = self.run_tree(self.tree, "remember", "--text", "la cláusula 47 da veinte días", "--anchor-file", str(self.project / "anclas-v1.json"))
        self.record_id = json.loads(done.stdout)["record_id"]
        remember(self.project, "otro hecho sin anclas", env=self.env_a)

    def reads(self) -> tuple[tuple[str, ...], ...]:
        return (("history", self.record_id), ("list",), ("state", "show", "--all-slots"), ("retrieve", "--query", "cláusula", "--budget", "4000"))

    def test_a_beta38_store_is_read_byte_for_byte_the_same_until_its_first_audit(self) -> None:
        for args in self.reads():
            with self.subTest(args=args):
                before, after = self.run_tree(self.tree, *args).stdout, self.run_tree(ROOT, *args).stdout
                self.assertEqual(after, before)
        shown = json.loads(self.run_tree(ROOT, "history", self.record_id).stdout)["nodes"][0]["anchors"][0]
        self.assertEqual((shown["freshness"], shown["reason"]), ("unverified", "kind_not_supported"))
        self.assertNotIn("checked_at", shown)
        self.assertEqual(json.loads(self.run_tree(ROOT, "history", self.record_id).stdout)["schema"], "an-kla/history-result-v1")

    def test_the_first_audit_stores_and_from_then_on_the_anchors_serve_what_is_stored(self) -> None:
        audit = json.loads(self.run_tree(ROOT, "anchors", "verify", self.record_id).stdout)
        record = audit["records"][0]
        self.assertTrue(record["recorded"], record)
        self.assertEqual((record["anchors"][0]["reason"], record["anchors"][0]["adapter_called"]), ("no_adapter", False))  # no custodian configured
        shown = json.loads(self.run_tree(ROOT, "history", self.record_id).stdout)
        self.assertEqual(shown["schema"], "an-kla/history-result-v2")
        self.assertEqual((shown["nodes"][0]["anchors"][0]["reason"], shown["nodes"][0]["anchors"][0]["checked_at"] is not None), ("no_adapter", True))
        self.assertEqual(len([r for r in self.store.snapshot().records["events"] if r.get("kind") == "anchor_check"]), 1)


class RollbackTests(BetaCase):
    """Acceptance 7: a store with ``document`` v2 anchors read by beta.38.  Declared, from what the run shows:

    * ``anchors verify`` (one id and ``--all``) and the reads do not break (rc 0);
    * beta.38 serves the v2 anchor as ``document`` / ``unverified`` / ``kind_not_supported`` (it never reads ``anchor_checks``
      nor the ``anchor_check`` annotations, which it treats as any other event it does not know);
    * an ``inbox-entry-v4`` still pending (an unintegrated v2 anchor) is **rejected whole** by beta.38, which does not know v4
      (``inbox_entry_invalid``, not ``anchor_schema_invalid`` as ADR-0071 §7 says: the rule «drain and pending at 0 before
      going down» is what covers it).
    """

    def setUp(self) -> None:
        super().setUp()
        (self.project / "docs").mkdir()
        pdf = b"%PDF-1.4\n" + bytes(range(256))
        (self.project / "docs" / "m.pdf").write_bytes(pdf)
        run_git(self.project, "add", "docs/m.pdf")
        run_git(self.project, "commit", "-q", "-m", "copia")
        self.branch = {"AN_KLA_DEFAULT_BRANCH": "main"}
        rc, body = remember(self.project, "la cláusula 47 da veinte días", *shortcut(document=hashlib.sha256(pdf).hexdigest(), copy="docs/m.pdf"),
                            env={**self.env_a, **self.branch})
        self.assertEqual((rc, body["state"]), (0, "committed"), body)
        self.record_id = body["record_id"]
        done = cli(self.project, "anchors", "verify", self.record_id, env={**self.env_a, **self.branch})  # now there is an annotation too
        self.assertTrue(json.loads(done.stdout)["records"][0]["recorded"], done.stdout)

    def test_beta38_reads_a_store_with_v2_anchors_without_breaking(self) -> None:
        for args in (("anchors", "verify", self.record_id), ("anchors", "verify", "--all"), ("history", self.record_id), ("list",),
                     ("state", "show", "--all-slots"), ("retrieve", "--query", "cláusula", "--budget", "4000")):
            with self.subTest(args=args):
                self.run_tree(self.tree, *args)
        audit = json.loads(self.run_tree(self.tree, "anchors", "verify", self.record_id).stdout)
        item = audit["records"][0]["anchors"][0]
        self.assertEqual((item["anchor"]["kind"], item["freshness"], item["reason"]), ("document", "unverified", "kind_not_supported"))
        self.assertNotIn("checked_at", item)
        self.assertNotIn("recorded", audit["records"][0])  # beta.38 writes nothing when auditing

    def test_a_pending_v4_entry_with_a_v2_anchor_is_rejected_by_beta38_and_drains_here(self) -> None:
        holder = subprocess.Popen(  # the write lock is held by another process: `remember` queues and does not drain
            [sys.executable, "-I", "-c", "import fcntl,os,sys\nfd=os.open(sys.argv[1],os.O_RDWR|os.O_CREAT,0o600)\nfcntl.flock(fd,fcntl.LOCK_EX)\nsys.stdout.write('ready\\n');sys.stdout.flush()\nsys.stdin.read()\n",
             str(Path(self.store.root) / ".write.lock")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        )
        self.addCleanup(lambda: (holder.stdin.close(), holder.wait(timeout=10), holder.stdout.close()) if holder.poll() is None else holder.stdout.close())
        self.assertEqual(holder.stdout.readline().strip(), "ready")
        rc, queued = remember(self.project, "otra cláusula", *shortcut(), "--idempotency-key", "pendiente", env={**self.env_a, **self.branch})
        self.assertEqual((rc, queued["state"]), (0, "queued"), queued)
        self.assertEqual(len(self.pending()), 1)
        holder.stdin.close()
        holder.wait(timeout=10)
        entry = json.loads((self.inbox / "pending" / self.pending()[0]).read_text())
        self.assertEqual((entry["schema"], entry["anchors"][0]["schema"]), ("an-kla/inbox-entry-v4", "memoria/ancla/v2"))
        done = self.run_tree(self.tree, "inbox", "drain", check=False)
        rejected = json.loads(done.stdout)["rejected"]["entries"]
        self.assertEqual([r["code"] for r in rejected], ["inbox_entry_invalid"], done.stdout[-500:])
        self.assertEqual(self.pending(), [])  # rejected, with its trace; nothing half written
        again, queued = remember(self.project, "otra cláusula", *shortcut(), "--idempotency-key", "pendiente", env={**self.env_a, **self.branch})
        self.assertEqual((again, queued["state"]), (0, "committed"), queued)  # here it goes through


if __name__ == "__main__":
    unittest.main()
