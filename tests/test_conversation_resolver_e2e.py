"""ADR-0073, acceptance 3 (process), 4 (the three moments), 5 (``directive``), 6 (``anchors verify``) and 8 (compatibility), end to end.

Real CLI in a real Git project, with a resolver that is a real process (``fixtures/custodian_adapter_fake.py``) in the store's ``config.json``.
Writing calls ``resolve`` and stores the result (the anchor stays ``pending``); auditing calls ``resolve`` or ``verify`` by the last conclusive
result and stores an annotation; reading serves the stored and starts no process; an attempt that does not conclude does not cover a conclusive
result; the anchors of a ``directive`` are never resolved.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests.custodian_support import FakeCustodian, schema_validator
from tests.remember_support import cli, cli_env
from tests.scope_support import ScopeCase
from tests.test_scope_compat import baseline_tree

QUOTE = "Adelante con el cambio de puerto del servidor de quetzal, a 8081."
SEAL = "m1:" + "ab" * 32
TURN = "claude-code:msg-0042"
RESOLVER_SCHEMA = "memoria/conversacion-resolutor/v1"


def resolved(**changes: Any) -> dict[str, Any]:
    return {"mode": "response", "response": {"schema": RESOLVER_SCHEMA, "session": "known", "resolution": "resolved", "reason": None, "turn_id": TURN, "seal": SEAL,
                                              "speaker": "user", "match": "literal", "candidates": {"user": 1, "pasted": 0, "other": 0}, "tail": "open", **changes}}


def pending(reason: str = "tail_open") -> dict[str, Any]:
    return {"mode": "response", "response": {"schema": RESOLVER_SCHEMA, "session": "known", "resolution": "pending", "reason": reason, "turn_id": None, "seal": None,
                                              "speaker": None, "match": None, "candidates": {"user": 0, "pasted": 0, "other": 0}, "tail": "open"}}


def verify(seal: str = "match", quote: str = "found", speaker: str | None = "user", session: str = "known", reason: str | None = None) -> dict[str, Any]:
    return {"mode": "response", "response": {"schema": RESOLVER_SCHEMA, "session": session, "seal": seal, "quote": quote, "speaker": speaker, "reason": reason}}


class ConversationCase(ScopeCase):
    def setUp(self) -> None:
        super().setUp()
        self.anchors = self.scratch / "conversacion.json"
        self.anchors.write_text(json.dumps([{"source": {"kind": "conversation"}, "quote": QUOTE}]))
        self.fake = FakeCustodian(self, name="skopos")
        self.fake.install_resolver(self.store.store_root, resolved())
        self.env_a = self.env("orq-a")

    def write(self, *args: str, text: str = "Se pidió cambiar el puerto a 8081.", **options: Any) -> tuple[int, dict]:
        done = cli(self.project, "remember", "--text-file", "-", "--anchor-file", str(self.anchors), *args, stdin=text, env=options.pop("env", self.env_a), **options)
        if done.stdout.strip():
            return done.returncode, json.loads(done.stdout)
        found = re.match(r"an-kla error: (\w+)", done.stderr)
        return done.returncode, {"code": found.group(1) if found else done.stderr[-200:]}

    def written(self, *args: str, **options: Any) -> dict:
        rc, body = self.write(*args, **options)
        self.assertEqual((rc, body.get("state")), (0, "committed"), body)
        return body

    def served(self, *args: str) -> dict:
        done = cli(self.project, *args, env=self.env_a)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def history(self, record_id: str) -> dict:
        return self.served("history", record_id)["nodes"][0]["anchors"][0]

    def stored(self, record_id: str) -> dict:
        return next(r for s in ("facts", "events", "episodes") for r in self.store.snapshot().records[s] if r["id"] == record_id)

    def events(self, kind: str) -> list[dict]:
        return [r for r in self.store.snapshot().records["events"] if r.get("kind") == kind]

    def audit(self, record_id: str) -> dict:
        return self.served("anchors", "verify", record_id)


class ThreeMomentsTests(ConversationCase):
    def test_writing_stores_the_result_and_the_anchor_stays_pending(self) -> None:
        body = self.written()
        self.assertEqual(body["schema"], "an-kla/remember-result-v4")
        item = body["anchors"][0]
        self.assertEqual((item["kind"], item["resolution"], item["turn_id"], item["seal"], item["speaker"], item["freshness"], item["resolver_called"]),
                         ("conversation", "resolved", TURN, SEAL, "user", "fresh", "resolve"))
        self.assertEqual(item["candidates"], {"user": 1, "pasted": 0, "other": 0})
        record = self.stored(body["record_id"])
        source = record["anchors"][0]["source"]
        self.assertEqual((source["resolution"], source["turn_id"], source["seal"]), ("pending", None, None))  # the anchor is stored as it is born
        self.assertEqual(record["anchors"][0]["schema"], "memoria/ancla/v1")
        (check,) = record["anchor_checks"]
        self.assertEqual((check["resolution"], check["turn_id"], check["seal"], check["speaker"], check["freshness"]), ("resolved", TURN, SEAL, "user", "fresh"))
        self.assertNotIn("manifest_sha256", check)  # the keys of a document are not here
        schema_validator(self, "remember-result-v4").validate(body)
        self.assertEqual(self.fake.log()["request"]["op"], "resolve")

    def test_a_pending_anchor_is_valid_and_is_written(self) -> None:
        self.fake.set(pending("only_in_other_voice"))
        body = self.written()
        item = body["anchors"][0]
        self.assertEqual((item["resolution"], item["freshness"], item["detail"], item["reason"]), ("pending", "pending", "only_in_other_voice", "resolution_pending"))

    def test_a_failing_resolver_never_rejects_the_write(self) -> None:
        for scenario, detail in (({"mode": "exit_nonzero"}, "resolver_error"), ({"mode": "bad_json"}, "resolver_error"), ({"mode": "bad_schema"}, "resolver_error")):
            with self.subTest(scenario["mode"]):
                self.fake.set(scenario)
                body = self.written("--idempotency-key", scenario["mode"])
                self.assertEqual((body["anchors"][0]["resolution"], body["anchors"][0]["detail"], body["anchors"][0]["freshness"]), ("pending", detail, "pending"))

    def test_reading_serves_the_stored_result_and_starts_no_process(self) -> None:
        body = self.written()
        self.fake.set({"mode": "exit_nonzero"})  # if anybody calls it, the log shows it
        for command in (("history", body["record_id"]), ("list",), ("state", "show")):
            self.served(*command)
        shown = self.served("history", body["record_id"])
        self.assertEqual(shown["schema"], "an-kla/history-result-v3")
        item = shown["nodes"][0]["anchors"][0]
        self.assertEqual((item["freshness"], item["resolution"], item["turn_id"], item["seal"], item["speaker"]), ("fresh", "resolved", TURN, SEAL, "user"))
        self.assertEqual(item["candidates"], {"user": 1, "pasted": 0, "other": 0})
        self.assertFalse(self.fake.called(), "reading started the resolver")
        schema_validator(self, "history-result-v3").validate(shown)

    def test_state_and_decision_records_are_resolved_too(self) -> None:
        for kind in ("state", "decision"):
            with self.subTest(kind):
                self.fake.set(resolved())
                body = self.written("--kind", kind, "--idempotency-key", kind)
                self.assertEqual(body["anchors"][0]["freshness"], "fresh")
        shown = self.served("state", "show")
        self.assertEqual(shown["schema"], "an-kla/state-result-v3")
        schema_validator(self, "state-result-v3").validate(shown)

    def test_auditing_verifies_a_resolved_anchor_and_stores_an_annotation(self) -> None:
        body = self.written()
        self.fake.set(verify())
        audit = self.audit(body["record_id"])
        self.assertEqual(self.fake.log()["request"]["op"], "verify")
        self.assertEqual((self.fake.log()["request"]["turn_id"], self.fake.log()["request"]["seal"]), (TURN, SEAL))  # those of the last conclusive result
        self.assertEqual(audit["schema"], "an-kla/anchors-verify-v4")
        item = audit["records"][0]["anchors"][0]
        self.assertEqual((item["freshness"], item["resolver_called"], item["resolution"], item["speaker"], item["served"]["freshness"]), ("fresh", "verify", "resolved", "user", "fresh"))
        self.assertTrue(audit["records"][0]["recorded"], audit)
        (note,) = self.events("anchor_check")
        self.assertEqual(note["anchor_check"]["schema"], "an-kla/anchor-check-v2")
        self.assertEqual(note["anchor_check"]["checks"][0]["candidates"], None)  # verify does not bring them
        schema_validator(self, "anchors-verify-v4").validate(audit)
        schema_validator(self, "anchor-check-v2").validate(note["anchor_check"])

    def test_auditing_resolves_a_pending_anchor(self) -> None:
        self.fake.set(pending())
        body = self.written()
        self.fake.set(resolved())
        audit = self.audit(body["record_id"])
        self.assertEqual(self.fake.log()["request"]["op"], "resolve")  # not resolved yet: resolve again
        item = audit["records"][0]["anchors"][0]
        self.assertEqual((item["resolution"], item["freshness"], item["served"]["freshness"]), ("resolved", "fresh", "fresh"))
        self.assertEqual(self.history(body["record_id"])["freshness"], "fresh")

    def test_a_failed_audit_does_not_lower_a_fresh(self) -> None:
        """C28 and C29."""
        body = self.written()
        written_at = self.stored(body["record_id"])["anchor_checks"][0]["checked_at"]
        for scenario, reason in (({"mode": "exit_nonzero"}, "resolver_error"), (verify(session="unknown", seal="unknown", quote="unknown", speaker=None, reason="session_unavailable"), "session_unavailable")):
            with self.subTest(reason):
                self.fake.set(scenario)
                item = self.audit(body["record_id"])["records"][0]["anchors"][0]
                self.assertEqual((item["freshness"], item["reason"], item["served"]["freshness"], item["served"]["checked_at"]), ("unverified", reason, "fresh", written_at))
                shown = self.history(body["record_id"])
                self.assertEqual((shown["freshness"], shown["checked_at"]), ("fresh", written_at))  # reading keeps serving the conclusive one
        (self.project / ".an-kla" / "config.json").write_text("{}", encoding="utf-8")  # no resolver at all: still fresh
        self.assertEqual(self.history(body["record_id"])["freshness"], "fresh")

    def test_a_verified_break_does_cover_a_fresh(self) -> None:
        """C32 and the sequence fresh, broken, failed audit: broken."""
        body = self.written()
        self.fake.set(verify(seal="mismatch"))
        item = self.audit(body["record_id"])["records"][0]["anchors"][0]
        self.assertEqual((item["freshness"], item["reason"], item["served"]["freshness"]), ("broken", "seal_mismatch", "broken"))
        self.fake.set({"mode": "exit_nonzero"})
        item = self.audit(body["record_id"])["records"][0]["anchors"][0]
        self.assertEqual((item["freshness"], item["served"]["freshness"], item["served"]["reason"]), ("unverified", "broken", "seal_mismatch"))
        self.assertEqual((self.history(body["record_id"])["freshness"], self.history(body["record_id"])["reason"]), ("broken", "seal_mismatch"))

    def test_the_speaker_is_reclassified_without_lowering_the_anchor(self) -> None:
        """C30: the quote is still there; the voice travels apart."""
        body = self.written()
        self.fake.set(verify(speaker="automatic"))
        item = self.audit(body["record_id"])["records"][0]["anchors"][0]
        self.assertEqual((item["freshness"], item["speaker"]), ("fresh", "automatic"))
        self.assertEqual((self.history(body["record_id"])["freshness"], self.history(body["record_id"])["speaker"]), ("fresh", "automatic"))

    def test_without_a_resolver_nothing_is_called_nothing_is_stored_and_all_is_as_before(self) -> None:
        (Path(self.store.store_root) / "config.json").unlink()
        body = self.written()
        self.assertNotIn("anchor_checks", self.stored(body["record_id"]))
        self.assertNotEqual(body["schema"], "an-kla/remember-result-v4")
        shown = self.history(body["record_id"])
        self.assertEqual((shown["freshness"], shown["reason"], shown["resolution"]), ("pending", "resolution_pending", "pending"))
        self.assertNotIn("speaker", shown)
        self.assertFalse(self.fake.called())
        audit = self.audit(body["record_id"])
        self.assertEqual(self.events("anchor_check"), [])  # an audit without a resolver writes nothing for a conversation
        self.assertNotIn("recorded", audit["records"][0])
        self.assertEqual(audit["records"][0]["anchors"][0]["served"]["freshness"], "pending")
        self.assertEqual(audit["schema"], "an-kla/anchors-verify-v4")  # served is always there, and a conversation was audited

    def test_an_unreadable_table_is_resolver_error_with_no_process_and_says_why(self) -> None:
        (Path(self.store.store_root) / "config.json").write_text("{no es json", encoding="utf-8")
        body = self.written()
        self.assertEqual((body["anchors"][0]["detail"], body["anchors"][0]["resolver_called"], body["custodians_config_error"]), ("resolver_error", None, "custodians_invalid_json"))
        self.assertFalse(self.fake.called())


class DirectiveTests(ConversationCase):
    """Acceptance 5: a ``directive`` is untouched; its anchors are never resolved."""

    def test_no_process_is_started_for_a_directive_and_its_state_is_the_one_of_beta40(self) -> None:
        rc, body = self.directive("orq-a", "usa el puerto 8081", "--subject", self.repo_id, "--audience", "agent:orq-a", "--until-revoked")
        self.assertEqual((rc, body["state"]), (0, "committed"), body)
        self.assertFalse(self.fake.called(), "writing a directive started the resolver")
        self.assertNotIn("anchor_checks", self.stored(body["record_id"]))
        self.assertEqual(body["anchors"][0]["resolution"], "pending")
        audit = self.audit(body["record_id"])
        self.assertFalse(self.fake.called(), "auditing a directive started the resolver")
        self.assertEqual(self.events("anchor_check"), [])
        self.assertNotIn("served", audit["records"][0]["anchors"][0])
        mine = json.loads(cli(self.project, "history", body["record_id"], env=self.env_a).stdout)["nodes"][0]
        with tempfile.TemporaryDirectory(prefix="beta40-") as scratch:
            tree = baseline_tree(Path(scratch), "v0.1.0-beta.40")
            if tree is None:
                self.skipTest("la etiqueta v0.1.0-beta.40 no está en este clon")
            old = subprocess.run([sys.executable, "-m", "an_kla", "--project-root", str(self.project), "history", body["record_id"]], cwd=tree,
                                 env={**cli_env(self.env_a), "PYTHONPATH": str(tree)}, capture_output=True, text=True)
            theirs = json.loads(old.stdout)["nodes"][0]
        self.assertEqual(mine["directive"], theirs["directive"])  # `status` and `actionable`, byte for byte those of beta.40
        self.assertEqual((mine["directive"]["status"], mine["directive"]["actionable"]), ("unverified", False if not mine["directive"]["actionable"] else True))
        self.assertEqual(mine["anchors"][0]["freshness"], "pending")


class Beta40Tests(ConversationCase):
    """Acceptance 6 (the way back) and 8: what beta.40 does with a store of this version."""

    def beta40(self, tree: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-m", "an_kla", "--project-root", str(self.project), *args], cwd=tree,
                              env={**cli_env(self.env_a), "PYTHONPATH": str(tree)}, capture_output=True, text=True)

    def test_beta40_reads_the_store_and_serves_the_anchor_pending(self) -> None:
        body = self.written()
        self.fake.set(verify())
        self.audit(body["record_id"])  # there is a result in the record and an annotation
        with tempfile.TemporaryDirectory(prefix="beta40-") as scratch:
            tree = baseline_tree(Path(scratch), "v0.1.0-beta.40")
            if tree is None:
                self.skipTest("la etiqueta v0.1.0-beta.40 no está en este clon")
            for args in (("verify",), ("status",), ("history", body["record_id"]), ("list",), ("state", "show"), ("anchors", "verify", body["record_id"])):
                done = self.beta40(tree, *args)
                self.assertEqual(done.returncode, 0, (args, done.stderr[-300:]))
            item = json.loads(self.beta40(tree, "history", body["record_id"]).stdout)["nodes"][0]["anchors"][0]
            self.assertEqual((item["freshness"], item["reason"]), ("pending", "resolution_pending"))  # ignores anchor_checks and the annotation
            self.assertNotIn("speaker", item)

    def test_an_entry_v5_is_rejected_by_beta40_and_recovered_here(self) -> None:
        import fcntl  # noqa: F401  (the holder is another process)

        holder = subprocess.Popen(
            [sys.executable, "-I", "-c", "import fcntl,os,sys\nfd=os.open(sys.argv[1],os.O_RDWR|os.O_CREAT,0o600)\nfcntl.flock(fd,fcntl.LOCK_EX)\nsys.stdout.write('ready\\n');sys.stdout.flush()\nsys.stdin.read()\n",
             str(Path(self.store.root) / ".write.lock")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: (holder.stdin.close(), holder.wait(timeout=10), holder.stdout.close()) if holder.poll() is None else holder.stdout.close())
        self.assertEqual(holder.stdout.readline().strip(), "ready")
        rc, queued = self.write("--idempotency-key", "pendiente-v5")
        self.assertEqual((rc, queued["state"]), (0, "queued"), queued)
        entry = json.loads((self.inbox / "pending" / self.pending()[0]).read_text())
        self.assertEqual(entry["schema"], "an-kla/inbox-entry-v5")
        schema_validator(self, "inbox-entry-v5").validate(entry)
        holder.stdin.close()
        holder.wait(timeout=10)
        with tempfile.TemporaryDirectory(prefix="beta40-") as scratch:
            tree = baseline_tree(Path(scratch), "v0.1.0-beta.40")
            if tree is None:
                self.skipTest("la etiqueta v0.1.0-beta.40 no está en este clon")
            drained = json.loads(self.beta40(tree, "inbox", "drain").stdout)
            self.assertEqual([r["code"] for r in drained["rejected"]["entries"]], ["inbox_entry_invalid"])
        done = cli(self.project, "inbox", "requeue", "--all-format", env=self.env_a)
        self.assertEqual(done.returncode, 0, done.stderr)
        report = json.loads(cli(self.project, "inbox", "drain", env=self.env_a).stdout)
        self.assertEqual((report["committed"]["count"], report["rejected"]["count"]), (1, 0), report)


if __name__ == "__main__":
    unittest.main()
