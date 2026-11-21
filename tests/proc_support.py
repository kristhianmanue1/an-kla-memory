"""proc_support.py — procesos con dueño para las pruebas (ADR-0074 §1).

Todo proceso que una prueba lanza vive en **un grupo propio dentro de la sesión de la corrida** (``process_group=0`` en 3.11+, ``os.setpgrp`` antes
del ``exec`` en 3.9; **nunca** ``start_new_session``: el hijo seguiría fuera de la sesión y el vigilante no lo alcanzaría) y muere con su prueba:
``killpg(SIGTERM)``, espera de 5 s, ``killpg(SIGKILL)`` y recogida (nunca un zombi). ``run`` con plazo mata el **grupo**: ``subprocess.run``
sólo mata al hijo directo. ``multiprocessing.Process`` sigue en la sesión por defecto y se mata con ``terminate``, ``join(5)`` y ``kill``.

Uso: ``child = spawn(argv, owner=self)``; el ``owner`` (un ``TestCase``) lo mata con ``addCleanup``. Sin ``owner`` queda en un registro que
``reap_all`` mata al acabar el módulo (``unittest.addModuleCleanup``) o el intérprete (``atexit``).
"""

from __future__ import annotations

import atexit
import contextlib
import os
import signal
import subprocess
import sys
import threading
import unittest
from typing import Any, Iterator, Sequence

TERM_WAIT = 5.0
_LIVE: list[subprocess.Popen] = []
_LOCK = threading.Lock()
_hooked = False


def _group_kwargs() -> dict[str, Any]:
    if sys.version_info >= (3, 11):
        return {"process_group": 0}
    return {"preexec_fn": os.setpgrp}  # 3.9: el mismo grupo nuevo, dentro de la misma sesión


def _killpg(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass  # ya no está: es lo que se buscaba


def terminate(child: subprocess.Popen, wait: float = TERM_WAIT) -> None:
    """Mata el **grupo** del hijo (``SIGTERM``, espera, ``SIGKILL``) y lo recoge. Idempotente."""
    pgid = child.pid  # el hijo es el líder de su grupo
    _killpg(pgid, signal.SIGTERM)
    try:
        child.wait(timeout=wait)
    except subprocess.TimeoutExpired:
        pass
    _killpg(pgid, signal.SIGKILL)  # a lo que quede del grupo (nietos incluidos), haya salido o no el líder
    try:
        child.wait(timeout=wait)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait()
    for stream in (child.stdin, child.stdout, child.stderr):
        if stream is not None:
            with contextlib.suppress(OSError, ValueError):
                stream.close()
    with _LOCK:
        if child in _LIVE:
            _LIVE.remove(child)


def reap_all() -> None:
    with _LOCK:
        live = list(_LIVE)
    for child in live:
        terminate(child)


def _hook() -> None:
    global _hooked
    if not _hooked:
        _hooked = True
        atexit.register(reap_all)


def spawn(argv: Sequence[str], *, owner: unittest.TestCase | None = None, **kw: Any) -> subprocess.Popen:
    """``Popen`` en un grupo nuevo de la misma sesión, registrado para morir con ``owner`` (o con el módulo)."""
    if "start_new_session" in kw or "process_group" in kw or "preexec_fn" in kw:
        raise TypeError("proc_support.spawn fija el grupo: nada de start_new_session ni process_group")
    child = subprocess.Popen(list(argv), **_group_kwargs(), **kw)
    with _LOCK:
        _LIVE.append(child)
    _hook()
    if owner is not None:
        owner.addCleanup(terminate, child)
    else:
        unittest.addModuleCleanup(terminate, child)
    return child


def spawn_for(owner: unittest.TestCase, argv: Sequence[str], **kw: Any) -> subprocess.Popen:
    """``spawn`` con dueño: ``proc_support.spawn_for(self, [...], stdin=...)`` (el hijo muere con la prueba)."""
    return spawn(argv, owner=owner, **kw)


def run(argv: Sequence[str], timeout: float, *, input: str | bytes | None = None, check: bool = False, **kw: Any) -> subprocess.CompletedProcess:
    """``subprocess.run`` con plazo que mata el **grupo** al vencer (``subprocess.TimeoutExpired`` como siempre)."""
    capture = kw.pop("capture_output", False)
    if capture:
        kw["stdout"] = kw["stderr"] = subprocess.PIPE
    if input is not None:
        kw["stdin"] = subprocess.PIPE
    child = spawn(argv, **kw)
    try:
        out, err = child.communicate(input=input, timeout=timeout)
    except BaseException:
        terminate(child)
        raise
    terminate(child)  # los nietos que hayan quedado
    completed = subprocess.CompletedProcess(list(argv), child.returncode, out, err)
    if check:
        completed.check_returncode()
    return completed


@contextlib.contextmanager
def owned(argv: Sequence[str], **kw: Any) -> Iterator[subprocess.Popen]:
    """El mismo ``spawn``, como gestor de contexto: el grupo muere al salir del ``with``, falle o no."""
    child = spawn(argv, **kw)
    try:
        yield child
    finally:
        terminate(child)


def stop_process(process: Any, wait: float = TERM_WAIT) -> None:
    """Para un ``multiprocessing.Process``: ``terminate``, ``join(5)`` y ``kill`` (va en un ``finally``)."""
    if process.pid is None:
        return  # nunca arrancó
    if process.is_alive():
        process.terminate()
    process.join(wait)
    if process.is_alive():
        process.kill()
        process.join(wait)


def children_left() -> list[tuple[int, str]]:
    """Los descendientes vivos de este proceso ``[(pid, nombre)]``: tras una prueba no debe quedar ninguno.

    Dentro de una corrida guardada (``run_guarded`` pone ``AN_KLA_GUARDED_RUN`` en el entorno del paso, que lo heredan sus descendientes) busca además por la **sesión**
    (sin contar a este proceso ni a sus ancestros):
    así encuentra también a un nieto reparentado a PID 1, que el árbol de ``ppid`` pierde. Fuera de una corrida guardada la sesión es la de la shell del
    usuario (su terminal, otros procesos suyos): buscar por ella daría falsos positivos, así que sólo mira los descendientes por ``ppid``. Límite
    declarado: sin corrida guardada, un huérfano reparentado a PID 1 no se ve."""
    import importlib

    scripts = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    guard = importlib.import_module("load_guard")
    tracker = getattr(getattr(__import__("multiprocessing.resource_tracker", fromlist=["x"]), "_resource_tracker", None), "_pid", None)
    guarded = os.environ.get(guard.GUARDED_ENV) == "1"
    table = guard.process_table()
    ancestors, pid = set(), os.getpid()
    while pid in table and pid not in ancestors:  # los ancestros (quien nos lanzó dentro de la corrida) no son «hijos que quedan»
        ancestors.add(pid)
        pid = table[pid][0]
    found = guard.find_run(os.getsid(0) if guarded else None, os.getpid(), exclude=ancestors | {os.getpid(), tracker}, table=table)  # el rastreador de recursos de `multiprocessing` vive lo que el intérprete
    return [(pid, guard.command_name(pid)) for pid in sorted(found)]
