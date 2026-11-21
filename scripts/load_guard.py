"""load_guard.py — el freno por carga de una corrida de pruebas (ADR-0074 §1 y §2).

Dos cosas en un archivo:

* **El vigilante** (``python scripts/load_guard.py --sid S --pid P --parent Q --reason R``): un proceso aparte que mira la carga a 1 minuto
  cada ``--interval`` segundos y, si supera ``--threshold`` en ``--samples`` muestras seguidas, mata a todos los procesos de la corrida
  (``kill_run``) y deja un archivo de motivo escrito de forma atómica. Muere si muere su padre (``--parent``).
* **``run_guarded``**: lanza una orden en su propia sesión, arranca un vigilante para esa sesión, y cuando la orden acaba mata y recoge al
  vigilante. Devuelve ``Outcome``: ``rc`` de la orden, ``aborted`` (por carga) y ``left`` (procesos que quedaron vivos y se mataron).

El que llama (``ci_local`` o ``run_guarded.py``) queda **fuera** de la sesión de la corrida: matarla no lo mata a él.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

DEFAULT_THRESHOLD = 30.0
EXIT_ABORTED = 75
SAMPLES = 6
INTERVAL = 5.0
TERM_WAIT = 10.0
GUARDED_ENV = "AN_KLA_GUARDED_RUN"  # lo pone run_guarded en el entorno del paso: dentro de una corrida guardada, el líder de la sesión es el paso


def threshold_from_env(default: float = DEFAULT_THRESHOLD) -> float:
    try:
        return float(os.environ.get("AN_KLA_CI_LOAD_ABORT", default))
    except ValueError:
        return default


def process_table() -> dict[int, tuple[int, int]]:
    """``pid -> (ppid, pgid)`` de los procesos vivos que ``ps`` ve (sin zombis)."""
    proc = subprocess.Popen(["ps", "-Ao", "pid=,ppid=,pgid=,stat="], stdout=subprocess.PIPE, text=True)
    out = proc.communicate()[0]
    table: dict[int, tuple[int, int]] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 4 and all(p.lstrip("-").isdigit() for p in parts[:3]) and not parts[3].startswith("Z"):  # un zombi ya no es de nadie
            table[int(parts[0])] = (int(parts[1]), int(parts[2]))
    table.pop(proc.pid, None)  # el propio `ps` es hijo de quien pregunta: no es de la corrida
    return table


def _sid(pid: int) -> int | None:
    try:
        return os.getsid(pid)
    except (ProcessLookupError, PermissionError, OSError):
        return None


def command_name(pid: int) -> str:
    """Sólo el nombre del ejecutable (sin argumentos: pueden llevar datos)."""
    out = subprocess.run(["ps", "-o", "comm=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return os.path.basename(out) or "?"


def find_run(sid: int | None, root_pid: int | None, *, pgids: set[int] = frozenset(), sids: set[int] = frozenset(),
             exclude: set[int] = frozenset(), table: dict[int, tuple[int, int]] | None = None) -> dict[int, tuple[int, int]]:
    """Los procesos de la corrida, ``pid -> (pgid, sid)``: los de su sesión, los descendientes de ``root_pid`` por el árbol de ``ppid`` y
    los que tengan un ``pgid`` o ``sid`` de los guardados (los reparentados a PID 1). Sin nunca los de ``exclude`` (el vigilante y el que llama)."""
    table = process_table() if table is None else table
    children: dict[int, list[int]] = {}
    for pid, (ppid, _pgid) in table.items():
        children.setdefault(ppid, []).append(pid)
    wanted: set[int] = set()
    if root_pid is not None and root_pid in table:
        stack = [root_pid]
        while stack:
            pid = stack.pop()
            if pid not in wanted:
                wanted.add(pid)
                stack.extend(children.get(pid, ()))
    found: dict[int, tuple[int, int]] = {}
    for pid, (_ppid, pgid) in table.items():
        if pid in exclude:
            continue
        psid = _sid(pid)
        if pid in wanted or (sid is not None and psid == sid) or pgid in pgids or (psid is not None and psid in sids):
            found[pid] = (pgid, psid if psid is not None else -1)
    return found


def _signal(pid: int, sig: int) -> None:
    try:
        os.kill(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass  # terminó solo entre la foto y la señal: ya no está, que es lo que se buscaba


def _killpg(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def kill_run(sid: int | None, root_pid: int | None, *, exclude: set[int] = frozenset(), term_wait: float = TERM_WAIT,
             sleep: Callable[[float], None] = time.sleep) -> list[tuple[int, str]]:
    """La muerte ordenada de ADR-0074 §1: foto, ``SIGSTOP``, ``killpg`` por cada ``pgid``, ``SIGCONT``, espera, nueva búsqueda (sesión, árbol y
    todo ``sid``/``pgid`` guardado) y ``SIGKILL``. Devuelve ``[(pid, nombre)]`` de lo que se mató."""
    own = {os.getpid(), os.getpgrp()}
    excluded_pids = set(exclude) | {os.getpid()}
    snap = find_run(sid, root_pid, exclude=excluded_pids)
    if not snap:
        return []
    names = {pid: command_name(pid) for pid in snap}
    pgids = {pgid for pgid, _ in snap.values() if pgid > 1 and pgid not in own}
    sids = {s for _, s in snap.values() if s > 1}
    for pid in snap:
        _signal(pid, signal.SIGSTOP)  # un proceso parado ni termina ni crea hijos: nadie se reparenta mientras tanto
    for pgid in pgids:
        _killpg(pgid, signal.SIGTERM)
    for pid in snap:
        _signal(pid, signal.SIGTERM)
    for pid in snap:
        _signal(pid, signal.SIGCONT)
    deadline = time.monotonic() + term_wait
    while time.monotonic() < deadline and find_run(sid, root_pid, pgids=pgids, sids=sids, exclude=excluded_pids):
        sleep(0.2)
    killed: dict[int, str] = {pid: names[pid] for pid in snap}
    for _ in range(5):
        rest = find_run(sid, root_pid, pgids=pgids, sids=sids, exclude=excluded_pids)
        if not rest:
            break
        for pid in rest:
            killed.setdefault(pid, command_name(pid))
            _signal(pid, signal.SIGKILL)
        sleep(0.2)
    return sorted(killed.items())


def write_reason(path: Path, data: dict) -> None:
    """Atómico: un temporal en la misma carpeta, ``fsync`` y ``rename``; quien lea nunca ve uno a medias (R74-13)."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.rename(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_load_file(path: str) -> Callable[[], float]:
    def read() -> float:
        try:
            return float(Path(path).read_text().split()[0])
        except (OSError, ValueError, IndexError):
            return 0.0

    return read


def watch(sid: int, pid: int, *, threshold: float, reason: Path, parent: int | None, interval: float = INTERVAL, samples: int = SAMPLES,
          term_wait: float = TERM_WAIT, load: Callable[[], float] | None = None, sleep: Callable[[float], None] = time.sleep,
          exclude: set[int] = frozenset()) -> int:
    """El bucle del vigilante. 0 si la corrida acabó o murió el padre sin abortar; ``EXIT_ABORTED`` si abortó por carga."""
    load = load or (lambda: os.getloadavg()[0])
    window: list[float] = []
    over = 0
    while True:
        if parent is not None and not _alive(parent):
            return 0  # nunca sobrevive a quien lo lanzó
        if not find_run(sid, pid, exclude=set(exclude) | {os.getpid()}):
            return 0  # la corrida ya no existe
        value = load()
        window = (window + [value])[-samples:]
        over = over + 1 if value > threshold else 0
        if over >= samples:
            killed = kill_run(sid, pid, exclude=set(exclude), term_wait=term_wait, sleep=sleep)
            write_reason(reason, {"reason": "abortada por carga", "threshold": threshold, "samples": window,
                                  "killed": [{"pid": p, "command": n} for p, n in killed], "at": time.time()})
            return EXIT_ABORTED
        sleep(interval)


@dataclass
class Outcome:
    rc: int
    aborted: bool = False
    reason: dict = field(default_factory=dict)
    left: list[tuple[int, str]] = field(default_factory=list)
    guard_pid: int = 0


def run_guarded(argv: list[str], *, threshold: float | None = None, cwd: str | None = None, env: dict | None = None,
                interval: float = INTERVAL, samples: int = SAMPLES, term_wait: float = TERM_WAIT, load_file: str | None = None,
                guard_env: dict | None = None) -> Outcome:
    """Corre ``argv`` en su propia sesión con un vigilante. Quien llama queda fuera de la sesión (no muere con ella)."""
    threshold = threshold_from_env() if threshold is None else threshold
    with tempfile.TemporaryDirectory(prefix="load-guard-") as tmp:
        reason_path = Path(tmp) / "reason.json"
        step = subprocess.Popen(argv, cwd=cwd, env={**(os.environ if env is None else env), GUARDED_ENV: "1"}, start_new_session=True)
        guard_cmd = [sys.executable, str(Path(__file__).resolve()), "--sid", str(step.pid), "--pid", str(step.pid), "--parent", str(os.getpid()),
                     "--reason", str(reason_path), "--threshold", str(threshold), "--interval", str(interval), "--samples", str(samples),
                     "--term-wait", str(term_wait)]
        if load_file:
            guard_cmd += ["--load-file", load_file]
        guard = subprocess.Popen(guard_cmd, env={**os.environ, **(guard_env or {})})
        try:
            rc = step.wait()
            if not reason_path.exists():  # una escritura atómica puede estar a punto de ocurrir: damos al vigilante un instante
                try:
                    guard.wait(timeout=0.5 if guard.poll() is None else 0)
                except subprocess.TimeoutExpired:
                    pass
        except BaseException:
            kill_run(step.pid, step.pid, exclude={os.getpid(), guard.pid}, term_wait=2)
            raise
        finally:
            if guard.poll() is None:
                guard.kill()
            guard.wait()
        reason = json.loads(reason_path.read_text()) if reason_path.exists() else {}
        left = kill_run(step.pid, step.pid, exclude={os.getpid()}, term_wait=2)  # ``children_left``: nada de la corrida sobrevive a su paso
    if reason:
        return Outcome(EXIT_ABORTED, True, reason, left, guard.pid)
    return Outcome(rc, False, {}, left, guard.pid)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Vigilante de carga de una corrida (ADR-0074).")
    parser.add_argument("--sid", type=int, required=True)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--parent", type=int, default=None)
    parser.add_argument("--reason", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--interval", type=float, default=INTERVAL)
    parser.add_argument("--samples", type=int, default=SAMPLES)
    parser.add_argument("--term-wait", type=float, default=TERM_WAIT)
    parser.add_argument("--load-file", default=None, help="fuente de carga inyectable, sólo para pruebas: un archivo con un número")
    args = parser.parse_args(argv)
    return watch(args.sid, args.pid, threshold=args.threshold, reason=args.reason, parent=args.parent, interval=args.interval,
                 exclude={args.parent} if args.parent else set(), samples=args.samples, term_wait=args.term_wait, load=read_load_file(args.load_file) if args.load_file else None)


if __name__ == "__main__":
    sys.exit(main())
