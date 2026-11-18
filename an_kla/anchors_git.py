"""Reading Git for ``repo-file`` anchors (C3; ADR-0066 §2 and §4).

Real Git through subprocesses, read-only.  Every call runs with a scrubbed
environment: no ``GIT_*`` inherited, no system or global config, and
``core.excludesFile`` pointed at an empty file, so "ignored" is decided by the
repository's own rules (``.gitignore`` files and ``.git/info/exclude``) and never
by the machine of whoever runs it (erratum 3.2).  Blobs are read in one batch
process; their declared size is asked first and a blob over the limit is never read.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_READ_BYTES = 4 * 1024 * 1024
BINARY_PROBE_BYTES = 8000
_SYMLINK_MODE = "120000"
_TIMEOUT = 60


class GitUnavailable(Exception):
    """Git could not answer (not ``not_found``): ``repo_unavailable``."""

    def __init__(self, reason: str = "repo_unavailable") -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class TreeEntry:
    """Result of looking a path up in a tree.

    ``kind`` is ``blob``, ``missing``, ``symlink`` (the path itself),
    ``symlink_component`` (a directory on the way) or ``other`` (a directory or a
    submodule where a file was expected).
    """

    kind: str
    sha: str | None = None


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_OPTIONAL_LOCKS="0",
        GIT_TERMINAL_PROMPT="0",
        LC_ALL="C",
        XDG_CONFIG_HOME=os.devnull,
    )
    return env


_BASE = ["git", "-c", f"core.excludesFile={os.devnull}", "-c", "core.quotePath=false"]


class GitRepo:
    """A repository read with the minimum Git needs; close it when done."""

    def __init__(self, root: Path) -> None:
        self._start = Path(root)
        self._env = _env()
        self._batch: subprocess.Popen[bytes] | None = None
        self._check: subprocess.Popen[bytes] | None = None
        self.root: Path | None = None
        self.no_git = False
        try:
            proc = self._run(["rev-parse", "--show-toplevel"], cwd=self._start)
        except FileNotFoundError:
            self.no_git = True
            return
        except (OSError, subprocess.SubprocessError):
            self.no_git = False
            raise GitUnavailable() from None
        if proc.returncode == 0:
            self.root = Path(proc.stdout.decode("utf-8", "surrogateescape").strip())
        else:
            self.no_git = True

    def __enter__(self) -> "GitRepo":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        for proc in (self._batch, self._check):
            if proc is not None:
                try:
                    proc.stdin.close()  # type: ignore[union-attr]
                    proc.wait(timeout=_TIMEOUT)
                except (OSError, subprocess.SubprocessError):
                    proc.kill()
        self._batch = self._check = None

    def _run(self, args: list[str], cwd: Path | None = None, stdin: bytes | None = None):
        return subprocess.run(
            [*_BASE, *args], cwd=cwd or self.root, env=self._env, input=stdin,
            capture_output=True, timeout=_TIMEOUT, check=False,
        )

    def _ok(self, args: list[str], expected: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess:
        try:
            proc = self._run(args)
        except (OSError, subprocess.SubprocessError):
            raise GitUnavailable() from None
        if proc.returncode not in expected:
            raise GitUnavailable()
        return proc

    # -- refs and commits -------------------------------------------------
    def commit_exists(self, sha: str) -> bool:
        return self._run(["cat-file", "-e", f"{sha}^{{commit}}"]).returncode == 0

    def ref_tip(self, *refs: str) -> str | None:
        for ref in refs:
            proc = self._run(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"])
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.decode().strip()
        return None

    def head(self) -> str | None:
        return self.ref_tip("HEAD")

    def is_ancestor(self, commit: str, tip: str) -> bool:
        proc = self._ok(["merge-base", "--is-ancestor", commit, tip], expected=(0, 1))
        return proc.returncode == 0

    # -- trees ------------------------------------------------------------
    def lookup(self, rev: str, path: str) -> TreeEntry:
        parts = path.split("/")
        prefixes = ["/".join(parts[: i + 1]) for i in range(len(parts))]
        proc = self._ok(["ls-tree", "-t", "-z", rev, "--", *prefixes])
        found: dict[str, tuple[str, str, str]] = {}
        for record in proc.stdout.split(b"\0"):
            if not record:
                continue
            meta, _, name = record.partition(b"\t")
            mode, kind, sha = meta.decode().split(" ")
            found[name.decode("utf-8", "surrogateescape")] = (mode, kind, sha)
        for position, prefix in enumerate(prefixes):
            entry = found.get(prefix)
            last = position == len(prefixes) - 1
            if entry is None:
                return TreeEntry("missing")
            mode, kind, sha = entry
            if mode == _SYMLINK_MODE:
                return TreeEntry("symlink" if last else "symlink_component")
            if last:
                return TreeEntry("blob", sha) if kind == "blob" else TreeEntry("other")
            if kind != "tree":
                return TreeEntry("missing")
        return TreeEntry("missing")

    # -- blobs, in batch --------------------------------------------------
    def _process(self, which: str) -> subprocess.Popen[bytes]:
        attr = "_batch" if which == "--batch" else "_check"
        proc = getattr(self, attr)
        if proc is None:
            try:
                proc = subprocess.Popen(
                    [*_BASE, "cat-file", which], cwd=self.root, env=self._env,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                )
            except OSError:
                raise GitUnavailable() from None
            setattr(self, attr, proc)
        return proc

    def blob_size(self, sha: str) -> int:
        proc = self._process("--batch-check")
        try:
            proc.stdin.write(sha.encode() + b"\n")  # type: ignore[union-attr]
            proc.stdin.flush()  # type: ignore[union-attr]
            header = proc.stdout.readline().split()  # type: ignore[union-attr]
        except OSError:
            raise GitUnavailable() from None
        if len(header) != 3 or header[1] != b"blob":
            raise GitUnavailable()
        return int(header[2])

    def blob_bytes(self, sha: str) -> bytes:
        proc = self._process("--batch")
        try:
            proc.stdin.write(sha.encode() + b"\n")  # type: ignore[union-attr]
            proc.stdin.flush()  # type: ignore[union-attr]
            header = proc.stdout.readline().split()  # type: ignore[union-attr]
            if len(header) != 3 or header[1] != b"blob":
                raise GitUnavailable()
            size = int(header[2])
            data = proc.stdout.read(size + 1)  # type: ignore[union-attr]
        except OSError:
            raise GitUnavailable() from None
        if len(data) != size + 1:
            raise GitUnavailable()
        return data[:size]

    # -- working tree -----------------------------------------------------
    def tracked(self, path: str) -> bool:
        proc = self._ok(["ls-files", "-z", "--cached", "--", f":(literal){path}"])
        return bool(proc.stdout.strip(b"\0"))

    def ignored(self, path: str) -> bool:
        proc = self._ok(["check-ignore", "-q", "--", path], expected=(0, 1))
        return proc.returncode == 0

    def worktree_lookup(self, path: str) -> tuple[str, Path | None]:
        """``blob`` (a regular file), ``missing``, ``symlink`` or ``symlink_component``."""
        assert self.root is not None
        current = self.root
        parts = path.split("/")
        for position, part in enumerate(parts):
            current = current / part
            try:
                info = current.lstat()
            except FileNotFoundError:
                return "missing", None
            except NotADirectoryError:
                return "missing", None
            except OSError:
                raise GitUnavailable() from None
            if current.is_symlink():
                return ("symlink" if position == len(parts) - 1 else "symlink_component"), None
            last = position == len(parts) - 1
            if last:
                import stat

                return ("blob", current) if stat.S_ISREG(info.st_mode) else ("other", None)
        return "missing", None


def classify_bytes(data: bytes) -> tuple[str | None, str | None]:
    """The read rules of C3 after the size: ``(text, None)`` or ``(None, reason)``."""
    if b"\0" in data[:BINARY_PROBE_BYTES]:
        return None, "binary"
    try:
        return data.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, "not_utf8"


def read_blob_text(repo: GitRepo, sha: str) -> tuple[str | None, str | None]:
    """Text of a blob, or ``(None, reason)`` for ``too_large``, ``binary``, ``not_utf8``."""
    if repo.blob_size(sha) > MAX_READ_BYTES:
        return None, "too_large"
    return classify_bytes(repo.blob_bytes(sha))


def read_worktree_text(path: Path) -> tuple[str | None, str | None]:
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            if os.fstat(fd).st_size > MAX_READ_BYTES:
                return None, "too_large"
            with os.fdopen(fd, "rb", closefd=False) as handle:
                data = handle.read(MAX_READ_BYTES + 1)
        finally:
            os.close(fd)
    except OSError:
        raise GitUnavailable() from None
    if len(data) > MAX_READ_BYTES:
        return None, "too_large"
    return classify_bytes(data)
