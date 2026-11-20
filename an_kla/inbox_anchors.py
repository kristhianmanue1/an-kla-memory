"""Anchors on the way into the inbox (ADR-0066 §1, §2): checking at enqueue, the entry fields, the record fields.

The three checks run **once**, in ``remember``, outside every lock: it is when the agent has the
source in hand.  The drain never reads Git again; it writes the anchors as they arrived (its
``write_check`` stays in the entry and never reaches the record).  Everything here is data, never
an instruction.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .anchors import (
    MAX_ANCHORS, ANCHOR_SCHEMA, AnchorRejected, normalize_quote, source_identity, validate_anchor,
)
from .anchors_conversation import check_conversation
from .audience import ENTRY_SCOPE_KEYS
from .anchors_coverage import coverage as compute_coverage
from .anchors_document import check_document
from .anchors_git import GitRepo
from .anchors_repo_file import ReadContext, verify_repo_file, write_rejection
from .canonical import digest_json

ENTRY_SCHEMA_V3 = "an-kla/inbox-entry-v3"  # v2 plus ``anchors``, ``verdict`` and ``operation``
OPERATIONS = ("remember", "dispute", "anchor_resolution")
VERDICTS = ("contradicted", "insufficient")  # `supported` and `not_reviewed` stay in agora's ledger (A6)
ANCHOR_INPUT_INVALID = "anchor_input_invalid"


@dataclass(frozen=True)
class Prepared:
    """Anchors ready to queue (each with its ``write_check``) and the coverage of the text against them."""

    anchors: list[dict[str, Any]]
    fields: dict[str, Any]


def strip_check(anchor: Mapping[str, Any]) -> dict[str, Any]:
    """The anchor as stored in the record: ``write_check`` never gets there."""
    return {key: copy.deepcopy(value) for key, value in anchor.items() if key != "write_check"}


def stored_anchors(anchors: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    return [strip_check(anchor) for anchor in anchors or []]


def anchors_digest(anchors: Sequence[Mapping[str, Any]] | None) -> str | None:
    """Canonical digest of the list, for ``payload_sha256``; ``None`` when there are no anchors."""
    return digest_json(stored_anchors(anchors)) if anchors else None


def key_extra(anchors: Sequence[Mapping[str, Any]] | None, verdict: str | None) -> dict[str, Any] | None:
    """What joins the derived idempotency key: each anchor's source and ``quote_sha256``, in order."""
    extra: dict[str, Any] = {}
    if anchors:
        extra["anchors"] = [[source_identity(a), a["quote_sha256"]] for a in anchors]
    if verdict is not None:
        extra["verdict"] = verdict
    return extra or None


def coverage_fields(text: str, anchors: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    """``coverage``, ``missing``, ``missing_total`` against the stored ``quote`` (never ``matched_text``, A3)."""
    if not anchors:
        return {}
    return compute_coverage(text, [a["quote"] for a in anchors])


def record_fields(data: Mapping[str, Any]) -> dict[str, Any]:
    """The top-level fields an entry adds to its record: anchors, coverage, and a dispute's verdict."""
    fields: dict[str, Any] = {}
    anchors = stored_anchors(data.get("anchors"))
    if anchors:
        fields["anchors"] = anchors
        fields.update(coverage_fields(data["text"], anchors))
    if data.get("verdict") is not None:
        fields["verdict"] = data["verdict"]
    return fields


def fill_anchor(
    raw: Mapping[str, Any], repo_id: str, session_id: str, record_type: str, head: Callable[[], str | None] = lambda: None
) -> dict[str, Any]:
    """What the tool fills in: ``repo`` and ``session`` (from C0), a pending conversation, a normalised quote.

    ``commit: "HEAD"`` (the shortcut's default) is the current ``HEAD`` for a ``fact`` or ``decision`` and
    ``null`` for a ``state``.

    A quote that arrives with its ``quote_sha256`` is *already stored*: it is not normalised here, so a
    stored quote that is not NFC or has edge white space is rejected (erratum 3.9).
    """
    if not isinstance(raw, Mapping) or not isinstance(raw.get("source"), Mapping):
        raise AnchorRejected("anchor_schema_invalid")
    anchor = copy.deepcopy(dict(raw))
    anchor.setdefault("schema", ANCHOR_SCHEMA)
    source = anchor["source"]
    if source.get("kind") == "repo-file":
        source["repo"] = repo_id
        if source.get("commit") == "HEAD":
            source["commit"] = None if record_type == "state" else head()
        if record_type == "state":
            source.setdefault("commit", None)
    elif source.get("kind") == "conversation":
        source.update(session=session_id, resolution="pending", turn_id=None, seal=None)
    if isinstance(anchor.get("quote"), str) and "quote_sha256" not in anchor:
        anchor["quote"] = normalize_quote(anchor["quote"])
    return anchor


def _check(repo: GitRepo, anchor: Mapping[str, Any], record_type: str) -> dict[str, Any]:
    kind = anchor["source"]["kind"]
    if kind == "repo-file":
        return verify_repo_file(repo, anchor, record_type, "write", ReadContext())
    if kind == "conversation":
        return check_conversation(anchor, None)
    return check_document(anchor)


def prepare(
    project_root: Any,
    raw_anchors: Sequence[Mapping[str, Any]],
    record_type: str,
    text: str,
    repo_id: str,
    session_id: str,
) -> Prepared:
    """Validate and check every anchor, in C3's order; raises :class:`AnchorRejected` for the first refusal.

    The count first (``anchor_too_many``), then anchor by anchor: shape, not normalised, size, path,
    ``source`` / ``quote`` / ``integrity`` ``not_found``.  A record refused for any of them is never queued.
    """
    if len(raw_anchors) > MAX_ANCHORS:
        raise AnchorRejected("anchor_too_many")
    stored: list[dict[str, Any]] = []
    with GitRepo(project_root) as repo:
        for index, raw in enumerate(raw_anchors):
            try:
                anchor = validate_anchor(fill_anchor(raw, repo_id, session_id, record_type, repo.head), record_type, index)
                result = _check(repo, anchor, record_type)
                code = write_rejection(result)
            except AnchorRejected as rejected:
                raise AnchorRejected(rejected.code, index) from None
            if code:
                raise AnchorRejected(code, index)
            stored.append({**anchor, "write_check": result})
    return Prepared(stored, coverage_fields(text, stored))


@dataclass(frozen=True)
class Extras:
    """What an anchored, disputed or annotating entry adds to a plain one (ADR-0066 §1)."""

    fields: dict[str, Any]  # entry keys: anchors, verdict, operation, anchor_resolution
    key: dict[str, Any] | None  # joins the derived idempotency key
    digest: dict[str, Any]  # joins ``payload_sha256``
    result: dict[str, Any]  # what ``remember`` answers beyond a plain write


def payload_extra(data: Mapping[str, Any]) -> dict[str, Any]:
    """The part of ``payload_sha256`` that anchors, verdict and operation contribute (nothing for a plain entry)."""
    extra: dict[str, Any] = {}
    if data.get("anchors"):
        extra["anchors"] = anchors_digest(data["anchors"])
    if data.get("verdict") is not None:
        extra["verdict"] = data["verdict"]
    operation = data.get("operation", "remember")
    if operation != "remember":
        extra["operation"] = operation
    if data.get("anchor_resolution") is not None:
        extra["anchor_resolution"] = digest_json(data["anchor_resolution"])
    extra.update(scope_extra(data))  # ADR-0069 §1: the same text for two projects or two addressees is two intentions
    return extra


def scope_extra(data: Mapping[str, Any]) -> dict[str, Any]:
    """The scope and directive fields an entry carries (``subject``, ``audience``, validity, ``revokes``), as given."""
    return {key: data[key] for key in ENTRY_SCOPE_KEYS if key in data}


def entry_extras(
    project_root: Any,
    identity: Mapping[str, Any],
    kind: str,
    text: str,
    anchors: Sequence[Mapping[str, Any]] | None,
    verdict: str | None,
    operation: str,
    anchor_resolution: Mapping[str, Any] | None,
) -> Extras | None:
    """Check the anchors (outside every lock) and gather the entry's extra fields; ``None`` for a plain one."""
    prepared = (
        prepare(project_root, anchors, kind, text, identity["repo"]["id"], identity["session"]["id"])
        if anchors else None
    )
    if prepared is None and verdict is None and operation == "remember" and anchor_resolution is None:
        return None
    fields: dict[str, Any] = {}
    if prepared is not None:
        fields["anchors"] = prepared.anchors
    if verdict is not None:
        fields["verdict"] = verdict
    if operation != "remember":
        fields["operation"] = operation
    if anchor_resolution is not None:
        fields["anchor_resolution"] = dict(anchor_resolution)
    result: dict[str, Any] = {}
    if prepared is not None:
        result["anchors"] = [
            {"index": i, "kind": a["source"]["kind"], "quote_sha256": a["quote_sha256"], **a["write_check"]}
            for i, a in enumerate(prepared.anchors)
        ]
        result.update(prepared.fields)
    if verdict is not None:
        result["verdict"] = verdict
    return Extras(fields, key_extra(prepared.anchors if prepared else None, verdict), payload_extra(fields), result)
