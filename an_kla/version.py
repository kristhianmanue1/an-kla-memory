"""Runtime version and release-tag normalization."""

from __future__ import annotations

import re

VERSION = "0.1.0b17"


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


def _parse_version_tuple(value: str) -> tuple[int, int, int, str, int]:
    """Parse a normalized version into a comparable tuple.

    Phase ordering follows the standard Python convention ``alpha < beta <
    rc < final`` so a final release sorts above any pre-release of the same
    base.  This helper is private because the canonical serialization remains
    the string form produced by :func:`normalized_release_tag`.
    """

    match = re.fullmatch(
        r"(\d+)\.(\d+)\.(\d+)(?:([ab]|rc)(\d+))?", value
    )
    if not match:
        raise ValueError("unsupported_version")
    major, minor, patch = (int(match.group(i)) for i in (1, 2, 3))
    phase = match.group(4) or "z"
    number = int(match.group(5)) if match.group(5) else 0
    return (major, minor, patch, phase, number)


def is_newer_release(candidate_tag: str, installed_version: str = VERSION) -> bool:
    """Return True when ``candidate_tag`` is strictly newer than installed."""

    return _parse_version_tuple(
        normalized_release_tag(candidate_tag)
    ) > _parse_version_tuple(installed_version)
