"""ADR-0071, acceptance 4: the three moments (write, audit, read) of a ``document`` anchor, end to end.

Real CLI in a real Git project, with a custodian that is a real process (``fixtures/custodian_adapter_fake.py``) in the
store's ``config.json``.  Writing stores ``anchor_checks``; auditing stores an ``anchor_check`` annotation and serves it;
reading serves the latest stored and **never starts a process** (the adapter is set to fail and its log must stay empty).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from tests.custodian_support import FakeCustodian, schema_validator
from tests.inbox_support import AGENT_ENV, run_git
from tests.remember_support import cli, remember
from tests.scope_support import ScopeCase

PDF = b"%PDF-1.4\n" + bytes(range(256)) * 40
DOC_SHA = hashlib.sha256(PDF).hexdigest()
COPY = "docs/fuentes/manual-2000.pdf"
DERIVATION = "372fdaef" + "0" * 56
MANIFEST = "7f81b161" + "0" * 56
PAGE_TEXT = "Cláusula 47. El personal de base tendrá derecho a veinte días de vacaciones al año."
QUOTE = "El personal de base tendrá derecho a veinte días de vacaciones"
BRANCH = {"AN_KLA_DEFAULT_BRANCH": "main"}


def response(**changes: Any) -> dict[str, Any]:
    """What a custodian answers for page 188, element ``i-13`` of the document above."""
    base = {
        "schema": "memoria/custodio-adaptador/v1", "document": "known", "manifest": "match", "derivation": "current",
        "derivation_parent_sha256": DOC_SHA, "locator": "match", "truncated": False, "custody": {"retention": "effective"},
        "items": [{"item_id": "i-13", "page": 188, "modality": "native_text", "text": PAGE_TEXT}],
    }
    return {**base, **changes}


def shortcut(quote: str = QUOTE, *, page: str | None = "188", items: tuple[str, ...] = ("i-13",), copy: str | None = None,
             document: str = DOC_SHA, custodian: str = "skopos", modality: str = "native_text") -> list[str]:
    args = ["--anchor-document", document, "--anchor-custodian", custodian, "--anchor-derivation", DERIVATION,
            "--anchor-manifest", MANIFEST, "--anchor-modality", modality]
    if page is not None:
        args += ["--anchor-page", page]
    for item in items:
        args += ["--anchor-item", item]
    if copy is not None:
        args += ["--anchor-copy", copy]
    return [*args, "--anchor-quote", quote]


class DocumentCase(ScopeCase):
    def setUp(self) -> None:
        super().setUp()
        (self.project / "docs" / "fuentes").mkdir(parents=True)
        (self.project / COPY).write_bytes(PDF)
        run_git(self.project, "add", COPY)
        run_git(self.project, "commit", "-q", "-m", "copia")
        self.env_a = {**self.env("orq-a"), **BRANCH}
        self.fake = FakeCustodian(self)
        self.fake.install(self.store.store_root, {"mode": "response", "response": response()})

    def write(self, *args: str, text: str = "La cláusula 47 da veinte días de vacaciones.", **options: Any) -> tuple[int, dict]:
        """``(rc, result)``; a rejection prints ``an-kla error: <code> (anchor N)`` on standard error: it comes back as ``{"code"}``."""
        done = cli(self.project, "remember", "--text-file", "-", *args, stdin=text, env=options.pop("env", self.env_a), **options)
        if done.stdout.strip():
            return done.returncode, json.loads(done.stdout)
        found = re.match(r"an-kla error: (\w+)", done.stderr)
        self.assertIsNotNone(found, done.stderr)
        self.assertNotIn(str(self.project), done.stderr)
        return done.returncode, {"code": found.group(1)}

    def written(self, *args: str) -> dict:
        rc, body = self.write(*args)
        self.assertEqual((rc, body.get("state")), (0, "committed"), body)
        return body

    def stored(self, record_id: str) -> dict:
        return next(r for s in ("facts", "events", "episodes") for r in self.store.snapshot().records[s] if r["id"] == record_id)

    def events(self, kind: str) -> list[dict]:
        return [r for r in self.store.snapshot().records["events"] if r.get("kind") == kind]

    def served(self, *args: str, **options: Any) -> dict:
        done = cli(self.project, *args, env=self.env_a, **options)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def history(self, record_id: str) -> dict:
        node = self.served("history", record_id)["nodes"][0]
        return node["anchors"][0]


class WriteTests(DocumentCase):
    def test_writing_stores_the_result_and_the_anchor_is_v2(self) -> None:
        body = self.written(*shortcut(copy=COPY))
        self.assertEqual(body["schema"], "an-kla/remember-result-v4")
        item = body["anchors"][0]
        self.assertEqual((item["kind"], item["freshness"], item["reason"], item["adapter_called"]), ("document", "fresh", None, True))
        self.assertEqual((item["derivation"], item["manifest_sha256"], item["custody"]), ("current", MANIFEST, {"retention": "effective"}))
        record = self.stored(body["record_id"])
        anchor = record["anchors"][0]
        self.assertEqual(anchor["schema"], "memoria/ancla/v2")
        self.assertNotIn("write_check", anchor)  # what writing found does not change the anchor
        self.assertEqual(anchor["source"]["copy"], {"repo": self.repo_id, "path": COPY})  # the tool puts the repo from C0
        self.assertEqual(anchor["source"]["locator"], {"page": 188, "item_id": "i-13"})
        (check,) = record["anchor_checks"]
        self.assertEqual((check["index"], check["quote_sha256"], check["freshness"], check["match"]), (0, anchor["quote_sha256"], "fresh", "literal"))
        self.assertEqual((check["source"], check["integrity"], check["quote"], check["checked_at"] == item["checked_at"]), ("verified",) * 3 + (True,))

    def test_the_locator_is_page_item_or_items_in_the_order_given(self) -> None:
        self.fake.set({"mode": "response", "response": response(items=[
            {"item_id": "i-12", "page": 188, "modality": "native_text", "text": "Cláusula 46."},
            {"item_id": "i-13", "page": 188, "modality": "native_text", "text": PAGE_TEXT}])})
        for items, locator in (((), {"page": 188}), (("i-12", "i-13"), {"page": 188, "item_ids": ["i-12", "i-13"]})):
            with self.subTest(items=items):
                body = self.written(*shortcut(items=items), "--idempotency-key", "k" + str(len(items)))
                self.assertEqual(self.stored(body["record_id"])["anchors"][0]["source"]["locator"], locator)
                self.assertEqual(body["anchors"][0]["freshness"], "fresh")

    def test_without_an_adapter_it_is_accepted_unverified(self) -> None:
        (Path(self.store.store_root) / "config.json").unlink()
        body = self.written(*shortcut())
        item = body["anchors"][0]
        self.assertEqual((item["freshness"], item["reason"], item["source_reason"], item["adapter_called"]), ("unverified", "no_adapter", "no_adapter", False))
        self.assertEqual(self.stored(body["record_id"])["anchor_checks"][0]["integrity_reason"], "no_adapter")
        self.assertFalse(self.fake.called())

    def test_a_failing_adapter_is_accepted_unverified(self) -> None:
        self.fake.set({"mode": "exit_nonzero"})
        item = self.written(*shortcut())["anchors"][0]
        self.assertEqual((item["freshness"], item["reason"], item["adapter_called"]), ("unverified", "adapter_error", True))

    def test_an_unreadable_table_is_adapter_error_with_no_process_and_says_why(self) -> None:
        (Path(self.store.store_root) / "config.json").write_text("{no es json", encoding="utf-8")
        body = self.written(*shortcut())
        item = body["anchors"][0]
        self.assertEqual((item["freshness"], item["reason"], item["adapter_called"]), ("unverified", "adapter_error", False))
        self.assertEqual(body["custodians_config_error"], "custodians_invalid_json")
        self.assertFalse(self.fake.called())

    def test_the_table_of_the_variable_replaces_the_stores_whole(self) -> None:
        other = FakeCustodian(self)
        table = other.dir / "tabla.json"
        table.write_text(json.dumps({"custodians": {"skopos": {"argv": list(other.table({"mode": "response", "response": response(document="unknown", manifest="missing", derivation=None, derivation_parent_sha256=None, locator="not_found", items=[])})["skopos"])}}}))
        rc, body = self.write(*shortcut(), env={**self.env_a, "AN_KLA_CUSTODIANS": str(table)})
        self.assertEqual((rc, body["code"]), (1, "anchor_source_not_found"))  # the variable's custodian answered, the store's did not
        self.assertFalse(self.fake.called())
        self.assertTrue(other.called())
        rc, body = self.write(*shortcut(), env={**self.env_a, "AN_KLA_CUSTODIANS": str(other.dir / "no-existe.json")})
        self.assertEqual((rc, body["state"], body["custodians_config_error"]), (0, "committed", "custodians_unreadable"))


class RejectionTests(DocumentCase):
    def rejected(self, *args: str, **options: Any) -> str:
        rc, body = self.write(*args, **options)
        self.assertNotEqual(rc, 0, body)
        self.assertEqual(self.pending(), [])  # nothing queued
        return body["code"]

    def test_each_rejection_with_the_code_of_its_cause(self) -> None:
        self.assertEqual(self.rejected(*shortcut(page=None)), "anchor_locator_required")
        self.assertEqual(self.rejected(*shortcut(page=None, items=())), "anchor_locator_required")
        self.assertEqual(self.rejected(*shortcut(copy="../fuera.pdf")), "anchor_path_invalid")
        self.assertEqual(self.rejected(*shortcut(copy="docs/no-existe.pdf")), "anchor_copy_not_found")
        self.assertFalse(self.fake.called())  # none of those asked anybody
        self.assertEqual(self.rejected(*shortcut(document="a" * 64, copy=COPY)), "anchor_integrity_not_found")  # another sha256: always
        self.assertFalse(self.fake.called())
        self.assertEqual(self.rejected(*shortcut("demasiado corta")), "anchor_quote_too_short")
        self.assertEqual(self.rejected(*shortcut(custodian="../skopos")), "anchor_schema_invalid")
        self.assertEqual(self.rejected(*shortcut(page="0")), "anchor_schema_invalid")
        self.fake.set({"mode": "response", "response": response(document="unknown", manifest="missing", derivation=None, derivation_parent_sha256=None, locator="not_found", items=[])})
        self.assertEqual(self.rejected(*shortcut()), "anchor_source_not_found")
        self.fake.set({"mode": "response", "response": response(manifest="mismatch", derivation=None, derivation_parent_sha256=None)})
        self.assertEqual(self.rejected(*shortcut()), "anchor_integrity_not_found")
        self.fake.set({"mode": "response", "response": response(derivation="superseded")})
        self.assertEqual(self.rejected(*shortcut()), "anchor_derivation_superseded")
        self.fake.set({"mode": "response", "response": response(items=[{"item_id": "i-13", "page": 188, "modality": "native_text", "text": "Otra cosa."}])})
        self.assertEqual(self.rejected(*shortcut()), "anchor_quote_not_found")

    def test_the_order_form_size_page_path_copy_sha_adapter(self) -> None:
        self.assertEqual(self.rejected(*shortcut("corta", page=None, copy="../x")), "anchor_quote_too_short")
        self.assertEqual(self.rejected(*shortcut(page=None, copy="../x")), "anchor_locator_required")
        self.assertEqual(self.rejected(*shortcut(copy="../x")), "anchor_path_invalid")  # before looking for the copy
        self.assertEqual(self.rejected(*shortcut(document="b" * 64, copy="docs/no-existe.pdf")), "anchor_copy_not_found")

    def test_the_two_exceptions_are_accepted_as_unverified(self) -> None:
        # a correct copy and a custodian that does not know the document
        self.fake.set({"mode": "response", "response": response(document="unknown", manifest="missing", derivation=None, derivation_parent_sha256=None, locator="not_found", items=[])})
        item = self.written(*shortcut(copy=COPY))["anchors"][0]
        self.assertEqual((item["freshness"], item["reason"]), ("unverified", "document_unknown"))
        # `visual`: document and derivation are required, the quote is not checked
        self.fake.set({"mode": "response", "response": response(items=[{"item_id": "i-13", "page": 188, "modality": "visual", "text": ""}])})
        item = self.written(*shortcut(modality="visual"), "--idempotency-key", "visual")["anchors"][0]
        self.assertEqual((item["freshness"], item["reason"]), ("unverified", "derived_modality"))


class CopyTests(DocumentCase):
    """The copy is read by Git from the tip of the default branch, in both moments, never from the working tree."""

    def test_a_copy_only_in_the_working_tree_is_absent(self) -> None:
        (self.project / "docs" / "fuentes" / "nueva.pdf").write_bytes(PDF)
        rc, body = self.write(*shortcut(copy="docs/fuentes/nueva.pdf"))
        self.assertEqual((rc, body["code"]), (1, "anchor_copy_not_found"))

    def test_a_copy_in_a_work_branch_not_integrated_is_absent(self) -> None:
        run_git(self.project, "checkout", "-q", "-b", "trabajo")
        (self.project / "docs" / "fuentes" / "rama.pdf").write_bytes(PDF)
        run_git(self.project, "add", "docs/fuentes/rama.pdf")
        run_git(self.project, "commit", "-q", "-m", "copia en la rama")
        rc, body = self.write(*shortcut(copy="docs/fuentes/rama.pdf"))
        self.assertEqual((rc, body["code"]), (1, "anchor_copy_not_found"))
        run_git(self.project, "checkout", "-q", "main")
        run_git(self.project, "merge", "-q", "--no-ff", "-m", "integrada", "trabajo")
        self.assertEqual(self.written(*shortcut(copy="docs/fuentes/rama.pdf"))["anchors"][0]["freshness"], "fresh")

    def test_without_a_default_branch_the_copy_counts_as_absent(self) -> None:
        rc, body = self.write(*shortcut(copy=COPY), env={**self.env("orq-a"), "AN_KLA_DEFAULT_BRANCH": ""})
        self.assertEqual((rc, body["code"]), (1, "anchor_copy_not_found"))

    def test_a_large_copy_is_hashed_by_blocks_with_no_4_mib_cap(self) -> None:
        big = (b"%PDF-1.4\n" + os.urandom(1024)) * 5200  # > 5 MiB
        self.assertGreater(len(big), 5 * 1024 * 1024)
        (self.project / "docs" / "fuentes" / "grande.pdf").write_bytes(big)
        run_git(self.project, "add", "docs/fuentes/grande.pdf")
        run_git(self.project, "commit", "-q", "-m", "copia grande")
        self.fake.set({"mode": "response", "response": response(derivation_parent_sha256=hashlib.sha256(big).hexdigest())})
        body = self.written(*shortcut(document=hashlib.sha256(big).hexdigest(), copy="docs/fuentes/grande.pdf"))
        self.assertEqual(body["anchors"][0]["freshness"], "fresh")

    def test_a_link_or_a_directory_counts_as_absent(self) -> None:
        os.symlink(COPY.split("/")[-1], self.project / "docs" / "fuentes" / "enlace.pdf")
        run_git(self.project, "add", "docs/fuentes/enlace.pdf")
        run_git(self.project, "commit", "-q", "-m", "enlace")
        for path in ("docs/fuentes/enlace.pdf", "docs/fuentes"):
            with self.subTest(path=path):
                rc, body = self.write(*shortcut(copy=path))
                self.assertEqual((rc, body["code"]), (1, "anchor_copy_not_found"))


class ThreeMomentsTests(DocumentCase):
    def test_reading_serves_the_stored_result_and_starts_no_process(self) -> None:
        body = self.written(*shortcut(copy=COPY))
        self.fake.set({"mode": "exit_nonzero"})  # if anybody calls it, the log shows it
        for command in (("history", body["record_id"]), ("state", "show"), ("list",)):
            self.served(*command)
        shown = self.history(body["record_id"])
        self.assertEqual((shown["freshness"], shown["checked_at"], shown["derivation"], shown["manifest_sha256"]),
                         ("fresh", body["anchors"][0]["checked_at"], "current", MANIFEST))
        self.assertIsNone(shown["matched_text"])
        self.assertFalse(self.fake.called(), "reading llamó al adaptador")

    def test_auditing_stores_an_annotation_and_serves_it(self) -> None:
        body = self.written(*shortcut(copy=COPY))
        written_at = body["anchors"][0]["checked_at"]
        self.fake.set({"mode": "response", "response": response(manifest="mismatch", derivation=None, derivation_parent_sha256=None)})
        audit = self.served("anchors", "verify", body["record_id"])
        self.assertEqual(audit["schema"], "an-kla/anchors-verify-v4")
        record = audit["records"][0]
        self.assertTrue(record["recorded"], record)
        item = record["anchors"][0]
        self.assertEqual((item["freshness"], item["reason"], item["integrity_reason"], item["adapter_called"]), ("broken", "manifest_mismatch", "manifest_mismatch", True))
        (note,) = self.events("anchor_check")
        self.assertEqual(note["anchor_check"]["schema"], "an-kla/anchor-check-v1")
        self.assertEqual(note["anchor_check"]["target"], {"stream": "facts", "record_id": body["record_id"]})
        self.assertEqual(note["an_kla_envelope"]["kind"], "fact")
        self.assertGreater(note["anchor_check"]["checks"][0]["checked_at"], written_at)
        self.fake.set({"mode": "exit_nonzero"})
        shown = self.history(body["record_id"])  # the audit is later than the write: it is what reading serves
        self.assertEqual((shown["freshness"], shown["reason"], shown["checked_at"]), ("broken", "manifest_mismatch", note["anchor_check"]["checks"][0]["checked_at"]))
        self.assertFalse(self.fake.called())

    def test_every_audit_adds_its_own_annotation(self) -> None:
        body = self.written(*shortcut())
        for _ in range(2):
            self.assertTrue(self.served("anchors", "verify", body["record_id"])["records"][0]["recorded"])
        self.assertEqual(len(self.events("anchor_check")), 2)

    def test_a_v2_anchor_never_checked_is_not_checked_and_a_v1_one_is_kind_not_supported(self) -> None:
        anchor = {"schema": "memoria/ancla/v2", "quote": QUOTE, "quote_sha256": hashlib.sha256(QUOTE.encode()).hexdigest(),
                  "source": {"kind": "document", "document_sha256": DOC_SHA, "locator": {"page": 188},
                            "derivation": {"custodian": "skopos", "derivation_id": DERIVATION, "manifest_sha256": MANIFEST, "modality": "native_text"}}}
        v1 = {**anchor, "schema": "memoria/ancla/v1", "source": {**anchor["source"], "locator": "unknown"}}
        self.commit_record("f-v2", anchors=[anchor])
        self.commit_record("f-v1", anchors=[v1])
        shown = self.history("f-v2")
        self.assertEqual((shown["freshness"], shown["reason"], shown["source_reason"], shown["checked_at"]), ("unverified", "not_checked", "not_checked", None))
        old = self.history("f-v1")
        self.assertEqual((old["freshness"], old["reason"], old["source_reason"]), ("unverified", "kind_not_supported", "kind_not_supported"))
        self.assertNotIn("checked_at", old)  # exactly what beta.38 served
        self.assertFalse(self.fake.called())

    def test_the_first_audit_of_a_v1_anchor_stores_its_result_also_without_a_custodian(self) -> None:
        (Path(self.store.store_root) / "config.json").unlink()
        v1 = {"schema": "memoria/ancla/v1", "quote": QUOTE, "quote_sha256": hashlib.sha256(QUOTE.encode()).hexdigest(),
              "source": {"kind": "document", "document_sha256": DOC_SHA, "locator": "unknown",
                         "derivation": {"custodian": "skopos", "derivation_id": DERIVATION, "manifest_sha256": MANIFEST, "modality": "native_text"}}}
        self.commit_record("f-v1", anchors=[v1])
        audit = self.served("anchors", "verify", "f-v1")["records"][0]
        self.assertTrue(audit["recorded"], audit)
        self.assertEqual((audit["anchors"][0]["reason"], audit["anchors"][0]["adapter_called"]), ("no_adapter", False))
        shown = self.history("f-v1")  # from now on it serves what is stored
        self.assertEqual((shown["reason"], shown["checked_at"] is not None), ("no_adapter", True))

    def test_auditing_without_a_c0_identity_answers_and_says_it_did_not_record(self) -> None:
        body = self.written(*shortcut())
        done = cli(self.project, "anchors", "verify", body["record_id"], env=BRANCH, agent=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        record = json.loads(done.stdout)["records"][0]
        self.assertEqual((record["recorded"], record["record_error"], record["anchors"][0]["freshness"]), (False, "identity_env_missing", "fresh"))
        self.assertEqual(self.events("anchor_check"), [])

    def test_auditing_only_writes_for_document_anchors(self) -> None:
        (self.project / "nota.txt").write_text("El puerto de quetzal es 8081 siempre.\n")
        run_git(self.project, "add", "nota.txt")
        run_git(self.project, "commit", "-q", "-m", "nota")
        rc, body = remember(self.project, "el puerto es 8081", "--anchor-path", "nota.txt", "--anchor-quote", "puerto de quetzal es 8081", env=self.env_a)
        self.assertEqual(rc, 0, body)
        before = self.store.read_current()
        audit = self.served("anchors", "verify", "--all")
        self.assertTrue(all("recorded" not in record and "record_error" not in record for record in audit["records"]))
        self.assertTrue(all("checked_at" not in a for record in audit["records"] for a in record["anchors"]))  # the output stays as it was
        self.assertEqual(self.store.read_current(), before)  # nothing was written

    def test_a_retry_of_the_same_audit_is_already_committed_and_does_not_duplicate(self) -> None:
        from datetime import datetime, timezone
        from types import SimpleNamespace
        from an_kla.anchors_read import verify_command

        body = self.written(*shortcut())
        fixed = lambda: datetime(2026, 11, 19, 21, 0, 0, tzinfo=timezone.utc)  # noqa: E731
        args = SimpleNamespace(all=False, id=body["record_id"], anchor_limit=32)
        with mock.patch.dict(os.environ, {**AGENT_ENV, "AN_KLA_AGENT_NAME": "orq-a", "AN_KLA_DEFAULT_BRANCH": "main"}):
            first = verify_command(self.store, args, clock=fixed)
            second = verify_command(self.store, args, clock=fixed)  # the cut-off retry: the same key
        self.assertEqual([r["records"][0]["recorded"] for r in (first, second)], [True, True])
        self.assertEqual(len(self.events("anchor_check")), 1)


class SchemaTests(DocumentCase):
    """ADR-0071 §6: what is answered and stored validates against the widened (unpublished) schemas and the new one."""

    def validator(self, name: str) -> Any:
        return schema_validator(self, name)

    def test_every_answer_validates_against_its_schema(self) -> None:
        body = self.written(*shortcut(copy=COPY))
        self.validator("remember-result-v4").validate(body)
        state = self.write(*shortcut(), "--kind", "state", "--idempotency-key", "estado", text="en curso: la cláusula 47")[1]
        self.assertEqual(state["state"], "committed", state)
        self.validator("remember-result-v4").validate(state)
        self.fake.set({"mode": "response", "response": response(manifest="mismatch", derivation=None, derivation_parent_sha256=None)})
        audit = self.served("anchors", "verify", "--all")
        self.validator("anchors-verify-v4").validate(audit)
        self.assertTrue(all(record["recorded"] for record in audit["records"]), audit)
        self.fake.set({"mode": "exit_nonzero"})
        history = self.served("history", body["record_id"])
        self.validator("history-result-v3").validate(history)
        self.assertEqual(history["schema"], "an-kla/history-result-v3")
        shown = self.served("state", "show", "--all-slots")
        self.validator("state-result-v3").validate(shown)
        for note in self.events("anchor_check"):
            self.validator("anchor-check-v1").validate(note["anchor_check"])
        self.assertFalse(self.fake.called())

    def test_a_not_checked_anchor_and_a_config_error_validate(self) -> None:
        anchor = {"schema": "memoria/ancla/v2", "quote": QUOTE, "quote_sha256": hashlib.sha256(QUOTE.encode()).hexdigest(),
                  "source": {"kind": "document", "document_sha256": DOC_SHA, "locator": {"page": 188},
                            "derivation": {"custodian": "skopos", "derivation_id": DERIVATION, "manifest_sha256": MANIFEST, "modality": "native_text"}}}
        self.commit_record("f-v2", anchors=[anchor])
        history = self.served("history", "f-v2")
        self.validator("history-result-v2").validate(history)
        (Path(self.store.store_root) / "config.json").write_text("[]", encoding="utf-8")
        body = self.written(*shortcut())
        self.assertEqual(body["custodians_config_error"], "custodians_invalid_shape")
        self.validator("remember-result-v4").validate(body)
        audit = self.served("anchors", "verify", "f-v2")
        self.assertEqual(audit["custodians_config_error"], "custodians_invalid_shape")
        self.validator("anchors-verify-v3").validate(audit)


class InvariantTests(DocumentCase):
    def annotation(self, record_id: str, **changes: Any) -> dict:
        record = self.stored(record_id)
        check = {"index": 0, "quote_sha256": record["anchors"][0]["quote_sha256"], "checked_at": "2026-11-19T21:00:00.000000Z",
                 "manifest_sha256": MANIFEST, "derivation": "current", "source": "verified", "source_reason": None,
                 "integrity": "verified", "integrity_reason": None, "quote": "verified", "quote_reason": None, "match": "literal",
                 "freshness": "fresh", "reason": None, "custody": None}
        note = {"schema": "an-kla/anchor-check-v1", "target": {"stream": "facts", "record_id": record_id}, "checks": [check]}
        return {**note, **changes}

    def drained_code(self, annotation: dict, name: str) -> list[str]:
        from an_kla import inbox
        from an_kla.inbox_drain import drain

        with mock.patch.dict(os.environ, {**AGENT_ENV, "AN_KLA_AGENT_NAME": "orq-a"}):
            queued = inbox.enqueue(self.store, f"anchor_check {name}", kind="fact", operation="anchor_check", anchor_check=annotation)
        report = drain(self.store, include_entry=queued["entry"], max_batches=1)
        return [r["code"] for r in report["rejected"]["entries"]]

    def test_an_annotation_that_breaks_an_invariant_is_rejected_when_drained(self) -> None:
        record_id = self.written(*shortcut())["record_id"]
        good = self.annotation(record_id)
        bad_sha = self.annotation(record_id)
        bad_sha["checks"][0]["quote_sha256"] = "0" * 64
        out_of_range = self.annotation(record_id)
        out_of_range["checks"][0]["index"] = 3
        bad_form = self.annotation(record_id)
        bad_form["checks"][0]["freshness"] = "stale"
        missing = self.annotation(record_id, target={"stream": "facts", "record_id": "no-existe"})
        for name, annotation in (("sha", bad_sha), ("index", out_of_range), ("forma", bad_form), ("destino", missing)):
            with self.subTest(name):
                self.assertEqual(self.drained_code(annotation, name), ["anchor_check_invalid"])
        self.assertEqual(self.drained_code(good, "buena"), [])
        self.assertEqual(len(self.events("anchor_check")), 1)

    def test_an_annotation_of_an_anchor_that_is_not_a_document_is_rejected(self) -> None:
        (self.project / "nota.txt").write_text("El puerto de quetzal es 8081 siempre.\n")
        run_git(self.project, "add", "nota.txt")
        run_git(self.project, "commit", "-q", "-m", "nota")
        rc, body = remember(self.project, "el puerto es 8081", "--anchor-path", "nota.txt", "--anchor-quote", "puerto de quetzal es 8081", env=self.env_a)
        self.assertEqual(rc, 0, body)
        self.assertEqual(self.drained_code(self.annotation(body["record_id"]), "repo"), ["anchor_check_invalid"])

    def test_an_annotation_of_a_retired_target_is_rejected(self) -> None:
        first = self.written(*shortcut())
        rc, newer = self.write(*shortcut(), "--supersedes", first["record_id"], "--idempotency-key", "otra", text="La cláusula 47, corregida.")
        self.assertEqual(rc, 0, newer)
        self.assertEqual(self.drained_code(self.annotation(first["record_id"]), "retirado"), ["anchor_check_invalid"])


if __name__ == "__main__":
    unittest.main()
