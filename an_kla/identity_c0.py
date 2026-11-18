"""Writer identity C0 ``memoria/identidad/v1`` and the record envelope (ADR-0063 D2).

C0 names the repo, the agent and the session in every agentic-memory record so
that what an-kla stores and what other tools capture can be joined without
ambiguity.  The contract is frozen at ``8fccbcc`` of the coordination repo; this
module is an independent implementation of it, checked against its vectors
(``tests/fixtures/identidad-v1``), not a dependency on its reference validator.

Pure helpers plus a thin ``git`` subprocess wrapper with fixed arguments.  The
environment and the clock are injectable.  Nothing calls this yet: it has no
CLI command and no MCP tool (D2 "alcance aceptado").  The identity is an
assertion by the emitter, stored as given: it supports audit and filtering, not
proof of authorship.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Callable, Mapping

from .canonical import digest_json
from .temporal import format_utc


IDENTITY_SCHEMA = "memoria/identidad/v1"
ENVELOPE_SCHEMA = "an-kla/record-envelope-v1"
TIME_SOURCE = "host-clock/v1"

ROLES = frozenset({"operador", "orquestador", "capitan", "ejecutor", "revisor", "desconocido"})
NAME_SENTINEL = "sin-nombre"
UNKNOWN_SENTINEL = "desconocido"
NO_SESSION_SENTINEL = "sin-sesion"
RESERVED_NAMES = frozenset({UNKNOWN_SENTINEL, NO_SESSION_SENTINEL})

ENV_NAME = "AN_KLA_AGENT_NAME"
ENV_CLI = "AN_KLA_AGENT_CLI"
ENV_MODEL = "AN_KLA_AGENT_MODEL"
ENV_ROLE = "AN_KLA_AGENT_ROLE"
ENV_SESSION = "AN_KLA_SESSION_ID"
BRANCH_FIELD = "repo.branch"
# Stands in for ``repo.id`` while the env-derived fields are validated before any git call.
_PENDING_REPO_ID = "local:" + "0" * 16

# ``--path-format=absolute`` (case 3 of ``repo.id``) needs Git 2.31.
GIT_MIN_VERSION = (2, 31)
GIT_TIMEOUT_SECONDS = 10
# Variables that would make ``git -C <checkout>`` look at another repository.
_GIT_REDIRECTING_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")
_GIT_SUFFIX = "." + "git"

_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?")
_SEGMENT = re.compile(r"[a-z0-9._~-]+")
_HASHED_ID = re.compile(r"(?:local|remoto):[0-9a-f]{16}")
_IDENT = re.compile(r"[a-z][a-z0-9_-]{0,31}")
SLOT_PATTERN = _IDENT  # ADR-0065 §1: el identificador de casilla es el identificador C0
DEFAULT_SLOT = "main"
# Whitespace spelled out, never ``\s``/``\S``: engines disagree on it (U+FEFF is
# ECMA-262 whitespace but not Python's).  C0's reference validator uses Python's
# ``\s`` on ``str``, so this class is exactly that set, enumerated, and the schema
# spells out the same one: validator, schema (any engine) and reference agree.
# ``tests/test_identity_c0.py`` checks it against ``\s`` over the whole Unicode range.
WHITESPACE_CLASS = (
    r"\t-\r\x1c-\x20\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000"
)
_SESSION = re.compile(rf"([a-z][a-z0-9_-]{{0,31}}):([^{WHITESPACE_CLASS}]{{1,200}})")
_BRANCH = re.compile(rf"[^{WHITESPACE_CLASS}~^:?*\[\\]{{1,200}}")
_NO_OUTER_SPACE = re.compile(rf"[^{WHITESPACE_CLASS}](?:.*[^{WHITESPACE_CLASS}])?", re.DOTALL)
_KIND = re.compile(r"[a-z][a-z0-9_-]{0,31}")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_ENQUEUED_AT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z")
_URL_WITH_HOST = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://(?:[^@/]+@)?([^/]+)/(.+)")
_SCP_SHAPE = re.compile(r"(?:[^@/]+@)?[^:/]+:.*")
_SCP_WITH_PATH = re.compile(r"(?:[^@/]+@)?([^:/]+):(.+)")

# Env var each validator reason points at, so a rejected value names its source.
_REASON_FIELDS = {
    "agent_name": ENV_NAME,
    "agent_name_reservado": ENV_NAME,
    "agent_cli": ENV_CLI,
    "agent_model": ENV_MODEL,
    "agent_role": ENV_ROLE,
    "session_id": ENV_SESSION,
    "session_no_calificada_por_cli": ENV_SESSION,
    "repo_branch": BRANCH_FIELD,
}


class IdentityC0Error(ValueError):
    """Stable identity construction failure.

    ``code`` is the contract (``identity_env_missing``, ``identity_env_invalid``,
    ``identity_repo_unavailable``); ``field`` names the culprit (an env var,
    ``repo.branch``, or ``git``) and never carries the offending value.  ``str(error)``
    equals ``code``.
    """

    def __init__(self, code: str, field: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.field = field


# --- repo.id ---------------------------------------------------------------


def is_canonical_repo_id(value: Any) -> bool:
    """True for an already normalized ``host[:port]/path``."""

    if not isinstance(value, str) or "/" not in value:
        return False
    authority, path = value.split("/", 1)
    host, has_port, port = authority.partition(":")
    if not all(_LABEL.fullmatch(label) for label in host.split(".")):
        return False
    if has_port and not (
        1 <= len(port) <= 5 and port.isascii() and port.isdigit()
        and port == str(int(port)) and 1 <= int(port) <= 65535
    ):
        return False
    segments = path.split("/")
    if any(not _SEGMENT.fullmatch(s) or s in (".", "..") for s in segments):
        return False
    return not path.endswith(_GIT_SUFFIX)


def _require_str(value: Any, what: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{what} must be str, got {type(value).__name__}")
    return value


def normalize_remote(url: str) -> str | None:
    """Origin URL to canonical ``host[:port]/path``, or ``None`` (case 2).

    ``url`` must be ``str``: anything else raises ``TypeError`` (a missing remote is
    handled by the caller, not by passing ``None``).
    """

    text = _require_str(url, "url").strip()
    if text.lower().startswith("file://"):
        return None  # Git ignores the host of file://: it identifies nothing
    match = _URL_WITH_HOST.fullmatch(text)
    if match is None and "://" in text:
        return None  # scheme without host, or malformed
    if match is None:
        match = _SCP_WITH_PATH.fullmatch(text)
        if match is None:
            return None
    host, path = match.groups()
    candidate = f"{host}/{path.strip('/')}".lower()
    if candidate.endswith(_GIT_SUFFIX):
        candidate = candidate[: -len(_GIT_SUFFIX)]
    return candidate if is_canonical_repo_id(candidate) else None


def _hash16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def repo_id_from_remote(url: str, base: str | os.PathLike[str] | None = None) -> str:
    """Case 1 when the URL normalizes, else ``remoto:`` + 16 hex (case 2).

    A scheme-less non-scp URL is a local path: its resolved absolute path,
    taken relative to ``base`` (the checkout root), is hashed so two repos with
    the same relative remote do not share an identity.  Anything else that does
    not normalize is hashed as the stripped URL.  ``url`` must be ``str``
    (``TypeError`` otherwise).
    """

    canonical = normalize_remote(url)
    if canonical is not None:
        return canonical
    text = url.strip()
    if "://" not in text and not _SCP_SHAPE.fullmatch(text):
        text = str((Path(base if base is not None else ".") / text).resolve())
    return "remoto:" + _hash16(text)


def repo_id_from_common_dir(common_dir: str) -> str:
    """Case 3: ``local:`` + 16 hex of the resolved absolute common git dir (``str``, else ``TypeError``)."""

    _require_str(common_dir, "common_dir")
    return "local:" + _hash16(common_dir)


def _git(checkout: str | os.PathLike[str], *args: str) -> str | None:
    """Run ``git -C <checkout> <args>``; stdout without its final newline, or ``None``."""

    env = {k: v for k, v in os.environ.items() if k not in _GIT_REDIRECTING_ENV}
    try:
        done = subprocess.run(
            ["git", "-C", os.fspath(checkout), *args],
            capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS, env=env,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None
    return done.stdout.rstrip("\n") if done.returncode == 0 else None


def git_version() -> tuple[int, ...] | None:
    """Installed Git version as a tuple, or ``None`` when absent or unparsable."""

    try:
        done = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None
    match = re.match(r"git version (\d+)\.(\d+)", done.stdout)
    return (int(match.group(1)), int(match.group(2))) if done.returncode == 0 and match else None


def git_is_usable() -> bool:
    """True when ``git`` exists and is at least ``GIT_MIN_VERSION``."""

    return git_problem() is None


def git_problem() -> str | None:
    """Why ``git`` cannot be used: ``git`` when absent, ``git>=<min>`` when too old, else ``None``."""

    version = git_version()
    if version is None:
        return "git"
    return None if version >= GIT_MIN_VERSION else "git>=" + ".".join(map(str, GIT_MIN_VERSION))


def repo_id_for(checkout: str | os.PathLike[str]) -> str:
    """Canonical ``repo.id`` of a checkout or worktree (cases 1, 2 and 3)."""

    url = _git(checkout, "remote", "get-url", "origin")
    if url:
        root = _git(checkout, "rev-parse", "--show-toplevel") or os.fspath(checkout)
        return repo_id_from_remote(url, root)
    common = _git(checkout, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not common:
        raise IdentityC0Error("identity_repo_unavailable")
    return repo_id_from_common_dir(str(Path(common).resolve()))


def is_valid_branch(branch: Any) -> bool:
    if not isinstance(branch, str) or not _BRANCH.fullmatch(branch):
        return False
    if branch == "HEAD" or branch.startswith(("-", "/", ".", "refs/")) or branch.endswith(("/", ".", ".lock")):
        return False
    return not any(token in branch for token in ("..", "//", "@{", "/."))


def branch_for(checkout: str | os.PathLike[str]) -> str | None:
    """Short branch name of the checkout; ``None`` when HEAD is detached.

    Read from the full ref, not ``--short``: the short form may disambiguate to
    ``heads/<name>`` when a tag shares the name.
    """

    ref = _git(checkout, "symbolic-ref", "--quiet", "HEAD")
    prefix = "refs/heads/"
    return ref[len(prefix):] if ref and ref.startswith(prefix) else None


# --- validation ------------------------------------------------------------


def validate(obj: Any) -> list[str]:
    """Rejection reasons for an identity object; empty when it is valid."""

    if not isinstance(obj, dict):
        return ["raiz_no_es_objeto"]
    reasons: list[str] = []
    if set(obj) != {"schema", "repo", "agent", "session"}:
        reasons.append("claves_raiz")
    if obj.get("schema") != IDENTITY_SCHEMA:
        reasons.append("schema")
    reasons += _validate_repo(obj.get("repo"))
    agent_reasons, cli = _validate_agent(obj.get("agent"))
    reasons += agent_reasons
    reasons += _validate_session(obj.get("session"), cli)
    return reasons


def _validate_repo(repo: Any) -> list[str]:
    if not isinstance(repo, dict) or "id" not in repo or not set(repo) <= {"id", "branch"}:
        return ["repo_forma"]
    reasons = []
    repo_id = repo["id"]
    if not (isinstance(repo_id, str) and (_HASHED_ID.fullmatch(repo_id) or is_canonical_repo_id(repo_id))):
        reasons.append("repo_id")
    if "branch" in repo and not is_valid_branch(repo["branch"]):
        reasons.append("repo_branch")
    return reasons


def _validate_agent(agent: Any) -> tuple[list[str], str | None]:
    """Reasons for ``agent`` plus its ``cli`` when well formed (for the session check)."""

    if not isinstance(agent, dict) or set(agent) != {"name", "cli", "model", "role"}:
        return ["agent_forma"], None
    reasons = []
    name, cli, model, role = agent["name"], agent["cli"], agent["model"], agent["role"]
    if not (isinstance(name, str) and _IDENT.fullmatch(name)):
        reasons.append("agent_name")
    elif name in RESERVED_NAMES:
        reasons.append("agent_name_reservado")
    valid_cli = isinstance(cli, str) and _IDENT.fullmatch(cli) is not None
    if not valid_cli:
        reasons.append("agent_cli")
    if not (isinstance(model, str) and 1 <= len(model) <= 80 and _NO_OUTER_SPACE.fullmatch(model)):
        reasons.append("agent_model")
    if not (isinstance(role, str) and role in ROLES):
        reasons.append("agent_role")
    return reasons, cli if valid_cli else None


def _validate_session(session: Any, cli: str | None) -> list[str]:
    if not isinstance(session, dict) or set(session) != {"id"}:
        return ["session_forma"]
    session_id = session["id"]
    match = _SESSION.fullmatch(session_id) if isinstance(session_id, str) else None
    if match is None:
        return ["session_id"]
    return ["session_no_calificada_por_cli"] if cli is not None and match.group(1) != cli else []


# --- identity from the environment -----------------------------------------


def build_identity(
    checkout: str | os.PathLike[str],
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Writer identity for ``checkout`` from the launcher's variables (D2).

    ``AN_KLA_AGENT_CLI`` is mandatory.  Absent name, model, role and session
    take the C0 sentinels; a variable that is present and violates C0 fails with
    its name and is never corrected or replaced by a sentinel.  ``env`` defaults
    to ``os.environ``.  A missing or too old ``git`` fails first with
    ``identity_repo_unavailable`` and ``field`` ``git`` or ``git>=<min>``.
    """

    problem = git_problem()
    if problem is not None:
        raise IdentityC0Error("identity_repo_unavailable", problem)
    source = os.environ if env is None else env
    cli = source.get(ENV_CLI)
    if cli is None:
        raise IdentityC0Error("identity_env_missing", ENV_CLI)
    session_part = source.get(ENV_SESSION)
    identity: dict[str, Any] = {
        "schema": IDENTITY_SCHEMA,
        "repo": {"id": _PENDING_REPO_ID},
        "agent": {
            "name": source.get(ENV_NAME, NAME_SENTINEL),
            "cli": cli,
            "model": source.get(ENV_MODEL, UNKNOWN_SENTINEL),
            "role": source.get(ENV_ROLE, UNKNOWN_SENTINEL),
        },
        "session": {"id": f"{cli}:{NO_SESSION_SENTINEL if session_part is None else session_part}"},
    }
    # Only env-derived fields can fail here (the repo id is a valid placeholder and the
    # branch is not set yet), so any reason is the env's fault; an unmapped one still fails.
    reasons = validate(identity)
    if reasons:
        raise IdentityC0Error("identity_env_invalid", _REASON_FIELDS.get(reasons[0], reasons[0]))
    identity["repo"] = {"id": repo_id_for(checkout)}
    branch = branch_for(checkout)
    if branch is not None:
        identity["repo"]["branch"] = branch
        if not is_valid_branch(branch):
            raise IdentityC0Error("identity_env_invalid", BRANCH_FIELD)
    return identity


# --- record envelope -------------------------------------------------------


def derive_idempotency_key(
    identity: Mapping[str, Any],
    kind: str,
    text: str,
    supersedes: str | None = None,
    slot: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> str:
    """Default key: sha256 of the canonical JSON of the writer, kind, text and target (D1 "Idempotencia").

    ``slot`` (ADR-0065 §3) joins the digest only for ``kind: state``: the same text in two slots is two
    intentions. Without it the key is byte-identical to the one before ADR-0065.  ``extra`` (ADR-0066: the
    anchors' sources and quote hashes, a dispute's ``verdict``) joins only when given, so the same holds.
    """

    material = {
        "repo": identity["repo"]["id"],
        "agent": identity["agent"]["name"],
        "session": identity["session"]["id"],
        "kind": kind,
        "text": text,
        "supersedes": supersedes,
    }
    if slot is not None:
        material["slot"] = slot
    if extra:
        material.update(extra)
    return digest_json(material)


def build_envelope(
    identity: Mapping[str, Any],
    kind: str,
    idempotency_key: str,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """``an-kla/record-envelope-v1`` for a record being accepted now.

    ``enqueued_at`` is the host clock in UTC with microseconds, declared
    ``host-clock/v1``: an observation, not a seal.  ``clock`` returns an aware
    datetime and defaults to the system clock.
    """

    if validate(identity):
        raise ValueError("invalid_writer_identity")
    if not isinstance(kind, str) or not _KIND.fullmatch(kind):
        raise ValueError("invalid_envelope_kind")
    if not isinstance(idempotency_key, str) or not _DIGEST.fullmatch(idempotency_key):
        raise ValueError("invalid_idempotency_key")
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    return {
        "schema": ENVELOPE_SCHEMA,
        "writer": copy.deepcopy(identity),
        "enqueued_at": format_utc(now),
        "time_source": TIME_SOURCE,
        "idempotency_key": idempotency_key,
        "kind": kind,
    }


def validate_envelope(obj: Any) -> list[str]:
    """Rejection reasons for an envelope; empty when it is valid."""

    if not isinstance(obj, dict):
        return ["raiz_no_es_objeto"]
    reasons = []
    if set(obj) != {"schema", "writer", "enqueued_at", "time_source", "idempotency_key", "kind"}:
        reasons.append("claves_raiz")
    if obj.get("schema") != ENVELOPE_SCHEMA:
        reasons.append("schema")
    reasons += [f"writer:{r}" for r in validate(obj.get("writer"))]
    stamp = obj.get("enqueued_at")
    if not (isinstance(stamp, str) and _ENQUEUED_AT.fullmatch(stamp) and _is_real_time(stamp)):
        reasons.append("enqueued_at")
    if obj.get("time_source") != TIME_SOURCE:
        reasons.append("time_source")
    key = obj.get("idempotency_key")
    if not (isinstance(key, str) and _DIGEST.fullmatch(key)):
        reasons.append("idempotency_key")
    kind = obj.get("kind")
    if not (isinstance(kind, str) and _KIND.fullmatch(kind)):
        reasons.append("kind")
    return reasons


def _is_real_time(stamp: str) -> bool:
    """The shape alone admits month 13 or second 61; ask the calendar."""

    try:
        datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        return False
    return True
