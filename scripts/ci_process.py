"""Bounded local CI subprocesses. POSIX process groups; fail closed elsewhere."""
from __future__ import annotations

import json
import ctypes
import os
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path

from scripts.ci_fixture_registry import cleanup_scripts

class _DarwinInfo(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int) for name in ("signo", "error", "code", "pid", "uid", "status")] + [
        ("remainder", ctypes.c_byte * 232)]

_DARWIN_WAITID = None


def child_exit_without_reaping(pid):
    """Pin the group leader PID until signals/cleanup finish; avoid recycled PGIDs."""
    if hasattr(os, "waitid"):
        info = os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        return None if info is None else (info.si_status if info.si_code == os.CLD_EXITED else -info.si_status)
    if sys.platform != "darwin":
        raise OSError("nonreaping_wait_unavailable")
    # Darwin SDK sys/signal.h siginfo_t starts with these six 32-bit fields.
    global _DARWIN_WAITID
    if _DARWIN_WAITID is None:
        _DARWIN_WAITID = ctypes.CDLL(None, use_errno=True).waitid
        _DARWIN_WAITID.argtypes = [ctypes.c_int, ctypes.c_uint, ctypes.c_void_p, ctypes.c_int]
        _DARWIN_WAITID.restype = ctypes.c_int
    info = _DarwinInfo()
    if _DARWIN_WAITID(1, pid, ctypes.byref(info), os.WEXITED | os.WNOHANG | os.WNOWAIT) != 0:
        raise OSError(ctypes.get_errno(), "waitid")
    return None if info.pid == 0 else (info.status if info.code == 1 else -info.status)


def live_group(group, deadline):
    if not _alive(group):
        return False
    if time.monotonic() >= deadline:
        return True  # Unknown must never become absence.
    try:
        result = subprocess.run(["ps", "-axo", "pgid=,pid=,stat="], capture_output=True, text=True,
                                timeout=max(.001, min(.25, deadline - time.monotonic())))
    except (OSError, subprocess.TimeoutExpired):
        return True
    if result.returncode != 0:
        return True
    for line in result.stdout.splitlines():
        pgid, pid, state = line.split()
        if int(pgid) == group and not state.startswith("Z"):
            return True
    return False


def _alive(group):
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Unverifiable is not evidence of absence.
        return True
    return True


def registered_cleanup(directory, deadline):
    """Only explicitly registered cooperative fixture processes, never a PID scan."""
    remaining = []
    for path in Path(directory).glob("*.json"):
        if time.monotonic() >= deadline:
            return remaining + ["registration_scan_incomplete"]
        entry = json.loads(path.read_text())
        pid, token = entry["pid"], entry["token"]
        if not isinstance(pid, int) or pid <= 1 or not isinstance(token, str) or len(token) < 20:
            raise ValueError("invalid_spawn_registration")
        if time.monotonic() >= deadline:
            return remaining + [pid]
        try:
            command = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="], capture_output=True,
                text=True, timeout=max(.01, min(.3, deadline - time.monotonic())),
            )
        except subprocess.TimeoutExpired:
            remaining.append(pid)
            continue
        if command.returncode == 1 and not command.stdout.strip():
            continue
        if command.returncode != 0 or token not in command.stdout:
            raise ValueError("spawn_identity_unverifiable")
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                break
            if sig == signal.SIGTERM:
                time.sleep(min(.02, max(0, deadline - time.monotonic())))
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(.01)
        else:
            remaining.append(pid)
    return remaining


def run_task(command, *, cwd, env, directory, deadline, timeout, log_limit=16 * 1024 * 1024):
    """deadline/timeout include cleanup. Results never imply an escaped hostile tree is contained."""
    if os.name != "posix":
        return {"status": "unsupported_containment", "rc": None, "duration_s": 0}
    started = time.monotonic()
    end = min(deadline, started + timeout)
    reserve = min(5., max(0., (end - started) / 3))
    execution_end = end - reserve
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    registry = directory / "registered"
    registry.mkdir(mode=0o700, exist_ok=True)
    env = dict(env, AN_KLA_CI_SPAWN_REGISTRY=str(registry))
    if execution_end <= started:
        return {"status": "not_started", "rc": None, "duration_s": 0}
    status, process, cleanup = "running", None, "not_started"
    post_exit_until = None
    exit_code = None
    signals_sent = []
    selector = selectors.DefaultSelector()
    counts = {"stdout": 0, "stderr": 0}
    with (directory / "stdout.txt").open("wb") as out, (directory / "stderr.txt").open("wb") as err:
        try:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       start_new_session=True)
            for pipe, stream, name in ((process.stdout, out, "stdout"), (process.stderr, err, "stderr")):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, (stream, name))
            def read_pipe(key):
                try:
                    chunk = os.read(key.fileobj.fileno(), 65536)
                except BlockingIOError:
                    return "blocked"
                if not chunk:
                    selector.unregister(key.fileobj)
                    return "eof"
                stream, name = key.data
                room = max(0, log_limit - counts[name])
                stream.write(chunk[:room])
                stream.flush()
                counts[name] += len(chunk)
                return "data"
            while True:
                events = selector.select(timeout=max(0, min(.03, execution_end - time.monotonic())))
                for key, _ in events:
                    read_pipe(key)
                if max(counts.values()) > log_limit:
                    status = "log_limit"
                    break
                if exit_code is None:
                    exit_code = child_exit_without_reaping(process.pid)
                code = exit_code
                if code is not None:
                    if post_exit_until is None:
                        # multiprocessing's tracker may release inherited stderr just
                        # after the parent exits. This grace never extends the task.
                        post_exit_until = min(execution_end, time.monotonic() + 1.)
                    # Exit can occur just after select times out. Read EOF directly;
                    # an absent readiness notification is not proof of a live writer.
                    for key in list(selector.get_map().values()):
                        while time.monotonic() < min(execution_end, post_exit_until):
                            state = read_pipe(key)
                            if state != "data" or max(counts.values()) > log_limit:
                                break
                    if max(counts.values()) > log_limit:
                        status = "log_limit"
                    elif not selector.get_map() and not live_group(process.pid, min(execution_end, post_exit_until)):
                        status = "ok" if code == 0 else "failed"
                    elif time.monotonic() >= execution_end:
                        status = "timeout"
                    elif time.monotonic() < post_exit_until:
                        continue
                    else:
                        status = "residual_pipes" if selector.get_map() else "residual_descendants"
                    break
                if time.monotonic() >= execution_end:
                    status = "timeout"
                    break
        except OSError as exc:
            status = "spawn_error: " + str(exc)
        except KeyboardInterrupt:
            status = "cancelled"
        finally:
            selector.close()
            (registry / "closed").touch()
            if process is not None:
                group = process.pid
                residual = live_group(group, end)
                if residual:
                    if status == "ok":
                        status = "residual_descendants"
                    try:
                        os.killpg(group, signal.SIGTERM)
                        signals_sent.append("TERM")
                    except (ProcessLookupError, PermissionError):
                        pass
                    term_end = min(end - .5, time.monotonic() + min(3., reserve / 2))
                    while time.monotonic() < term_end:
                        if not live_group(group, end):
                            break
                        time.sleep(.01)
                    if live_group(group, end):
                        try:
                            os.killpg(group, signal.SIGKILL)
                            signals_sent.append("KILL")
                        except (ProcessLookupError, PermissionError):
                            pass
                try:
                    live_fixtures = []
                    fixture_pending = cleanup_scripts(registry, end, observed_live=live_fixtures)
                    if status == "ok" and live_fixtures:
                        status = "residual_fixture_descendants"
                    escaped = registered_cleanup(registry, end)
                    while live_group(group, end) and time.monotonic() < end:
                        time.sleep(.01)
                    group_closed = not live_group(group, end)
                    process.wait(timeout=max(.001, end - time.monotonic()))
                    cleanup = "complete" if group_closed and not escaped and not fixture_pending else "incomplete"
                except (subprocess.TimeoutExpired, OSError, ValueError):
                    cleanup = "incomplete"
                if cleanup != "complete":
                    status = "teardown_incomplete"
                for pipe in (process.stdout, process.stderr):
                    pipe.close()
            out.flush()
            err.flush()
    return {"status": status, "rc": None if process is None else process.returncode,
            "pid": None if process is None else process.pid,
            "cleanup": cleanup, "duration_s": time.monotonic() - started,
            "deadline_monotonic": end, "command": list(command),
            "cleanup_scope": "owned_group_registered_fixture_intents_and_registered_escapees",
            "group_signals_sent": signals_sent,
            "bytes_observed": counts, "logs_truncated": max(counts.values()) > log_limit}
