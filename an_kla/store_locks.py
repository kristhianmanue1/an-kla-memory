"""Lock de escritura del store (#117: partición; #111/P2: liveness).

Una sola disciplina para todas las plataformas: adquisición no
bloqueante con backoff y deadline (10s, constante congelada), fallando
con ``LockBusyError("write_lock_busy")``. El fallback sin ``fcntl`` ni
``msvcrt`` usa un directorio con ``mkdir`` atómico.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .store_errors import LockBusyError

WRITE_LOCK_DEADLINE_SECONDS = 10.0
_WRITE_LOCK_BACKOFF_SECONDS = 0.05


@dataclass
class LockResult:
    release_error: str | None = None


@contextmanager
def write_lock(root: Path) -> Iterator[LockResult]:
    result = LockResult()
    try:
        import fcntl  # type: ignore
    except ImportError:
        try:
            import msvcrt  # type: ignore
        except ImportError:
            lock_dir = root / ".write.lock-dir"
            try:
                lock_dir.mkdir()
            except FileExistsError as exc:
                raise LockBusyError("write_lock_busy") from exc
            try:
                yield result
            finally:
                try:
                    lock_dir.rmdir()
                except OSError:
                    result.release_error = "lock_release_incomplete"
            return
        lock_path = root / ".write.lock"
        with lock_path.open("a+b") as handle:
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            deadline = time.monotonic() + WRITE_LOCK_DEADLINE_SECONDS
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise LockBusyError("write_lock_busy") from exc
                    time.sleep(_WRITE_LOCK_BACKOFF_SECONDS)
            try:
                yield result
            finally:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    result.release_error = "lock_release_incomplete"
        return
    lock_path = root / ".write.lock"
    with lock_path.open("a+b") as handle:
        # Issue #111/P2: LOCK_NB + backoff con deadline (paridad con la
        # rama Windows). Antes: flock bloqueante sin deadline — un writer
        # colgado bloqueaba a todos los demás indefinidamente.
        deadline = time.monotonic() + WRITE_LOCK_DEADLINE_SECONDS
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise LockBusyError("write_lock_busy") from exc
                time.sleep(_WRITE_LOCK_BACKOFF_SECONDS)
        try:
            yield result
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                result.release_error = "lock_release_incomplete"


__all__ = ["WRITE_LOCK_DEADLINE_SECONDS", "LockResult", "write_lock"]
