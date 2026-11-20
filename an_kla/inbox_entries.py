"""Lectura, validación y rechazo de entradas de ``pending/`` (ADR-0063 D1, paso 2 del vaciado).

Una entrada se examina con ``lstat`` antes de abrirla: un directorio se ignora sin tocarlo y
cualquier cosa que no sea un archivo regular con ``st_nlink == 1`` (FIFO, socket, enlace,
hardlink) se rechaza sin abrirla, de modo que un FIFO no puede colgar el vaciado. Un rechazo
conserva el nombre de la entrada en ``rejected/`` y, junto a ella, ``<nombre>.reason`` con
``{"code": <código>, "reason_codes": [...]}`` (convención de B1, que lee ``inbox status``): el
motivo se escribe primero y la entrada se mueve después, así un corte entre ambos sólo deja un
motivo huérfano y el siguiente vaciado repite el rechazo.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import stat
from dataclasses import dataclass, field
from typing import Any, Mapping

from . import directive, identity_c0
from .anchors import ANCHOR_SCHEMA_V2, AnchorRejected, validate_anchors
from .audience import ENTRY_SCOPE_KEYS, ScopeError
from .canonical import canonical_json, digest_json
from .inbox import (
    DEFAULT_SLOT,
    ENTRY_SCHEMA,
    ENTRY_SCHEMA_V2,
    ENTRY_SCHEMA_V3,
    ENTRY_SCHEMA_V4,
    ENTRY_SCHEMA_V5,
    ALL_KINDS,
    MAX_TEXT_BYTES,
    REASON_SUFFIX,
    SLOT_PATTERN,
    InboxPaths,
    inbox_paths,
    payload_digest,
)
from .inbox_anchors import OPERATIONS, VERDICTS, payload_extra, stored_anchors
from .storage_primitives import fsync_directory

UNSAFE = "inbox_entry_unsafe"
INVALID = "inbox_entry_invalid"
MAX_ENTRY_BYTES = 8 * MAX_TEXT_BYTES
_REASON = re.compile(r"[a-z0-9_:.-]{1,80}")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_REQUIRED = {"schema", "text", "kind", "kind_explicit", "envelope", "idempotency_key", "payload_sha256"}


class Reject(Exception):
    """La entrada no se puede comprometer: va a ``rejected/`` con ``code`` y ``reason_codes``."""

    def __init__(self, code: str, reason_codes: list[str] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.reason_codes = safe_codes(reason_codes or [])


def safe_codes(values: Any) -> list[str]:
    """Reduce los motivos al alfabeto cerrado que ``inbox status`` acepta (nunca texto de recuerdos)."""

    if not isinstance(values, (list, tuple, set)):
        return []
    cleaned = {str(item).lower() for item in values}
    return sorted(item for item in cleaned if _REASON.fullmatch(item))[:32]


@dataclass
class Entry:
    name: str
    data: dict[str, Any]
    digest: str
    op: Any = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return self.data["text"]

    @property
    def key(self) -> str:
        return self.data["idempotency_key"]

    @property
    def payload(self) -> str:
        return self.data["payload_sha256"]

    @property
    def envelope(self) -> Mapping[str, Any]:
        return self.data["envelope"]

    @property
    def target_id(self) -> str | None:
        return self.data.get("target_id")

    @property
    def slot(self) -> str | None:
        """Casilla de un ``state`` (v1 sin ``slot`` = ``main``, ADR-0065 §1); ``None`` para los demás ``kind``."""

        return self.data.get("slot", DEFAULT_SLOT) if self.data["kind"] == "state" else None


def age_key(name: str) -> tuple[int, str]:
    """Orden de vaciado: ``<tiempo_ns>`` numérico y luego el nombre (no es orden causal entre relojes)."""

    return int(name.split("-", 1)[0]), name


def kind_of_path(path: Any) -> str:
    """``dir`` (se ignora), ``unsafe`` (no regular o ``st_nlink != 1``), ``ok`` o ``gone``."""

    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return "gone"
    if stat.S_ISDIR(info.st_mode):
        return "dir"
    return "ok" if stat.S_ISREG(info.st_mode) and info.st_nlink == 1 else "unsafe"


def _read_regular(path: Any) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        raise Reject(INVALID, ["unreadable"]) from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise Reject(UNSAFE)
        raw = os.read(fd, MAX_ENTRY_BYTES + 1)
    except OSError:
        raise Reject(INVALID, ["unreadable"]) from None
    finally:
        os.close(fd)
    if len(raw) > MAX_ENTRY_BYTES:
        raise Reject(INVALID, ["entry_too_large"])
    return raw


_V3_KEYS = {"anchors", "verdict", "operation", "anchor_resolution"}
_V4_KEYS = set(ENTRY_SCOPE_KEYS) | {"anchor_check"}  # ADR-0071 §6: v4 also carries the audit's annotation


def _validate_scope(data: dict[str, Any]) -> None:
    """The v4 fields (ADR-0069 §1–§3): their types, then the write rejections in the ADR's order (the drain's second look)."""

    for key in ("subject", "audience", "valid_until"):
        if key in data and not isinstance(data[key], str):
            raise Reject(INVALID, [key])
    for key in ("until_revoked", "revokes"):
        if key in data and data[key] is not True:
            raise Reject(INVALID, [key])
    try:
        directive.check_entry(data)
    except ScopeError as refused:
        raise Reject(refused.code) from None


def _validate_v3(data: dict[str, Any]) -> None:
    """The v3 fields (ADR-0066 §1): operation, verdict, resolution and the anchors' rejections in C3's order."""

    operation = data.get("operation", "remember")
    if operation not in OPERATIONS or ("operation" in data and operation == "remember"):
        raise Reject(INVALID, ["operation"])
    v4 = data.get("schema") in (ENTRY_SCHEMA_V4, ENTRY_SCHEMA_V5)  # v5 is v4 plus a resolver result (ADR-0073 §2)
    if (operation == "anchor_check") != isinstance(data.get("anchor_check"), dict) or (operation == "anchor_check" and not v4):
        raise Reject(INVALID, ["anchor_check"])
    verdict = data.get("verdict")
    if (operation == "dispute") != (verdict is not None) or (verdict is not None and verdict not in VERDICTS):
        raise Reject(INVALID, ["verdict"])
    if operation == "dispute" and (data["kind"] != "fact" or "target_id" not in data):
        raise Reject(INVALID, ["dispute"])
    if (operation == "anchor_resolution") != isinstance(data.get("anchor_resolution"), dict):
        raise Reject(INVALID, ["anchor_resolution"])
    anchors = data.get("anchors")
    if "anchors" in data and (not isinstance(anchors, list) or not anchors):
        raise Reject(INVALID, ["anchors"])
    if anchors:
        if not v4 and any(isinstance(a, dict) and a.get("schema") == ANCHOR_SCHEMA_V2 for a in anchors):
            raise Reject("anchor_schema_invalid", ["anchor_schema"])  # a v2 anchor travels in an inbox-entry-v4 (ADR-0071 §6)
        try:
            validate_anchors(stored_anchors(anchors), "decision" if data["kind"] == "directive" else data["kind"])
        except AnchorRejected as refused:
            raise Reject(refused.code, [] if refused.anchor_index is None else [f"anchor_{refused.anchor_index}"]) from None


def _validate(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise Reject(INVALID, ["not_object"])
    keys = set(data)
    v4 = data.get("schema") in (ENTRY_SCHEMA_V4, ENTRY_SCHEMA_V5)  # v5 is v4 plus a resolver result (ADR-0073 §2)
    v3 = data.get("schema") in (ENTRY_SCHEMA_V3, ENTRY_SCHEMA_V4, ENTRY_SCHEMA_V5)
    v2 = data.get("schema") == ENTRY_SCHEMA_V2 or (v3 and "slot" in data)
    optional = {"target_id"} | ({"slot"} if v2 else set()) | (_V3_KEYS if v3 else set()) | (_V4_KEYS if v4 else set())
    if not _REQUIRED <= keys or not keys <= _REQUIRED | optional:
        raise Reject(INVALID, ["keys"])
    if data["schema"] not in (ENTRY_SCHEMA, ENTRY_SCHEMA_V2, ENTRY_SCHEMA_V3, ENTRY_SCHEMA_V4, ENTRY_SCHEMA_V5):
        raise Reject(INVALID, ["schema"])
    if data.get("kind") == "directive" and not v4:  # ADR-0069 §1: `directive` es de v4
        raise Reject(INVALID, ["kind"])
    text, kind, target = data["text"], data["kind"], data.get("target_id")
    slot = data.get("slot")
    if v2 and (kind != "state" or not isinstance(slot, str) or not SLOT_PATTERN.fullmatch(slot)):
        raise Reject(INVALID, ["slot"])
    if v3:
        _validate_v3(data)
    if not isinstance(text, str) or not text:
        raise Reject(INVALID, ["text"])
    try:
        if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
            raise Reject(INVALID, ["text_too_large"])
    except UnicodeEncodeError:
        raise Reject(INVALID, ["text"]) from None
    if kind not in ALL_KINDS or not isinstance(data["kind_explicit"], bool):
        raise Reject(INVALID, ["kind"])
    if "target_id" in data and not (isinstance(target, str) and 0 < len(target) <= 256):
        raise Reject(INVALID, ["target_id"])
    for field_name in ("idempotency_key", "payload_sha256"):
        if not isinstance(data[field_name], str) or not _DIGEST.fullmatch(data[field_name]):
            raise Reject(INVALID, [field_name])
    problems = identity_c0.validate_envelope(data["envelope"])
    if problems:
        raise Reject(INVALID, ["envelope", *problems])
    envelope = data["envelope"]
    if envelope["idempotency_key"] != data["idempotency_key"] or envelope["kind"] != kind:
        raise Reject(INVALID, ["envelope_mismatch"])
    if v4 and (kind == "directive" or any(key in data for key in ENTRY_SCOPE_KEYS)):
        _validate_scope(data)
    if data["payload_sha256"] != payload_digest(text, kind, target, slot, payload_extra(data) or None):
        raise Reject(INVALID, ["payload_sha256_mismatch"])
    return data


def parse_entry_file(path: Any) -> dict[str, Any]:
    """Contenido validado de un archivo de entrada (en ``pending/`` o ``rejected/``), o ``Reject``."""

    raw = _read_regular(path)
    try:
        parsed = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        raise Reject(INVALID, ["json"]) from None
    return _validate(parsed)


def load_entry(store: Any, name: str) -> Entry | None:
    """Entrada válida, ``None`` si es un directorio o ya no está, o ``Reject`` con el motivo."""

    path = inbox_paths(store).pending / name
    state = kind_of_path(path)
    if state in ("dir", "gone"):
        return None
    if state == "unsafe":
        raise Reject(UNSAFE)
    data = parse_entry_file(path)
    return Entry(name=name, data=data, digest=digest_json(data))


def _lstat_evidence(info: os.stat_result) -> dict[str, Any]:
    """Metadatos de ``lstat`` de un inodo inseguro: tipo, modo, ``st_nlink`` y tamaño (nunca destino ni contenido)."""

    mode = info.st_mode
    kinds = (
        (stat.S_ISLNK, "symlink"), (stat.S_ISFIFO, "fifo"), (stat.S_ISSOCK, "socket"),
        (stat.S_ISCHR, "chardev"), (stat.S_ISBLK, "blockdev"), (stat.S_ISREG, "regular"),
    )
    return {
        "type": next((name for test, name in kinds if test(mode)), "other"),
        "mode": format(stat.S_IMODE(mode), "04o"),
        "st_nlink": info.st_nlink,
        "size": info.st_size,
    }


def reject_entry(store: Any, name: str, code: str, reason_codes: list[str] | None = None) -> str:
    """Rechaza ``pending/<name>`` con su motivo; devuelve el nombre final del rastro en ``rejected/``.

    Una entrada que es archivo regular con ``st_nlink == 1`` se mueve a ``rejected/`` (más su
    ``.reason``). Un inodo que no lo es (enlace, FIFO, socket, dispositivo, hardlink) **no** se
    mueve: ``export``, ``relocate`` y ``compact`` recorren ``rejected/`` y fallarían para
    siempre. Para esos se escribe sólo ``rejected/<nombre>.reason`` con el código y los
    metadatos de ``lstat`` (``lstat``: tipo, modo, ``st_nlink``, tamaño; nunca el destino de un
    enlace ni su contenido) y se borra el nombre de ``pending/`` con ``unlink`` (no sigue
    enlaces; un hardlink sólo pierde ese nombre).
    """

    paths: InboxPaths = inbox_paths(store)
    final = name
    counter = 0
    while os.path.lexists(paths.rejected / final) or os.path.lexists(paths.rejected / (final + REASON_SUFFIX)):
        counter += 1
        final = f"{name}.{counter}"
    reason: dict[str, Any] = {"code": code, "reason_codes": safe_codes(reason_codes or [])}
    try:
        info = os.lstat(paths.pending / name)
    except FileNotFoundError:
        info = None
    safe_inode = info is None or (stat.S_ISREG(info.st_mode) and info.st_nlink == 1)
    if not safe_inode:
        reason["lstat"] = _lstat_evidence(info)
    store._atomic_write(paths.rejected / (final + REASON_SUFFIX), canonical_json(reason))
    if safe_inode:
        try:
            os.replace(paths.pending / name, paths.rejected / final)
        except FileNotFoundError:
            pass
    else:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(paths.pending / name)
    fsync_directory(paths.rejected)
    fsync_directory(paths.pending)
    return final if safe_inode else final + REASON_SUFFIX


__all__ = [
    "Entry", "INVALID", "MAX_ENTRY_BYTES", "Reject", "UNSAFE", "age_key", "kind_of_path",
    "load_entry", "parse_entry_file", "reject_entry", "safe_codes",
]
