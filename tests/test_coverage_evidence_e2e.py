"""Erratum 7 of ``ancla/v1`` (ADR-0073 §8), end to end: the page and the copy of a ``document`` anchor count as evidence, the answer says so, and
without such an anchor the output is what it always was."""

from __future__ import annotations

import unittest

from tests.custodian_support import schema_validator
from tests.test_document_v2_write import COPY, DocumentCase, shortcut

TEXT = "En la página 188 de docs/fuentes/manual-2000.pdf consta que hay veinte días de vacaciones."


class EvidenceTests(DocumentCase):
    def test_the_page_and_the_path_of_the_copy_are_present_and_the_answer_declares_the_evidence(self) -> None:
        rc, body = self.write(*shortcut(copy=COPY), text=TEXT)
        self.assertEqual((rc, body["state"]), (0, "committed"), body)
        self.assertEqual(body["coverage"], {"total": 2, "present": 2, "level": "full", "rules": "fact-checks-rules/v2", "evidence": "ancla-document/v1"})
        self.assertEqual((body["missing"], body["missing_total"]), ([], 0))
        self.assertEqual(body["schema"], "an-kla/remember-result-v4")  # `coverage.evidence` alone raises the sparse version
        self.assertEqual(self.stored(body["record_id"])["coverage"], body["coverage"])
        schema_validator(self, "remember-result-v4").validate(body)
        shown = self.served("history", body["record_id"])
        self.assertEqual((shown["schema"], shown["nodes"][0]["coverage"]["evidence"]), ("an-kla/history-result-v3", "ancla-document/v1"))
        schema_validator(self, "history-result-v3").validate(shown)

    def test_without_the_copy_only_the_page_counts(self) -> None:
        rc, body = self.write(*shortcut(), text=TEXT)
        self.assertEqual((rc, body["coverage"]["present"], body["coverage"]["total"]), (0, 1, 2), body)
        self.assertEqual(body["missing"], [{"type": "path", "value": "docs/fuentes/manual-2000.pdf"}])

    def test_a_record_without_a_document_anchor_is_as_it_was(self) -> None:
        (self.project / "nota.txt").write_text("El puerto de quetzal es 8081 siempre.\n")
        from tests.inbox_support import run_git

        run_git(self.project, "add", "nota.txt")
        run_git(self.project, "commit", "-q", "-m", "nota")
        done = self.write("--anchor-path", "nota.txt", "--anchor-quote", "puerto de quetzal es 8081", text="El puerto es 8081.")
        self.assertEqual(done[0], 0, done[1])
        self.assertNotIn("evidence", done[1]["coverage"])
        self.assertEqual(done[1]["schema"], "an-kla/remember-result-v2")


if __name__ == "__main__":
    unittest.main()
