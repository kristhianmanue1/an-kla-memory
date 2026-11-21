"""ADR-0074 §1: los procesos de las pruebas tienen dueño (``tests/proc_support.py``) y ``drain_loop`` tiene plazo propio."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests import proc_support
from tests.remember_support import ROOT, cli_env

sys.path.insert(0, str(ROOT / "scripts"))

SLEEPER = "import time\nwhile True:\n    time.sleep(60)"
WITH_GRANDCHILD = ("import subprocess, sys, time\n"
                   "g = subprocess.Popen([sys.executable, '-c', 'import time\\nwhile True:\\n    time.sleep(60)'])\n"
                   "print(g.pid, flush=True)\n"
                   "while True:\n    time.sleep(60)")


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(state) and not state.startswith("Z")


def gone(pid: int, seconds: float = 8) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not alive(pid):
            return True
        time.sleep(0.05)
    return False


class DeathByGroupTests(unittest.TestCase):
    def test_a_failure_in_the_middle_of_a_spawn_leaves_nobody_of_the_group(self) -> None:
        """Aceptación 1: una prueba falla a mitad de un ``spawn`` con un nieto vivo; al acabar no queda nadie de su grupo."""
        seen: dict[str, int] = {}

        class Failing(unittest.TestCase):
            def test_it(self) -> None:
                child = proc_support.spawn_for(self, [sys.executable, "-c", WITH_GRANDCHILD], stdout=subprocess.PIPE, text=True)
                seen["child"], seen["grandchild"] = child.pid, int(child.stdout.readline())
                seen["sid"], seen["child_sid"] = os.getsid(0), os.getsid(child.pid)
                seen["pgid"] = os.getpgid(child.pid)
                self.fail("fallo a mitad del spawn")

        result = unittest.TextTestRunner(stream=open(os.devnull, "w")).run(unittest.defaultTestLoader.loadTestsFromTestCase(Failing))
        self.assertEqual((len(result.failures), len(result.errors)), (1, 0))
        self.assertTrue(gone(seen["child"]), "el hijo sobrevivió a su prueba")
        self.assertTrue(gone(seen["grandchild"]), "el nieto del grupo sobrevivió a su prueba")
        self.assertEqual(seen["child_sid"], seen["sid"])  # el hijo sigue en la sesión de la corrida: el vigilante lo alcanza
        self.assertEqual(seen["pgid"], seen["child"])  # y en un grupo propio
        self.assertNotEqual(seen["pgid"], os.getpgid(0))

    def test_run_with_a_timeout_kills_the_group_not_only_the_direct_child(self) -> None:
        code = "import subprocess, sys, time\ng = subprocess.Popen([sys.executable, '-c', 'import time\\nwhile True:\\n    time.sleep(60)'])\nprint(g.pid, flush=True)\ntime.sleep(60)"
        child_pid: list[int] = []
        real = proc_support.spawn

        def spy(argv, **kw):
            child = real(argv, **kw)
            child_pid.append(child.pid)
            return child

        proc_support.spawn = spy
        try:
            with self.assertRaises(subprocess.TimeoutExpired):
                proc_support.run([sys.executable, "-c", code], timeout=1.5, capture_output=True, text=True)
        finally:
            proc_support.spawn = real
        self.assertTrue(gone(child_pid[0]))
        self.assertEqual(proc_support.children_left(), [])  # ni el nieto

    def test_spawn_refuses_to_leave_the_session(self) -> None:
        for kw in ({"start_new_session": True}, {"process_group": 0}):
            with self.assertRaises(TypeError):
                proc_support.spawn([sys.executable, "-c", "pass"], **kw)

    def test_a_context_manager_kills_the_group_on_exit_and_a_normal_child_leaves_no_zombie(self) -> None:
        with proc_support.owned([sys.executable, "-c", WITH_GRANDCHILD], stdout=subprocess.PIPE, text=True) as child:
            grandchild = int(child.stdout.readline())
        self.assertTrue(gone(child.pid) and gone(grandchild))
        done = proc_support.run([sys.executable, "-c", "print(7)"], timeout=20, capture_output=True, text=True)
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "7"))
        self.assertEqual(proc_support.children_left(), [])

    def test_children_left_lists_the_live_descendants(self) -> None:
        self.assertEqual(proc_support.children_left(), [])
        child = proc_support.spawn_for(self, [sys.executable, "-c", SLEEPER])
        self.assertIn(child.pid, [pid for pid, _name in proc_support.children_left()])
        proc_support.terminate(child)
        self.assertEqual(proc_support.children_left(), [])

    def test_q03_inside_a_guarded_run_children_left_also_finds_a_grandchild_reparented_to_pid_1(self) -> None:
        """Q-03: el árbol de ``ppid`` pierde al nieto huérfano (PID 1); dentro de una corrida guardada la búsqueda por sesión lo encuentra."""
        import json
        import load_guard

        code = ("import json, os, subprocess, sys, time\n"
                "r, w = os.pipe()\n"
                "if os.fork() == 0:\n"
                "    if os.fork() == 0:\n"
                "        null = os.open(os.devnull, os.O_RDWR); os.dup2(null, 1); os.dup2(null, 2)\n"  # sin tubería heredada: no retiene al que lee
                "        os.write(w, str(os.getpid()).encode()); os.close(w)\n"
                "        time.sleep(300)\n"
                "    os._exit(0)\n"
                "orphan = int(os.read(r, 20))\n"
                "time.sleep(0.5)\n"
                f"sys.path.insert(0, {str(ROOT)!r})\n"
                "from tests import proc_support\n"
                "print(json.dumps([pid for pid, _ in proc_support.children_left()]), flush=True)\n"
                "print(orphan, flush=True)\n")
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "out"
            wrapper = f"import subprocess, sys; open({str(out)!r}, 'w').write(subprocess.run([sys.executable, '-c', {code!r}], capture_output=True, text=True).stdout)"
            outcome = load_guard.run_guarded([sys.executable, "-c", wrapper], threshold=1e9, load_file=os.devnull, interval=0.2, term_wait=2)
            self.assertEqual(outcome.rc, 0)
            seen, orphan = out.read_text().split("\n")[:2]
            self.assertIn(int(orphan), json.loads(seen))  # el huérfano reparentado a PID 1 se ve
            self.assertTrue(gone(int(orphan)))  # y run_guarded lo mató al acabar el paso (children_left)
        # fuera de una corrida guardada sólo se mira por ppid: sin falsos positivos por la shell del usuario
        with mock.patch.dict(os.environ, {"AN_KLA_GUARDED_RUN": ""}):
            self.assertEqual(proc_support.children_left(), [])

    def test_stop_process_handles_a_multiprocessing_child_and_one_that_never_started(self) -> None:
        import multiprocessing

        ctx = multiprocessing.get_context("spawn")
        never = ctx.Process(target=time.sleep, args=(1,))
        proc_support.stop_process(never)  # no arrancó: no revienta
        process = ctx.Process(target=time.sleep, args=(60,))
        process.start()
        proc_support.stop_process(process)
        self.assertFalse(process.is_alive())


class DrainLoopLimitsTests(unittest.TestCase):
    """Aceptación 2: el ``drain_loop`` de las pruebas de concurrencia no queda lanzando ``inbox drain`` sin fin."""

    def run_loop(self, module: str, deadline: str, *, remove_project_after: float | None = None, timeout: float = 90) -> int:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "proj"
            project.mkdir()
            logs = Path(temp) / "logs"
            logs.mkdir()
            child = proc_support.spawn_for(self, [sys.executable, "-m", module, "drain_loop", str(project), str(logs / "drain.jsonl"),
                                                  str(logs / "STOP"), deadline], cwd=ROOT, env=cli_env(),
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if remove_project_after is not None:
                time.sleep(remove_project_after)
                project.rmdir()
            return child.wait(timeout=timeout)

    def test_without_stop_it_ends_by_its_own_deadline(self) -> None:
        for module in ("tests.remember_conc_worker", "tests.inbox_conc_worker"):
            with self.subTest(module=module):
                self.assertEqual(self.run_loop(module, "2"), 3)

    def test_it_ends_too_if_the_project_disappears(self) -> None:
        for module in ("tests.remember_conc_worker", "tests.inbox_conc_worker"):
            with self.subTest(module=module):
                self.assertEqual(self.run_loop(module, "600", remove_project_after=2.0), 4)

    def test_stop_still_ends_it_with_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "STOP").write_text("x")
            child = proc_support.spawn_for(self, [sys.executable, "-m", "tests.remember_conc_worker", "drain_loop", temp, str(Path(temp) / "o"),
                                                  str(Path(temp) / "STOP"), "600"], cwd=ROOT, env=cli_env())
            self.assertEqual(child.wait(timeout=60), 0)


class RememberConcurrencyCleanupTests(unittest.TestCase):
    def test_a_failing_client_leaves_everything_clean(self) -> None:
        """Aceptación 2: ``test_remember_concurrency`` deja todo limpio aunque un cliente falle (fallo inyectado tras lanzar los procesos)."""
        from tests import test_remember_concurrency as module

        seen: dict[str, object] = {}

        class Injected(module.RememberConcurrencyTests):
            clients, per_client = 2, 3

            def after_spawn(self) -> None:
                seen["alive"] = [pid for pid, _name in proc_support.children_left()]
                seen["temp"] = [p for p in Path(tempfile.gettempdir()).glob("rconc-*")]
                raise RuntimeError("fallo inyectado")

        result = unittest.TextTestRunner(stream=open(os.devnull, "w")).run(unittest.defaultTestLoader.loadTestsFromName("test_eight_processes_200_remembers_a_looping_drain_and_a_final_drain", Injected))
        self.assertEqual((len(result.errors), len(result.failures)), (1, 0))
        self.assertIn("fallo inyectado", result.errors[0][1])
        self.assertTrue(seen["alive"])  # había clientes y vaciador vivos en el momento del fallo
        for pid in seen["alive"]:
            self.assertTrue(gone(pid), f"el proceso {pid} sobrevivió al fallo")
        self.assertEqual(proc_support.children_left(), [])
        self.assertEqual([p for p in seen["temp"] if p.exists()], [])  # el temporal, con sus registros dentro, se borró


class SpawnGuardTests(unittest.TestCase):
    def test_a_spawn_child_does_not_launch_the_run_again(self) -> None:
        """Aceptación 5: un guion con ``multiprocessing`` en ``spawn`` y su guarda de ``main``: el hijo no vuelve a lanzar la corrida (una marca)."""
        with tempfile.TemporaryDirectory() as temp:
            mark = Path(temp) / "marks"
            script = Path(temp) / "medidor.py"
            script.write_text(
                "import multiprocessing, sys\n"
                f"MARK = {str(mark)!r}\n"
                "def work(n):\n    return n\n"
                "def main():\n"
                "    open(MARK, 'a').write('x')\n"
                "    ctx = multiprocessing.get_context('spawn')\n"
                "    p = ctx.Process(target=work, args=(1,))\n    p.start(); p.join(30)\n"
                "    return 0\n"
                "if __name__ == '__main__':\n    sys.exit(main())\n")
            done = proc_support.run([sys.executable, str(script)], timeout=60, cwd=temp, capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(mark.read_text(), "x")  # una sola corrida

    def test_every_script_of_the_repo_that_runs_code_has_the_main_guard(self) -> None:
        """La medición `c74` tumbó la máquina por faltar esta guarda: ningún guion de ``scripts/`` llama a ``main()`` a pelo."""
        import ast

        for path in sorted((ROOT / "scripts").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            bare = [node for node in tree.body if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name) and node.value.func.id in ("main", "run", "measure")]
            with self.subTest(script=path.name):
                self.assertEqual(bare, [], "llamada a main() sin `if __name__ == \"__main__\"`")


if __name__ == "__main__":
    unittest.main()
