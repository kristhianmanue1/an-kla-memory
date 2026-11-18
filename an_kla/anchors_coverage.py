"""Deterministic coverage of checkable elements (``fact-checks-rules/v1``).

Pure functions, no I/O.  The checkable elements of a record text (identifiers
in backticks, paths and URLs, versions and numbers) must show up in at least
one of its anchors' quotes.  The result is information, never a verdict: the
record is always stored and only the ``none`` level is served as a warning.
Rules were derived from the C3 vectors, not from another implementation.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable, Sequence

COVERAGE_RULES = "fact-checks-rules/v1"
MISSING_MAX = 8
TYPE_ORDER = ("identifier", "path", "version", "number")

_SPAN = re.compile(r"`([^`\n]*)`")
_TOKEN = re.compile(r"\S+")
_URL = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_LEAD = "([{<'\"“‘"
_TRAIL = ".,;:!?)]}>'\"”’"
_VERSION = re.compile(
    r"(?<![\w.])(?P<v>[vV])?(?P<base>\d+(?:\.\d+)+)"
    r"(?P<suffix>(?:[-_]?[^\W\d_]+\.?\d+(?:\.\d+)*)*)(?!\w)"
)
_NUMBER = re.compile(r"(?<!\w)\d+(?:[.,]\d+)*(?!\w)")


def _blank(text: str, start: int, end: int) -> str:
    return text[:start] + " " * (end - start) + text[end:]


def _canonical_number(token: str) -> str:
    seps = [c for c in token if c in ".,"]
    if not seps:
        return token
    if "." in seps and "," in seps:
        cut = max(token.rfind("."), token.rfind(","))
        whole, frac = token[:cut], token[cut + 1 :]
        return re.sub(r"[.,]", "", whole) + "." + frac
    if len(seps) > 1:
        return re.sub(r"[.,]", "", token)
    cut = token.find(seps[0])
    whole, frac = token[:cut], token[cut + 1 :]
    if len(frac) == 3:
        return whole + frac
    return whole + "." + frac


def _versions(text: str) -> list[tuple[int, str, int]]:
    found = []
    for m in _VERSION.finditer(text):
        if m["v"] or m["suffix"] or m["base"].count(".") >= 2:
            found.append((m.start(), m.group(0), m.end()))
    return found


def _numbers(text: str) -> list[tuple[int, str, int]]:
    return [
        (m.start(), _canonical_number(m.group(0)), m.end())
        for m in _NUMBER.finditer(text)
    ]


def _paths(text: str) -> list[tuple[int, str, int]]:
    found = []
    for m in _TOKEN.finditer(text):
        start, end = m.start(), m.end()
        while start < end and text[start] in _LEAD:
            start += 1
        while end > start and text[end - 1] in _TRAIL:
            end -= 1
        token = text[start:end]
        if _URL.match(token) or ("/" in token and any(c.isalpha() for c in token)):
            found.append((start, token, end))
    return found


def extract_elements(text: str) -> list[dict[str, str]]:
    """Checkable elements of ``text`` by first appearance, without repeats."""
    work = unicodedata.normalize("NFC", text)
    hits: list[tuple[int, str, str]] = []
    for m in list(_SPAN.finditer(work)):
        value = m.group(1).strip()
        if value:
            hits.append((m.start(), "identifier", value))
        work = _blank(work, m.start(), m.end())
    for kind, finder in (("path", _paths), ("version", _versions), ("number", _numbers)):
        for start, value, end in finder(work):
            hits.append((start, kind, value))
            work = _blank(work, start, end)
    hits.sort(key=lambda hit: hit[0])
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for _, kind, value in hits:
        if (kind, value) not in seen:
            seen.add((kind, value))
            out.append({"type": kind, "value": value})
    return out


def check_elements(text: str, quotes: Iterable[str]) -> list[dict[str, Any]]:
    """Each element of ``text`` with ``present`` against the union of ``quotes``."""
    norm = [unicodedata.normalize("NFC", q) for q in quotes]
    versions = {v for q in norm for _, v, _ in _versions(q)}
    numbers = {n for q in norm for _, n, _ in _numbers(q)}
    out = []
    for element in extract_elements(text):
        kind, value = element["type"], element["value"]
        if kind == "version":
            present = value in versions
        elif kind == "number":
            present = value in numbers
        else:
            present = any(value in q for q in norm)
        out.append({**element, "present": present})
    return out


def coverage_from_elements(elements: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """``coverage``, ``missing`` and ``missing_total`` from checked elements."""
    total = len(elements)
    absent = [e for e in elements if not e["present"]]
    present = total - len(absent)
    if total == 0:
        level = "unchecked"
    elif present == 0:
        level = "none"
    elif not absent:
        level = "full"
    else:
        level = "partial"
    absent.sort(key=lambda e: TYPE_ORDER.index(e["type"]))
    return {
        "coverage": {"total": total, "present": present, "level": level},
        "missing": [
            {"type": e["type"], "value": e["value"]} for e in absent[:MISSING_MAX]
        ],
        "missing_total": len(absent),
    }


def coverage(text: str, quotes: Iterable[str]) -> dict[str, Any]:
    """Coverage of the record ``text`` against the stored anchor ``quotes``."""
    return coverage_from_elements(check_elements(text, list(quotes)))
