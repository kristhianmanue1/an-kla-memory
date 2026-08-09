"""Process-shared reader/compaction gate for safe archival."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import stat
import threading
import time
from typing import Any, BinaryIO, Iterator


class ReaderGateError(RuntimeError):
    pass


_LOCAL = threading.local()


def _states() -> dict[tuple[str, int, int], dict[str, Any]]:
    value = getattr(_LOCAL, "states", None)
    if value is None:
        value = {}
        _LOCAL.states = value
    return value


def _key(root: Path) -> tuple[str, int, int]:
    return (str(root.resolve()), os.getpid(), threading.get_ident())


def reader_gate_mode(store: Any) -> str | None:
    state = _states().get(_key(store.root))
    return str(state["mode"]) if state is not None else None


def _open_gate(path: Path) -> BinaryIO:
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise ReaderGateError("reader_gate_platform_unsafe")
    descriptor = os.open(path, flags | nofollow, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ReaderGateError("reader_gate_unsafe_file")
        os.fchmod(descriptor, 0o600)
        return os.fdopen(descriptor, "r+b")
    except Exception:
        os.close(descriptor)
        raise


@contextmanager
def shared_reader_gate(store: Any) -> Iterator[None]:
    """Hold a reentrant shared lease around all archival-sensitive reads."""

    key = _key(store.root)
    states = _states()
    existing = states.get(key)
    if existing is not None:
        if existing["mode"] != "shared":
            raise ReaderGateError("reader_gate_mode_reentry")
        existing["depth"] += 1
        try:
            yield
        finally:
            existing["depth"] -= 1
        return
    try:
        import fcntl  # type: ignore
    except ImportError:
        # Reads remain supported on platforms where compact is disabled.
        yield
        return
    path = store.root / ".reader-gate"
    with _open_gate(path) as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
        states[key] = {"mode": "shared", "depth": 1}
        try:
            yield
        finally:
            states.pop(key, None)
            # Closing the descriptor releases flock.  Avoid a separate
            # LOCK_UN call so reader teardown cannot interfere with the
            # transaction lock's own release/audit semantics.


@contextmanager
def exclusive_reader_gate(store: Any, *, timeout: float = 10.0) -> Iterator[None]:
    """Wait for all local-process readers, then exclude new ones."""

    key = _key(store.root)
    if key in _states():
        raise ReaderGateError("reader_gate_mode_reentry")
    try:
        import fcntl  # type: ignore
    except ImportError as exc:
        raise ReaderGateError("compaction_platform_unsupported") from exc
    path = store.root / ".reader-gate"
    with _open_gate(path) as handle:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise ReaderGateError("compaction_readers_active") from exc
                time.sleep(0.01)
        _states()[key] = {"mode": "exclusive", "depth": 1}
        try:
            yield
        finally:
            _states().pop(key, None)
            # The surrounding file context releases the exclusive lease.


__all__ = [
    "ReaderGateError", "exclusive_reader_gate", "reader_gate_mode",
    "shared_reader_gate",
]
