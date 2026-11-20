"""``directive``: una orden o preferencia del Operador, escrita por quien la recibió (ADR-0069 §2, §3, §5).

Dos mitades. La de escritura (:func:`check_entry`, :func:`check_target`) la usan el encolado y, otra vez, el
vaciado: los códigos salen en el orden del ADR y una entrada escrita a mano en ``pending/`` acaba en ``rejected/``
con el mismo código. La de lectura (:class:`DirectiveReader`) calcula el objeto ``directive`` con su ``status`` y su
``actionable``; leer no usa Git para las anclas ``conversation`` ni arranca ningún resolutor. Todo es dato no confiable.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from .anchors_conversation import ConversationVerifier
from .anchors_read import AnchorServer
from .audience import (
    Reader, ScopeError, instant, is_audience, is_subject, names_reader, normalize_valid_until, session_is_real,
)
from .disputes import _valid_disputes
from .identity_c0 import validate_envelope
from .store import STREAMS
from .vigency import is_active

KIND = "directive"
WRITER_ROLES = ("orquestador", "capitan")
INACTIVE = ("malformed", "revocation", "invalidated", "expired")
_NO_LIMIT = 10**9  # la vista de una directiva no comparte el tope --anchor-limit de la superficie que la sirve


def _conversation(anchors: Any) -> bool:
    return isinstance(anchors, list) and any(
        isinstance(a, Mapping) and isinstance(a.get("source"), Mapping) and a["source"].get("kind") == "conversation"
        for a in anchors
    )


def check_entry(data: Mapping[str, Any], *, now: Callable[[], datetime] | None = None) -> None:
    """Los rechazos de escritura de ADR-0069 §1–§3 para una entrada (o sus campos), en su orden; ``ScopeError`` el primero.

    ``now`` sólo lo pasa el encolado: ``directive_valid_until_past`` no se repite al vaciar (una entrada que esperó en
    la bandeja no se rechaza porque su vigencia corra).
    """

    kind = data["kind"]
    if kind != KIND:
        if any(key in data for key in ("valid_until", "until_revoked", "revokes")):
            raise ScopeError("remember_directive_field_not_allowed", "valid_until, until_revoked y revokes sólo valen en directive")
        _check_syntax(data)
        return
    envelope = data["envelope"]
    writer = envelope["writer"]
    if writer["agent"]["role"] not in WRITER_ROLES:
        raise ScopeError("directive_role_not_allowed", "una directive la escribe un orquestador o un capitán")
    if not session_is_real(writer["session"]["id"]):
        raise ScopeError("directive_session_missing", "define AN_KLA_SESSION_ID: la orden lleva la sesión de origen")
    for field, code in (("subject", "directive_missing_subject"), ("audience", "directive_missing_audience")):
        if field not in data:
            raise ScopeError(code, f"--{field} es obligatorio en una directive (--revoke lo hereda del destino)")
    _check_syntax(data)
    revokes = data.get("revokes") is True
    given = [key for key in ("valid_until", "until_revoked") if key in data]
    if revokes and given:
        raise ScopeError("directive_validity_conflict", "una revocación no lleva vigencia")
    if not revokes and not given:
        raise ScopeError("directive_validity_missing", "--valid-until o --until-revoked")
    if not revokes and len(given) == 2:
        raise ScopeError("directive_validity_conflict", "--valid-until y --until-revoked son excluyentes")
    stamp = normalize_valid_until(data["valid_until"]) if "valid_until" in data else None
    if not _conversation(data.get("anchors")):
        raise ScopeError("directive_anchor_missing", "al menos un ancla conversation (--anchor-file)")
    if stamp is not None and now is not None and instant(stamp) < now():
        raise ScopeError("directive_valid_until_past", "la vigencia ya pasó")


def _check_syntax(data: Mapping[str, Any]) -> None:
    if "subject" in data and not is_subject(data["subject"]):
        raise ScopeError("remember_subject_invalid", "un repo.id de C0 canónico")
    if "audience" in data and not is_audience(data["audience"]):
        raise ScopeError("remember_audience_invalid", "all, role:<papel> o agent:<nombre>")


def check_target(data: Mapping[str, Any], target: Mapping[str, Any]) -> None:
    """``directive_subject_mismatch`` y ``directive_audience_mismatch`` contra la directiva que se sustituye o revoca."""

    if data.get("subject") != target.get("subject"):
        raise ScopeError("directive_subject_mismatch", "el destino trata de otro proyecto")
    if data.get("revokes") is True and data.get("audience") != target.get("audience"):
        raise ScopeError("directive_audience_mismatch", "la revocación hereda el destinatario del destino")


def is_directive(row: Mapping[str, Any]) -> bool:
    envelope = row.get("an_kla_envelope")
    return isinstance(envelope, Mapping) and envelope.get("kind") == KIND


def form_problems(row: Mapping[str, Any]) -> list[str]:
    """Las invariantes de forma de §2 y §3 que el registro no cumple al leerlo (vacío = bien formada)."""

    envelope = row.get("an_kla_envelope")
    if not isinstance(envelope, dict) or validate_envelope(envelope):
        return ["envelope"]
    problems: list[str] = []
    writer = envelope["writer"]
    if writer["agent"]["role"] not in WRITER_ROLES:
        problems.append("role")
    if not session_is_real(writer["session"]["id"]):
        problems.append("session")
    if not is_subject(row.get("subject")):
        problems.append("subject")
    if not is_audience(row.get("audience")):
        problems.append("audience")
    revokes = row.get("revokes") is True
    if "revokes" in row and not revokes:
        problems.append("revokes")
    given = [key for key in ("valid_until", "until_revoked") if key in row]
    if "until_revoked" in row and row["until_revoked"] is not True:
        problems.append("until_revoked")
    if len(given) != (0 if revokes else 1):
        problems.append("validity")
    if "valid_until" in row:
        try:
            if normalize_valid_until(row["valid_until"]) != row["valid_until"]:
                problems.append("valid_until")  # lo guardado es el instante normalizado
        except ScopeError:
            problems.append("valid_until")
    anchors = row.get("anchors")
    shaped = isinstance(anchors, list) and all(
        isinstance(a, Mapping) and isinstance(a.get("source"), Mapping) and isinstance(a["source"].get("kind"), str)
        for a in anchors
    )
    if not shaped or not _conversation(anchors):
        problems.append("anchors")
    return problems


def dispute_counts(snapshot: Any) -> Counter[tuple[str, str]]:
    """Disputas vigentes por objetivo ``(stream, id)``, contadas como ``disputes list``."""

    count: Counter[tuple[str, str]] = Counter()
    for stream in STREAMS:
        for row in snapshot.records[stream]:
            disputes = row.get("disputes")
            if _valid_disputes(disputes) and is_active(row):
                count[(disputes["stream"], disputes["target_id"])] += 1
    return count


class DirectiveReader:
    """Calcula el objeto ``directive`` de los registros que una lectura sirve, con un solo reloj y una sola vista de anclas."""

    def __init__(
        self, store: Any, snapshot: Any, reader: Reader, *, clock: Callable[[], datetime] | None = None,
        verifier: ConversationVerifier | None = None,
    ) -> None:
        self.store, self.snapshot, self.reader, self.verifier = store, snapshot, reader, verifier
        self._clock = clock
        self._now: datetime | None = None
        self._server: AnchorServer | None = None
        self._disputes: Counter[tuple[str, str]] | None = None

    def now(self) -> datetime:
        if self._now is None:
            moment = self._clock() if self._clock is not None else datetime.now(timezone.utc)
            self._now = moment.astimezone(timezone.utc)
        return self._now

    def _anchors(self, stream: str, row: Mapping[str, Any]) -> dict[str, Any]:
        if self._server is None:
            self._server = AnchorServer(self.store, self.snapshot, _NO_LIMIT, verifier=self.verifier)
        return self._server.serve(stream, row)

    def close(self) -> None:
        if self._server is not None:
            self._server.__exit__(None, None, None)

    def _status(self, row: Mapping[str, Any], served: Mapping[str, Any] | None) -> str:
        if form_problems(row):
            return "malformed"
        if row.get("revokes") is True:
            return "revocation"
        views = [a for a in (served or {}).get("anchors", []) if a["anchor"]["kind"] == "conversation"]
        if any(a["freshness"] == "broken" for a in views):
            return "invalidated"
        if "valid_until" in row and instant(row["valid_until"]) < self.now():
            return "expired"
        return "verified" if views and all(a["freshness"] == "fresh" for a in views) else "unverified"

    def render(self, stream: str, row: Mapping[str, Any], *, freshness: bool = True) -> dict[str, Any]:
        """El objeto ``directive`` de §5. Con ``freshness=False`` (``list``) no se comprueban anclas que no sean de conversación."""

        malformed = bool(form_problems(row))
        served = None if malformed else self._anchors(stream, row) if freshness else self._conversation_view(stream, row)
        status = self._status(row, served)
        out: dict[str, Any] = {"status": status, "actionable": False}
        for key in ("subject", "audience"):
            if key in row and (is_subject(row[key]) if key == "subject" else is_audience(row[key])):
                out[key] = row[key]
        for key in ("valid_until", "until_revoked", "revokes"):
            if key in row and not malformed:
                out[key] = row[key]
        envelope = row.get("an_kla_envelope")
        if isinstance(envelope, dict) and not validate_envelope(envelope):
            writer = envelope["writer"]
            out["writer"] = {"name": writer["agent"]["name"], "role": writer["agent"]["role"]}
            out["session"] = writer["session"]["id"]
        if freshness and served and served.get("anchors_freshness"):
            out["anchor_freshness"] = served["anchors_freshness"]
        count = self.disputes().get((stream, str(row.get("id", ""))), 0)
        if count:
            out["disputed"] = count
        out["actionable"] = self._actionable(status, row, count)
        return out

    def _conversation_view(self, stream: str, row: Mapping[str, Any]) -> dict[str, Any]:
        """Sólo las anclas de conversación (``list`` no usa Git): la misma vista de resoluciones que ``serve``."""

        from .anchors_conversation import apply_resolution, check_conversation  # evita el ciclo en importación

        if self._server is None:
            self._server = AnchorServer(self.store, self.snapshot, _NO_LIMIT, verifier=self.verifier)
        views = []
        for index, anchor in enumerate(row["anchors"]):
            if anchor["source"]["kind"] != "conversation":
                continue
            view = apply_resolution(anchor, str(row.get("id", "")), index, self._server.notes)
            views.append({"anchor": {"kind": "conversation"}, **check_conversation(view, self.verifier)})
        return {"anchors": views}

    def disputes(self) -> Counter[tuple[str, str]]:
        if self._disputes is None:
            self._disputes = dispute_counts(self.snapshot)
        return self._disputes

    def _actionable(self, status: str, row: Mapping[str, Any], disputes: int) -> bool:
        if status not in ("unverified", "verified") or disputes:
            return False
        return (
            self.reader.project() == row["subject"]  # `subject` bien formado: `status` no es malformed
            and names_reader(row["audience"], self.reader)
        )


__all__ = [
    "INACTIVE", "KIND", "WRITER_ROLES", "DirectiveReader", "check_entry", "check_target", "dispute_counts",
    "form_problems", "is_directive",
]
