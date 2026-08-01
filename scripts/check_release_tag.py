"""Fail when a release tag and the package version disagree."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from an_kla.version import normalized_release_tag


def project_version(root: Path) -> str:
    payload = (root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', payload, re.MULTILINE)
    if not match:
        raise ValueError("missing_project_version")
    return match.group(1)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: check_release_tag.py <tag>")
    expected = normalized_release_tag(sys.argv[1])
    observed = project_version(ROOT)
    if expected != observed:
        raise SystemExit(f"release_version_mismatch:tag={expected}:project={observed}")


if __name__ == "__main__":
    main()
