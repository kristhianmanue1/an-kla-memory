"""G3 R1c: entry × custody-state matrix (ADR-0048 §1, §5).

Every entry (CLI, MCP, upgrade, attest, hook-runs, the git hook template)
opens the same identity and revision under external custody, and none of
them creates a twin vault when resolution is missing or divergent.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from an_kla.custody import pointer_path
from an_kla.integration import integration_status_v2, integration_status_v3
from an_kla.mcp import ReadOnlyMcp
from an_kla.store import MemoryStore
from an_kla.upgrade import verify_upgrade
from tests.test_upgrade import TARGET

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "docs" / "hooks-template" / "pre-commit"


def _env(**extra: str) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key != "AN_KLA_STORE_ROOT"}
    env["AN_KLA_NO_UPDATE_CHECK"] = "1"
    env.update(extra)
    return env


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True,
        env=_env(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e",
                 GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e"),
    )


class CustodyEntryMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name).resolve()
        self.project = self.base / "project"
        self.project.mkdir()
        self.vault = self.base / "vaults" / "vault"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _cli(self, *args: str, root: Path | None = None, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "an_kla", "--project-root", str(root or self.project), *args],
            capture_output=True, text=True, cwd=str(ROOT), env=_env(**env),
        )

    def _json(self, completed: subprocess.CompletedProcess) -> dict:
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def _init_external_cli(self) -> str:
        result = self._json(self._cli("--store-root", str(self.vault), "init"))
        self.assertTrue(pointer_path(self.project).exists())
        return result["revision"]

    def test_cli_resolves_flag_env_and_pointer_to_the_same_vault(self) -> None:
        revision = self._init_external_cli()
        by_pointer = self._json(self._cli("status"))
        by_env = self._json(self._cli("status", AN_KLA_STORE_ROOT=str(self.vault)))
        by_flag = self._json(self._cli("--store-root", str(self.vault), "status"))
        for result in (by_pointer, by_env, by_flag):
            self.assertEqual(result["revision"], revision)
        self.assertFalse((self.project / ".an-kla" / "memory").exists())

    def test_cli_divergent_env_warns_and_cannot_mutate(self) -> None:
        self._init_external_cli()
        other = self.base / "other"
        other.mkdir()
        foreign = self.base / "foreign"
        self._json(self._cli("--store-root", str(foreign), "init", root=other))
        status = self._cli("status", AN_KLA_STORE_ROOT=str(foreign))
        self.assertIn("pointer_fingerprint_mismatch", status.stderr)
        init = self._cli("init", AN_KLA_STORE_ROOT=str(foreign))
        self.assertNotEqual(init.returncode, 0)
        self.assertIn("store_root_divergence", init.stderr)
        self.assertNotIn(str(self.base), init.stderr)

    def test_cli_flag_env_divergence_is_reported(self) -> None:
        self._init_external_cli()
        completed = self._cli(
            "--store-root", str(self.vault), "status",
            AN_KLA_STORE_ROOT=str(self.base / "elsewhere"),
        )
        self._json(completed)
        self.assertIn("store_root_flag_env_divergence", completed.stderr)

    def test_cli_invalid_pointer_keeps_carve_outs_and_fails_closed(self) -> None:
        anchor = self.project / ".an-kla"
        anchor.mkdir()
        pointer_path(self.project).write_bytes(b"garbage")
        self._json(self._cli("capabilities"))
        init = self._cli("init")
        self.assertNotEqual(init.returncode, 0)
        self.assertIn("store_root_pointer_invalid", init.stderr)
        self.assertFalse((anchor / "memory").exists())

    def test_cli_attest_and_hook_evidence_live_in_vault(self) -> None:
        self._init_external_cli()
        receipt = self._json(self._cli("attest", "run", "--", "git", "diff"))
        self.assertTrue((self.vault / receipt["receipt_path"].removeprefix(".an-kla/")).exists())
        self.assertFalse((self.project / ".an-kla" / "receipts").exists())
        self.assertEqual(sorted(os.listdir(self.project / ".an-kla")), ["store-root.txt"])

    def test_startup_and_integration_through_cli(self) -> None:
        self._init_external_cli()
        startup = self._json(self._cli("startup-diagnostic"))
        self.assertEqual(startup["schema"], "an-kla/startup-diagnostic-v3")
        self.assertEqual(startup["custody"]["divergence"], "none")
        integration = self._json(self._cli("integration", "status", "--schema-version", "v3"))
        self.assertEqual(integration["host_hooks"]["runs_custody"], "store_external")
        v1 = self._json(self._cli("integration", "status"))
        self.assertIs(v1["store"]["external_memory_evaluated"], False)
        self.assertNotIn(str(self.base), json.dumps(integration))

    def test_integration_v2_and_v3_read_vault_hook_runs(self) -> None:
        store = MemoryStore(self.project, store_root=self.vault)
        store.initialize()
        self.assertEqual(integration_status_v2(store)["host_hooks"]["degraded_codes"], [])
        self.assertEqual(
            integration_status_v3(store)["store"]["custody"]["store_external"], True
        )

    def test_mcp_and_upgrade_follow_the_pointer(self) -> None:
        revision = self._init_external_cli()
        server = ReadOnlyMcp(self.project)
        self.assertEqual(server.call("an_kla_status", {})["revision"], revision)
        self.assertTrue(server.store.store_external)
        verified = verify_upgrade(self.project, TARGET)
        self.assertEqual(verified["memory"]["status"], "verified")
        self.assertEqual(verified["memory"]["verification"]["revision"], revision)

    def test_worktree_without_and_with_resolution(self) -> None:
        _git(self.project, "init", "-q")
        (self.project / "README").write_text("x", encoding="utf-8")
        _git(self.project, "add", "README")
        _git(self.project, "commit", "-q", "-m", "init")
        revision = self._init_external_cli()
        worktree = self.base / "worktree"
        _git(self.project, "worktree", "add", "-q", str(worktree))

        bare = self._json(self._cli("startup-diagnostic", root=worktree))
        self.assertEqual(bare["store_presence"], "absent")
        self.assertEqual(bare["repo_context"], "linked_worktree")
        self.assertFalse((worktree / ".an-kla").exists())

        resolved = self._json(
            self._cli("status", root=worktree, AN_KLA_STORE_ROOT=str(self.vault))
        )
        self.assertEqual(resolved["revision"], revision)
        ids = self._json(self._cli(
            "identity", "status", "--show-ids", root=worktree,
            AN_KLA_STORE_ROOT=str(self.vault),
        ))
        main = self._json(self._cli("identity", "status", "--show-ids"))
        for key in ("project_uuid", "store_uuid", "store_identity", "identity_status"):
            self.assertEqual(ids[key], main[key])
        # The worktree path is observational only (ADR-0048 §2).
        self.assertIs(ids["root_relocated"], True)
        self.assertFalse((worktree / ".an-kla").exists())

    def test_git_hook_template_ignores_inherited_env(self) -> None:
        _git(self.project, "init", "-q")
        (self.project / "README").write_text("x", encoding="utf-8")
        _git(self.project, "add", "README")
        _git(self.project, "commit", "-q", "-m", "init")
        self._init_external_cli()
        worktree = self.base / "worktree"
        _git(self.project, "worktree", "add", "-q", str(worktree))
        log = self.base / "env.log"
        wrapper = self.base / "python-wrapper"
        wrapper.write_text(
            "#!/bin/bash\n"
            f'echo "${{AN_KLA_STORE_ROOT-unset}}" >> "{log}"\n'
            f'exec "{sys.executable}" "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        foreign = str(self.base / "foreign")
        env = _env(AN_KLA_PYTHON=str(wrapper), AN_KLA_STORE_ROOT=foreign,
                   PYTHONPATH=str(ROOT))
        # Positive control: the wrapper does record an inherited variable.
        subprocess.run([str(wrapper), "-c", "pass"], env=env, check=True)
        self.assertEqual(log.read_text(encoding="utf-8").split(), [foreign])
        log.unlink()
        for cwd in (self.project, worktree):
            completed = subprocess.run(
                ["bash", str(HOOK)], cwd=str(cwd), capture_output=True,
                text=True, env=env,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertNotIn("BLOQ", completed.stderr)
        calls = log.read_text(encoding="utf-8").split()
        self.assertTrue(calls)
        self.assertEqual(set(calls), {"unset"})
        self.assertFalse((worktree / ".an-kla").exists())
        self.assertEqual(sorted(os.listdir(self.project / ".an-kla")), ["store-root.txt"])


if __name__ == "__main__":
    unittest.main()
