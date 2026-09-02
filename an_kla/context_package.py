"""Managed, compact agent-context integration for AN-KLA.

The pure document transformer owns only the bytes between explicit markers.
Filesystem wrappers add compare-and-swap, a local lock, content-addressed
backups, and atomic replacement.  Recovered memory is never parsed here.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
from typing import Any, Iterator

from an_kla.canonical import digest_json
from an_kla.context_text import (
    BLOCK_ID,
    COMPACT_PAYLOAD,
    CONTEXT_SCHEMA,
    CONTRACT_RELATIVE,
    DETAILED_CONTRACT,
    INSTALLATION_SCHEMA,
    MANIFEST_RELATIVE,
    PLAN_SCHEMA,
    TEMPLATE_VERSION,
    _KNOWN_CONTEXT_TEMPLATES,
)

_BEGIN_PREFIX = "<!-- an-kla:managed-begin "
_END_PREFIX = "<!-- an-kla:managed-end "
_BEGIN_ANCHOR = "<!-- an-kla:managed-begin"
_END_ANCHOR = "<!-- an-kla:managed-end"
_MARKER_SUFFIX = " -->"
_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class ContextPackageError(ValueError):
    """Stable, non-sensitive context-package diagnostic."""


class ContextConcurrentUpdate(ContextPackageError):
    pass


class ContextLockBusy(ContextPackageError):
    pass


@dataclass(frozen=True)
class ManagedBlock:
    begin_index: int
    end_index: int
    metadata: dict[str, Any]
    payload: str


def _sha(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _semantic_text_sha(text: str) -> str:
    # Normaliza TODO separador de línea a LF. Además del CRLF de un
    # editor, en NT write_text con newline=None convierte un "\r\n"
    # ya presente en "\r\r\n" (el \n final se traduce a os.linesep) —
    # la semántica del texto no cambia en ningún caso.
    return _sha(_canonical_payload(text).encode("utf-8"))


def _known_template_equivalent(block: ManagedBlock | None, contract_text: str | None) -> bool:
    if block is None or contract_text is None:
        return False
    known = _KNOWN_CONTEXT_TEMPLATES.get(str(block.metadata.get("version")))
    return bool(
        known
        and block.metadata.get("content_sha256") == known["content_sha256"]
        and _semantic_text_sha(contract_text) == known["contract_sha256"]
    )


def _desired_contract_bytes(contract_text: str | None) -> bytes:
    newline = _newline_for(contract_text or "")
    return DETAILED_CONTRACT.replace("\n", newline).encode("utf-8")


def _canonical_payload(payload: str) -> str:
    return payload.replace("\r\n", "\n").replace("\r", "\n")


def managed_payload_sha256(payload: str = COMPACT_PAYLOAD) -> str:
    return _sha(_canonical_payload(payload).encode("utf-8"))


def _contract_equivalent(text: str | None) -> bool:
    return text is not None and _canonical_payload(text) == DETAILED_CONTRACT


def get_template(version: str | None = None) -> dict[str, Any]:
    """Expose the canonical managed-block text for inspection or manual repair.

    For the installed ``TEMPLATE_VERSION`` the full payload and contract text
    are returned.  For historical versions listed in ``_KNOWN_CONTEXT_TEMPLATES``
    only the recorded hashes are returned; the source text of those releases
    remains retrievable via Git history of the corresponding tag.
    """

    target = TEMPLATE_VERSION if version is None else str(version)
    if target != TEMPLATE_VERSION and target not in _KNOWN_CONTEXT_TEMPLATES:
        raise ValueError("unknown_template_version")
    known_versions = sorted(set(_KNOWN_CONTEXT_TEMPLATES) | {TEMPLATE_VERSION})
    if target == TEMPLATE_VERSION:
        return {
            "schema": "an-kla/context-template-v1",
            "version": TEMPLATE_VERSION,
            "current": True,
            "compact_payload": COMPACT_PAYLOAD,
            "detailed_contract": DETAILED_CONTRACT,
            "content_sha256": managed_payload_sha256(),
            "contract_sha256": _semantic_text_sha(DETAILED_CONTRACT),
            "known_versions": known_versions,
        }
    known = _KNOWN_CONTEXT_TEMPLATES[target]
    return {
        "schema": "an-kla/context-template-v1",
        "version": target,
        "current": False,
        "content_sha256": known["content_sha256"],
        "contract_sha256": known["contract_sha256"],
        "note": (
            "Source text for historical templates is not bundled; recover it "
            "from the corresponding release tag in Git history."
        ),
        "known_versions": known_versions,
    }


def _marker(prefix: str, metadata: dict[str, Any]) -> str:
    body = json.dumps(metadata, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return prefix + body + _MARKER_SUFFIX


def render_managed_block(newline: str = "\n") -> str:
    if newline not in {"\n", "\r\n"}:
        raise ContextPackageError("unsupported_newline")
    metadata = {
        "content_sha256": managed_payload_sha256(),
        "id": BLOCK_ID,
        "schema": CONTEXT_SCHEMA,
        "version": TEMPLATE_VERSION,
    }
    payload = COMPACT_PAYLOAD.replace("\n", newline)
    return (
        _marker(_BEGIN_PREFIX, metadata)
        + newline
        + payload
        + _marker(_END_PREFIX, {"id": BLOCK_ID})
        + newline
    )


def _parse_marker(line: str, prefix: str) -> dict[str, Any]:
    bare = line.rstrip("\r\n")
    if not bare.startswith(prefix) or not bare.endswith(_MARKER_SUFFIX):
        raise ContextPackageError("managed_block_structure_invalid")
    encoded = bare[len(prefix) : -len(_MARKER_SUFFIX)]
    try:
        value = json.loads(encoded)
    except json.JSONDecodeError:
        raise ContextPackageError("managed_block_structure_invalid") from None
    if not isinstance(value, dict):
        raise ContextPackageError("managed_block_structure_invalid")
    return value


def parse_managed_block(document: str) -> ManagedBlock | None:
    """Return the single valid block, rejecting ambiguous marker structures.

    Only a line whose marker syntax is anchored at the start (ignoring leading
    whitespace) is a marker candidate. Bare mentions of ``an-kla:managed-`` in
    prose or inside inline code spans are ignored so the managed-block mechanism
    can be documented inside ``AGENTS.md`` itself. Anchored candidates still fail
    closed when malformed, indented, fenced, duplicated, nested or out of order,
    as required by ADR-0009; the fenced case raises the distinct code
    ``managed_block_inside_fence`` (issue #105) so an unclosed fence is not
    indistinguishable from corruption.
    """

    lines = document.splitlines(keepends=True)
    begins: list[int] = []
    ends: list[int] = []
    fence: tuple[str, int] | None = None
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        fence_match = re.match(r"(`{3,}|~{3,})", stripped)
        if fence_match:
            token = fence_match.group(1)
            kind = token[0]
            if fence is None:
                fence = (kind, len(token))
            elif fence[0] == kind and len(token) >= fence[1]:
                fence = None
        if "an-kla:managed-" not in line:
            continue
        if not stripped.startswith((_BEGIN_ANCHOR, _END_ANCHOR)):
            continue
        if fence is not None:
            # Issue #105 (H4): a fence around the markers is a distinct,
            # recoverable authoring mistake (bug real del consumidor
            # infosalud, 2026-09-01); distinguishable from corruption.
            raise ContextPackageError("managed_block_inside_fence")
        if line.startswith((" ", "\t")):
            raise ContextPackageError("managed_block_structure_invalid")
        if line.startswith(_BEGIN_PREFIX):
            begins.append(index)
        elif line.startswith(_END_PREFIX):
            ends.append(index)
        else:
            raise ContextPackageError("managed_block_structure_invalid")

    if not begins and not ends:
        return None
    if len(begins) != 1 or len(ends) != 1 or begins[0] >= ends[0]:
        raise ContextPackageError("managed_block_structure_invalid")

    begin_index, end_index = begins[0], ends[0]
    metadata = _parse_marker(lines[begin_index], _BEGIN_PREFIX)
    closing = _parse_marker(lines[end_index], _END_PREFIX)
    required = {"content_sha256", "id", "schema", "version"}
    if (
        set(metadata) != required
        or metadata.get("schema") != CONTEXT_SCHEMA
        or metadata.get("id") != BLOCK_ID
        or closing != {"id": BLOCK_ID}
        or not isinstance(metadata.get("version"), str)
        or not isinstance(metadata.get("content_sha256"), str)
        or not _HASH_RE.fullmatch(metadata["content_sha256"])
    ):
        raise ContextPackageError("managed_block_structure_invalid")
    payload = "".join(lines[begin_index + 1 : end_index])
    if managed_payload_sha256(payload) != metadata["content_sha256"]:
        raise ContextPackageError("managed_block_modified")
    return ManagedBlock(begin_index, end_index, metadata, payload)


def _newline_for(document: str) -> str:
    crlf = document.count("\r\n")
    lf = document.count("\n") - crlf
    return "\r\n" if crlf > lf else "\n"


def _legacy_context(document: str) -> bool:
    signals = (
        ".an-kla/memory",
        "scripts/save-context.sh",
        "--expected-current",
        "python3 -m an_kla",
        "rebuild-index",
    )
    return sum(signal in document for signal in signals) >= 2


def transform_document(document: str | None, operation: str) -> tuple[str | None, str]:
    """Pure managed-block create/update/uninstall transformation."""

    if operation not in {"install", "update", "uninstall"}:
        raise ContextPackageError("unsupported_context_operation")
    current = document or ""
    block = parse_managed_block(current)
    newline = _newline_for(current)
    lines = current.splitlines(keepends=True)

    if operation in {"install", "update"}:
        desired = render_managed_block(newline)
        if block is None:
            if operation == "update":
                raise ContextPackageError("managed_block_missing")
            if _legacy_context(current):
                raise ContextPackageError("legacy_an_kla_context_detected")
            if not current:
                return desired, "create"
            separator = "" if current.endswith(("\n", "\r")) else newline
            if not current.endswith(newline * 2):
                separator += newline
            return current + separator + desired, "append"
        replacement = "".join(lines[: block.begin_index]) + desired + "".join(
            lines[block.end_index + 1 :]
        )
        if replacement == current:
            return current, "noop"
        return replacement, "replace"

    if block is None:
        raise ContextPackageError("managed_block_missing")
    remainder = "".join(lines[: block.begin_index] + lines[block.end_index + 1 :])
    if not remainder.strip():
        return None, "delete"
    return remainder, "remove_block"


def _target_path(project_root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.parts != ("AGENTS.md",):
        raise ContextPackageError("invalid_context_target")
    target = project_root.joinpath(*pure.parts)
    cursor = project_root
    for part in pure.parts:
        cursor = cursor / part
        if cursor.exists() and cursor.is_symlink():
            raise ContextPackageError("context_target_symlink_forbidden")
    return target


def _project_root(value: str | Path) -> Path:
    root = Path(value).resolve()
    if not root.is_dir():
        raise ContextPackageError("project_root_not_directory")
    return root


def _read_utf8(path: Path) -> tuple[bytes | None, str | None]:
    if not path.exists():
        return None, None
    if path.is_symlink():
        raise ContextPackageError("context_target_symlink_forbidden")
    if not path.is_file():
        raise ContextPackageError("context_file_not_regular")
    payload = path.read_bytes()
    try:
        return payload, payload.decode("utf-8")
    except UnicodeDecodeError:
        raise ContextPackageError("context_target_not_utf8") from None


def _assert_managed_path(root: Path, path: Path) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError:
        raise ContextPackageError("context_path_outside_project") from None
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.exists() and cursor.is_symlink():
            raise ContextPackageError("context_directory_symlink_forbidden")


def _observed_sha(payload: bytes | None) -> str:
    return "missing" if payload is None else _sha(payload)


def plan_context_change(
    project_root: str | Path,
    operation: str,
    target: str = "AGENTS.md",
    *,
    allow_target_drift: bool = False,
) -> dict[str, Any]:
    root = _project_root(project_root)
    target_path = _target_path(root, target)
    before_bytes, before_text = _read_utf8(target_path)
    result_text, action = transform_document(before_text, operation)
    manifest = _load_manifest(root)
    manifest_path = root / MANIFEST_RELATIVE
    manifest_bytes = manifest_path.read_bytes() if manifest_path.exists() else None
    if manifest is not None and manifest.get("target") != target:
        raise ContextPackageError("context_manifest_target_mismatch")
    if (
        operation in {"update", "install"}
        and not allow_target_drift
        and manifest is not None
        and before_bytes is not None
        and manifest.get("target_sha256") != _sha(before_bytes)
    ):
        # ADR-0040 §6: update (and reinstall over an existing manifest)
        # must not silently absorb unrecognized drift; the only escape
        # hatches are adopt-baseline and upgrade's --confirm-target-drift
        # (carve-out passed by inspect/apply_upgrade).
        raise ContextPackageError("context_target_drift_adoption_required")
    if operation == "uninstall" and result_text is None and not (
        manifest and manifest.get("file_created_by_an_kla") is True
    ):
        current = before_text or ""
        block = parse_managed_block(current)
        if block is None:
            raise ContextPackageError("managed_block_missing")
        lines = current.splitlines(keepends=True)
        result_text = "".join(lines[: block.begin_index] + lines[block.end_index + 1 :])
        action = "preserve_empty"
    result_bytes = None if result_text is None else result_text.encode("utf-8")
    contract_path = root / CONTRACT_RELATIVE
    contract_bytes, contract_text = _read_utf8(contract_path)
    block = parse_managed_block(before_text or "")
    expected_contract = _desired_contract_bytes(contract_text)
    current_contract = _contract_equivalent(contract_text)
    known_update_source = _known_template_equivalent(block, contract_text)
    if (
        operation in {"install", "update"}
        and contract_bytes is not None
        and not current_contract
        and not (operation == "update" and known_update_source)
    ):
        raise ContextPackageError("managed_contract_modified")
    if operation in {"install", "update"}:
        result_contract_sha = (
            _sha(contract_bytes)
            if contract_bytes is not None and current_contract
            else _sha(expected_contract)
        )
    elif (
        _contract_equivalent(contract_text)
        and manifest
        and manifest.get("contract_created_by_an_kla") is True
    ):
        result_contract_sha = "missing"
    else:
        result_contract_sha = _observed_sha(contract_bytes)
    return {
        "schema": PLAN_SCHEMA,
        "operation": operation,
        "target": target,
        "action": action,
        "base_target_sha256": _observed_sha(before_bytes),
        "result_target_sha256": _observed_sha(result_bytes),
        "base_contract_sha256": _observed_sha(contract_bytes),
        "base_manifest_sha256": _observed_sha(manifest_bytes),
        "result_contract_sha256": result_contract_sha,
        "managed_content_sha256": managed_payload_sha256(),
        "template_version": TEMPLATE_VERSION,
    }


def _atomic_write(path: Path, payload: bytes, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".an-kla-context-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode if mode is not None else 0o644)
        os.replace(temporary, path)
        if os.name == "posix":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


@contextmanager
def _context_lock(root: Path) -> Iterator[None]:
    context_root = root / ".an-kla" / "context"
    _assert_managed_path(root, context_root)
    context_root.mkdir(parents=True, exist_ok=True)
    _assert_managed_path(root, context_root)
    lock_path = context_root / ".install.lock"
    with lock_path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            if handle.read(1) == b"":
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise ContextLockBusy("context_install_lock_busy") from None
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            return

        import fcntl

        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ContextLockBusy("context_install_lock_busy") from None
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _load_manifest(root: Path) -> dict[str, Any] | None:
    path = root / MANIFEST_RELATIVE
    _assert_managed_path(root, path)
    if not path.exists():
        return None
    if path.is_symlink():
        raise ContextPackageError("context_manifest_symlink_forbidden")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ContextPackageError("context_manifest_invalid") from None
    required = {
        "schema",
        "target",
        "block_id",
        "template_version",
        "managed_content_sha256",
        "target_sha256",
        "contract_sha256",
        "original_target_sha256",
        "original_backup",
        "file_created_by_an_kla",
        "contract_created_by_an_kla",
    }
    hashes = (
        value.get("managed_content_sha256"),
        value.get("target_sha256"),
        value.get("contract_sha256"),
    ) if isinstance(value, dict) else ()
    original_hash = value.get("original_target_sha256") if isinstance(value, dict) else None
    backup = value.get("original_backup") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or set(value) != required
        or value.get("schema") != INSTALLATION_SCHEMA
        or value.get("target") != "AGENTS.md"
        or value.get("block_id") != BLOCK_ID
        or not isinstance(value.get("template_version"), str)
        or not all(isinstance(item, str) and _HASH_RE.fullmatch(item) for item in hashes)
        or not (
            original_hash == "missing"
            or isinstance(original_hash, str) and _HASH_RE.fullmatch(original_hash)
        )
        or not isinstance(value.get("file_created_by_an_kla"), bool)
        or not isinstance(value.get("contract_created_by_an_kla"), bool)
        or not (
            backup is None
            or isinstance(backup, str)
            and backup.startswith(".an-kla/context/backups/")
            and ".." not in PurePosixPath(backup).parts
        )
    ):
        raise ContextPackageError("context_manifest_invalid")
    return value


def apply_context_plan(
    project_root: str | Path,
    plan: dict[str, Any],
    *,
    allow_target_drift: bool = False,
) -> dict[str, Any]:
    root = _project_root(project_root)
    if not isinstance(plan, dict) or plan.get("schema") != PLAN_SCHEMA:
        raise ContextPackageError("invalid_context_plan")
    operation = plan.get("operation")
    target = plan.get("target")
    if not isinstance(operation, str) or not isinstance(target, str):
        raise ContextPackageError("invalid_context_plan")
    target_path = _target_path(root, target)

    with _context_lock(root):
        rebuilt = plan_context_change(
            root, operation, target, allow_target_drift=allow_target_drift
        )
        if rebuilt != plan:
            if rebuilt.get("base_target_sha256") != plan.get("base_target_sha256"):
                raise ContextConcurrentUpdate("context_file_concurrent_update")
            raise ContextPackageError("context_plan_mismatch")

        before_bytes, _ = _read_utf8(target_path)
        result_text, action = transform_document(
            None if before_bytes is None else before_bytes.decode("utf-8"), operation
        )
        context_root = root / ".an-kla" / "context"
        manifest = _load_manifest(root)
        if manifest is not None and manifest.get("target") != target:
            raise ContextPackageError("context_manifest_target_mismatch")
        contract_path = root / CONTRACT_RELATIVE
        contract_before_bytes, contract_before_text = _read_utf8(contract_path)
        if (
            operation in {"install", "update"}
            and action == "noop"
            and manifest is not None
            and manifest.get("target_sha256") == plan["result_target_sha256"]
            and manifest.get("template_version") == TEMPLATE_VERSION
            and contract_path.is_file()
            and not contract_path.is_symlink()
            and _contract_equivalent(contract_before_text)
        ):
            return {
                "schema": "an-kla/context-apply-result/v1",
                "operation": operation,
                "action": "noop",
                "target": target,
                "target_sha256": plan["result_target_sha256"],
                "template_version": TEMPLATE_VERSION,
            }
        original_sha = _observed_sha(before_bytes)
        original_backup: str | None = None
        if operation in {"install", "update"}:
            if manifest:
                original_sha = str(manifest.get("original_target_sha256", original_sha))
                original_backup = manifest.get("original_backup")
            elif before_bytes is not None:
                digest = hashlib.sha256(before_bytes).hexdigest()
                backup_path = context_root / "backups" / digest / "AGENTS.md"
                _assert_managed_path(root, backup_path)
                if not backup_path.exists():
                    _atomic_write(backup_path, before_bytes, stat.S_IMODE(target_path.stat().st_mode))
                original_backup = backup_path.relative_to(root).as_posix()

            contract_path = root / CONTRACT_RELATIVE
            desired_contract_bytes = _desired_contract_bytes(contract_before_text)
            if contract_before_bytes is None:
                _atomic_write(contract_path, desired_contract_bytes, 0o644)
                installed_contract_bytes = desired_contract_bytes
            elif _contract_equivalent(contract_before_text):
                installed_contract_bytes = contract_before_bytes
            else:
                digest = hashlib.sha256(contract_before_bytes).hexdigest()
                contract_backup = context_root / "backups" / digest / CONTRACT_RELATIVE
                _assert_managed_path(root, contract_backup)
                if not contract_backup.exists():
                    _atomic_write(
                        contract_backup,
                        contract_before_bytes,
                        stat.S_IMODE(contract_path.stat().st_mode),
                    )
                _atomic_write(
                    contract_path,
                    desired_contract_bytes,
                    stat.S_IMODE(contract_path.stat().st_mode),
                )
                installed_contract_bytes = desired_contract_bytes
            result_bytes = result_text.encode("utf-8") if result_text is not None else b""
            mode = stat.S_IMODE(target_path.stat().st_mode) if target_path.exists() else 0o644
            _atomic_write(target_path, result_bytes, mode)
            manifest_payload = {
                "schema": INSTALLATION_SCHEMA,
                "target": target,
                "block_id": BLOCK_ID,
                "template_version": TEMPLATE_VERSION,
                "managed_content_sha256": managed_payload_sha256(),
                "target_sha256": _sha(result_bytes),
                "contract_sha256": _sha(installed_contract_bytes),
                "original_target_sha256": original_sha,
                "original_backup": original_backup,
                "file_created_by_an_kla": before_bytes is None if not manifest else bool(
                    manifest.get("file_created_by_an_kla", False)
                ),
                "contract_created_by_an_kla": (
                    plan["base_contract_sha256"] == "missing"
                    if not manifest
                    else bool(manifest.get("contract_created_by_an_kla", False))
                ),
            }
            _atomic_write(
                root / MANIFEST_RELATIVE,
                (json.dumps(manifest_payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
                    "utf-8"
                ),
                0o600,
            )
        else:
            if result_text is None and not (
                manifest and manifest.get("file_created_by_an_kla") is True
            ):
                current = before_bytes.decode("utf-8") if before_bytes else ""
                block = parse_managed_block(current)
                if block is None:
                    raise ContextPackageError("managed_block_missing")
                lines = current.splitlines(keepends=True)
                result_text = "".join(
                    lines[: block.begin_index] + lines[block.end_index + 1 :]
                )
                action = "preserve_empty"
            if result_text is None:
                target_path.unlink()
            else:
                mode = stat.S_IMODE(target_path.stat().st_mode)
                _atomic_write(target_path, result_text.encode("utf-8"), mode)
            contract_path = root / CONTRACT_RELATIVE
            contract_bytes, contract_text = _read_utf8(contract_path)
            if (
                _contract_equivalent(contract_text)
                and manifest
                and manifest.get("contract_created_by_an_kla") is True
            ):
                contract_path.unlink()
            manifest_path = root / MANIFEST_RELATIVE
            if manifest_path.exists() and not manifest_path.is_symlink():
                manifest_path.unlink()

        return {
            "schema": "an-kla/context-apply-result/v1",
            "operation": operation,
            "action": action,
            "target": target,
            "target_sha256": plan["result_target_sha256"],
            "template_version": TEMPLATE_VERSION,
        }


def context_status(project_root: str | Path, target: str = "AGENTS.md") -> dict[str, Any]:
    root = _project_root(project_root)
    target_path = _target_path(root, target)
    diagnostics: list[str] = []
    warnings: list[str] = []
    target_text: str | None = None
    try:
        target_bytes, target_text = _read_utf8(target_path)
        block = parse_managed_block(target_text or "")
    except ContextPackageError as exc:
        target_bytes, block = None, None
        diagnostics.append(str(exc))
    manifest: dict[str, Any] | None = None
    try:
        manifest = _load_manifest(root)
    except ContextPackageError as exc:
        diagnostics.append(str(exc))
    contract_path = root / CONTRACT_RELATIVE
    contract_error = False
    contract_text: str | None = None
    try:
        contract_bytes, contract_text = _read_utf8(contract_path)
    except ContextPackageError as exc:
        contract_bytes = None
        contract_error = True
        diagnostics.append(str(exc))
    if block and manifest is None:
        warnings.append("context_manifest_missing")
    if block is None and target_text and _legacy_context(target_text):
        diagnostics.append("legacy_an_kla_context_detected")
    if manifest and block is None:
        diagnostics.append("managed_block_missing")
    known_outdated = _known_template_equivalent(block, contract_text)
    if block and block.metadata.get("version") != TEMPLATE_VERSION:
        diagnostics.append("context_template_outdated")
    if contract_bytes is None and block and not contract_error:
        diagnostics.append("managed_contract_missing")
    elif _contract_equivalent(contract_text) and block is None:
        diagnostics.append("orphan_managed_contract")
    elif (
        contract_bytes is not None
        and not _contract_equivalent(contract_text)
        and not known_outdated
    ):
        diagnostics.append("managed_contract_modified")
    if manifest and target_bytes is not None and manifest.get("target_sha256") != _sha(target_bytes):
        warnings.append("context_target_changed_outside_managed_block")
    return {
        "schema": "an-kla/context-status/v1",
        "installed": block is not None,
        "target": target,
        "template_version": block.metadata.get("version") if block else None,
        "current_template_version": TEMPLATE_VERSION,
        "diagnostics": sorted(set(diagnostics)),
        "warnings": sorted(set(warnings)),
        "ok": block is not None and not diagnostics,
    }
