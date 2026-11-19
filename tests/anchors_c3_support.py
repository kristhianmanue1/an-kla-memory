"""Support for the C3 vector harness: pinned vectors and Git scenarios.

``load_vectors`` refuses a copy whose sha256 differs from the one C3 froze.
``materialize`` turns the declarative ``setup`` of a ``repo_file`` case into a real
Git repository (the operations are those of C3's README).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures" / "anchors-c3"
PINNED = {
    "vectores.json": "948a11305fe2c6a8c1640538c6460efafd14bd6a89da43c8e69ee74d7e3032a9",
    "vectores-errata-1.json": "1f7236430cd9d9a6c23c8e2b7000f43e83306dfd86d67e44a6928d654eb145e6",
    "vectores-errata-2.json": "6fc5c744c39ee2a6e8508860a006b507c6ed141ce2328c7b20f52129fa72d197",
    "fact-checks-v1-vectors.json": "3ef67fa54dae313d0112cb7cf6ba10fc948d15cc42204323e68a91f4fdcc3bbc",
}
REPO_ID = "github.com/ejemplo/repo"


def load_vectors(name: str) -> dict[str, Any]:
    raw = (FIXTURES / name).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != PINNED[name]:
        raise AssertionError(f"{name}: sha256 {digest} is not the one C3 froze")
    return json.loads(raw)


def _git(root: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
        GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid",
    )
    proc = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args], cwd=root, env=env,
        capture_output=True, text=True, check=True,
    )
    return proc.stdout.strip()


def _file_bytes(step: dict[str, Any]) -> bytes:
    if "hex" in step:
        return bytes.fromhex(step["hex"])
    data = step["text"].encode("utf-8")
    if "pad_to" in step:
        data = data + b"a" * (step["pad_to"] - len(data))
    if "nul_at" in step:
        data = data[: step["nul_at"]] + b"\0" + data[step["nul_at"] + 1 :]
    return data


def materialize(setup: list[dict[str, Any]], root: Path) -> dict[str, str]:
    """Build the repository; returns ``{commit name: sha}``."""
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main")
    commits: dict[str, str] = {}
    for step in setup:
        op = step["op"]
        target = root / step["path"] if "path" in step else None
        if op == "write":
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink() or target.exists():
                target.unlink()
            target.write_bytes(_file_bytes(step))
        elif op == "delete":
            target.unlink()
        elif op == "rename":
            (root / step["to"]).parent.mkdir(parents=True, exist_ok=True)
            target.rename(root / step["to"])
        elif op == "symlink":
            target.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(step["target"], target)
        elif op == "ignore":
            with (root / ".git" / "info" / "exclude").open("a") as handle:
                handle.write(step["path"] + "\n")
        elif op == "commit":
            _git(root, "add", "-A")
            _git(root, "commit", "-q", "--allow-empty", "-m", step["name"])
            commits[step["name"]] = _git(root, "rev-parse", "HEAD")
        elif op == "branch":
            _git(root, "checkout", "-q", "-b", step["name"])
        elif op == "checkout":
            _git(root, "checkout", "-q", step["name"])
        elif op == "delete_branch":
            _git(root, "branch", "-q", "-D", step["name"])
        elif op == "merge":
            _git(root, "merge", "-q", "--no-ff", "-m", step["name"], step["from"])
            commits[step["name"]] = _git(root, "rev-parse", "HEAD")
        elif op == "squash_merge":
            _git(root, "merge", "-q", "--squash", step["from"])
            _git(root, "commit", "-q", "--allow-empty", "-m", step["name"])
            commits[step["name"]] = _git(root, "rev-parse", "HEAD")
        else:
            raise AssertionError(f"unknown setup op {op}")
    return commits


def full_anchor(raw: dict[str, Any], commits: dict[str, str]) -> dict[str, Any]:
    """The flat anchor of a vector as a C3 ``memoria/ancla/v1`` object."""
    commit = raw.get("commit")
    if isinstance(commit, str) and commit.startswith("@"):
        commit = commits[commit[1:]]
    return {
        "schema": "memoria/ancla/v1",
        "source": {"kind": "repo-file", "repo": REPO_ID, "commit": commit, "path": raw["path"]},
        "quote": raw["quote"],
    }
