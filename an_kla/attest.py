"""Attestation of locally-observed commands (ADR-0046, issue #102 Fase A).

The CLI acquires receipts signed by the motor (HMAC-SHA256 over the
canonical JSON of the receipt) for whitelisted, read-only-intent commands.
A valid receipt is the only way ``tool_observed`` authority crosses the
CLI surface (``__main__._cli_authority``); the engine re-verifies and
marks consumption under the write lock as defense-in-depth.

Trust boundary (honest threat model, ADR-0046 §1): the key lives on the
same host as the agent; this is *auditable provenance for honest agents*,
not a defense against a malicious one. A receipt proves execution and
observed output digests — never semantic correctness nor command purity.

Layout under ``.an-kla/``:
- ``attest.key``                     HMAC key (0o600, never exported)
- ``attest-whitelist.json``          whitelist (exact argv or prefix+deny-flags)
- ``receipts/receipts/sha256/*.json`` durable receipts (content-addressed)
- ``receipts/nonces/sha256/*.json``  consumption tombstones (O_EXCL only)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from .canonical import canonical_json, digest_json
from .write_policy import WritePolicyError, policy_fingerprint

KEY_RELATIVE = Path(".an-kla") / "attest.key"
WHITELIST_RELATIVE = Path(".an-kla") / "attest-whitelist.json"
RECEIPTS_RELATIVE = Path(".an-kla") / "receipts" / "receipts" / "sha256"
NONCES_RELATIVE = Path(".an-kla") / "receipts" / "nonces" / "sha256"

RECEIPT_SCHEMA = "an-kla/attest-receipt-v1"
WHITELIST_SCHEMA = "an-kla/attest-whitelist-v1"
TOMBSTONE_SCHEMA = "an-kla/attest-tombstone-v1"
RESULT_SCHEMA = "an-kla/attest-result-v1"
SIGNATURE_PREFIX = "hmac-sha256:"

DEFAULT_WHITELIST: dict[str, Any] = {
    "schema": WHITELIST_SCHEMA,
    "entries": [
        {"argv": ["git", "rev-parse", "HEAD"]},
        {
            "argv_prefix": ["git", "diff"],
            "deny_flags": ["--ext-diff", "--textconv", "--output", "-o"],
        },
        {
            "argv_prefix": ["python", "-m", "unittest", "discover"],
            "deny_flags": [],
        },
        {
            "argv_prefix": ["python3", "-m", "unittest", "discover"],
            "deny_flags": [],
        },
        {"argv_prefix": ["sha256sum"], "deny_flags": []},
    ],
}

DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_OUTPUT_CAP_BYTES = 64 * 1024 * 1024
_CHUNK = 1024 * 1024
_SENSITIVE_ENV = re.compile(
    r"TOKEN|SECRET|PASSWORD|PASSWD|PRIVATE|CREDENTIAL|COOKIE|SESSION|AUTH"
    r"|KEY|AWS_",
    re.IGNORECASE,
)
_HEX64 = re.compile(r"[0-9a-f]{64}")


class AttestError(WritePolicyError):
    """Stable attestation error; ``str(exc) == code`` (see WritePolicyError)."""


def key_path(project_root: Path | str) -> Path:
    return Path(project_root) / KEY_RELATIVE


def whitelist_path(project_root: Path | str) -> Path:
    return Path(project_root) / WHITELIST_RELATIVE


def receipt_path(project_root: Path | str, receipt_digest: str) -> Path:
    hexpart = receipt_digest.split(":", 1)[1]
    return Path(project_root) / RECEIPTS_RELATIVE / f"{hexpart}.json"


def tombstone_path(project_root: Path | str, nonce: str) -> Path:
    nonce_digest = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    return Path(project_root) / NONCES_RELATIVE / f"{nonce_digest}.json"


def _fsync_dir(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_exclusive(target: Path, payload: bytes, mode: int) -> None:
    """Create ``target`` O_EXCL or raise FileExistsError; fsync file+dir."""

    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        target,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
        mode,
    )
    try:
        view = memoryview(payload)
        # Issue #114/A1: os.write puede devolver una escritura parcial;
        # un bucle garantiza el payload completo (clave/receipt íntegros).
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_dir(target.parent)


def ensure_attest_files(
    project_root: Path | str,
    *,
    entries: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create the key and the whitelist if absent (idempotent, ADR-0046 §1)."""

    root = Path(project_root)
    created: list[str] = []
    existed: list[str] = []
    key = key_path(root)
    if key.exists():
        existed.append("attest.key")
    else:
        key_bytes = os.urandom(32)
        _write_exclusive(key, key_bytes, 0o600)
        created.append("attest.key")
    whitelist = whitelist_path(root)
    if whitelist.exists():
        existed.append("attest-whitelist.json")
    else:
        document = entries if entries is not None else DEFAULT_WHITELIST
        _write_exclusive(
            whitelist,
            canonical_json(document) + b"\n",
            0o600,
        )
        created.append("attest-whitelist.json")
    return {
        "schema": "an-kla/attest-init-result-v1",
        "created": created,
        "existed": existed,
        "ok": True,
    }


def _load_key(project_root: Path | str) -> bytes:
    path = key_path(project_root)
    try:
        key = path.read_bytes()
    except OSError:
        raise AttestError("attest_not_initialized") from None
    if not key:
        raise AttestError("attest_not_initialized")
    return key


def load_whitelist(project_root: Path | str) -> dict[str, Any]:
    try:
        document = json.loads(whitelist_path(project_root).read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise AttestError("attest_whitelist_invalid") from None
    if (
        not isinstance(document, dict)
        or document.get("schema") != WHITELIST_SCHEMA
        or not isinstance(document.get("entries"), list)
        or not document["entries"]
    ):
        raise AttestError("attest_whitelist_invalid")
    return document


def whitelist_digest(document: dict[str, Any]) -> str:
    return digest_json(document)


def command_allowed(document: dict[str, Any], command: list[str]) -> bool:
    """Exact-argv match, or prefix match with every deny flag enforced.

    Fail-closed: malformed entries never match (ADR-0046 §2 — matching
    exacto de argv; prefijos sólo con deny_flags explícitas).
    """

    for entry in document["entries"]:
        if not isinstance(entry, dict):
            continue
        exact = entry.get("argv")
        if isinstance(exact, list):
            if command == [str(item) for item in exact]:
                return True
            continue
        prefix = entry.get("argv_prefix")
        if not isinstance(prefix, list) or not prefix:
            continue
        prefix = [str(item) for item in prefix]
        if command[: len(prefix)] != prefix:
            continue
        denied = entry.get("deny_flags", [])
        if not isinstance(denied, list):
            continue
        denied = [str(item) for item in denied]
        tail = command[len(prefix):]
        if any(
            any(arg.startswith(flag) for flag in denied if flag)
            for arg in tail
        ):
            continue
        return True
    return False


def _sign(key: bytes, receipt: dict[str, Any]) -> str:
    mac = hmac.new(key, canonical_json(receipt), hashlib.sha256).hexdigest()
    return SIGNATURE_PREFIX + mac


def _sanitized_env() -> dict[str, str]:
    return {
        name: value
        for name, value in os.environ.items()
        if not _SENSITIVE_ENV.search(name)
    }


def attest_run(
    project_root: Path | str,
    command: list[str],
    *,
    expected_current: str | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    output_cap_bytes: int = DEFAULT_OUTPUT_CAP_BYTES,
    now: str | None = None,
    nonce: str | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Execute one whitelisted command and mint a signed receipt.

    Injectable ``now``/``nonce`` exist for deterministic goldens only
    (ADR-0046 §3); the CLI never passes them.
    """

    # Deferred imports keep ``store`` out of this module's import graph.
    from .identity import IdentityError, read_binding
    from .store import MemoryStore

    if not command or any(not isinstance(item, str) or not item for item in command):
        raise AttestError("attest_command_not_allowed")
    root = Path(project_root)
    key = _load_key(root)
    document = load_whitelist(root)
    if not command_allowed(document, command):
        raise AttestError("attest_command_not_allowed")

    store = MemoryStore(root)
    observed = store.read_current()
    if expected_current is not None and expected_current != observed:
        raise WritePolicyError("write_plan_base_changed")
    try:
        binding = read_binding(store)
    except IdentityError:
        raise AttestError("attest_not_initialized") from None

    sanitized = env if env is not None else _sanitized_env()
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=sanitized,
            cwd=str(root),
        )
    except OSError:
        raise AttestError("attest_command_not_allowed") from None

    import threading

    class _Drainer(threading.Thread):
        """Stream-hash one pipe; never blocks the timeout path (ADR-0046 §3)."""

        def __init__(self, pipe: Any) -> None:
            super().__init__(daemon=True)
            self.pipe = pipe
            self.digest = hashlib.sha256()
            self.total = 0
            self.truncated = False

        def run(self) -> None:
            while True:
                try:
                    chunk = self.pipe.read(_CHUNK)
                except OSError:
                    break
                if not chunk:
                    break
                self.total += len(chunk)
                if self.total <= output_cap_bytes:
                    self.digest.update(chunk)
                else:
                    self.truncated = True
            try:
                self.pipe.close()
            except OSError:
                pass

        def result(self) -> tuple[str, int, bool]:
            return self.digest.hexdigest(), self.total, self.truncated

    stdout_drain = _Drainer(process.stdout)
    stderr_drain = _Drainer(process.stderr)
    stdout_drain.start()
    stderr_drain.start()
    timed_out = False
    try:
        exit_code = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()  # no zombie (ronda de fase, LOW)
        exit_code = None
        timed_out = True
    stdout_drain.join(timeout=10)
    stderr_drain.join(timeout=10)
    if timed_out:
        raise AttestError("attest_timeout")
    stdout_digest, stdout_bytes, stdout_truncated = stdout_drain.result()
    stderr_digest, stderr_bytes, stderr_truncated = stderr_drain.result()
    truncated = stdout_truncated or stderr_truncated

    nonce_value = nonce or os.urandom(16).hex()
    receipt_id = os.urandom(16).hex()
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "receipt_id": receipt_id,
        "command": list(command),
        "exit_code": exit_code,
        "stdout_digest": "sha256:" + stdout_digest,
        "stderr_digest": "sha256:" + stderr_digest,
        "stdout_bytes": stdout_bytes,
        "stderr_bytes": stderr_bytes,
        "truncated": truncated,
        "project_uuid": binding["store"]["project_uuid"],
        "store_identity": binding["store_identity"],
        "whitelist_digest": whitelist_digest(document),
        "base_revision": observed,
        "nonce": nonce_value,
        "observed_at": now if now is not None else _utc_now(),
        "policy_fingerprint": policy_fingerprint(),
    }
    receipt["receipt_hmac"] = _sign(key, receipt)
    encoded = canonical_json(receipt) + b"\n"
    receipt_digest = "sha256:" + hashlib.sha256(
        canonical_json(receipt)
    ).hexdigest()
    target = receipt_path(root, receipt_digest)
    try:
        _write_exclusive(target, encoded, 0o644)
    except FileExistsError:
        pass  # content-addressed: an identical receipt already exists
    return {
        "schema": RESULT_SCHEMA,
        "ok": True,
        "receipt": receipt,
        "receipt_digest": receipt_digest,
        "receipt_path": target.relative_to(root).as_posix(),
        "observed_base_revision": observed,
    }


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def find_receipt_evidence(authority: dict[str, Any]) -> dict[str, Any] | None:
    """Return the first ``attestation_receipt`` evidence item, or None."""

    for item in authority.get("evidence", []) or []:
        if (
            isinstance(item, dict)
            and item.get("kind") == "attestation_receipt"
        ):
            return item
    return None


def verify_receipt_for_authority(
    store: Any,
    authority: dict[str, Any],
    *,
    tombstone_absence_advisory: bool = True,
) -> dict[str, Any]:
    """Verify the receipt referenced by ``authority`` (ADR-0046 §4).

    Raises ``WritePolicyError``/``AttestError`` with stable codes on any
    failure; returns the loaded receipt. Callers decide enforcement:
    the CLI verifies before accepting ``tool_observed``; the engine
    re-verifies under the lock before consuming the tombstone.
    """

    root = Path(store.project_root)
    item = find_receipt_evidence(authority)
    if item is None:
        raise AttestError("receipt_invalid", "evidence_item_missing")
    if item.get("resolution") != "verified":
        raise AttestError("receipt_invalid", "resolution_not_verified")
    sha = item.get("sha256")
    if not isinstance(sha, str) or not sha.startswith("sha256:"):
        raise AttestError("receipt_invalid", "sha256_missing")
    hexpart = sha.split(":", 1)[1]
    if not _HEX64.fullmatch(hexpart):
        raise AttestError("receipt_invalid", "sha256_malformed")
    try:
        payload = receipt_path(root, sha).read_bytes()
    except OSError:
        raise AttestError("receipt_invalid", "receipt_file_missing") from None
    try:
        receipt = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise AttestError("receipt_invalid", "receipt_unreadable") from None
    if not isinstance(receipt, dict) or receipt.get("schema") != RECEIPT_SCHEMA:
        raise AttestError("receipt_invalid", "schema")
    # Issue #114/A2: el receipt es content-addressed; el digest canónico
    # del objeto leído debe coincidir con la dirección bajo la que se
    # sirvió (un archivo reescrito con otro contenido no es el receipt).
    actual_digest = "sha256:" + hashlib.sha256(
        canonical_json(receipt)
    ).hexdigest()
    if actual_digest != sha:
        raise AttestError("receipt_invalid", "receipt_digest_mismatch")
    # El id del evidence debe ser el receipt_id firmado (ronda de fase).
    if item.get("id") != receipt.get("receipt_id"):
        raise AttestError("receipt_invalid", "receipt_id_mismatch")
    claimed = receipt.pop("receipt_hmac", None)
    if not isinstance(claimed, str) or not claimed.startswith(SIGNATURE_PREFIX):
        raise AttestError("receipt_invalid", "hmac_malformed")
    key = _load_key(root)
    expected = _sign(key, receipt)
    if not hmac.compare_digest(claimed, expected):
        raise AttestError("receipt_invalid", "hmac_mismatch")
    if receipt.get("policy_fingerprint") != policy_fingerprint():
        raise AttestError("receipt_invalid", "policy_fingerprint_changed")
    if receipt.get("exit_code") != 0:
        raise AttestError("receipt_invalid", "exit_code_not_zero")
    document = load_whitelist(root)
    if receipt.get("whitelist_digest") != whitelist_digest(document):
        raise AttestError("receipt_whitelist_changed")
    if not command_allowed(document, [str(a) for a in receipt.get("command", [])]):
        raise AttestError("attest_command_not_allowed")

    from .identity import read_binding

    try:
        binding = read_binding(store)
    except Exception:
        raise AttestError("receipt_identity_mismatch") from None
    if (
        receipt.get("store_identity") != binding["store_identity"]
        or receipt.get("project_uuid") != binding["store"]["project_uuid"]
    ):
        raise AttestError("receipt_identity_mismatch")
    if tombstone_absence_advisory and tombstone_path(root, str(receipt["nonce"])).exists():
        raise AttestError("receipt_replayed")
    receipt["receipt_hmac"] = claimed
    return receipt


def enforce_for_commit(store: Any, authority: dict[str, Any]) -> None:
    """Engine-level defense-in-depth (ADR-0046 §4): re-verify the receipt
    against the live binding and consume its tombstone under the write
    lock — created, never compared. Forged or replayed receipts die here
    with CURRENT intact.
    """

    receipt = verify_receipt_for_authority(store, authority)
    consume_tombstone(store, receipt)


def consume_tombstone(store: Any, receipt: dict[str, Any]) -> None:
    """Create the consumption tombstone under the write lock (ADR-0046 §3).

    Created, never compared: O_EXCL is the whole mechanism. A conflicting
    path is ``receipt_replayed`` — quarantine-retry of ``write_immutable``
    is intentionally not used here.
    """

    nonce = str(receipt["nonce"])
    target = tombstone_path(Path(store.project_root), nonce)
    tombstone = {
        "schema": TOMBSTONE_SCHEMA,
        "nonce": nonce,
        "receipt_id": str(receipt.get("receipt_id", "")),
        "created_at": _utc_now(),
    }
    payload = canonical_json(tombstone) + b"\n"
    try:
        _write_exclusive(target, payload, 0o644)
    except FileExistsError:
        raise AttestError("receipt_replayed") from None


__all__ = [
    "AttestError",
    "DEFAULT_WHITELIST",
    "attest_run",
    "consume_tombstone",
    "command_allowed",
    "ensure_attest_files",
    "find_receipt_evidence",
    "load_whitelist",
    "verify_receipt_for_authority",
    "whitelist_digest",
]
