"""The local copy of a ``document`` anchor (``memoria/ancla/v2``; ADR-0071 §2).

The copy is read **by Git, from the tip of the default branch**, in the two moments (writing and auditing),
never from the working tree: writer and external auditor look at the same thing.  Its state is one of
``none`` (no copy declared), ``ok`` (there is a file at the declared path), ``missing`` (there is not, or Git
cannot read it) and ``bad_sha`` (there is one, with another sha256).  Only a copy of *this* project is looked
at: one that names another repository counts as missing here (no clone of it).
"""

from __future__ import annotations

from typing import Any, Mapping

from .anchors import AnchorRejected
from .anchors_git import GitRepo, GitUnavailable
from .anchors_repo_file import ABSENT, default_tip, validate_path

COPY_STATES = ("none", "ok", "missing", "bad_sha")


def copy_state(
    repo: GitRepo, anchor: Mapping[str, Any], project_repo_id: str | None, setting: Any = ABSENT, *, strict: bool = False
) -> str:
    """What is at the declared copy.  ``strict`` (writing) raises ``anchor_path_invalid`` for a bad path; auditing
    counts it as missing (the anchor is already stored)."""
    source = anchor["source"]
    copy = source.get("copy")
    if copy is None:
        return "none"
    if not (isinstance(copy, Mapping) and isinstance(copy.get("path"), str)):  # a v1 anchor's copy is not shape-checked
        return "missing"
    try:
        path = validate_path(copy["path"])
    except AnchorRejected:
        if strict:
            raise
        return "missing"
    if project_repo_id is None or copy.get("repo") != project_repo_id or repo.no_git or repo.root is None:
        return "missing"
    try:
        tip = default_tip(repo, setting)
        if tip is None:
            return "missing"
        entry = repo.lookup(tip, path)
        if entry.kind != "blob":  # a link, a directory or an object Git does not read counts as absent
            return "missing"
        return "ok" if repo.blob_sha256(entry.sha) == source["document_sha256"] else "bad_sha"  # type: ignore[arg-type]
    except GitUnavailable:
        return "missing"
