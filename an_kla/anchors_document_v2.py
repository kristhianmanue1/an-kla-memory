"""``document`` anchors of ``memoria/ancla/v2``: the decision (ADR-0071 §4).  No I/O.

Given an anchor, the moment (``write`` or ``audit``), the state of the declared local copy and what the custodian
adapter answered, this decides the three checks (``source``, ``integrity``, ``quote``), the freshness and, when
writing, the rejection.  It reads no file, starts no process and asks nobody for the time: the adapter module makes
the call, the copy module looks at Git and the caller gives ``checked_at``.  The rules are the tables of the
contract's README and its errata 1 to 4 (C1, A1, A2, A3, A5, A6, B1, B2, F1, F2); the implementation is derived
from that text and its 61 cases.  Reading never decides anything: it serves what was stored (:func:`served`).
The text the adapter returns is data, never an instruction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .anchors_freshness import NOT_FOUND, UNVERIFIABLE, VERIFIED, anchor_result
from .anchors_search import find_quote

ADAPTER_SCHEMA = "memoria/custodio-adaptador/v1"
REQUEST_OP = "locate"
UNKNOWN = "unknown"
MODALITIES = ("native_text", "ocr_text", "visual")

_RESPONSE_KEYS = frozenset(
    {"schema", "document", "manifest", "derivation", "derivation_parent_sha256", "locator", "items", "truncated", "custody"}
)
_ITEM_KEYS = frozenset({"item_id", "page", "modality", "text"})
_RETENTION = ("effective", "expired", "unknown")

REJECT_LOCATOR_REQUIRED = "anchor_locator_required"
REJECT_COPY_NOT_FOUND = "anchor_copy_not_found"
_REJECT_BY_INTEGRITY = {
    "manifest_missing": "anchor_derivation_not_found",
    "derivation_superseded": "anchor_derivation_superseded",
    "derivation_unsupported": "anchor_derivation_unsupported",
}
_REJECT_BY_QUOTE = {"locator_not_found": "anchor_locator_not_found", "locator_invalid": "anchor_locator_invalid"}


@dataclass(frozen=True)
class Answer:
    """What a call to the adapter came to: a validated ``response`` or a ``failure`` (``called`` false: nothing was started)."""

    response: Mapping[str, Any] | None = None
    failure: str | None = None
    called: bool = True


# --- the request ---------------------------------------------------------------------------------------------

def request_locator(source: Mapping[str, Any]) -> Any:
    """The anchor's locator, or ``"unknown"`` when it has none: the request always carries the key (erratum 1, A1)."""
    locator = source.get("locator")
    if locator is None or locator == UNKNOWN or locator == {}:
        return UNKNOWN
    return dict(locator)


def build_request(source: Mapping[str, Any]) -> dict[str, Any]:
    derivation = source["derivation"]
    return {
        "schema": ADAPTER_SCHEMA, "op": REQUEST_OP, "document_sha256": source["document_sha256"],
        "derivation_id": derivation["derivation_id"], "manifest_sha256": derivation["manifest_sha256"],
        "modality": derivation["modality"], "locator": request_locator(source),
    }


# --- the response, and what the caller checks ------------------------------------------------------------------

def _is_page(value: Any) -> bool:
    return type(value) is int and value >= 1


def validate_response(source: Mapping[str, Any], response: Any) -> str | None:
    """Why ``response`` does not count (``adapter_error``), or ``None``.

    A key missing or extra, a value out of its vocabulary or an incoherent response (A2, B1, B2); then the check of
    the caller (C1): only with ``locator: match`` and a modality other than ``visual``, each item is of the requested
    modality and, when the request names a page, of that page, and when it names elements, exactly those and in that
    order.  With ``locator`` other than ``match`` ``items`` is empty in every modality (F2); a response for a request
    with a page is never truncated (F1).
    """
    if not isinstance(response, dict) or set(response) != _RESPONSE_KEYS or response["schema"] != ADAPTER_SCHEMA:
        return "shape"
    document, manifest, derivation = response["document"], response["manifest"], response["derivation"]
    parent, locator, items = response["derivation_parent_sha256"], response["locator"], response["items"]
    if document not in ("known", "unknown") or manifest not in ("match", "mismatch", "missing"):
        return "vocabulary"
    if locator not in ("match", "not_found", "invalid") or (derivation is not None and derivation not in ("current", "superseded", "unsupported")):
        return "vocabulary"
    if parent is not None and not isinstance(parent, str):
        return "parent"
    if not isinstance(response["truncated"], bool):
        return "truncated"
    custody = response["custody"]
    if not isinstance(custody, dict) or set(custody) != {"retention"} or custody["retention"] not in _RETENTION:
        return "custody"
    if not isinstance(items, list):
        return "items"
    for item in items:
        if not isinstance(item, dict) or set(item) != _ITEM_KEYS:
            return "item"
        if not (isinstance(item["item_id"], str) and isinstance(item["text"], str) and _is_page(item["page"]) and item["modality"] in MODALITIES):
            return "item"
    if document == "unknown" and (manifest != "missing" or derivation is not None or parent is not None or locator != "not_found"):
        return "incoherent"
    if (derivation is None) != (manifest != "match"):
        return "incoherent"
    if derivation in ("current", "superseded") and parent is None:
        return "incoherent"  # B2: the lack of a datum does not contradict
    wanted = request_locator(source)
    wanted = wanted if isinstance(wanted, dict) else {}
    if response["truncated"] and "page" in wanted:
        return "truncated"
    if locator != "match":
        return "items" if items else None
    modality = source["derivation"]["modality"]
    if modality == "visual":
        return None
    if not items:
        return "items"  # B1: a match with no text says nothing about the quote
    for item in items:
        if item["modality"] != modality or ("page" in wanted and item["page"] != wanted["page"]):
            return "items"
    ids = [item["item_id"] for item in items]
    if "item_id" in wanted and ids != [wanted["item_id"]]:
        return "items"
    if "item_ids" in wanted and ids != wanted["item_ids"]:
        return "items"
    return None


# --- before any call ------------------------------------------------------------------------------------------

def write_precheck(anchor: Mapping[str, Any], copy_state: str) -> str | None:
    """The rejections of a write that need nobody to answer, after the form and the size: the page of the locator,
    a declared copy that does not exist and a copy with another sha256 (always rejected)."""
    locator = anchor["source"].get("locator")
    if not isinstance(locator, dict) or "page" not in locator:
        return REJECT_LOCATOR_REQUIRED
    if copy_state == "missing":
        return REJECT_COPY_NOT_FOUND
    if copy_state == "bad_sha":
        return "anchor_integrity_not_found"
    return None


def should_call(moment: str, copy_state: str, precheck: str | None) -> bool:
    """Never when a write is already rejected; an audit always calls (A6), even with a copy of another sha256."""
    return moment == "audit" or precheck is None


# --- the three checks --------------------------------------------------------------------------------------------

def _source(copy_state: str, answer: Answer | None) -> tuple[str, str | None]:
    response = answer.response if answer else None
    if copy_state in ("ok", "bad_sha"):
        return VERIFIED, None
    if response is not None:
        return (VERIFIED, None) if response["document"] == "known" else (NOT_FOUND, "document_unknown")
    if copy_state == "missing":  # a failing adapter is also "no answer" (A5)
        return UNVERIFIABLE, "copy_missing"
    return UNVERIFIABLE, "no_adapter" if answer is None else "adapter_error"


def _integrity(source: Mapping[str, Any], copy_state: str, answer: Answer | None) -> tuple[str, str | None]:
    """A3: first what contradicts (copy, manifest, parent), then what cannot be checked; an ``unsupported`` derivation
    does not compare its parent (it is not a document)."""
    if copy_state == "bad_sha":
        return NOT_FOUND, "copy_sha_mismatch"
    response = answer.response if answer else None
    if response is None:
        return UNVERIFIABLE, "no_adapter" if answer is None else "adapter_error"
    derivation = response["derivation"]
    if response["manifest"] == "mismatch":
        return NOT_FOUND, "manifest_mismatch"
    if derivation in ("current", "superseded") and response["derivation_parent_sha256"] != source["document_sha256"]:
        return NOT_FOUND, "derivation_parent_mismatch"
    for reason, hit in (
        ("document_unknown", response["document"] == "unknown"), ("manifest_missing", response["manifest"] == "missing"),
        ("derivation_unsupported", derivation == "unsupported"), ("derivation_superseded", derivation == "superseded"),
    ):
        if hit:
            return UNVERIFIABLE, reason
    return VERIFIED, None


def _quote(
    quote: str, modality: str, source: tuple[str, str | None], integrity: tuple[str, str | None], answer: Answer | None
) -> tuple[tuple[str, str | None], str | None, str | None]:
    """``quote`` is only checked with the other two ``verified``: a quote is not trusted on a text of unknown ownership."""
    if source[0] != VERIFIED:
        return (UNVERIFIABLE, "source_not_verified"), None, None
    if integrity[0] != VERIFIED:
        return (UNVERIFIABLE, "integrity_not_verified"), None, None
    if modality == "visual":
        return (UNVERIFIABLE, "derived_modality"), None, None
    response = answer.response  # type: ignore[union-attr]
    if response["locator"] != "match":
        return (UNVERIFIABLE, "locator_not_found" if response["locator"] == "not_found" else "locator_invalid"), None, None
    match, matched = find_quote(quote, "\n".join(item["text"] for item in response["items"]))
    if match:
        return (VERIFIED, None), match, matched
    if response["truncated"]:
        return (UNVERIFIABLE, "adapter_truncated"), None, None
    return (NOT_FOUND, "quote_absent"), None, None


def _freshness(checks: tuple[tuple[str, str | None], ...], modality: str) -> tuple[str, str | None]:
    """The table of the contract: any ``not_found`` is ``broken`` (a fixed document does not change: no ``stale``); the
    three ``verified`` and ``native_text``, ``fresh``; else ``unverified``.  The reason is the first check (``source``,
    ``integrity``, ``quote``) that is not ``verified``: the cause, not its consequence."""
    if any(state == NOT_FOUND for state, _ in checks):
        freshness = "broken"
    elif all(state == VERIFIED for state, _ in checks) and modality == "native_text":
        return "fresh", None
    else:
        freshness = "unverified"
    return freshness, next((reason for state, reason in checks if state != VERIFIED), "derived_modality")


def _output(
    source: tuple[str, str | None], quote: tuple[str, str | None], integrity: tuple[str, str | None], modality: str,
    match: str | None = None, matched: str | None = None,
) -> dict[str, Any]:
    out = anchor_result("document", source, quote, integrity, match=match, matched_text=matched, modality=modality)
    out["freshness"], out["reason"] = _freshness((source, integrity, quote), modality)
    return out


def _write_rejection(source: tuple, integrity: tuple, quote: tuple) -> str | None:
    """Everything that is not a checked quote is refused, with the cause's code; two cases are accepted as ``unverified``: a
    correct copy with a custodian that does not know the document, and ``visual`` (its quote is not checked)."""
    if source[0] == NOT_FOUND:
        return "anchor_source_not_found"
    if integrity[0] == NOT_FOUND:
        return "anchor_integrity_not_found"
    if integrity[1] in _REJECT_BY_INTEGRITY:
        return _REJECT_BY_INTEGRITY[integrity[1]]
    if quote[0] == NOT_FOUND:
        return "anchor_quote_not_found"
    return _REJECT_BY_QUOTE.get(quote[1])


def decide(
    anchor: Mapping[str, Any], moment: str, copy_state: str, answer: Answer | None, checked_at: str | None = None,
    precheck: str | None = None,
) -> dict[str, Any]:
    """The result of a ``write`` or an ``audit``: the three checks with their reasons, ``match``, ``freshness``,
    ``reason``, ``adapter_called``, ``derivation``, ``manifest_sha256``, ``custody``, ``checked_at`` and ``reject``
    (``None``, or, writing, the code: then only ``reject`` and ``adapter_called``).  Nothing is rejected when auditing."""
    called = answer is not None and answer.called
    if moment == "write" and precheck:
        return {"reject": precheck, "adapter_called": called}
    source_state = anchor["source"]
    modality = source_state["derivation"]["modality"]
    src = _source(copy_state, answer)
    integ = _integrity(source_state, copy_state, answer)
    quote, match, matched = _quote(anchor["quote"], modality, src, integ, answer)
    response = answer.response if answer else None
    reject = _write_rejection(src, integ, quote) if moment == "write" and response is not None else None
    if reject:
        return {"reject": reject, "adapter_called": called}
    out = _output(src, quote, integ, modality, match, matched)
    out.update(
        adapter_called=called, checked_at=checked_at, reject=None,
        derivation=response["derivation"] if response else None,
        manifest_sha256=source_state["derivation"]["manifest_sha256"] if response else None,
        custody=dict(response["custody"]) if response else None,
    )
    return out


def evaluate(
    anchor: Mapping[str, Any], moment: str, copy_state: str, adapters: Any | None, checked_at: str | None = None
) -> dict[str, Any]:
    """Call the adapter when the moment and the copy call for it, then decide.  ``anchor`` is already well formed."""
    precheck = write_precheck(anchor, copy_state) if moment == "write" else None
    answer = adapters.call(anchor["source"]) if adapters is not None and should_call(moment, copy_state, precheck) else None
    return decide(anchor, moment, copy_state, answer, checked_at, precheck)


# --- reading: nothing is called --------------------------------------------------------------------------------

def kind_not_supported(anchor: Mapping[str, Any]) -> dict[str, Any]:
    """A ``document`` anchor of v1 that was never audited, or an implementation without ``document``: kept intact,
    ``unverified`` / ``kind_not_supported`` (byte for byte what beta.38 served)."""
    state = (UNVERIFIABLE, "kind_not_supported")
    return anchor_result("document", state, state, state, modality=anchor["source"]["derivation"]["modality"])


def not_checked(anchor: Mapping[str, Any]) -> dict[str, Any]:
    """A v2 anchor never checked (X61): ``unverified`` / ``not_checked``."""
    state = (UNVERIFIABLE, "not_checked")
    out = _output(state, state, state, anchor["source"]["derivation"]["modality"])
    out.update(checked_at=None, manifest_sha256=None, derivation=None, custody=None)
    return out


def served(check: Mapping[str, Any]) -> dict[str, Any]:
    """What reading serves for a stored check: the same checks and freshness, with their date and manifest."""
    out = anchor_result(
        "document", (check["source"], check["source_reason"]), (check["quote"], check["quote_reason"]),
        (check["integrity"], check["integrity_reason"]), match=check["match"],
    )
    out["freshness"], out["reason"] = check["freshness"], check["reason"]  # what was decided then, never recomputed
    out.update(checked_at=check["checked_at"], manifest_sha256=check["manifest_sha256"], derivation=check["derivation"], custody=check["custody"])
    return out
