"""The anchor commands through the real CLI: ``remember --anchor-*``, ``dispute``, ``anchors verify`` and the limit flags."""

from __future__ import annotations

import json
from typing import Any

from tests.inbox_support import InboxCase, run_git
from tests.remember_support import cli, remember

QUOTE = "El servidor usa port = 8081"
BRANCH = {"AN_KLA_DEFAULT_BRANCH": "main"}


class AnchorsCliTest(InboxCase):
    def setUp(self) -> None:
        super().setUp()
        (self.project / "docs").mkdir()
        (self.project / "docs" / "a.md").write_text(f"# Bandeja\n\n{QUOTE}.\n", encoding="utf-8")
        run_git(self.project, "add", "-A")
        run_git(self.project, "commit", "-q", "-m", "doc")

    def run_json(self, *args: str, **options: Any) -> tuple[int, dict]:
        done = cli(self.project, *args, env=BRANCH, **options)
        return done.returncode, json.loads(done.stdout) if done.stdout.strip() else {}

    def test_remember_with_the_shortcut_takes_head_and_reports_the_checks(self) -> None:
        rc, result = remember(self.project, "el servidor usa el puerto 8080", "--anchor-path", "docs/a.md",
                              "--anchor-quote", QUOTE, env=BRANCH)
        self.assertEqual((rc, result["state"]), (0, "committed"))
        self.assertEqual((result["anchors"][0]["at"], result["anchors"][0]["freshness"]), ("commit", "fresh"))
        self.assertEqual((result["coverage"]["level"], result["missing"]), ("none", [{"type": "number", "value": "8080"}]))
        rc, verified = self.run_json("anchors", "verify", result["record_id"])
        self.assertEqual((rc, verified["records"][0]["anchors_freshness"]), (0, "fresh"))
        self.assertEqual(verified["records"][0]["anchors"][0]["anchor"]["path"], "docs/a.md")

    def test_two_shortcut_groups_and_an_anchor_file_make_three_anchors(self) -> None:
        extra = json.dumps([{"source": {"kind": "conversation"}, "quote": "manda renovar de manera indefinida"}])
        done = cli(self.project, "remember", "--text-file", "-", "--anchor-file", "-",
                   "--anchor-path", "docs/a.md", "--anchor-quote", QUOTE, "--anchor-path", "docs/a.md",
                   "--anchor-quote", "# Bandeja", env=BRANCH, stdin="x")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("anchor_input_invalid", done.stderr)  # stdin cannot carry the text and the anchors
        path = self.project / "anclas.json"
        path.write_text(extra, encoding="utf-8")
        rc, result = remember(self.project, "un hecho con tres anclas citadas", "--anchor-file", str(path),
                              "--anchor-path", "docs/a.md", "--anchor-quote", QUOTE,
                              "--anchor-path", "docs/a.md", "--anchor-quote", "# Bandeja", env=BRANCH)
        self.assertEqual(rc, 0, result)
        self.assertEqual([a["kind"] for a in result["anchors"]], ["conversation", "repo-file", "repo-file"])
        self.assertEqual(result["anchors"][0]["freshness"], "pending")

    def test_bad_inputs_are_refused_without_queueing_anything(self) -> None:
        bad = self.project / "mala.json"
        bad.write_text("{no json", encoding="utf-8")
        for args, code in (
            (("--anchor-file", str(bad)), "anchor_input_invalid"),
            (("--anchor-path", "docs/a.md"), "anchor_input_invalid"),
            (("--anchor-path", "docs/a.md", "--anchor-quote", "no está en el archivo"), "anchor_quote_not_found"),
            (("--anchor-path", "../fuera.md", "--anchor-quote", QUOTE), "anchor_path_invalid"),
            (("--anchor-path", "docs/a.md", "--anchor-quote", "abc"), "anchor_quote_too_short"),
        ):
            with self.subTest(code=code, args=args):
                done = cli(self.project, "remember", "--text-file", "-", *args, env=BRANCH, stdin="un texto")
                self.assertNotEqual(done.returncode, 0)
                self.assertIn(code, done.stderr)
                self.assertNotIn(str(self.project), done.stderr)
        self.assertEqual(list((self.inbox / "pending").glob("*.json")) if (self.inbox / "pending").exists() else [], [])

    def test_dispute_through_the_cli_and_the_read_commands(self) -> None:
        _, target = remember(self.project, "el servidor usa 8081", "--anchor-path", "docs/a.md",
                             "--anchor-quote", QUOTE, env=BRANCH)
        done = cli(self.project, "dispute", target["record_id"], "--verdict", "supported", "--text-file", "-",
                   env=BRANCH, stdin="dictamen")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("dispute_verdict_invalid", done.stderr)
        done = cli(self.project, "dispute", "f-r-nadie", "--verdict", "contradicted", "--text-file", "-",
                   env=BRANCH, stdin="dictamen")
        self.assertIn("dispute_target_missing", done.stderr)
        rc, result = self.run_json("dispute", target["record_id"], "--verdict", "contradicted", "--text-file", "-",
                                   stdin="la prueba no respalda el hecho")
        self.assertEqual((rc, result["state"], result["verdict"]), (0, "committed", "contradicted"))
        self.assertEqual(result["disputed"]["target_id"], target["record_id"])
        rc, history = self.run_json("history", target["record_id"], "--anchor-limit", "1")
        self.assertEqual(rc, 0)
        by_id = {n["id"]: n for n in history["nodes"]}
        self.assertEqual(by_id[target["record_id"]]["disputed"][0]["verdict"], "contradicted")
        self.assertEqual((history["anchor_limit"], history["anchors_checked"]), (1, 1))
        rc, listed = self.run_json("disputes", "list", "--target", target["record_id"])
        self.assertEqual((rc, listed["disputes"][0]["verdict"]), (0, "contradicted"))

    def test_anchors_verify_needs_an_id_or_all_and_a_positive_limit(self) -> None:
        for args in (("anchors", "verify"), ("anchors", "verify", "x", "--all"),
                     ("anchors", "verify", "--all", "--anchor-limit", "0")):
            done = cli(self.project, *args, env=BRANCH)
            self.assertNotEqual(done.returncode, 0, args)
        done = cli(self.project, "anchors", "verify", "f-r-nadie", env=BRANCH)
        self.assertIn("anchors_id_not_found", done.stderr)
