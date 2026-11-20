"""Anchors on the way into the inbox (ADR-0066 §1, §2): checking at enqueue, the entry fields, the record fields.

The three checks run **once**, in ``remember``, outside every lock: it is when the agent has the
source in hand.  The drain never reads Git again; it writes the anchors as they arrived (its
``write_check`` stays in the entry and never reaches the record).  Everything here is data, never
an instruction.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from .anchor_checks import CHECK_SCHEMA_V2, stored_check
from .anchors import (
    MAX_ANCHORS, ANCHOR_SCHEMA, ANCHOR_SCHEMA_V2, AnchorRejected, normalize_quote, source_identity, validate_anchor,
)
from .anchors_conversation import check_conversation
from .anchors_conversation_check import evaluate as evaluate_conversation
from .audience import ENTRY_SCOPE_KEYS
from .anchors_coverage_evidence import COVERAGE_ERROR, EVIDENCE, evidence_quotes
from .anchors_coverage_v2 import COVERAGE_RULES, coverage as compute_coverage
from .anchors_document_copy import copy_state
from .anchors_document_v2 import REJECT_LOCATOR_REQUIRED, evaluate
from .anchors_git import GitRepo
from .anchors_read import default_branch_setting
from .anchors_repo_file import ABSENT, ReadContext, verify_repo_file, write_rejection
from .canonical import digest_json
from .custodian_adapter import Adapters
from .temporal import format_utc

ENTRY_SCHEMA_V3 = "an-kla/inbox-entry-v3"  # v2 plus ``anchors``, ``verdict`` and ``operation``
OPERATIONS = ("remember", "dispute", "anchor_resolution", "anchor_check")
VERDICTS = ("contradicted", "insufficient")  # `supported` and `not_reviewed` stay in agora's ledger (A6)
ANCHOR_INPUT_INVALID = "anchor_input_invalid"


@dataclass(frozen=True)
class Prepared:
    """Anchors ready to queue (each with its ``write_check``) and the coverage of the text against them."""

    anchors: list[dict[str, Any]]
    fields: dict[str, Any]
    config_error: str | None = None  # the table of custodians could not be read and a ``document`` anchor was checked (ADR-0071 §3)


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


def coverage_fields(text: str, anchors: Sequence[Mapping[str, Any]] | None, kind: str = "fact") -> dict[str, Any]:
    """``coverage``, ``missing``, ``missing_total`` against the stored ``quote`` (never ``matched_text``, A3).

    Always ``fact-checks-rules/v2`` (ADR-0070): ``coverage.rules`` says so.  ``kind`` picks the mode: a ``state`` counts
    only identifiers, paths, hashes and versions; every other kind counts the six element types.

    The evidence is one string per anchor (erratum 7 of ``ancla/v1``, ADR-0073 §8): the quote, except for a ``document`` anchor of valid
    form, which adds its page and the path of its copy.  With such an anchor ``coverage.evidence`` says ``ancla-document/v1``; without
    one the output is what it always was.  An evidence over 16 384 bytes voids the whole record's coverage (``coverage_error``)."""
    if not anchors:
        return {}
    evidence = evidence_quotes(anchors, "decision" if kind == "directive" else kind)
    if evidence is None:
        return {"coverage": {"coverage_error": COVERAGE_ERROR, "rules": COVERAGE_RULES, "evidence": EVIDENCE}}
    quotes, marked = evidence
    result = compute_coverage(text, quotes, "state" if kind == "state" else "fact")
    if marked:
        result["coverage"] = {**result["coverage"], "evidence": EVIDENCE}
    return result


def record_fields(data: Mapping[str, Any]) -> dict[str, Any]:
    """The top-level fields an entry adds to its record: anchors, coverage, and a dispute's verdict."""
    fields: dict[str, Any] = {}
    anchors = stored_anchors(data.get("anchors"))
    if anchors:
        fields["anchors"] = anchors
        fields.update(coverage_fields(data["text"], anchors, data["kind"]))  # R70-01: the mode comes from the entry's kind
        checks = [  # ADR-0071 §5: what writing found out about each ``document`` anchor; the anchor itself does not change
            stored_check(index, anchor["quote_sha256"], anchor["write_check"])
            for index, anchor in enumerate(data["anchors"])
            if anchor["source"]["kind"] in ("document", "conversation") and "checked_at" in anchor.get("write_check", {})  # ADR-0073 §2: also a resolver's
        ]
        if checks:
            fields["anchor_checks"] = checks
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
    source = anchor["source"]
    # ADR-0071 §1: only a ``document`` is written as v2; a repo-file or a conversation stays v1 (beta.38 keeps reading them)
    anchor.setdefault("schema", ANCHOR_SCHEMA_V2 if source.get("kind") == "document" else ANCHOR_SCHEMA)
    if source.get("kind") == "document" and isinstance(source.get("copy"), dict):
        source["copy"]["repo"] = repo_id  # the tool puts it from C0, as for a repo-file
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


@dataclass(frozen=True)
class WriteContext:
    """What a ``document`` anchor needs to be checked when written: the project's ``repo.id``, the default-branch setting, the
    custodians' adapters and the clock (ADR-0071 §2, §3)."""

    repo_id: str
    setting: Any
    adapters: Adapters
    clock: Callable[[], datetime]
    resolve_conversations: bool = True  # ADR-0073 §5: false for a ``directive``, whose anchors are never resolved


def _check_document(repo: GitRepo, anchor: Mapping[str, Any], ctx: WriteContext) -> dict[str, Any]:
    """The seven rejections in their order: form and size (already done), the page, the path, the copy, its sha256, then
    the adapter.  The result is what is stored; a rejection raises."""
    locator = anchor["source"].get("locator")
    if not (isinstance(locator, dict) and "page" in locator):
        raise AnchorRejected(REJECT_LOCATOR_REQUIRED)
    state = copy_state(repo, anchor, ctx.repo_id, ctx.setting, strict=True)  # anchor_path_invalid
    out = evaluate(anchor, "write", state, ctx.adapters, format_utc(ctx.clock()))
    if out["reject"]:
        raise AnchorRejected(out["reject"])
    del out["reject"]
    return out


def _check(repo: GitRepo, anchor: Mapping[str, Any], record_type: str, ctx: WriteContext) -> dict[str, Any]:
    kind = anchor["source"]["kind"]
    if kind == "repo-file":
        return verify_repo_file(repo, anchor, record_type, "write", ReadContext())
    if kind == "conversation":
        # ADR-0073 §2: with a resolver (or a configuration that cannot be read) ``resolve`` is called; the result is stored in
        # ``anchor_checks`` and the anchor stays as it was born.  Without one, as before: nothing is called and nothing stored.
        if ctx.resolve_conversations and ctx.adapters.resolver_state() != "absent":
            return evaluate_conversation(anchor, None, ctx.adapters, format_utc(ctx.clock()))
        return check_conversation(anchor, None)
    return _check_document(repo, anchor, ctx)


def prepare(
    project_root: Any,
    raw_anchors: Sequence[Mapping[str, Any]],
    record_type: str,
    text: str,
    repo_id: str,
    session_id: str,
    *,
    store: Any = None,
    clock: Callable[[], datetime] | None = None,
    adapters: Adapters | None = None,
    resolve_conversations: bool = True,
) -> Prepared:
    """Validate and check every anchor, in C3's order; raises :class:`AnchorRejected` for the first refusal.

    The count first (``anchor_too_many``), then anchor by anchor: shape, not normalised, size, path,
    ``source`` / ``quote`` / ``integrity`` ``not_found``.  A record refused for any of them is never queued.
    A ``document`` anchor follows ADR-0071 §2 (the adapter is called last); ``store`` gives it the table of custodians and
    the default branch.
    """
    if len(raw_anchors) > MAX_ANCHORS:
        raise AnchorRejected("anchor_too_many")
    if adapters is None:
        adapters = Adapters.for_store(store) if store is not None else Adapters()
    ctx = WriteContext(
        repo_id, default_branch_setting(store) if store is not None else ABSENT, adapters,
        clock or (lambda: datetime.now(timezone.utc)), resolve_conversations,
    )
    stored: list[dict[str, Any]] = []
    with GitRepo(project_root) as repo:
        for index, raw in enumerate(raw_anchors):
            try:
                anchor = validate_anchor(fill_anchor(raw, repo_id, session_id, record_type, repo.head), record_type, index)
                result = _check(repo, anchor, record_type, ctx)
                code = write_rejection(result)
            except AnchorRejected as rejected:
                raise AnchorRejected(rejected.code, index) from None
            if code:
                raise AnchorRejected(code, index)
            stored.append({**anchor, "write_check": result})
    documents = any(a["source"]["kind"] == "document" or "resolver_called" in a["write_check"] for a in stored)
    return Prepared(stored, coverage_fields(text, stored, record_type), adapters.config_error if documents else None)


@dataclass(frozen=True)
class Extras:
    """What an anchored, disputed or annotating entry adds to a plain one (ADR-0066 §1)."""

    fields: dict[str, Any]  # entry keys: anchors, verdict, operation, anchor_resolution
    key: dict[str, Any] | None  # joins the derived idempotency key
    digest: dict[str, Any]  # joins ``payload_sha256``
    result: dict[str, Any]  # what ``remember`` answers beyond a plain write
    v4: bool = False  # ADR-0071 §6: a v2 anchor or an ``anchor_check`` annotation travels in an ``inbox-entry-v4``
    v5: bool = False  # ADR-0073 §2: a resolver's result in the anchors, or an ``anchor-check-v2`` annotation, in an ``inbox-entry-v5``


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
    if data.get("anchor_check") is not None:
        extra["anchor_check"] = digest_json(data["anchor_check"])
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
    anchor_check: Mapping[str, Any] | None = None,
    *,
    store: Any = None,
    clock: Callable[[], datetime] | None = None,
    resolve_conversations: bool = True,
) -> Extras | None:
    """Check the anchors (outside every lock) and gather the entry's extra fields; ``None`` for a plain one."""
    prepared = (
        prepare(project_root, anchors, kind, text, identity["repo"]["id"], identity["session"]["id"], store=store, clock=clock,
                resolve_conversations=resolve_conversations)
        if anchors else None
    )
    if prepared is None and verdict is None and operation == "remember" and anchor_resolution is None and anchor_check is None:
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
    if anchor_check is not None:
        fields["anchor_check"] = copy.deepcopy(dict(anchor_check))
    result: dict[str, Any] = {}
    if prepared is not None:
        result["anchors"] = [
            {"index": i, "kind": a["source"]["kind"], "quote_sha256": a["quote_sha256"], **a["write_check"]}
            for i, a in enumerate(prepared.anchors)
        ]
        result.update(prepared.fields)
        if prepared.config_error:
            result["custodians_config_error"] = prepared.config_error
    if verdict is not None:
        result["verdict"] = verdict
    key = key_extra(prepared.anchors if prepared else None, verdict)
    if anchor_check is not None:  # ADR-0071 §5: the target, the digest of the results and their date (a retry is the same audit)
        target = anchor_check["target"]
        key = {**(key or {}), "anchor_check": [
            [target["stream"], target["record_id"]], digest_json(anchor_check["checks"]), anchor_check["checks"][0]["checked_at"]]}
    v4 = anchor_check is not None or any(a.get("schema") == ANCHOR_SCHEMA_V2 for a in (prepared.anchors if prepared else []))
    v5 = any("resolver_called" in a["write_check"] for a in (prepared.anchors if prepared else [])) or (
        anchor_check is not None and anchor_check.get("schema") == CHECK_SCHEMA_V2
    )
    return Extras(fields, key, payload_extra(fields), result, v4 or v5, v5)
