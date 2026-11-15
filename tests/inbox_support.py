"""Apoyo de las pruebas de la bandeja (ADR-0063 D1): proyecto Git con store, entorno y candado ajeno."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from typing import Any
from unittest import mock

from an_kla.store import MemoryStore
from tests import write_commit_scenarios as scenarios

GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
AGENT_ENV = {
    "AN_KLA_AGENT_NAME": "ankla-ejecutor-1",
    "AN_KLA_AGENT_CLI": "claude-code",
    "AN_KLA_AGENT_MODEL": "claude-sonnet-5-5",
    "AN_KLA_AGENT_ROLE": "ejecutor",
    "AN_KLA_SESSION_ID": "0a92bdfb-286a-44b5-8c24-8d7a1332c6b6",
}
# Mantiene un candado `flock` en otro proceso hasta que se cierra su stdin.
HOLDER = (
    "import fcntl, os, sys\n"
    "fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)\n"
    "fcntl.flock(fd, fcntl.LOCK_EX if sys.argv[2] == 'ex' else fcntl.LOCK_SH)\n"
    "sys.stdout.write('ready\\n'); sys.stdout.flush()\n"
    "sys.stdin.read()\n"
)


def run_git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main", *args],
        check=True, capture_output=True, env={**os.environ, **GIT_ENV},
    )


def make_project(path: Path) -> Path:
    """Directorio con un repo Git y un commit vacío (C0 exige un repo)."""

    run_git(path, "init", "-q")
    run_git(path, "commit", "-q", "--allow-empty", "-m", "base")
    return path


class InboxCase(unittest.TestCase):
    """Un proyecto Git temporal con un store inicializado; el reloj y el entorno son del test."""

    init_store = True

    def setUp(self) -> None:
        patcher = mock.patch.dict(os.environ, GIT_ENV)
        patcher.start()
        self.addCleanup(patcher.stop)
        temp = tempfile.TemporaryDirectory(prefix="inbox-")
        self.addCleanup(temp.cleanup)
        self.project = make_project(Path(temp.name).resolve())
        self.store = MemoryStore(self.project)
        if self.init_store:
            self.store.initialize()
        self.inbox = Path(self.store.root) / "inbox"

    def commit_record(self, record_id: str, *, stream: str = "facts", **record: Any) -> str:
        """Añade un record vigente (con los campos extra dados) y devuelve la revisión."""

        base = self.store.read_current()
        candidate = scenarios.proposal_v1(base, record_id, **record)
        candidate["stream"] = stream
        authority = scenarios.authority_for(candidate)
        planning = self.store.plan_write(candidate, authority)
        return self.store.commit_write_plan(
            expected_current_hash=base, plan=planning["plan"], proposal=candidate,
            authority=authority, decision=planning["decision"],
        )["revision"]

    def hold_lock(self, mode: str) -> subprocess.Popen:
        """Otro proceso toma ``memory/inbox/.lock`` (``ex`` o ``sh``) hasta cerrar su stdin."""

        self.inbox.mkdir(exist_ok=True)
        child = subprocess.Popen(
            [sys.executable, "-I", "-c", HOLDER, str(self.inbox / ".lock"), mode],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        )
        self.addCleanup(self.release, child)
        self.assertEqual(child.stdout.readline().strip(), "ready")
        return child

    @staticmethod
    def release(child: subprocess.Popen) -> None:
        if child.poll() is None:
            child.stdin.close()
            child.wait(timeout=10)
        child.stdout.close()
