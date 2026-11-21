"""measure_suite.py — mide los arranques de proceso de la suite (ADR-0074 §6).

    measure_suite.py --out DIR tests.test_x tests.test_y      # módulos concretos
    measure_suite.py --out DIR --full                          # la suite completa: sólo la lanza el capitán, avisando al orquestador

Siempre corre bajo ``load_guard.run_guarded`` (sesión propia, vigilante de carga, rc 75 si aborta) y lleva la guarda de ``main``: un hijo de
``multiprocessing`` en ``spawn`` reimporta el guion y, sin la guarda, volvería a lanzar la medición entera (así cayó la medición ``c74``).

El hijo (``--child``) parchea ``subprocess.Popen.__init__`` y apunta cada arranque por prueba, **clasificado por ``argv[0]``** (no por ``-m``: un
``git commit -m base`` no es un módulo de Python): ``git``, ``python -m an_kla``, ``python -m <otro>``, ``python -c``/script, y el resto por nombre. De
cada ``git`` apunta la función de la pila que lo pide (``archivo:función``). Escribe ``medicion.json`` y ``medicion.md``: pruebas y tiempo, arranques por
tipo, por módulo, los ``git`` por quien los pide, las 25 pruebas más lentas y la carga (inicio, fin, pico; una muestra cada 60 s).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import traceback
import unittest
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_FRAMES = ("subprocess.py", "proc_support.py", "load_guard.py", "measure_suite.py", os.sep + "unittest" + os.sep, "contextlib.py", "threading.py")


def kind_of(args) -> str:
    """Por ``argv[0]``: ``git``, ``python -m an_kla``, ``python -m otro``, ``python -c/script`` u otro ejecutable."""
    argv = [str(a) for a in (args if isinstance(args, (list, tuple)) else [args])]
    if not argv:
        return "?"
    base = os.path.basename(argv[0])
    if base.startswith(("python", "Python")):
        for i, a in enumerate(argv[1:], 1):
            if a == "-m" and i + 1 < len(argv):
                module = argv[i + 1].split(".")[0]
                return "python -m an_kla" if module == "an_kla" else f"python -m {module}"
            if a == "-c":
                return "python -c"
        return "python script"
    return base


def caller_of(skip: int = 2) -> str:
    """La función de la pila que pide el arranque: la primera de ``an_kla/`` o ``tests/`` (``archivo:función``)."""
    for frame in reversed(traceback.extract_stack()[:-skip]):
        name = frame.filename
        if any(part in name for part in SKIP_FRAMES):
            continue
        for marker in ("an_kla", "tests"):
            if os.sep + marker + os.sep in name:
                return f"{marker}/{os.path.basename(name)}:{frame.name}"
    return "?"


class Measurer:
    def __init__(self) -> None:
        self.current: str | None = None
        self.spawns: list[tuple[str | None, str, str]] = []  # (prueba, tipo, quien lo pide si es git)
        self.durations: dict[str, float] = {}
        self.load: list[tuple[float, float, float, float]] = []
        self._orig = subprocess.Popen.__init__

    def patch(self) -> None:
        measurer = self

        def patched(popen, args, *a, **kw):
            kind = kind_of(args)
            measurer.spawns.append((measurer.current, kind, caller_of() if kind == "git" else ""))
            return measurer._orig(popen, args, *a, **kw)

        subprocess.Popen.__init__ = patched

    def sample(self) -> None:
        self.load.append((time.time(), *os.getloadavg()))


def module_of(test_id: str | None) -> str:
    if not test_id:
        return "(fuera de prueba)"
    return ".".join(test_id.split(".")[:2]) if test_id.startswith("tests.") else test_id.split(".")[0]


def child(out: Path, modules: list[str], full: bool) -> int:
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    measurer = Measurer()
    measurer.patch()
    stop = threading.Event()
    measurer.sample()

    def sampler() -> None:
        while not stop.wait(60):
            measurer.sample()

    threading.Thread(target=sampler, daemon=True).start()

    class Result(unittest.TextTestResult):
        def startTest(self, test) -> None:
            measurer.current = test.id()
            self._t0 = time.perf_counter()
            super().startTest(test)

        def stopTest(self, test) -> None:
            measurer.durations[test.id()] = time.perf_counter() - self._t0
            measurer.current = None
            super().stopTest(test)

    loader = unittest.defaultTestLoader
    suite = loader.discover("tests", pattern="test_*.py") if full else loader.loadTestsFromNames(modules)
    out.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with open(out / "medicion.unittest.log", "w") as log:
        result = unittest.TextTestRunner(resultclass=Result, stream=log, verbosity=0).run(suite)
    total = time.perf_counter() - started
    stop.set()
    measurer.sample()
    write_report(out, measurer, result, total, modules, full)
    return 0 if result.wasSuccessful() else 1


def write_report(out: Path, m: Measurer, result, total: float, modules: list[str], full: bool) -> None:
    kinds = Counter(kind for _t, kind, _c in m.spawns)
    git_callers = Counter(caller for _t, kind, caller in m.spawns if kind == "git")
    by_module: dict[str, dict] = defaultdict(lambda: {"tests": 0, "seconds": 0.0, "an_kla": 0, "git": 0, "other": 0})
    for tid, seconds in m.durations.items():
        row = by_module[module_of(tid)]
        row["tests"] += 1
        row["seconds"] += seconds
    for test_id, kind, _caller in m.spawns:
        row = by_module[module_of(test_id)]
        row["an_kla" if kind == "python -m an_kla" else "git" if kind == "git" else "other"] += 1
    slow = sorted(m.durations.items(), key=lambda kv: -kv[1])[:25]
    load = m.load
    data = {
        "scope": "full" if full else modules, "python": sys.version.split()[0], "tests_run": result.testsRun, "ok": result.wasSuccessful(),
        "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped), "total_seconds": total,
        "spawns_total": len(m.spawns), "spawns_by_kind": dict(kinds), "git_by_caller": dict(git_callers.most_common()),
        "modules": dict(by_module), "slowest": [{"test": k, "seconds": v} for k, v in slow],
        "load": {"start": load[0][1:], "end": load[-1][1:], "peak_l1": max(x[1] for x in load), "peak_l5": max(x[2] for x in load), "samples": len(load)},
    }
    (out / "medicion.json").write_text(json.dumps(data, indent=1, ensure_ascii=False))
    lines = [f"# Medición — {'suite completa' if full else ', '.join(modules)}", "",
             f"- Python {data['python']}; {'OK' if data['ok'] else 'FALLA'} (fallos {data['failures']}, errores {data['errors']}, saltadas {data['skipped']})",
             f"- Pruebas: {data['tests_run']}; tiempo: {total:.1f} s",
             f"- Arranques totales: {len(m.spawns)}; por tipo (`argv[0]`): " + ", ".join(f"{k} {v}" for k, v in kinds.most_common()),
             f"- Carga 1/5/15 min al empezar {', '.join(f'{x:.2f}' for x in data['load']['start'])}; al acabar {', '.join(f'{x:.2f}' for x in data['load']['end'])}; "
             f"pico {data['load']['peak_l1']:.2f} / {data['load']['peak_l5']:.2f}", "",
             "## Por módulo", "", "| módulo | pruebas | s | `-m an_kla` | git | otros |", "|---|---:|---:|---:|---:|---:|"]
    for name, row in sorted(by_module.items(), key=lambda kv: (-(kv[1]["an_kla"] + kv[1]["git"] + kv[1]["other"]), kv[0])):
        lines.append(f"| {name} | {row['tests']} | {row['seconds']:.1f} | {row['an_kla']} | {row['git']} | {row['other']} |")
    lines += ["", "## `git` por quien lo pide", "", "| arranques | función |", "|---:|---|"]
    lines += [f"| {n} | {caller} |" for caller, n in git_callers.most_common(25)]
    lines += ["", "## Las 25 pruebas más lentas", "", "| s | prueba |", "|---:|---|"] + [f"| {v:.2f} | {k} |" for k, v in slow]
    (out / "medicion.md").write_text("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mide los arranques de proceso de la suite (ADR-0074 §6).")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--full", action="store_true", help="la suite completa (sólo la primera corrida del capitán, avisando al orquestador)")
    parser.add_argument("--child", action="store_true", help="interno: el hijo que mide, ya bajo el vigilante")
    parser.add_argument("modules", nargs="*", help="módulos de prueba (tests.test_x)")
    args = parser.parse_args(argv)
    if not args.full and not args.modules:
        parser.error("hay que dar módulos o --full: no se mide la suite completa por descuido")
    if args.child:
        return child(args.out, args.modules, args.full)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import load_guard

    command = [sys.executable, str(Path(__file__).resolve()), "--child", "--out", str(args.out), *(["--full"] if args.full else []), *args.modules]
    outcome = load_guard.run_guarded(command, cwd=str(ROOT))
    if outcome.aborted:
        print(f"measure_suite: abortada por carga: {outcome.reason}", file=sys.stderr)
        return load_guard.EXIT_ABORTED
    if outcome.left:
        print(f"measure_suite: children_left: {outcome.left}", file=sys.stderr)
    return outcome.rc


if __name__ == "__main__":
    sys.exit(main())
