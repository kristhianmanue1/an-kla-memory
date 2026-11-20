"""Ámbito y destinatario de un recuerdo (ADR-0069 §1, §4): ``subject``, ``audience`` y quién lee.

Funciones puras y un lector perezoso. ``subject`` y ``audience`` son campos de primer nivel del registro, como
``slot``: ``record-envelope-v1`` y C0 no cambian. Un registro sin los campos nuevos **nunca** se filtra ni se marca.
El lector es la identidad C0 del entorno (``AN_KLA_AGENT_NAME`` y ``AN_KLA_AGENT_ROLE``); su proyecto sólo se
calcula (una llamada a ``git``) si algún registro leído trae un ``subject`` explícito, y si no se puede calcular
falla cerrado: todo registro con ``subject`` explícito es para otro.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from .identity_c0 import (
    ENV_NAME, ENV_ROLE, NAME_SENTINEL, NO_SESSION_SENTINEL, RESERVED_NAMES, ROLES, SLOT_PATTERN, UNKNOWN_SENTINEL,
    IdentityC0Error, is_canonical_repo_id, repo_id_for,
)

AUDIENCE_ALL = "all"
SCOPE_FIELDS = ("subject", "audience")
DIRECTIVE_FIELDS = ("valid_until", "until_revoked", "revokes")
ENTRY_SCOPE_KEYS = SCOPE_FIELDS + DIRECTIVE_FIELDS
_HASHED_ID = re.compile(r"(?:local|remoto):[0-9a-f]{16}")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_INSTANT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_AUDIENCE_NAME_BLOCKED = RESERVED_NAMES | {NAME_SENTINEL}


class ScopeError(ValueError):
    """Error estable de escritura de ámbito: ``str(error)`` es el código."""

    def __init__(self, code: str, hint: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.hint = hint


def is_subject(value: Any) -> bool:
    """Un ``repo.id`` de C0 en forma canónica (``host[:puerto]/ruta``, ``local:`` o ``remoto:`` + 16 hex)."""

    return isinstance(value, str) and (_HASHED_ID.fullmatch(value) is not None or is_canonical_repo_id(value))


def is_audience(value: Any) -> bool:
    """``all``, ``role:<papel de C0 distinto de desconocido>`` o ``agent:<nombre de C0 no reservado>``."""

    if not isinstance(value, str):
        return False
    if value == AUDIENCE_ALL:
        return True
    kind, _, rest = value.partition(":")
    if kind == "role":
        return rest in ROLES and rest != UNKNOWN_SENTINEL
    if kind == "agent":
        return SLOT_PATTERN.fullmatch(rest) is not None and rest not in _AUDIENCE_NAME_BLOCKED
    return False


def check_subject(value: Any) -> str:
    if not is_subject(value):
        raise ScopeError("remember_subject_invalid", "un repo.id de C0 canónico (host[:puerto]/ruta, local:|remoto:<16 hex>)")
    return value


def check_audience(value: Any) -> str:
    if not is_audience(value):
        raise ScopeError("remember_audience_invalid", "all, role:<papel> o agent:<nombre>")
    return value


def normalize_valid_until(value: Any) -> str:
    """El instante UTC en que acaba la vigencia: ``AAAA-MM-DD`` vale hasta el final de ese día; si no, el instante dado."""

    if isinstance(value, str) and _DATE.fullmatch(value):
        stamp = value + "T23:59:59Z"
    elif isinstance(value, str) and _INSTANT.fullmatch(value):
        stamp = value
    else:
        raise ScopeError("directive_valid_until_invalid", "AAAA-MM-DD o AAAA-MM-DDTHH:MM:SSZ")
    try:
        datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise ScopeError("directive_valid_until_invalid", "una fecha real") from None
    return stamp


def instant(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def scope_violation(record: Mapping[str, Any]) -> bool:
    """True si un registro de ``plan-write`` lleva ``kind: directive`` en su sobre o algún campo de ámbito (ADR-0069 §2)."""

    envelope = record.get("an_kla_envelope")
    return any(key in record for key in ENTRY_SCOPE_KEYS) or (
        isinstance(envelope, Mapping) and envelope.get("kind") == "directive"
    )


def has_scope(row: Mapping[str, Any]) -> bool:
    return "subject" in row or "audience" in row


def explicit_scope(row: Mapping[str, Any]) -> dict[str, Any]:
    """Los campos de ámbito explícitos del registro (``subject`` y ``audience`` que traiga)."""

    return {key: row[key] for key in SCOPE_FIELDS if key in row}


def scope_row_fields(data: Mapping[str, Any]) -> dict[str, Any]:
    """Campos de primer nivel que una entrada añade a su registro (la vigencia se normaliza; el original se conserva)."""

    fields = {key: data[key] for key in ("subject", "audience", "until_revoked", "revokes") if key in data}
    if "valid_until" in data:
        fields["valid_until"] = normalize_valid_until(data["valid_until"])
        fields["valid_until_input"] = data["valid_until"]
    return fields


class Reader:
    """Quien lee: nombre y papel de C0 del entorno y su proyecto (el del checkout o el declarado con ``--subject``)."""

    def __init__(
        self, name: str, role: str, *, project_root: Any = None, subject: str | None = None,
        include_other: bool = False, resolver: Callable[[Any], str] = repo_id_for,
    ) -> None:
        self.name, self.role = name, role
        self.include_other = include_other
        self._root, self._declared, self._resolver = project_root, subject, resolver
        self._computed = False
        self._project: str | None = subject

    @property
    def declared_subject(self) -> str | None:
        """El proyecto que el lector declaró con ``--subject``, si lo hizo."""

        return self._declared

    @property
    def anonymous(self) -> bool:
        return self.name == NAME_SENTINEL and self.role == UNKNOWN_SENTINEL

    def project(self) -> str | None:
        """El proyecto del lector; ``None`` si no se puede calcular. Una sola llamada a ``git``, y sólo si hace falta."""

        if self._declared is None and not self._computed:
            self._computed = True
            try:
                self._project = self._resolver(self._root) if self._root is not None else None
            except (IdentityC0Error, OSError, ValueError, TypeError):
                self._project = None
        return self._project


def reader_identity(env: Mapping[str, str] | None = None) -> tuple[str, str]:
    """``(nombre, papel)`` como al escribir; un valor ausente o fuera de C0 es el centinela (nunca se corrige)."""

    source = os.environ if env is None else env
    name = source.get(ENV_NAME, NAME_SENTINEL)
    role = source.get(ENV_ROLE, UNKNOWN_SENTINEL)
    if not (isinstance(name, str) and SLOT_PATTERN.fullmatch(name)) or name in RESERVED_NAMES:
        name = NAME_SENTINEL
    if role not in ROLES:
        role = UNKNOWN_SENTINEL
    return name, role


def make_reader(
    store: Any = None, *, subject: str | None = None, include_other: bool = False, env: Mapping[str, str] | None = None,
    resolver: Callable[[Any], str] = repo_id_for,
) -> Reader:
    name, role = reader_identity(env)
    return Reader(
        name, role, project_root=getattr(store, "project_root", None), subject=subject, include_other=include_other,
        resolver=resolver,
    )


def is_for_other(row: Mapping[str, Any], reader: Reader) -> bool:
    """True si el registro es para otro: ``subject`` explícito que no es el del lector, o ``audience`` que no lo nombra.

    Un registro sin ``subject`` ni ``audience`` explícitos es para el lector, siempre. Un valor explícito mal formado
    (un registro que no pasó por ``remember``) falla cerrado.
    """

    if "subject" in row:
        subject = row["subject"]
        if not is_subject(subject) or reader.project() != subject:
            return True
    if "audience" in row:
        audience = row["audience"]
        if not is_audience(audience):
            return True
        return not _names_reader(audience, reader, explicit_all=True)
    return False


def _names_reader(audience: str, reader: Reader, *, explicit_all: bool) -> bool:
    if audience == AUDIENCE_ALL:
        return explicit_all
    kind, _, rest = audience.partition(":")
    if kind == "role":
        return reader.role != UNKNOWN_SENTINEL and rest == reader.role
    return reader.name != NAME_SENTINEL and rest == reader.name


def names_reader(audience: Any, reader: Reader) -> bool:
    """La condición 3 de ``actionable``: ``agent:<su nombre>`` o ``role:<su papel>``; ``all`` no basta."""

    return is_audience(audience) and audience != AUDIENCE_ALL and _names_reader(audience, reader, explicit_all=False)


def session_is_real(session_id: Any) -> bool:
    """La sesión de origen real: ``<cli>:<id>`` con ``<id>`` distinto de ``sin-sesion``."""

    if not isinstance(session_id, str) or ":" not in session_id:
        return False
    return session_id.split(":", 1)[1] != NO_SESSION_SENTINEL


__all__ = [
    "AUDIENCE_ALL", "DIRECTIVE_FIELDS", "ENTRY_SCOPE_KEYS", "SCOPE_FIELDS", "Reader", "ScopeError", "check_audience",
    "check_subject", "explicit_scope", "has_scope", "instant", "is_audience", "is_for_other", "is_subject", "make_reader",
    "names_reader", "normalize_valid_until", "reader_identity", "scope_row_fields", "scope_violation", "session_is_real",
]
