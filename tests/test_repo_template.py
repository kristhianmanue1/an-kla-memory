"""ADR-0074 §4: la plantilla de repo de ``make_project`` y la caché de ``identity_c0`` (``repo_id_for`` y ``branch_for``)."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from an_kla import identity_c0
from tests import inbox_support
from tests.inbox_support import GIT_ENV, make_project, run_git, tree_digest


def git_out(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True, env={**os.environ, **GIT_ENV}).stdout.strip()


class TemplateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()

    def project(self, name: str) -> Path:
        path = self.base / name
        path.mkdir()
        return make_project(path)

    def test_a_copy_is_a_working_repo_with_the_base_commit_and_without_locks(self) -> None:
        self.project("calentar")  # la primera crea la plantilla; las siguientes son copias
        calls = []
        with mock.patch.object(inbox_support, "run_git", side_effect=lambda *a, **k: calls.append(a)):
            project = self.project("uno")
        self.assertEqual(calls, [])  # ni un solo arranque: es una copia
        self.assertEqual(git_out(project, "log", "--format=%s"), "base")
        self.assertEqual(git_out(project, "symbolic-ref", "--short", "HEAD"), "main")
        self.assertEqual(list(project.rglob("*.lock")), [])

    def test_a_copy_is_writable_and_independent_of_the_template(self) -> None:
        one, two = self.project("uno"), self.project("dos")
        (one / "a.txt").write_text("a\n")
        run_git(one, "add", "a.txt")
        run_git(one, "commit", "-q", "-m", "segundo")  # git escribe en la copia
        self.assertEqual(git_out(one, "rev-list", "--count", "HEAD"), "2")
        self.assertEqual(git_out(two, "rev-list", "--count", "HEAD"), "1")  # la otra copia y la plantilla, intactas
        self.assertEqual(tree_digest(inbox_support._TEMPLATE["base"] / ".git"), inbox_support._TEMPLATE["digest"])

    def test_the_local_repo_id_is_still_different_in_each_copy(self) -> None:
        one, two = self.project("uno"), self.project("dos")
        self.assertNotEqual(identity_c0.repo_id_for(one), identity_c0.repo_id_for(two))  # depende de la ruta

    def test_a_touched_template_is_regenerated_and_never_copied(self) -> None:
        self.project("uno")
        template = inbox_support._TEMPLATE["base"]
        (template / ".git" / "config").write_text((template / ".git" / "config").read_text() + "[user]\n\tname = intruso\n")
        self.assertNotEqual(tree_digest(template / ".git"), inbox_support._TEMPLATE["digest"])
        project = self.project("dos")
        self.assertNotIn("intruso", (project / ".git" / "config").read_text())
        self.assertEqual(tree_digest(inbox_support._TEMPLATE["base"] / ".git"), inbox_support._TEMPLATE["digest"])  # regenerada y de nuevo en regla
        self.assertEqual(git_out(project, "log", "--format=%s"), "base")

    def test_the_old_path_is_still_there_to_measure_before_and_after(self) -> None:
        calls = []
        real = inbox_support.run_git
        with mock.patch.dict(os.environ, {"AN_KLA_TEST_NO_REPO_TEMPLATE": "1"}), \
                mock.patch.object(inbox_support, "run_git", side_effect=lambda *a, **k: calls.append(a) or real(*a, **k)):
            project = self.project("antes")
        self.assertEqual([c[1] for c in calls], ["init", "commit"])
        self.assertEqual(git_out(project, "log", "--format=%s"), "base")


class IdentityCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve() / "p"
        root.mkdir()
        self.project = make_project(root)
        identity_c0.clear_cache()
        self.addCleanup(identity_c0.clear_cache)
        real = subprocess.run
        self.runs: list[list[str]] = []
        patcher = mock.patch.object(identity_c0.subprocess, "run", side_effect=lambda cmd, *a, **k: self.runs.append(list(cmd)) or real(cmd, *a, **k))
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, GIT_ENV)
        env.start()
        self.addCleanup(env.stop)

    def test_the_second_call_launches_nothing_and_gives_the_same_answer(self) -> None:
        first = identity_c0.repo_id_for(self.project)
        launched = len(self.runs)
        self.assertGreater(launched, 0)
        self.assertEqual(identity_c0.repo_id_for(self.project), first)
        self.assertEqual(len(self.runs), launched)
        self.assertEqual(identity_c0.branch_for(self.project), "main")
        launched = len(self.runs)
        self.assertEqual(identity_c0.branch_for(self.project), "main")
        self.assertEqual(len(self.runs), launched)

    def test_changing_the_remote_invalidates_the_repo_id(self) -> None:
        before = identity_c0.repo_id_for(self.project)
        self.assertTrue(before.startswith("local:"))
        run_git(self.project, "remote", "add", "origin", "https://example.invalid/org/repo.git")
        after = identity_c0.repo_id_for(self.project)
        self.assertNotEqual(after, before)  # ya no es `local:`
        self.assertFalse(after.startswith("local:"))
        run_git(self.project, "remote", "set-url", "origin", "https://example.invalid/org/otro.git")
        self.assertNotEqual(identity_c0.repo_id_for(self.project), after)

    def test_changing_the_branch_invalidates_the_branch(self) -> None:
        self.assertEqual(identity_c0.branch_for(self.project), "main")
        run_git(self.project, "checkout", "-q", "-b", "feat/otra")
        self.assertEqual(identity_c0.branch_for(self.project), "feat/otra")
        run_git(self.project, "checkout", "-q", "--detach")
        self.assertIsNone(identity_c0.branch_for(self.project))

    def test_a_linked_worktree_follows_its_own_head_and_the_common_config(self) -> None:
        wt = Path(self.temp.name).resolve() / "wt"
        run_git(self.project, "worktree", "add", "-q", "-b", "rama-wt", str(wt))
        self.assertEqual(identity_c0.branch_for(wt), "rama-wt")
        self.assertEqual(identity_c0.branch_for(self.project), "main")  # el principal no se contamina con el del worktree
        before = identity_c0.repo_id_for(wt)
        run_git(self.project, "remote", "add", "origin", "https://example.invalid/org/repo.git")  # el remoto vive en el config común
        self.assertNotEqual(identity_c0.repo_id_for(wt), before)

    def test_a_subdirectory_or_a_changed_environment_is_not_served_from_the_cache(self) -> None:
        sub = self.project / "sub"
        sub.mkdir()
        identity_c0.repo_id_for(sub)
        launched = len(self.runs)
        identity_c0.repo_id_for(sub)
        self.assertGreater(len(self.runs), launched)  # sin `.git` resoluble no se cachea
        identity_c0.repo_id_for(self.project)
        launched = len(self.runs)
        with mock.patch.dict(os.environ, {"HOME": self.temp.name}):
            identity_c0.repo_id_for(self.project)
        self.assertGreater(len(self.runs), launched)  # el entorno que gobierna la configuración entra en la clave


if __name__ == "__main__":
    unittest.main()
