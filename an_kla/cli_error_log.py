"""Local, private log for unexpected CLI failures (issue #84).

The traceback of an unexpected failure never goes to stderr (it leaks
absolute paths of code and project, §11.1 of practicas-ingenieria.md).
It is appended to a per-user, 0600 log next to the update-check cache.
This module is best-effort: it must never raise while handling an error.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

LOG_FILENAME = "cli-errors.log"
DEBUG_ENV = "AN_KLA_DEBUG"
DISABLE_LOG_ENV = "AN_KLA_NO_CLI_ERROR_LOG"
MAX_LOG_BYTES = 5 * 1024 * 1024

_NO_PATH = "<unavailable>"


def error_log_path() -> Path:
    """Resolve the per-user log path honoring XDG when present."""

    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        base = Path(xdg) / "an-kla"
    elif os.name == "nt":
        local_app = os.environ.get("LOCALAPPDATA")
        base = (
            Path(local_app) / "an-kla"
            if local_app
            else Path.home() / ".cache" / "an-kla"
        )
    else:
        base = Path.home() / ".cache" / "an-kla"
    return base / LOG_FILENAME


def display_path(path: Path) -> str:
    """Render the log location without leaking absolute paths.

    Under home: ``~/...``.  Anywhere else (e.g. XDG_CACHE_HOME outside
    home): the relative tail only.  Never raises, even if home resolution
    fails inside the error handler.
    """

    try:
        home = Path.home()
        try:
            return "~/" + str(path.relative_to(home))
        except ValueError:
            parts = [part for part in path.parts[-2:] if part != "/"]
            return "/".join(parts) if parts else _NO_PATH
    except Exception:
        return _NO_PATH


def write_error_log(traceback_text: str, argv: list[str] | None = None) -> Path | None:
    """Append the failure record; return the path or None on any problem.

    Creates the file atomically with 0600 (no readable window), replaces
    unencodable argv characters instead of losing the record, and resets
    the log when it exceeds MAX_LOG_BYTES so a crash loop cannot grow it
    without bound.
    """

    if os.environ.get(DISABLE_LOG_ENV) == "1":
        return None
    try:
        path = error_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(path.parent, 0o700)
        except OSError:
            pass
        try:
            if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
                path.unlink()
        except OSError:
            pass
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"
        argv_line = " ".join(argv if argv is not None else sys.argv)
        record = f"[{stamp}] argv: {argv_line}\n{traceback_text}\n"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8", errors="replace") as handle:
            handle.write(record)
        return path
    except Exception:
        return None
