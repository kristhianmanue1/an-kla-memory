"""``remember``: guardar un recuerdo en una invocación (ADR-0063 D1 «Orden», D2, D3).

Encola con :func:`an_kla.inbox.enqueue` (la identidad C0 y la hora las pone la herramienta; el
único dato obligatorio es el texto) y vacía como máximo un lote, que incluye su propia entrada
(:func:`an_kla.inbox_drain.drain` con ``include_entry`` y ``max_batches=1``). La respuesta
(``remember-result-v1``) cubre todos los desenlaces de la tabla del ADR:

======================================  ==============================================
Desenlace de su entrada                 ``state``
======================================  ==============================================
comprometida                            ``committed`` y ``revision``
rechazada                               ``rejected``, ``code`` y ``reason_codes``
``write_lock`` ocupado                  ``queued``
vaciado abortado, resultado conocido    ``queued`` + ``drain_error``
resultado desconocido                   ``queued`` + ``outcome: "unknown"``
======================================  ==============================================

Reintentar es idempotente (misma clave, mismo id): tras ``queued`` nunca duplica. Ningún error
sale como ``OSError`` crudo ni con rutas: cada uno lleva un código estable y una pista.
"""

from __future__ import annotations

import hashlib
import re
import sys
from typing import Any, BinaryIO, Mapping

from .identity import IdentityError
from .identity_c0 import IdentityC0Error
from .inbox import MAX_TEXT_BYTES, InboxError, enqueue
from .inbox_drain import DEFAULT_BUDGET_SECONDS, drain, error_code
from .reader_gate import ReaderGateError
from .store_errors import StoreError
from .transaction_attempts import TransactionError

RESULT_SCHEMA = "an-kla/remember-result-v1"
KEY_MAX_CHARS = 256
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_STORAGE_HINT = "la escritura falló en disco; no se perdió nada confirmado: reintenta (es idempotente)"
_IDENTITY_HINTS = {
    "identity_env_missing": "define AN_KLA_AGENT_CLI en el lanzador (obligatorio); ver «Primer consumidor» en el ADR-0063 D2",
    "identity_env_invalid": "un valor de AN_KLA_AGENT_* o de la rama viola C0; nunca se corrige ni se sustituye",
    "identity_repo_unavailable": "remember exige un repo Git en --project-root; sin Git usa la receta plan-write",
}
# Fallos de la fase de vaciado de `remember` que no deshacen el encolado: `queued` + `drain_error`.
_DRAIN_ERRORS = (StoreError, IdentityError, TransactionError, ReaderGateError, InboxError, OSError)


class RememberError(ValueError):
    """Error estable de ``remember``; ``str(error)`` es el código y ``detail`` la pista (el CLI la imprime)."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


def normalize_idempotency_key(value: str) -> str:
    """La clave dada: texto libre de 1 a 256 caracteres. ``sha256:<64 hex>`` se usa tal cual; el resto, hasheado."""

    if not isinstance(value, str) or not 0 < len(value) <= KEY_MAX_CHARS:
        raise RememberError("remember_idempotency_key_invalid", f"de 1 a {KEY_MAX_CHARS} caracteres")
    if _DIGEST.fullmatch(value):
        return value
    try:
        data = value.encode("utf-8")
    except UnicodeEncodeError:
        raise RememberError("remember_idempotency_key_invalid", "no es UTF-8 válido") from None
    return "sha256:" + hashlib.sha256(data).hexdigest()


def read_text_file(path: str, stdin: BinaryIO | None = None) -> str:
    """Texto de ``--text-file`` (``-`` = stdin), en UTF-8 estricto y con el tope del ADR (sin rutas en los errores)."""

    try:
        if path == "-":
            raw = (stdin if stdin is not None else sys.stdin.buffer).read(MAX_TEXT_BYTES + 1)
        else:
            with open(path, "rb") as handle:
                raw = handle.read(MAX_TEXT_BYTES + 1)
    except OSError:
        raise RememberError("remember_text_file_unreadable", "no se pudo leer el archivo de texto") from None
    if len(raw) > MAX_TEXT_BYTES:
        raise RememberError("inbox_text_too_large", f"máximo {MAX_TEXT_BYTES} bytes UTF-8")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise RememberError("remember_text_invalid", "el texto no es UTF-8 válido") from None


def _enqueue(
    store: Any, text: str, kind: str | None, target_id: str | None, key: str | None, env: Mapping[str, str] | None
) -> dict[str, Any]:
    try:
        return enqueue(store, text, kind=kind, target_id=target_id, idempotency_key=key, env=env)
    except IdentityC0Error as exc:
        field = f" ({exc.field})" if exc.field else ""
        raise RememberError(exc.code, _IDENTITY_HINTS.get(exc.code, "identidad C0 inválida") + field) from None
    except OSError:
        raise RememberError("storage_io_failed", _STORAGE_HINT) from None


def _drain(store: Any, name: str) -> dict[str, Any]:
    """Un lote con la entrada propia dentro; un fallo del vaciado nunca borra el encolado."""

    try:
        return drain(store, include_entry=name, max_batches=1, budget_seconds=DEFAULT_BUDGET_SECONDS)
    except _DRAIN_ERRORS as exc:
        return {"state": "aborted", "outcome": "known", "drain_error": error_code(exc), "warnings": [],
                "committed": {"entries": []}, "rejected": {"entries": []}, "already_committed": {"entries": []},
                "duplicates_removed": {"names": []}}


def _find(items: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((item for item in items if item.get("entry") == name), None)


def _result(queued: dict[str, Any], report: dict[str, Any], pending_resolution: bool) -> dict[str, Any]:
    name = queued["entry"]
    result: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "untrusted_memory_data": True,
        "entry": name,
        "kind": queued["kind"],
        "idempotency_key": queued["idempotency_key"],
        "enqueued_at": queued["enqueued_at"],
        "outcome": report.get("outcome", "known"),
        "warnings": list(report.get("warnings", [])),
    }
    if "record_id" in queued:
        result["record_id"] = queued["record_id"]
    rejections = report["rejected"]["entries"]
    result["rejected"] = {"count": len(rejections), "entries": rejections}
    committed = _find(report["committed"]["entries"], name)
    rejected = _find(rejections, name)
    twin = name in report["duplicates_removed"]["names"]
    already = _find(report["already_committed"]["entries"], name)
    if committed is not None:
        result.update(
            state="committed", record_id=committed["record_id"], revision=committed["revision"],
            stream=committed["stream"], operation=committed["operation"],
        )
        for field in ("disputed", "superseded"):
            if field in committed:
                result[field] = committed[field]
    elif rejected is not None:
        result.update(state="rejected", code=rejected["code"], reason_codes=rejected["reason_codes"])
    elif already is not None or twin:
        # Un reintento: otra entrada con la misma clave ya está (o acaba de quedar) comprometida.
        result.update(state="committed", already_committed=True)
        suffix = "-r-" + queued["idempotency_key"][len("sha256:"):][:24]
        sibling = next((c for c in report["committed"]["entries"] if c["record_id"].endswith(suffix)), None)
        if already is not None:
            result["record_id"] = already["record_id"]
        if sibling is not None:
            result.update(record_id=sibling["record_id"], revision=sibling["revision"])
    else:
        result["state"] = "queued"
        if report.get("drain_error"):
            result["drain_error"] = report["drain_error"]
        if pending_resolution:
            result["resolution"] = "pending"  # D3: la resolución propia/ajena ocurre al vaciar
    return result


def remember(
    store: Any,
    text: str,
    *,
    kind: str | None = None,
    supersedes: str | None = None,
    idempotency_key: str | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Guarda ``text`` y devuelve ``remember-result-v1``. Los errores previos al encolado salen como ``RememberError``
    (o con el código de la bandeja, la custodia o la identidad): en ellos no queda ninguna entrada."""

    key = None if idempotency_key is None else normalize_idempotency_key(idempotency_key)
    queued = _enqueue(store, text, kind, supersedes, key, env)
    report = _drain(store, queued["entry"])
    result = _result(queued, report, supersedes is not None)
    return result


__all__ = ["RESULT_SCHEMA", "RememberError", "normalize_idempotency_key", "read_text_file", "remember"]
