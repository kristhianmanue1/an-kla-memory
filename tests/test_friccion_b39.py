"""ADR-0072, pruebas de aceptación 1 a 6 (la 7, la compatibilidad, la fijan `test_scope_compat`, `test_document_v2_compat`, los goldens y los 61 casos).

El caso del primer día de uso real de beta.39: una cita `fresh` auditada desde un entorno sin tabla de custodios.  Un intento que no
concluye (`no_adapter`, `adapter_error`) no sustituye a un resultado concluyente (errata 6 de `memoria/ancla/v2`); `--subject` trae su
pista y normaliza mayúsculas; lo guardado con ámbito se ve al escribir y en `state show`.  Adaptador de prueba: un proceso real.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests.custodian_support import schema_validator
from tests.inbox_support import run_git
from tests.remember_support import ROOT, cli, cli_env
from tests.test_document_v2_write import BRANCH, COPY, DOC_SHA, PDF, DocumentCase, response, shortcut
from tests.test_scope_compat import BASELINE_TAG, baseline_tree

OTHER_TEXT = {"mode": "response", "response": response(items=[{"item_id": "i-13", "page": 188, "modality": "native_text", "text": "Otra cosa."}])}


class InconclusiveAttemptTests(DocumentCase):
    """Aceptación 1, 2 y 3."""

    def audit(self, record_id: str) -> dict:
        return self.served("anchors", "verify", record_id)

    def anchor_of(self, audit: dict) -> dict:
        return audit["records"][0]["anchors"][0]

    def assert_reads_fresh(self, record_id: str, checked_at: str) -> None:
        shown = self.history(record_id)
        self.assertEqual((shown["freshness"], shown["reason"], shown["checked_at"]), ("fresh", None, checked_at))

    def test_the_exact_case_an_audit_without_a_table_warns_and_reading_stays_fresh(self) -> None:
        body = self.written(*shortcut())
        written_at = body["anchors"][0]["checked_at"]
        (Path(self.store.store_root) / "config.json").unlink()  # the environment of the audit has no table of custodians
        audit = self.audit(body["record_id"])
        self.assertEqual(audit["schema"], "an-kla/anchors-verify-v4")
        self.assertEqual(audit["warnings"], [{"code": "custodian_not_configured", "custodian": "skopos", "anchors": 1}])
        self.assertNotIn("custodians_config_error", audit)
        item = self.anchor_of(audit)
        self.assertEqual((item["freshness"], item["reason"], item["adapter_called"]), ("unverified", "no_adapter", False))  # the attempt, as it was
        self.assertEqual(item["served"], {"freshness": "fresh", "reason": None, "checked_at": written_at})
        self.assertEqual(audit["records"][0]["anchors_freshness"], "unverified")  # the aggregate describes the attempt (R72-03)
        self.assertTrue(audit["records"][0]["recorded"])  # the attempt is stored: its date and reason are data
        self.assert_reads_fresh(body["record_id"], written_at)
        state = self.write(*shortcut(), "--kind", "state", "--idempotency-key", "estado", text="en curso: la cláusula 47")[1]
        self.assertEqual(state["state"], "committed", state)
        shown = self.served("state", "show")["slots"][0]["anchors"][0]
        self.assertEqual(shown["freshness"], "unverified")  # a state never audited and never concluded: nothing to keep
        schema_validator(self, "anchors-verify-v4").validate(audit)

    def test_a_failing_process_with_the_custodian_configured_is_no_configuration_warning(self) -> None:
        body = self.written(*shortcut())
        written_at = body["anchors"][0]["checked_at"]
        self.fake.set({"mode": "exit_nonzero"})
        audit = self.audit(body["record_id"])
        self.assertNotIn("warnings", audit)
        item = self.anchor_of(audit)
        self.assertEqual((item["reason"], item["adapter_called"], item["served"]["freshness"]), ("adapter_error", True, "fresh"))
        self.assertEqual(audit["schema"], "an-kla/anchors-verify-v4")  # the record carries `coverage.evidence` (erratum 7): v4
        self.assert_reads_fresh(body["record_id"], written_at)

    def test_an_unreadable_table_says_config_error_and_not_custodian_not_configured(self) -> None:
        body = self.written(*shortcut())
        written_at = body["anchors"][0]["checked_at"]
        (Path(self.store.store_root) / "config.json").write_text("{no es json", encoding="utf-8")
        audit = self.audit(body["record_id"])
        self.assertEqual(audit["custodians_config_error"], "custodians_invalid_json")
        self.assertNotIn("warnings", audit)
        self.assertEqual(self.anchor_of(audit)["served"]["freshness"], "fresh")
        self.assert_reads_fresh(body["record_id"], written_at)

    def test_a_conclusive_attempt_has_its_own_served_and_no_warning(self) -> None:
        body = self.written(*shortcut())
        audit = self.audit(body["record_id"])
        self.assertEqual((audit["schema"], "warnings" in audit, "served" in self.anchor_of(audit)), ("an-kla/anchors-verify-v4", False, True))  # ADR-0073 §6: `served` is always there, also when the attempt concludes

    def test_a_conclusive_attempt_does_rule(self) -> None:
        """Aceptación 2: `quote_absent` y `copy_sha_mismatch` mandan; `fresh` → `broken` → `no_adapter` se sirve `broken`."""
        body = self.written(*shortcut())
        self.fake.set(OTHER_TEXT)
        audit = self.audit(body["record_id"])
        self.assertEqual((self.anchor_of(audit)["freshness"], self.anchor_of(audit)["reason"]), ("broken", "quote_absent"))
        self.assertEqual(self.anchor_of(audit)["served"]["freshness"], "broken")  # the attempt itself: it concludes
        self.assertEqual(self.history(body["record_id"])["reason"], "quote_absent")
        (Path(self.store.store_root) / "config.json").unlink()
        audit = self.audit(body["record_id"])
        self.assertEqual(self.anchor_of(audit)["served"]["freshness"], "broken")  # an attempt that does not conclude does not cover a contradiction
        self.assertEqual((self.history(body["record_id"])["freshness"], self.history(body["record_id"])["reason"]), ("broken", "quote_absent"))

    def test_a_copy_that_contradicts_concludes(self) -> None:
        body = self.written(*shortcut(copy=COPY))
        (self.project / COPY).write_bytes(PDF + b"cambiado")  # the copy on the default branch is no longer the cited document
        run_git(self.project, "commit", "-q", "-am", "otro documento")
        (Path(self.store.store_root) / "config.json").unlink()  # even with no adapter: A3 puts the copy first
        audit = self.audit(body["record_id"])
        item = self.anchor_of(audit)
        self.assertEqual((item["freshness"], item["integrity_reason"]), ("broken", "copy_sha_mismatch"))
        self.assertEqual(item["served"]["reason"], "copy_sha_mismatch")
        self.assertEqual(self.history(body["record_id"])["integrity_reason"], "copy_sha_mismatch")
        audit = self.audit(body["record_id"])  # and it is the one that rules from now on, over the fresh of the write
        self.assertEqual(self.history(body["record_id"])["freshness"], "broken")

    def test_without_a_prior_conclusive_result_the_attempt_is_served_as_before(self) -> None:
        """Aceptación 3."""
        (Path(self.store.store_root) / "config.json").unlink()
        body = self.written(*shortcut())  # written with no adapter: `unverified` / `no_adapter`
        audit = self.audit(body["record_id"])
        item = self.anchor_of(audit)
        self.assertEqual(item["served"]["reason"], "no_adapter")  # nothing concluded before: reading serves the attempt
        self.assertEqual((item["freshness"], item["reason"]), ("unverified", "no_adapter"))
        self.assertEqual(audit["warnings"][0]["code"], "custodian_not_configured")  # the warning does not depend on a prior result
        shown = self.history(body["record_id"])
        self.assertEqual((shown["freshness"], shown["reason"]), ("unverified", "no_adapter"))


class Beta39StoreTests(DocumentCase):
    """Aceptación 4: un store escrito por beta.39 con un `fresh` y después una anotación `no_adapter`."""

    def test_the_store_written_by_beta39_is_served_fresh_without_writing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="beta39-") as scratch:
            tree = baseline_tree(Path(scratch), "v0.1.0-beta.39")
            if tree is None:
                self.skipTest("la etiqueta v0.1.0-beta.39 no está en este clon")

            def beta39(*args: str, stdin: str | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
                return subprocess.run([sys.executable, "-m", "an_kla", "--project-root", str(self.project), *args], cwd=tree, input=stdin,
                                      env={**cli_env({**self.env_a, **(env or {})}), "PYTHONPATH": str(tree)}, capture_output=True, text=True)

            written = beta39("remember", "--text-file", "-", *shortcut(), stdin="La cláusula 47 da veinte días.")
            self.assertEqual(written.returncode, 0, written.stderr[-300:])
            body = json.loads(written.stdout)
            record_id, written_at = body["record_id"], body["anchors"][0]["checked_at"]
            (Path(self.store.store_root) / "config.json").unlink()
            audit = beta39("anchors", "verify", record_id)
            self.assertTrue(json.loads(audit.stdout)["records"][0]["recorded"], audit.stdout[-300:])
            old = json.loads(beta39("history", record_id).stdout)["nodes"][0]["anchors"][0]
            self.assertEqual((old["freshness"], old["reason"]), ("unverified", "no_adapter"))  # what beta.39 serves: the bug
            before = self.store.read_current()
            now = self.history(record_id)
            self.assertEqual((now["freshness"], now["reason"], now["checked_at"]), ("fresh", None, written_at))
            self.assertEqual(self.store.read_current(), before)  # nothing was written
            self.assertEqual(len([r for r in self.store.snapshot().records["events"] if r.get("kind") == "anchor_check"]), 1)


class SubjectTests(DocumentCase):
    """Aceptación 5."""

    def upper(self) -> str:
        return self.repo_id.upper()

    def test_uppercase_is_stored_lowercase_and_says_so(self) -> None:
        rc, body = self.write("--subject", self.upper(), "--audience", "all", text="hecho para este proyecto")
        self.assertEqual((rc, body["state"]), (0, "committed"), body)
        self.assertEqual((body["subject"], body["subject_normalized_from"]), (self.repo_id, self.upper()))
        self.assertEqual(self.stored(body["record_id"])["subject"], self.repo_id)

    def test_reads_with_an_uppercase_subject_read_the_same(self) -> None:
        self.assertEqual(self.write("--subject", self.repo_id, "--audience", "all", text="puerto 8081 de quetzal")[0], 0)
        for args in (("retrieve", "--query", "puerto", "--budget", "4000"), ("list", "--status", "all", "--text"), ("state", "show")):
            with self.subTest(args=args):
                low = cli(self.project, *args, "--subject", self.repo_id, env=self.env_a)
                high = cli(self.project, *args, "--subject", self.upper(), env=self.env_a)
                self.assertEqual((high.returncode, high.stdout), (low.returncode, low.stdout), high.stderr)

    def test_anything_else_is_rejected_and_the_hint_names_the_projects_repo_id(self) -> None:
        for bad in ("https://example.org/a/b", "example.org/a/b.git", " " + self.repo_id, "https://EXAMPLE.org/A/b"):
            with self.subTest(bad=bad):
                rc, body = self.write("--subject", bad, text="no entra")
                self.assertEqual((rc, body["code"]), (3, "remember_subject_invalid"))
                for command in (("retrieve", "--query", "x", "--budget", "4000"), ("list",), ("state", "show")):
                    done = cli(self.project, *command, "--subject", bad, env=self.env_a)
                    self.assertNotEqual(done.returncode, 0)
                    self.assertIn("subject_invalid", done.stderr)
                    self.assertIn(self.repo_id, done.stderr)  # «por ejemplo, el de este proyecto es …»

    def test_the_hint_of_a_write_rejection_has_the_repo_id(self) -> None:
        done = cli(self.project, "remember", "--text", "x", "--subject", "https://example.org/a", env=self.env_a)
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertIn(self.repo_id, json.loads(done.stdout)["hint"])
        self.assertNotIn(str(self.project), done.stdout)  # the hint carries the repo.id, never a path of the machine

    def test_without_git_the_hint_is_the_usual_one(self) -> None:
        nogit = self.scratch / "sin-git"
        nogit.mkdir()
        done = cli(self.project, "retrieve", "--query", "x", "--budget", "4000", "--subject", "https://example.org/a", env={**self.env_a, "PATH": str(nogit)})
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("retrieve_subject_invalid", done.stderr)
        self.assertNotIn(self.repo_id, done.stderr)
        self.assertIn("repo.id de C0 canónico", done.stderr)


class ScopeVisibleTests(DocumentCase):
    """Aceptación 6."""

    def test_remember_returns_what_was_stored_with_remember_result_v3(self) -> None:
        rc, body = self.write("--subject", self.repo_id, "--audience", "role:orquestador", text="hecho con ámbito")
        self.assertEqual((rc, body["state"], body["schema"]), (0, "committed", "an-kla/remember-result-v3"), body)
        self.assertEqual((body["subject"], body["audience"]), (self.repo_id, "role:orquestador"))
        self.assertNotIn("subject_normalized_from", body)
        schema_validator(self, "remember-result-v3").validate(body)

    def test_a_directive_returns_its_scope_and_validity(self) -> None:
        rc, body = self.directive("orq-a", "usa el puerto 8081", "--subject", self.repo_id.upper(), "--audience", "agent:orq-a", "--valid-until", "2099-01-01")
        self.assertEqual((rc, body["state"], body["schema"]), (0, "committed", "an-kla/remember-result-v3"), body)
        self.assertEqual((body["subject"], body["audience"], body["valid_until"], body["valid_until_input"], body["subject_normalized_from"]),
                         (self.repo_id, "agent:orq-a", "2099-01-01T23:59:59Z", "2099-01-01", self.repo_id.upper()))
        stored = self.stored(body["record_id"])
        self.assertEqual((stored["valid_until"], stored["valid_until_input"]), (body["valid_until"], body["valid_until_input"]))
        schema_validator(self, "remember-result-v3").validate(body)
        rc, forever = self.directive("orq-a", "y siempre", "--subject", self.repo_id, "--audience", "agent:orq-a", "--until-revoked", "--idempotency-key", "k2")
        self.assertEqual((rc, forever["until_revoked"]), (0, True))

    def test_state_show_shows_the_explicit_scope_of_a_head(self) -> None:
        rc, body = self.write("--kind", "state", "--subject", self.repo_id, "--audience", "all", text="en curso: con ámbito")
        self.assertEqual(rc, 0, body)
        head = self.served("state", "show")["slots"][0]
        self.assertEqual((head["subject"], head["audience"]), (self.repo_id, "all"))
        self.assertNotIn("for_reader", head)  # it is for the reader: only the scope is shown
        schema_validator(self, "state-result-v2").validate(self.served("state", "show"))

    def test_without_scope_the_outputs_are_those_of_beta39(self) -> None:
        rc, plain = self.write(text="hecho sin ámbito")
        self.assertEqual(rc, 0, plain)
        self.assertEqual(plain["schema"], "an-kla/remember-result-v1")
        self.assertFalse(any(k in plain for k in ("subject", "audience", "valid_until", "valid_until_input", "until_revoked", "revokes", "subject_normalized_from")))
        rc, state = self.write("--kind", "state", text="estado sin ámbito")
        head = self.served("state", "show")["slots"][0]
        self.assertFalse(any(k in head for k in ("subject", "audience", "for_reader")))
        self.assertEqual(self.served("state", "show")["schema"], "an-kla/state-result-v1")


if __name__ == "__main__":
    unittest.main()
