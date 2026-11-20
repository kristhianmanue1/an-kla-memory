"""The call to a custodian adapter, ``memoria/custodio-adaptador/v1`` (ADR-0071 §3).

Whoever keeps memories does not read the custodian's files: it asks a program the Operator configures.  One
process per request: the request goes as UTF-8 JSON through standard input and the answer comes back through
standard output (at most 8 MiB, exit code 0); standard error is discarded.

The program comes **only** from an explicit table, ``custodians`` of the store's ``config.json`` (or, replacing it
whole, of the file ``AN_KLA_CUSTODIANS`` points to)::

    {"custodians": {"skopos": {"argv": ["/abs/python", "-B", "/abs/adapter.py", "--runs-root", "..."]}}}

``argv`` is a list and never goes through a shell; the custodian's name is a key of the table and nothing else,
never part of a path or of ``argv``.  A custodian that is not in the table is "no adapter"; a table that cannot be
read is not: the Operator configured something, so every custodian answers ``adapter_error`` with no process
started and the answer says why (``custodians_config_error``).  A failure of the adapter is *returned*, never raised.
"""

from __future__ import annotations

import json
import os
import selectors
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .anchors import CUSTODIAN_ID
from .anchors_document_v2 import Answer, build_request, validate_response

CONFIG_FILE = "config.json"
TABLE_KEY = "custodians"
RESOLVER_KEY = "conversation_resolver"
ENV_TABLE = "AN_KLA_CUSTODIANS"
MAX_STDOUT_BYTES = 8 * 1024 * 1024  # more is a failure
TIMEOUT_SECONDS = 10.0  # the contract's deadline; a test may pass a shorter one (erratum 1, A7)
ADAPTER_ENV = {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}
_MAX_TABLE_BYTES = 1024 * 1024

CONFIG_ERRORS = ("custodians_unreadable", "custodians_invalid_json", "custodians_invalid_shape")


class TableError(ValueError):
    """The table of custodians cannot be read; ``str(error)`` is one of :data:`CONFIG_ERRORS`."""


def parse_table(table: Any) -> dict[str, tuple[str, ...]]:
    """``{custodian: argv}`` from the value of ``custodians``; ``custodians_invalid_shape`` otherwise."""
    if not isinstance(table, dict):
        raise TableError("custodians_invalid_shape")
    parsed: dict[str, tuple[str, ...]] = {}
    for name, entry in table.items():
        argv = entry.get("argv") if isinstance(entry, dict) and set(entry) == {"argv"} else None
        if not CUSTODIAN_ID.fullmatch(name) or not isinstance(argv, list) or not argv:
            raise TableError("custodians_invalid_shape")
        if not all(isinstance(part, str) and part and "\0" not in part for part in argv) or not os.path.isabs(argv[0]):
            raise TableError("custodians_invalid_shape")
        parsed[name] = tuple(argv)
    return parsed


def _read_json(path: Path) -> Any:
    try:
        raw = path.read_bytes()
    except OSError:
        raise TableError("custodians_unreadable") from None
    if len(raw) > _MAX_TABLE_BYTES:
        raise TableError("custodians_unreadable")
    try:
        return json.loads(raw)
    except (ValueError, RecursionError):
        raise TableError("custodians_invalid_json") from None


def parse_resolver(entry: Any) -> tuple[str, tuple[str, ...]]:
    """``(custodian, argv)`` from the value of ``conversation_resolver`` (ADR-0073 §1): a custodian id, only to inform, and an ``argv`` as in the table."""
    if not isinstance(entry, dict) or set(entry) != {"custodian", "argv"} or not isinstance(entry["custodian"], str) or not CUSTODIAN_ID.fullmatch(entry["custodian"]):
        raise TableError("custodians_invalid_shape")
    return entry["custodian"], parse_table({entry["custodian"]: {"argv": entry["argv"]}})[entry["custodian"]]


def load_config(store_root: Any, env: Mapping[str, str] | None = None) -> tuple[dict[str, tuple[str, ...]], tuple[str, tuple[str, ...]] | None]:
    """The table of custodians and the conversation resolver (``None``: no resolver) of the Operator.  ``AN_KLA_CUSTODIANS``, if
    defined, replaces the store's file whole; raises :class:`TableError`.  One file, one error: a file that cannot be read says so for both."""
    env = os.environ if env is None else env
    if ENV_TABLE in env:
        if not env[ENV_TABLE]:
            raise TableError("custodians_unreadable")
        document = _read_json(Path(env[ENV_TABLE]))
        if not isinstance(document, dict) or not (TABLE_KEY in document or RESOLVER_KEY in document):
            raise TableError("custodians_invalid_shape")
    else:
        path = Path(store_root, CONFIG_FILE)
        if not path.exists():
            return {}, None  # no config: nothing configured, no adapter and no resolver
        document = _read_json(path)
        if not isinstance(document, dict):
            raise TableError("custodians_invalid_shape")
    table = parse_table(document[TABLE_KEY]) if TABLE_KEY in document else {}
    return table, parse_resolver(document[RESOLVER_KEY]) if RESOLVER_KEY in document else None


def load_table(store_root: Any, env: Mapping[str, str] | None = None) -> dict[str, tuple[str, ...]]:
    """The table of the Operator (see :func:`load_config`)."""
    return load_config(store_root, env)[0]


def _kill(proc: subprocess.Popen[bytes]) -> None:
    """Kill the process group (the child leads its own session); the group is signalled even if the leader is gone."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
        return
    except OSError:
        pass
    if proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass


def _feed(stdin: Any, payload: bytes) -> None:
    try:
        stdin.write(payload)
    except (OSError, ValueError):
        pass
    finally:
        try:
            stdin.close()
        except (OSError, ValueError):
            pass


def run_process(argv: list[str], payload: bytes, timeout: float, limit: int = MAX_STDOUT_BYTES) -> tuple[str | None, bytes]:
    """One process: ``(failure, stdout)``.  ``failure`` is ``None`` when it ended with 0 inside the deadline and the cap."""
    deadline = time.monotonic() + timeout
    try:
        proc = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=dict(ADAPTER_ENV), cwd="/", shell=False, start_new_session=True,
        )
    except (OSError, ValueError):
        return "launch_failed", b""
    feeder = threading.Thread(target=_feed, args=(proc.stdin, payload), daemon=True)
    feeder.start()
    chunks: list[bytes] = []
    total, failure = 0, None
    fd = proc.stdout.fileno()  # type: ignore[union-attr]
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(fd, selectors.EVENT_READ)
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    failure = "timeout"
                    break
                if not selector.select(min(left, 0.5)):
                    continue
                chunk = os.read(fd, 1 << 16)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    failure = "stdout_too_large"
                    break
                chunks.append(chunk)
        if failure is None:
            try:
                proc.wait(timeout=max(deadline - time.monotonic(), 0.05))
            except subprocess.TimeoutExpired:
                failure = "timeout"
        if failure is None and proc.returncode != 0:
            failure = "exit_nonzero"
    except (OSError, ValueError):
        failure = "launch_failed"
    finally:
        _kill(proc)  # always: a grandchild of the group may hold the pipe open
        try:
            proc.stdout.close()  # type: ignore[union-attr]
        except (OSError, ValueError):
            pass
        try:
            proc.wait(timeout=2)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            pass
        feeder.join(timeout=0.5)
    return failure, b"".join(chunks) if failure is None else b""


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate key")
    return dict(pairs)


def _no_constant(name: str) -> Any:
    raise ValueError("not JSON: " + name)


@dataclass
class Adapters:
    """The custodians of one operation: the table (or why it cannot be read) and the deadline."""

    table: dict[str, tuple[str, ...]] = field(default_factory=dict)
    config_error: str | None = None
    timeout: float = TIMEOUT_SECONDS
    resolver: tuple[str, tuple[str, ...]] | None = None  # ADR-0073 §1: (custodian, argv) of the single conversation resolver

    @classmethod
    def for_store(cls, store: Any, env: Mapping[str, str] | None = None, timeout: float = TIMEOUT_SECONDS) -> "Adapters":
        try:
            table, resolver = load_config(store.store_root, env)
            return cls(table, None, timeout, resolver)
        except TableError as error:
            return cls({}, str(error), timeout)

    def resolver_state(self) -> str | None:
        """``None`` if a resolver is configured; ``"unreadable"`` if the file could not be read; ``"absent"`` otherwise (no resolver)."""
        if self.config_error is not None:
            return "unreadable"
        return None if self.resolver is not None else "absent"

    def call_resolver(self, request: dict[str, Any], validate: Any) -> Answer | None:
        """Ask the resolver: ``None`` for "no resolver", else an :class:`Answer` (``called`` false when the file cannot be read); never raises.
        ``validate`` checks the answer's form and coherence (:mod:`an_kla.conversation_resolver`): any violation is a failure."""
        if self.config_error is not None:
            return Answer(failure=self.config_error, called=False)
        if self.resolver is None:
            return None
        payload = json.dumps(request, ensure_ascii=False).encode("utf-8")
        failure, out = run_process(list(self.resolver[1]), payload, self.timeout)
        if failure:
            return Answer(failure=failure)
        try:
            response = json.loads(out.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
        except (UnicodeDecodeError, ValueError, RecursionError, MemoryError):
            return Answer(failure="bad_json")
        if not isinstance(response, dict):
            return Answer(failure="bad_json")
        if validate(response) is not None:
            return Answer(failure="invalid_response")
        return Answer(response=response)

    def call(self, source: Mapping[str, Any]) -> Answer | None:
        """Ask the adapter of ``source``'s custodian: ``None`` for "no adapter", else an :class:`Answer`; never raises."""
        name = (source.get("derivation") or {}).get("custodian")
        if not isinstance(name, str) or not CUSTODIAN_ID.fullmatch(name):
            return None
        if self.config_error is not None:
            return Answer(failure=self.config_error, called=False)
        argv = self.table.get(name)
        if argv is None:
            return None
        payload = json.dumps(build_request(source), ensure_ascii=False).encode("utf-8")
        failure, out = run_process(list(argv), payload, self.timeout)
        if failure:
            return Answer(failure=failure)
        try:
            response = json.loads(out.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
        except (UnicodeDecodeError, ValueError, RecursionError, MemoryError):
            return Answer(failure="bad_json")
        if not isinstance(response, dict):
            return Answer(failure="bad_json")
        if validate_response(source, response) is not None:
            return Answer(failure="invalid_response")
        return Answer(response=response)
