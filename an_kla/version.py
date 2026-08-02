"""Runtime version and release-tag normalization."""

from __future__ import annotations

import re

VERSION = "0.1.0b1"


def normalized_release_tag(tag: str) -> str:
    match = re.fullmatch(
        r"v(\d+\.\d+\.\d+)(?:-(alpha|beta|rc)\.(\d+))?", tag
    )
    if not match:
        raise ValueError("unsupported_release_tag")
    base, phase, number = match.groups()
    if phase is None:
        return base
    marker = {"alpha": "a", "beta": "b", "rc": "rc"}[phase]
    return f"{base}{marker}{number}"
