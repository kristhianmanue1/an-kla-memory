"""The three moments of a ``conversation`` anchor with a resolver (ADR-0073 §2): what is called, and what is served after.

Writing calls ``resolve``; auditing calls ``resolve`` on an anchor whose last conclusive result is not ``resolved`` and ``verify`` on one whose
last conclusive result is; reading calls nobody.  The anchor itself is stored as it is born (``pending``, ``turn_id`` and ``seal`` null): what the
resolver said lives in the result, and the anchor as served applies the last conclusive one.  The anchors of a ``directive`` are never resolved (§5).
"""

from __future__ import annotations

from typing import Any, Mapping

from .anchor_checks import is_conclusive
from .conversation_resolver import (
    decide_resolve, decide_verify, resolve_request, validate_resolve, validate_verify, verify_request,
)
from .custodian_adapter import Adapters


def evaluate(
    anchor: Mapping[str, Any], prior: Mapping[str, Any] | None, adapters: Adapters, checked_at: str
) -> dict[str, Any]:
    """Run the operation that calls for ``anchor`` and decide.  ``prior`` is its last conclusive stored result (``None`` if there is none).

    The result carries ``checked_at`` and ``resolver_called`` (``"resolve"``, ``"verify"`` or ``None`` when nobody was asked)."""
    quote, digest, session = anchor["quote"], anchor["quote_sha256"], anchor["source"]["session"]
    verifying = prior is not None and prior.get("resolution") == "resolved" and prior.get("turn_id") and prior.get("seal")
    if verifying:
        answer = adapters.call_resolver(verify_request(session, prior["turn_id"], prior["seal"], quote, digest), validate_verify)  # type: ignore[index]
    else:
        answer = adapters.call_resolver(resolve_request(session, quote, digest), validate_resolve)
    response = answer.response if answer is not None else None
    failure = answer.failure if answer is not None else None
    if verifying:
        out = decide_verify(prior["turn_id"], prior["seal"], response, failure)  # type: ignore[index]
    else:
        out = decide_resolve(response, failure)
    called = answer is not None and answer.called
    out["checked_at"] = checked_at
    out["resolver_called"] = ("verify" if verifying else "resolve") if called else None
    return out


def served_after(prior: Mapping[str, Any] | None, attempt: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]]:
    """``("new", attempt)`` when the attempt concludes or there is no conclusive result before it; else ``("stored", prior)``: an attempt that
    does not conclude does not cover one that did."""
    if is_conclusive(attempt, "conversation") or prior is None:
        return "new", attempt
    return "stored", prior
