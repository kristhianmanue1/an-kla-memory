"""ADR-0074 §2: el freno por carga (``scripts/load_guard.py``, ``scripts/run_guarded.py``, ``ci_local.run_step``).

Con la fuente de carga inyectable (un archivo con un número). Ninguna de estas pruebas lanza la suite: los «pasos» son un ``sleep`` o un
``python -c`` pequeño, y todo lo que se lanza se mata al acabar.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ci_local  # noqa: E402
import load_guard  # noqa: E402

FAST = {"interval": 0.05, "samples": 6, "term_wait": 3}
HANG = [sys.executable, "-c", "import time\nwhile True:\n    time.sleep(60)"]  # un proceso principal atascado, sin salida


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:  # un zombi no cuenta como vivo
        state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    except OSError:
        return True
    return bool(state) and not state.startswith("Z")


def wait_for(path: Path, timeout: float = 10) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists() and path.read_text().strip():
            return path.read_text().strip()
        time.sleep(0.05)
    raise AssertionError(f"{path} no apareció")


class GuardCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.load = self.dir / "load"
        self.load.write_text("99\n")
        self.spawned: list[subprocess.Popen] = []
        self.addCleanup(self.reap)

    def reap(self) -> None:
        for child in self.spawned:
            if child.poll() is None:
                load_guard.kill_run(child.pid, child.pid, term_wait=2)
                child.kill()
            child.wait()

    def spawn_session(self, argv: list[str]) -> subprocess.Popen:
        child = subprocess.Popen(argv, start_new_session=True)
        self.spawned.append(child)
        return child

    def run_hang(self, argv=None, **kw):
        return load_guard.run_guarded(argv or HANG, threshold=20, load_file=str(self.load), **{**FAST, **kw})


class AbortTests(GuardCase):
    def test_a_sustained_load_aborts_with_75_kills_the_session_and_leaves_the_reason(self) -> None:
        started = time.time()
        outcome = self.run_hang()
        self.assertEqual((outcome.rc, outcome.aborted), (75, True))
        self.assertLess(time.time() - started, 20)  # con el proceso principal atascado en un bucle sin salida
        self.assertEqual(outcome.reason["reason"], "abortada por carga")
        self.assertEqual((outcome.reason["threshold"], len(outcome.reason["samples"])), (20, 6))
        self.assertTrue(all(sample == 99 for sample in outcome.reason["samples"]))
        self.assertTrue(outcome.reason["killed"])

    def test_the_caller_survives_and_ci_local_exits_with_75(self) -> None:
        ci_local.ABORTED.clear()
        self.addCleanup(ci_local.ABORTED.clear)
        self.assertEqual(ci_local.run_step(HANG, threshold=20, load_file=str(self.load), **FAST), "ABORT")  # seguimos vivos para poder decirlo
        self.assertEqual(len(ci_local.ABORTED), 1)
        names = ("paso_import", "paso_redteam_selftest", "paso_matriz", "paso_kill9_bandeja", "paso_sizes", "paso_plans", "paso_adrs")
        patches = [mock.patch.object(ci_local, name, return_value="OK") for name in names]
        patches.append(mock.patch.object(ci_local, "paso_tests", side_effect=lambda simulate: ci_local.run_step(
            HANG, threshold=20, load_file=str(self.load), **FAST)))
        patches.append(mock.patch.object(sys, "argv", ["ci_local.py"]))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.assertEqual(ci_local.main(), 75)  # abortada por carga: distinto de fallo (rc 1)

    def test_a_grandchild_that_went_to_another_session_is_reached_by_the_ppid_tree(self) -> None:
        pidfile = self.dir / "grandchild.pid"
        code = ("import os, subprocess, sys, time\n"
                "child = subprocess.Popen([sys.executable, '-c', 'import time\\nwhile True:\\n    time.sleep(60)'], start_new_session=True)\n"
                f"open({str(pidfile)!r}, 'w').write(str(child.pid))\n"
                "while True:\n    time.sleep(60)\n")
        step = subprocess.Popen([sys.executable, "-c", code], start_new_session=True)  # un paso que lanza un nieto en otra sesión
        self.spawned.append(step)
        grandchild = int(wait_for(pidfile))
        self.assertNotEqual(os.getsid(grandchild), step.pid)
        reason = self.dir / "reason.json"
        status = load_guard.watch(step.pid, step.pid, threshold=20, reason=reason, parent=os.getpid(), load=lambda: 99, **FAST)
        self.assertEqual(status, 75)
        step.wait(timeout=5)
        for _ in range(50):
            if not alive(grandchild):
                break
            time.sleep(0.1)
        self.assertFalse(alive(grandchild))
        self.assertIn(grandchild, [item["pid"] for item in json.loads(reason.read_text())["killed"]])

    def test_a_peak_shorter_than_the_window_does_not_abort(self) -> None:
        self.load.write_text("99\n")
        loads = iter([99, 99, 99, 99, 99] + [1] * 400)  # cinco muestras seguidas: una menos que la ventana

        def load() -> float:
            return next(loads)

        step = self.spawn_session([sys.executable, "-c", "import time; time.sleep(1.5)"])
        status = load_guard.watch(step.pid, step.pid, threshold=20, reason=self.dir / "reason.json", parent=os.getpid(), load=load, **FAST)
        self.assertEqual(status, 0)
        self.assertFalse((self.dir / "reason.json").exists())
        self.assertEqual(step.wait(timeout=5), 0)

    def test_a_reparented_child_is_found_by_its_saved_sid_or_pgid(self) -> None:
        pidfile = self.dir / "orphan.pid"
        code = ("import os, sys, time\n"
                "if os.fork() == 0:\n"
                "    os.setsid()\n"
                f"    open({str(pidfile)!r}, 'w').write(str(os.getpid()))\n"
                "    while True:\n        time.sleep(60)\n"
                "os._exit(0)\n")  # el padre muere antes que su hijo: el hijo queda reparentado a PID 1, en su propia sesión
        subprocess.run([sys.executable, "-c", code], check=True, timeout=20)
        orphan = int(wait_for(pidfile))
        self.addCleanup(lambda: alive(orphan) and os.kill(orphan, signal.SIGKILL))
        table = load_guard.process_table()
        self.assertEqual(table[orphan][0], 1)  # reparentado: fuera de cualquier árbol
        self.assertEqual(load_guard.find_run(None, None, table=table), {})
        saved = os.getsid(orphan)
        self.assertEqual(saved, orphan)
        self.assertIn(orphan, load_guard.find_run(None, None, sids={saved}, table=table))
        self.assertIn(orphan, load_guard.find_run(None, None, pgids={table[orphan][1]}, table=table))
        killed = load_guard.kill_run(None, None, exclude=set(), term_wait=1)  # sin sesión ni árbol: nada que matar, y no mata nada ajeno
        self.assertEqual(killed, [])
        self.assertTrue(alive(orphan))


class LifecycleTests(GuardCase):
    def test_the_guard_of_a_step_is_gone_before_the_next_one_starts(self) -> None:
        self.load.write_text("0\n")
        first = load_guard.run_guarded([sys.executable, "-c", "pass"], threshold=20, load_file=str(self.load), **FAST)
        self.assertEqual((first.rc, first.aborted), (0, False))
        self.assertFalse(alive(first.guard_pid))
        second = load_guard.run_guarded([sys.executable, "-c", "raise SystemExit(3)"], threshold=20, load_file=str(self.load), **FAST)
        self.assertEqual(second.rc, 3)
        self.assertFalse(alive(second.guard_pid))
        self.assertNotEqual(first.guard_pid, second.guard_pid)

    def test_the_kill9_step_and_the_discover_each_have_their_own_guard(self) -> None:
        seen = []
        with mock.patch.object(ci_local, "run_step", side_effect=lambda argv, **kw: seen.append(argv) or "OK"), \
                mock.patch.object(ci_local.Path, "exists", return_value=True):
            self.assertEqual(ci_local.paso_kill9_bandeja(), "OK")
            self.assertEqual(ci_local.paso_tests(False), "OK")
        self.assertIn("tests.test_inbox_crash.Kill9MatrixTests", seen[0])
        self.assertIn("discover", seen[1])

    def test_the_guard_dies_when_its_parent_dies(self) -> None:
        step = self.spawn_session(HANG)
        parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.spawned.append(parent)
        guard = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "load_guard.py"), "--sid", str(step.pid), "--pid", str(step.pid),
                                  "--parent", str(parent.pid), "--reason", str(self.dir / "r.json"), "--threshold", "20", "--interval", "0.05",
                                  "--load-file", str(self.dir / "ninguno")])
        self.addCleanup(lambda: guard.poll() is None and guard.kill())
        time.sleep(0.4)
        self.assertIsNone(guard.poll())  # sigue vivo mientras su padre vive
        parent.kill()
        parent.wait()
        self.assertEqual(guard.wait(timeout=10), 0)  # y muere si su padre muere, sin matar la corrida
        self.assertTrue(alive(step.pid))

    def test_the_reason_file_is_atomic(self) -> None:
        target = self.dir / "reason.json"
        load_guard.write_reason(target, {"a": 1})
        self.assertEqual(json.loads(target.read_text()), {"a": 1})
        self.assertEqual([p.name for p in self.dir.iterdir() if p.name.startswith("reason.json.")], [])  # sin temporales a medias

    def test_a_step_that_leaves_a_process_behind_is_children_left(self) -> None:
        self.load.write_text("0\n")
        pidfile = self.dir / "left.pid"
        code = ("import subprocess, sys\n"
                "child = subprocess.Popen([sys.executable, '-c', 'import time\\nwhile True:\\n    time.sleep(60)'])\n"
                f"open({str(pidfile)!r}, 'w').write(str(child.pid))\n")
        outcome = load_guard.run_guarded([sys.executable, "-c", code], threshold=20, load_file=str(self.load), **FAST)
        self.assertEqual(outcome.rc, 0)
        self.assertTrue(outcome.left)  # el hijo escapado a propósito
        left = int(pidfile.read_text())
        self.assertIn(left, [pid for pid, _name in outcome.left])
        for _ in range(50):
            if not alive(left):
                break
            time.sleep(0.1)
        self.assertFalse(alive(left))  # y se mató
        self.assertEqual(ci_local.run_step([sys.executable, "-c", code], threshold=20, load_file=str(self.load), **FAST), "FAIL")


class RunGuardedCliTests(GuardCase):
    def cli(self, *argv: str, load: str = "0", threshold: str = "20") -> subprocess.CompletedProcess:
        self.load.write_text(load + "\n")
        runner = (f"import sys; sys.path.insert(0, {str(ROOT / 'scripts')!r}); import load_guard, run_guarded\n"
                  f"real = load_guard.run_guarded\n"
                  f"load_guard.run_guarded = lambda *a, **k: real(*a, load_file={str(self.load)!r}, interval=0.05, samples=6, term_wait=3, **k)\n"
                  f"run_guarded.run_guarded = load_guard.run_guarded\n"
                  f"sys.exit(run_guarded.main({list(argv)!r}))")
        return subprocess.run([sys.executable, "-c", runner], capture_output=True, text=True, timeout=60,
                              env={**os.environ, "AN_KLA_CI_LOAD_ABORT": threshold})

    def test_the_rc_of_the_command_passes_through(self) -> None:
        self.assertEqual(self.cli(sys.executable, "-c", "raise SystemExit(7)").returncode, 7)
        self.assertEqual(self.cli(sys.executable, "-c", "pass").returncode, 0)

    def test_it_exits_with_75_when_the_load_aborts_the_command(self) -> None:
        done = self.cli(*HANG, load="99")
        self.assertEqual(done.returncode, 75, done.stderr)
        self.assertIn("abortada por carga", done.stderr)

    def test_the_threshold_comes_from_the_environment(self) -> None:
        self.assertEqual(load_guard.threshold_from_env(), 30.0) if "AN_KLA_CI_LOAD_ABORT" not in os.environ else None
        with mock.patch.dict(os.environ, {"AN_KLA_CI_LOAD_ABORT": "20"}):
            self.assertEqual(load_guard.threshold_from_env(), 20.0)
        with mock.patch.dict(os.environ, {"AN_KLA_CI_LOAD_ABORT": "basura"}):
            self.assertEqual(load_guard.threshold_from_env(), 30.0)


if __name__ == "__main__":
    unittest.main()
