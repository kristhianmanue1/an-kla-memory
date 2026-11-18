"""The three checks of a ``repo-file`` anchor against real Git (C3; ADR-0066 §2, §4).

``verify_repo_file`` answers "where do I look" (C3, "Dónde se mira"): a ``state``
in the working tree, a ``fact``/``decision`` in the declared commit when writing
and at the tip of the default branch (then the envelope's branch) when reading.
A failure to read that is not "does not exist" is ``repo_unavailable``, never
``not_found`` (erratum E4).  The writer's rejections are raised as
:class:`~an_kla.anchors.AnchorRejected`; reading never rejects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .anchors import AnchorRejected
from .anchors_freshness import anchor_result
from .anchors_git import GitRepo, GitUnavailable, read_blob_text, read_worktree_text
from .anchors_search import find_quote

ABSENT: Any = object()  # default_branch not configured: fall back to ``origin/HEAD``
_UNVERIFIABLE = "unverifiable"
_SOURCE_NOT_VERIFIED = (_UNVERIFIABLE, "source_not_verified")


@dataclass(frozen=True)
class ReadContext:
    """Configuration and envelope the checks depend on.

    ``default_branch``: a name, ``None`` (there is none: ``no_default_branch``) or
    :data:`ABSENT` (use ``origin/HEAD``).  ``envelope_branch`` is ``repo.branch`` of C0.
    """

    default_branch: Any = ABSENT
    envelope_branch: str | None = None


@dataclass
class _Observation:
    """What one place says about the path and the quote."""

    source: tuple[str, str | None]
    quote: tuple[str, str | None]
    match: str | None = None
    matched_text: str | None = None

    @property
    def not_found(self) -> bool:
        return "not_found" in (self.source[0], self.quote[0])


def validate_path(path: Any) -> str:
    """Relative, no ``..``, no empty or ``.git`` component; else ``anchor_path_invalid``."""
    if not isinstance(path, str) or not path or "\0" in path or path.startswith("/"):
        raise AnchorRejected("anchor_path_invalid")
    for part in path.split("/"):
        if part in ("", ".", "..") or part.lower() == ".git":
            raise AnchorRejected("anchor_path_invalid")
    return path


def _content_observation(text: str | None, reason: str | None, quote: str) -> _Observation:
    if text is None:
        return _Observation(("verified", None), (_UNVERIFIABLE, reason))
    match, matched = find_quote(quote, text)
    if match is None:
        return _Observation(("verified", None), ("not_found", "quote_absent"))
    return _Observation(("verified", None), ("verified", None), match, matched)


def _observe_rev(repo: GitRepo, rev: str, path: str, quote: str) -> _Observation:
    entry = repo.lookup(rev, path)
    if entry.kind != "blob":
        return _Observation(("not_found", "path_missing"), _SOURCE_NOT_VERIFIED)
    text, reason = read_blob_text(repo, entry.sha)  # type: ignore[arg-type]
    return _content_observation(text, reason, quote)


def _integrity(repo: GitRepo, commit: str, path: str, quote: str) -> tuple[str, str | None]:
    """The blob of the declared commit contains the quote?  (Same question everywhere.)"""
    if not repo.commit_exists(commit):
        return _UNVERIFIABLE, "commit_not_in_clone"
    entry = repo.lookup(commit, path)
    if entry.kind != "blob":
        return "not_found", "commit_blob_lacks_quote"
    text, reason = read_blob_text(repo, entry.sha)  # type: ignore[arg-type]
    if text is None:
        return _UNVERIFIABLE, reason
    if find_quote(quote, text)[0] is None:
        return "not_found", "commit_blob_lacks_quote"
    return "verified", None


def _unavailable(kind: str = "repo-file", reason: str = "repo_unavailable") -> dict[str, Any]:
    state = (_UNVERIFIABLE, reason)
    return anchor_result(
        kind, state, _SOURCE_NOT_VERIFIED, _SOURCE_NOT_VERIFIED, at=None
    )


def _state_check(repo: GitRepo, path: str, quote: str, moment: str) -> dict[str, Any]:
    """A ``state`` is looked up in the working tree; ``integrity`` is ``working_tree``."""
    kind, where = repo.worktree_lookup(path)
    working = (_UNVERIFIABLE, "working_tree")
    if kind in ("symlink_component", "symlink") and moment == "write":
        raise AnchorRejected("anchor_path_invalid")
    versioned = kind == "blob" and (repo.tracked(path) or not repo.ignored(path))
    if not versioned:
        return anchor_result(
            "repo-file", ("not_found", "path_missing"), _SOURCE_NOT_VERIFIED, working, at="worktree"
        )
    text, reason = read_worktree_text(where)  # type: ignore[arg-type]
    obs = _content_observation(text, reason, quote)
    return anchor_result(
        "repo-file", obs.source, obs.quote, working, at="worktree",
        match=obs.match, matched_text=obs.matched_text,
    )


def _write_fact_check(repo: GitRepo, commit: str, path: str, quote: str) -> dict[str, Any]:
    if not repo.commit_exists(commit):
        state = (_UNVERIFIABLE, "commit_not_in_clone")
        return anchor_result("repo-file", state, _SOURCE_NOT_VERIFIED, state, at=None)
    entry = repo.lookup(commit, path)
    if entry.kind in ("symlink", "symlink_component"):
        raise AnchorRejected("anchor_path_invalid")
    obs = _observe_rev(repo, commit, path, quote)
    if obs.source[0] == "not_found":
        integrity = (_UNVERIFIABLE, "source_not_verified")
    elif obs.quote[0] == "not_found":
        integrity = ("not_found", "commit_blob_lacks_quote")
    elif obs.quote[0] == "verified":
        integrity = ("verified", None)
    else:
        integrity = (_UNVERIFIABLE, obs.quote[1])
    return anchor_result(
        "repo-file", obs.source, obs.quote, integrity, at="commit",
        match=obs.match, matched_text=obs.matched_text,
    )


def _tips(repo: GitRepo, ctx: ReadContext) -> list[tuple[str, str]]:
    """Default branch tip first, then the envelope branch tip (if it exists and differs)."""
    tips: list[tuple[str, str]] = []
    if ctx.default_branch is ABSENT:
        found = repo.ref_tip("refs/remotes/origin/HEAD")
    elif ctx.default_branch is None or ctx.default_branch == "":
        found = None
    else:
        name = str(ctx.default_branch)
        found = repo.ref_tip(f"refs/heads/{name}", f"refs/remotes/origin/{name}")
    if found is None:
        return []
    tips.append(("default", found))
    if ctx.envelope_branch:
        name = ctx.envelope_branch
        other = repo.ref_tip(f"refs/heads/{name}", f"refs/remotes/origin/{name}")
        if other and other != found:
            tips.append(("branch", other))
    return tips


def _read_fact_check(
    repo: GitRepo, commit: str, path: str, quote: str, ctx: ReadContext
) -> dict[str, Any]:
    integrity = _integrity(repo, commit, path, quote)
    tips = _tips(repo, ctx)
    if not tips:
        return anchor_result(
            "repo-file", (_UNVERIFIABLE, "no_default_branch"), _SOURCE_NOT_VERIFIED,
            integrity, at=None,
        )
    in_clone = integrity[1] != "commit_not_in_clone"
    chosen: tuple[str, _Observation] | None = None
    first: _Observation | None = None
    for label, tip in tips:
        obs = _observe_rev(repo, tip, path, quote)
        first = first or obs
        # Finding the quote (or being unable to read it) always counts; an absence
        # only counts when the declared commit is an ancestor of the place looked at.
        if not obs.not_found or (in_clone and repo.is_ancestor(commit, tip)):
            chosen = (label, obs)
            break
    if chosen is not None:
        label, obs = chosen
        return anchor_result(
            "repo-file", obs.source, obs.quote, integrity, at=label,
            match=obs.match, matched_text=obs.matched_text,
        )
    assert first is not None
    reason = "commit_not_on_default_branch" if in_clone else "commit_not_in_clone"
    source, quote_state = first.source, first.quote
    if source[0] == "not_found":
        source, quote_state = (_UNVERIFIABLE, reason), _SOURCE_NOT_VERIFIED
    else:
        quote_state = (_UNVERIFIABLE, reason)
    return anchor_result("repo-file", source, quote_state, integrity, at="default")


def verify_repo_file(
    repo: GitRepo,
    anchor: Mapping[str, Any],
    record_type: str,
    moment: str,
    ctx: ReadContext | None = None,
) -> dict[str, Any]:
    """Run the three checks of one ``repo-file`` anchor; ``moment`` is ``write`` or ``read``."""
    ctx = ctx or ReadContext()
    source = anchor["source"]
    quote = anchor["quote"]
    path = source["path"]
    try:
        if moment == "write":
            validate_path(path)
        if repo.no_git or repo.root is None:
            state = (_UNVERIFIABLE, "no_git")
            return anchor_result("repo-file", state, _SOURCE_NOT_VERIFIED, _SOURCE_NOT_VERIFIED, at=None)
        if record_type == "state":
            return _state_check(repo, path, quote, moment)
        commit = source["commit"]
        if moment == "write":
            return _write_fact_check(repo, commit, path, quote)
        return _read_fact_check(repo, commit, path, quote, ctx)
    except GitUnavailable as failure:
        return _unavailable(reason=failure.reason)


WRITE_REJECTIONS = (
    ("source", "anchor_source_not_found"),
    ("quote", "anchor_quote_not_found"),
    ("integrity", "anchor_integrity_not_found"),
)


def write_rejection(result: Mapping[str, Any]) -> str | None:
    """C3's rule 1: a ``not_found`` check rejects, in that order of precedence."""
    for check, code in WRITE_REJECTIONS:
        if result[check] == "not_found":
            return code
    return None
