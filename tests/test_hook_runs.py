"""test_hook_runs.py — F3-C de ADR-0047 (#56).

Cubre el registro de invocaciones: acuñación por el motor (HMAC +
binding + O_EXCL idempotente por run_id), lectura verificada (entrada
inválida jamás contribuye; `attest_not_initialized`; `unknown_hooks`),
el ciclo e2e por CLI (`--on-behalf-of-hook` acuña; invocación plana no
escribe nada) y el perfil `host-managed/v1` con evidencia reciente.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from an_kla import hook_runs
from an_kla.attest import AttestError, ensure_attest_files
from an_kla.store import MemoryStore

ROOT = Path(__file__).resolve().parents[1]


def _declaration() -> dict:
    return {
        "schema": "an-kla/host-hooks-v1",
        "adapter": {
            "name": "cline", "version": "1.0.0",
            "configuration_fingerprint": "sha256:" + "a" * 64,
        },
        "declared_profile": "host-managed/v1",
        "hooks": [
            {"id": "before-task-retrieve", "trigger": "before_task",
             "action": "retrieve", "budget_bytes": 4096},
            {"id": "material-close-checkpoint",
             "trigger": "material_close_or_handoff", "action": "checkpoint",
             "required": True},
        ],
    }


class HookRunsBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="ankla-hook-runs-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = MemoryStore(self.root)
        self.store.initialize()
        ensure_attest_files(self.root)
        self.runs_dir = self.root / ".an-kla" / "hook-runs" / "runs" / "sha256"

    def write_declaration(self) -> None:
        path = self.root / ".an-kla" / "host-hooks.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_declaration()), encoding="utf-8")


class MintTests(HookRunsBase):
    def test_mint_persists_verifiable_entry(self) -> None:
        outcome = hook_runs.mint_hook_run(
            self.store, hook_id="before-task-retrieve",
            trigger="before_task", action="retrieve", exit_code=0,
            subject={"kind": "query", "query": "x", "budget": 100},
        )
        files = list(self.runs_dir.glob("*.json"))
        self.assertEqual(len(files), 1)
        entry = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(entry["schema"], "an-kla/hook-run-v1")
        self.assertEqual(entry["run_id"], outcome["run_id"])
        runs, degraded, unknown = hook_runs.read_verified_runs(
            self.store, {"before-task-retrieve", "material-close-checkpoint"}
        )
        self.assertEqual(degraded, [])
        self.assertEqual(unknown, [])
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["hook_id"], "before-task-retrieve")

    def test_mint_is_idempotent_by_run_id(self) -> None:
        for _ in range(2):
            hook_runs.mint_hook_run(
                self.store, hook_id="before-task-retrieve",
                trigger="before_task", action="retrieve", exit_code=0,
                subject={"kind": "query", "query": "x", "budget": 100},
                run_id="fijo",
            )
        self.assertEqual(len(list(self.runs_dir.glob("*.json"))), 1)

    def test_mint_without_key_fails_closed(self) -> None:
        (self.root / ".an-kla" / "attest.key").unlink()
        with self.assertRaises(AttestError) as ctx:
            hook_runs.mint_hook_run(
                self.store, hook_id="before-task-retrieve",
                trigger="before_task", action="retrieve", exit_code=0,
                subject={"kind": "query", "query": "x", "budget": 100},
            )
        self.assertEqual(str(ctx.exception), "attest_not_initialized")
        self.assertFalse(self.runs_dir.exists())

    def test_mint_rejects_undeclared_grammar(self) -> None:
        with self.assertRaises(hook_runs.HookRunError):
            hook_runs.mint_hook_run(
                self.store, hook_id="mal id", trigger="before_task",
                action="retrieve", exit_code=0, subject={},
            )

    def test_read_tampered_entry_is_invalid_and_never_served(self) -> None:
        hook_runs.mint_hook_run(
            self.store, hook_id="before-task-retrieve",
            trigger="before_task", action="retrieve", exit_code=0,
            subject={"kind": "query", "query": "x", "budget": 100},
        )
        path = next(self.runs_dir.glob("*.json"))
        entry = json.loads(path.read_text(encoding="utf-8"))
        entry["exit_code"] = 1  # mentira con firma vieja
        path.write_text(json.dumps(entry), encoding="utf-8")
        runs, degraded, _ = hook_runs.read_verified_runs(self.store, set())
        self.assertEqual(runs, [])
        self.assertEqual(degraded, ["hook_run_invalid"])

    def test_read_foreign_binding_is_invalid(self) -> None:
        hook_runs.mint_hook_run(
            self.store, hook_id="before-task-retrieve",
            trigger="before_task", action="retrieve", exit_code=0,
            subject={"kind": "query", "query": "x", "budget": 100},
        )
        other = tempfile.TemporaryDirectory(prefix="ankla-other-store-")
        self.addCleanup(other.cleanup)
        other_root = Path(other.name)
        MemoryStore(other_root).initialize()
        ensure_attest_files(other_root)
        foreign = other_root / ".an-kla" / "hook-runs" / "runs" / "sha256"
        foreign.mkdir(parents=True)
        for file in self.runs_dir.glob("*.json"):
            (foreign / file.name).write_bytes(file.read_bytes())
        runs, degraded, _ = hook_runs.read_verified_runs(
            MemoryStore(other_root), set()
        )
        self.assertEqual(runs, [])
        self.assertEqual(degraded, ["hook_run_invalid"])


class ReadEdgeTests(HookRunsBase):
    def test_read_without_key_degrades_not_initialized(self) -> None:
        hook_runs.mint_hook_run(
            self.store, hook_id="before-task-retrieve",
            trigger="before_task", action="retrieve", exit_code=0,
            subject={"kind": "query", "query": "x", "budget": 100},
        )
        runs, degraded, _ = hook_runs.read_verified_runs(self.store, set())
        self.assertEqual(len(runs), 1)
        (self.root / ".an-kla" / "attest.key").unlink()
        runs, degraded, _ = hook_runs.read_verified_runs(self.store, set())
        self.assertEqual(runs, [])
        self.assertEqual(degraded, ["attest_not_initialized"])

    def test_unknown_hook_ids_are_listed_not_served_as_known(self) -> None:
        hook_runs.mint_hook_run(
            self.store, hook_id="before-task-retrieve",
            trigger="before_task", action="retrieve", exit_code=0,
            subject={"kind": "query", "query": "x", "budget": 100},
        )
        runs, _, unknown = hook_runs.read_verified_runs(
            self.store, {"material-close-checkpoint"}
        )
        self.assertEqual(len(runs), 1)
        self.assertEqual(unknown, ["before-task-retrieve"])

    def test_recency_window_is_frozen_24h(self) -> None:
        now = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
        self.assertTrue(hook_runs.is_recent(
            "2026-09-05T00:00:00Z", now))  # 12h
        self.assertFalse(hook_runs.is_recent(
            "2026-09-04T00:00:00Z", now))  # 36h
        self.assertFalse(hook_runs.is_recent("no-es-fecha", now))


class CliEndToEndTests(HookRunsBase):
    def _cli(self, args: list) -> subprocess.CompletedProcess:
        env = dict(os.environ, AN_KLA_NO_UPDATE_CHECK="1")
        return subprocess.run(
            [sys.executable, "-m", "an_kla", "--project-root", str(self.root)] + args,
            capture_output=True, text=True, cwd=str(ROOT), env=env,
        )

    def test_plain_invocation_writes_nothing_and_flag_mints(self) -> None:
        self.write_declaration()
        self._cli(["retrieve", "--query", "x", "--budget", "100"])
        self.assertFalse(self.runs_dir.exists())
        completed = self._cli([
            "retrieve", "--query", "x", "--budget", "100",
            "--on-behalf-of-hook", "before-task-retrieve",
        ])
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(len(list(self.runs_dir.glob("*.json"))), 1)

    def test_status_flag_mints_and_v2_flips_profile(self) -> None:
        self.write_declaration()
        self._cli(["status", "--on-behalf-of-hook", "before-task-retrieve"])
        # hook declarado con acción retrieve: status no coincide -> skip
        self.assertFalse(self.runs_dir.exists() and list(self.runs_dir.glob("*.json")))
        self._cli(["status", "--on-behalf-of-hook", "material-close-checkpoint"])
        # acción declarada es checkpoint, no status -> skip
        self.assertFalse(list(self.runs_dir.glob("*.json")))
        v2 = self._cli(["integration", "status", "--schema-version", "v2"])
        payload = json.loads(v2.stdout)
        self.assertEqual(payload["integration"]["observed_profile"], "declared-not-invoked")
        self.assertEqual(payload["host_hooks"]["pending_continuity"], "required")

    def test_verified_recent_run_flips_profile_to_host_managed(self) -> None:
        self.write_declaration()
        completed = self._cli([
            "retrieve", "--query", "x", "--budget", "100",
            "--on-behalf-of-hook", "before-task-retrieve",
        ])
        self.assertEqual(completed.returncode, 0, completed.stderr)
        v2 = self._cli(["integration", "status", "--schema-version", "v2"])
        payload = json.loads(v2.stdout)
        self.assertEqual(payload["integration"]["observed_profile"], "host-managed/v1")
        self.assertEqual(len(payload["host_hooks"]["hook_invoked"]), 1)
        self.assertEqual(payload["host_hooks"]["pending_continuity"], "required")

    def test_tampered_run_degrades_profile_and_pending_indeterminate(self) -> None:
        self.write_declaration()
        self._cli([
            "retrieve", "--query", "x", "--budget", "100",
            "--on-behalf-of-hook", "before-task-retrieve",
        ])
        path = next(self.runs_dir.glob("*.json"))
        path.write_text("{roto", encoding="utf-8")
        v2 = self._cli(["integration", "status", "--schema-version", "v2"])
        payload = json.loads(v2.stdout)
        self.assertEqual(payload["integration"]["observed_profile"], "declared-not-invoked")
        self.assertIn("hook_run_invalid", payload["host_hooks"]["degraded_codes"])
        self.assertEqual(payload["host_hooks"]["pending_continuity"], "indeterminate")

    def test_recent_unknown_hook_does_not_inflate_profile(self) -> None:
        # Ronda final H1: run reciente de un hook que la declaración ya
        # no lista -> unknown_hooks, perfil declarado-sin-evidencia.
        self.write_declaration()
        self._cli([
            "retrieve", "--query", "x", "--budget", "100",
            "--on-behalf-of-hook", "before-task-retrieve",
        ])
        declaration = _declaration()
        declaration["hooks"] = [
            {"id": "material-close-checkpoint",
             "trigger": "material_close_or_handoff", "action": "checkpoint",
             "required": True},
        ]
        path = self.root / ".an-kla" / "host-hooks.json"
        path.write_text(json.dumps(declaration), encoding="utf-8")
        v2 = self._cli(["integration", "status", "--schema-version", "v2"])
        payload = json.loads(v2.stdout)
        self.assertEqual(payload["integration"]["observed_profile"], "declared-not-invoked")
        self.assertEqual(payload["host_hooks"]["unknown_hooks"], ["before-task-retrieve"])
        self.assertEqual(payload["host_hooks"]["pending_continuity"], "required")

    def test_verified_stale_runs_with_clean_reading_pending_required(self) -> None:
        # Ronda final H2: runs verificados pero viejos y lectura limpia
        # -> required (indeterminate sólo con lectura degradada).
        self.write_declaration()
        old = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        hook_runs.mint_hook_run(
            self.store, hook_id="material-close-checkpoint",
            trigger="material_close_or_handoff", action="checkpoint",
            exit_code=0, subject={"kind": "revision", "value": "x"}, now=old,
        )
        v2 = self._cli(["integration", "status", "--schema-version", "v2"])
        payload = json.loads(v2.stdout)
        self.assertEqual(payload["integration"]["observed_profile"], "declared-not-invoked")
        self.assertEqual(len(payload["host_hooks"]["hook_invoked"]), 1)
        self.assertEqual(payload["host_hooks"]["degraded_codes"], [])
        self.assertEqual(payload["host_hooks"]["pending_continuity"], "required")

    def test_unwritable_runs_dir_does_not_break_successful_command(self) -> None:
        # Ronda final H3: fallo OSError al acuñar no debe romper un
        # comando ya exitoso ni filtrar rutas (hook_run_unwritable).
        declaration = _declaration()
        declaration["hooks"].append(
            {"id": "status-probe", "trigger": "before_task", "action": "status"}
        )
        path = self.root / ".an-kla" / "host-hooks.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(declaration), encoding="utf-8")
        sabotage = self.root / ".an-kla" / "hook-runs"
        sabotage.write_text("no soy directorio", encoding="utf-8")
        completed = self._cli([
            "status", "--on-behalf-of-hook", "status-probe",
        ])
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("hook_run_unwritable", completed.stderr)
        self.assertNotIn(str(self.root), completed.stderr)


if __name__ == "__main__":
    unittest.main()
