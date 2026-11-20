"""Reading anchors: freshness with a limit, and the audit ``anchors verify`` (ADR-0066 §4, §5).

Every anchor served is checked again with the state of *now* (``moment: read``); nothing the writer
observed is trusted.  Only the anchors of what is served are checked, in serving order and, inside a
record, in stored order, up to ``--anchor-limit`` (32 by default); the rest answer ``unverified`` /
``anchor_limit`` and the output says how many were and were not checked.  There is never a time limit.
Reading never starts a custodian or a resolver.  Anchor text is untrusted data.

The exception is a ``document`` anchor (ADR-0071): it is not checked again when read, it is served as stored
(``anchor_checks`` of its record or the latest ``anchor_check`` annotation; ``not_checked`` / ``kind_not_supported`` if
none) and nobody is called.  ``anchors verify`` is the audit that does call the adapter and stores what it finds.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from .disputes import _valid_disputes
from .anchor_checks import check_annotations, check_kind, has_checks, has_conversation_result, is_conclusive, is_directive_row, latest_check, normalized
from .conversation_resolver import served as conversation_served
from .anchors import ANCHOR_SCHEMA_V2
from .anchors_audit import AuditSession
from .anchors_conversation import ConversationVerifier, apply_resolution, check_conversation
from .anchors_document_v2 import kind_not_supported, not_checked, served
from .anchors_freshness import aggregate_freshness, unchecked_result
from .anchors_git import GitRepo
from .anchors_repo_file import ABSENT, ReadContext, verify_repo_file
from .anchors_coverage_v2 import has_rules
from .audience import has_scope, is_for_other, make_reader
from .identity_c0 import validate_envelope
from .store import STREAMS
from .vigency import is_active

DEFAULT_ANCHOR_LIMIT = 32
RESULT_SCHEMA = "an-kla/anchors-verify-v1"
RESULT_SCHEMA_V2 = "an-kla/anchors-verify-v2"  # ADR-0069 §4: sólo con `for_reader`
RESULT_SCHEMA_V3 = "an-kla/anchors-verify-v3"  # ADR-0072 §2: sólo con `served` o `warnings` (v2 está publicado)
RESULT_SCHEMA_V4 = "an-kla/anchors-verify-v4"  # ADR-0073 §6: con alguna ancla `conversation` auditada
CONFIG_FILE = "config.json"
ENV_DEFAULT_BRANCH = "AN_KLA_DEFAULT_BRANCH"
_STREAM_RECORD_TYPE = {"facts": "fact", "events": "fact", "episodes": "state"}


class AnchorsReadError(ValueError):
    """Stable error of ``anchors verify``: ``str(error)`` is the code (rc 1)."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


def default_branch_setting(store: Any, env: Mapping[str, str] | None = None) -> Any:
    """A branch name, ``None`` (there is none) or :data:`ABSENT` (use ``origin/HEAD``); never guessed (A4, E5).

    The variable ``AN_KLA_DEFAULT_BRANCH`` replaces the ``default_branch`` key of the store's optional
    ``config.json`` (next to ``project-identity.json``; this release only reads it).  A defined but empty
    variable, or a null key, means "no default branch".
    """

    env = os.environ if env is None else env
    if ENV_DEFAULT_BRANCH in env:
        return env[ENV_DEFAULT_BRANCH] or None
    try:
        config = json.loads(Path(store.store_root, CONFIG_FILE).read_bytes())
    except (OSError, ValueError, AttributeError):
        return ABSENT
    if isinstance(config, dict) and "default_branch" in config:
        value = config["default_branch"]
        return value if isinstance(value, str) and value else None
    return ABSENT


def record_type_of(stream: str, row: Mapping[str, Any]) -> str:
    envelope = row.get("an_kla_envelope")
    if isinstance(envelope, dict) and not validate_envelope(envelope) and envelope["kind"] in ("fact", "decision", "state"):
        return envelope["kind"]
    return _STREAM_RECORD_TYPE.get(stream, "fact")


def resolution_annotations(snapshot: Any) -> list[dict[str, Any]]:
    """The vigent ``anchor_resolution`` records of ``events``, with the ``enqueued_at`` that orders them."""

    notes: list[dict[str, Any]] = []
    for row in snapshot.records.get("events", []):
        if row.get("kind") != "anchor_resolution" or not is_active(row):
            continue
        envelope = row.get("an_kla_envelope")
        if isinstance(row.get("anchor_resolution"), dict) and isinstance(envelope, dict):
            notes.append({"id": str(row.get("id", "")), "enqueued_at": envelope.get("enqueued_at"),
                          "anchor_resolution": row["anchor_resolution"]})
    return notes


def _descriptor(index: int, anchor: Mapping[str, Any]) -> dict[str, Any]:
    source = anchor.get("source") or {}
    kind = source.get("kind")
    locator = {"repo-file": ("path", "commit"), "conversation": ("session",), "document": ("document_sha256",)}.get(kind, ())
    return {"index": index, "kind": kind, "quote": anchor.get("quote"), "quote_sha256": anchor.get("quote_sha256"),
            **{key: source.get(key) for key in locator}}


def disputed_by(snapshot: Any) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Vigent disputes that carry a ``verdict``, by target ``(stream, id)``: the latest of each writer (ADR-0066 §6)."""

    latest: dict[tuple[str, str], dict[tuple[str, str], dict[str, Any]]] = {}
    for stream in STREAMS:
        for row in snapshot.records[stream]:
            disputes, verdict = row.get("disputes"), row.get("verdict")
            if not (_valid_disputes(disputes) and isinstance(verdict, str) and is_active(row)):
                continue
            envelope = row.get("an_kla_envelope")
            if not (isinstance(envelope, dict) and not validate_envelope(envelope)):
                continue
            writer = envelope["writer"]
            who = (writer["repo"]["id"], writer["agent"]["name"])
            item = {"id": str(row.get("id", "")), "verdict": verdict, "writer": dict(writer),
                    "enqueued_at": envelope["enqueued_at"]}
            target = (disputes["stream"], disputes["target_id"])
            seen = latest.setdefault(target, {})
            if who not in seen or (item["enqueued_at"], item["id"]) > (seen[who]["enqueued_at"], seen[who]["id"]):
                seen[who] = item
    return {t: sorted(v.values(), key=lambda i: (i["enqueued_at"], i["id"])) for t, v in latest.items()}


class AnchorServer:
    """Checks the anchors of the records a read command serves, sharing one limit and one Git reader."""

    def __init__(
        self, store: Any, snapshot: Any, limit: int = DEFAULT_ANCHOR_LIMIT, *,
        env: Mapping[str, str] | None = None, verifier: ConversationVerifier | None = None,
        audit: AuditSession | None = None,
    ) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise AnchorsReadError("anchor_limit_invalid", "entero positivo")
        self.store, self.limit, self.verifier, self.audit = store, limit, verifier, audit
        self.checked = self.unchecked = 0
        self.notes = resolution_annotations(snapshot)
        self.checks = check_annotations(snapshot)  # ADR-0071 §5: what audits stored for ``document`` anchors
        self.disputes = disputed_by(snapshot)
        self.setting = default_branch_setting(store, env)
        self._repo: GitRepo | None = None

    def __enter__(self) -> "AnchorServer":
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._repo is not None:
            self._repo.close()

    def repo(self) -> GitRepo:
        if self._repo is None:
            self._repo = GitRepo(self.store.project_root)
        return self._repo

    def declare(self) -> dict[str, int]:
        """The limit and what it did; empty when nothing anchored was served (plain output stays as it was)."""
        if not self.checked + self.unchecked:
            return {}
        return {"anchor_limit": self.limit, "anchors_checked": self.checked, "anchors_unchecked": self.unchecked}

    def _check(self, row: Mapping[str, Any], stream: str, index: int, anchor: Mapping[str, Any]) -> dict[str, Any]:
        kind = anchor["source"]["kind"]
        if kind == "repo-file":
            writer_repo = (row.get("an_kla_envelope") or {}).get("writer", {}).get("repo", {})
            ctx = ReadContext(self.setting, writer_repo.get("branch"))
            return verify_repo_file(self.repo(), anchor, record_type_of(stream, row), "read", ctx)
        if kind == "conversation":
            return self._conversation(row, stream, index, anchor)
        if self.audit is not None:  # the audit calls the adapter and stores the result; reading never does
            attempt = self.audit.audit(self.repo(), stream, str(row.get("id", "")), index, anchor)
            prior = latest_check(row, stream, index, anchor, self.checks)
            prior = prior if prior is not None and is_conclusive(prior) else None
            # ADR-0072 §2, ADR-0073 §6: ``served`` always says what reading keeps serving: the attempt if it concludes (or nothing
            # concluded before), else the last conclusive result
            chosen = prior if prior is not None and not is_conclusive(attempt) else attempt
            attempt["served"] = {"freshness": chosen["freshness"], "reason": chosen["reason"], "checked_at": chosen["checked_at"]}
            return attempt
        stored = latest_check(row, stream, index, anchor, self.checks)
        if stored is not None:
            return served(stored)
        return not_checked(anchor) if anchor.get("schema") == ANCHOR_SCHEMA_V2 else kind_not_supported(anchor)

    def _conversation(self, row: Mapping[str, Any], stream: str, index: int, anchor: Mapping[str, Any]) -> dict[str, Any]:
        """A ``conversation`` anchor (ADR-0073).  Those of a ``directive`` are never resolved (§5): as in beta.40.  Otherwise, reading serves
        the last conclusive stored result of the resolver (else the last), unless a newer ``anchor-resolution-v1`` annotation says otherwise;
        auditing calls the resolver, stores the attempt and says in ``served`` what reading keeps serving."""
        record_id = str(row.get("id", ""))
        view = apply_resolution(anchor, record_id, index, self.notes)
        old = check_conversation(view, self.verifier)
        if is_directive_row(row):
            return old
        stored = latest_check(row, stream, index, anchor, self.checks)
        stored = stored if stored is not None and check_kind(stored) == "conversation" else None
        newer_note = stored is not None and any(
            normalized(n["enqueued_at"]) > normalized(stored["checked_at"]) for n in self.notes
            if (n["anchor_resolution"].get("target") or {}).get("record_id") == record_id and (n["anchor_resolution"].get("target") or {}).get("anchor_index") == index
            and n["enqueued_at"]
        )
        if self.audit is None:
            return old if stored is None or newer_note else conversation_served(stored)
        prior = stored if stored is not None and is_conclusive(stored) else None
        attempt = self.audit.audit_conversation(stream, record_id, index, anchor, prior)
        if attempt is None:  # no resolver: nothing is called and nothing stored, as in beta.40
            attempt = dict(old)
        chosen = prior if prior is not None and not is_conclusive(attempt, "conversation") else attempt
        attempt["served"] = {"freshness": chosen["freshness"], "reason": chosen["reason"], "checked_at": chosen.get("checked_at")}
        return attempt

    def serve(self, stream: str, row: Mapping[str, Any]) -> dict[str, Any]:
        """``disputed``, ``anchors`` (each with its descriptor and checks), ``anchors_freshness``, the stored coverage."""

        out: dict[str, Any] = {}
        disputed = self.disputes.get((stream, str(row.get("id", ""))))
        if disputed:
            out["disputed"] = disputed  # the latest verdict of each writer; the target stays vigent
        anchors = row.get("anchors")
        if not isinstance(anchors, list) or not anchors:
            return out
        served: list[dict[str, Any]] = []
        for index, anchor in enumerate(anchors):
            if self.checked >= self.limit:
                self.unchecked += 1
                result = unchecked_result(anchor["source"]["kind"])
            else:
                self.checked += 1
                result = self._check(row, stream, index, anchor)
            served.append({"anchor": _descriptor(index, anchor), **result})
        out.update(anchors=served, anchors_freshness=aggregate_freshness(served))
        for key in ("coverage", "missing", "missing_total"):
            if key in row:
                out[key] = row[key]
        return out


def verify_command(store: Any, args: Any, clock: Callable[[], datetime] | None = None) -> dict[str, Any]:
    """``anchors verify <id>`` or ``--all``; the only limit is ``--anchor-limit``.  It writes only for ``document`` anchors
    (ADR-0071 §5): for ``repo-file``, ``conversation`` and a store without ``document`` anchors it stores nothing."""

    if args.all == (args.id is not None):
        raise AnchorsReadError("anchors_target_required", "un id, o --all (no los dos)")
    snapshot = store.snapshot()
    if args.all:
        rows = [(s, r) for s in STREAMS for r in snapshot.records[s] if is_active(r) and r.get("anchors")]
        rows.sort(key=lambda sr: (STREAMS.index(sr[0]), sr[1].get("an_kla_envelope", {}).get("enqueued_at") is None,
                                  str((sr[1].get("an_kla_envelope") or {}).get("enqueued_at") or ""), str(sr[1].get("id", ""))))
    else:
        rows = [(s, r) for s in STREAMS for r in snapshot.records[s] if str(r.get("id", "")) == args.id]
        if not rows:
            raise AnchorsReadError("anchors_id_not_found")
        if len(rows) > 1:
            raise AnchorsReadError("anchors_id_ambiguous", "el id está en más de un stream")
    records: list[dict[str, Any]] = []
    reader = make_reader(store)
    audit = AuditSession(store, default_branch_setting(store), clock=clock)
    with AnchorServer(store, snapshot, args.anchor_limit, audit=audit) as server:
        for stream, row in rows:
            # ADR-0069 §4: auditar no filtra; lo que trae ámbito explícito y es para otro se marca
            marked = {"for_reader": False} if has_scope(row) and is_for_other(row, reader) else {}
            shown = server.serve(stream, row)
            # ADR-0071 §5: a record with ``document`` anchors audited gets its annotation (and says whether it was recorded)
            stored = audit.finish(stream, str(row.get("id", "")))
            records.append({"id": str(row.get("id", "")), "stream": stream, **marked, **shown, **stored})
        declared = server.declare()
    if audit.used_adapters and audit.adapters.config_error:
        declared["custodians_config_error"] = audit.adapters.config_error
    warnings = audit.warnings()
    if warnings:
        declared["warnings"] = warnings  # ADR-0072 §2: a warning, not a failure: the rc does not change
    versioned = any("for_reader" in r or "recorded" in r or has_rules(r) or has_checks(r) for r in records)
    third = bool(warnings) or any("served" in a for r in records for a in r.get("anchors", []))  # ADR-0072 §2: v2 is published
    # ADR-0073 §6: v3 is published and closed for ``served``: with a ``conversation`` anchor audited (``served``, never of a directive) it is v4
    fourth = any("served" in a and a.get("anchor", {}).get("kind") == "conversation" for r in records for a in r.get("anchors", []))
    fourth = fourth or any(isinstance(r.get("coverage"), dict) and "evidence" in r["coverage"] for r in records)  # erratum 7: coverage.evidence is not in the published v3
    return {"schema": RESULT_SCHEMA_V4 if fourth else RESULT_SCHEMA_V3 if third else RESULT_SCHEMA_V2 if versioned else RESULT_SCHEMA,
            "untrusted_memory_data": True,
            "revision": snapshot.revision_id, **declared, "records": records}
