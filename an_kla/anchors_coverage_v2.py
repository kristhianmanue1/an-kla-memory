"""Deterministic coverage of checkable elements (``fact-checks-rules/v2``; C3 erratum 4, ADR-0070).

Pure functions, no I/O.  Derived from the 74 vectors of the erratum and from the written text of the rules (which v2
inherits from v1 for identifiers, paths, versions and numbers), not from another implementation.  It imports nothing
from :mod:`an_kla.anchors_coverage` (v1, untouched): each extractor follows the text, so v1's deviations from it
(word-based paths, a looser version suffix, a looser number canon) are not inherited.  It adds two element types, ``hash``
and ``date``, plus ``rc.N``-style pre-release tags as versions.

Extraction order on the text, each type masking what it found before the next one looks (the vectors fix it):
``identifier`` (backticks), ``path`` (so a date inside a path is part of the path), ``date`` (with an ISO time that
follows it), ``hash``, ``version``, ``number``.  Presence is read from the *raw* quotes (a figure inside a code span,
a path or a URL of the quote counts), except that a date and its ISO time are masked before the quote's numbers are
read, so a day, a month or a minute of a date never covers a bare number.

``state`` mode counts only ``identifier``, ``path``, ``hash`` and ``version``: without any of them the level is
``unchecked``, so ``none`` keeps warning only when a state cites something foreign.  The result is information, never
a verdict.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable, Sequence

COVERAGE_RULES = "fact-checks-rules/v2"
MISSING_MAX = 8
TYPE_ORDER = ("identifier", "path", "hash", "version", "date", "number")
STATE_TYPES = ("identifier", "path", "hash", "version")
MODES = ("fact", "state")

_DATE = re.compile(r"(?<!\d)\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])(?!\d)")
# "a backtick, one or more characters that are neither a backtick nor a line break, a backtick" (v1 text, inherited by v2)
_SPAN = re.compile(r"`([^`\n\r]+)`")
# the zone of an ISO time is "(Z|[+-]\d{2}:?\d{2})?": the colon is optional (v2 text)
_ISO_TIME = re.compile(r"T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?")
_HASH = re.compile(r"(?<!\w)[0-9a-f]{7,64}(?!\w)")
_PRERELEASE = re.compile(r"(?<![\w.])(?:alpha|beta|rc)\.\d+(?:\.\d+)*(?!\w)")
_HASH_MIN = 7
# 1b: "first URLs, then paths"; "trailing .,;:!? are stripped repeatedly from each match"; a path without any ASCII
# letter ("12/15") "is not a path and is not masked"
_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s`'\"<>()\[\]{}]+")
_PATH = re.compile(r"(?<![\w/.~-])(?:~|\.{1,2})?/?[\w.-]+(?:/[\w.-]+)+/?")
_TRAILING = ".,;:!?"
_ASCII_LETTER = re.compile(r"[A-Za-z]")
# 1c: only with a leading "v", or two or more dots in the numeric core, or a pre-release suffix
_VERSION = re.compile(
    r"(?<![\w.])(?P<v>v)?(?P<core>\d+(?:\.\d+)+)(?P<suffix>(?:a|b|rc)\d+|-[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)?(?!\w)"
)
# 1d
_NUMBER = re.compile(r"(?<!\w)\d+(?:[.,]\d+)*(?!\w)")


def _blank(text: str, start: int, end: int) -> str:
    return text[:start] + " " * (end - start) + text[end:]


def _paths(text: str) -> list[tuple[int, str, int]]:
    """URLs, then paths, each step masking what it captured; a rejected match is not masked and scanning goes on after it."""
    found: list[tuple[int, str, int]] = []
    work = text
    for pattern in (_URL, _PATH):
        hits = []
        for m in pattern.finditer(work):
            value = m.group(0).rstrip(_TRAILING)
            if value and _ASCII_LETTER.search(value):
                hits.append((m.start(), value, m.start() + len(value)))
        for start, value, end in hits:
            work = _blank(work, start, end)
        found.extend(hits)
    return found


def _versions(text: str) -> list[tuple[int, str, int]]:
    return [
        (m.start(), m.group(0), m.end())
        for m in _VERSION.finditer(text)
        if m["v"] or m["suffix"] or m["core"].count(".") >= 2
    ]


def _canonical_number(token: str) -> str:
    """1d: thousands, decimal or thousands plus decimal; anything else is the token with ``,`` replaced by ``.``."""
    groups = re.split(r"[.,]", token)
    separators = re.findall(r"[.,]", token)
    if not separators:
        return token
    if len(set(separators)) == 1 and all(len(group) == 3 for group in groups[1:]):
        return "".join(groups)
    if len(groups) == 2:
        return groups[0] + "." + groups[1]
    if (
        len(groups) >= 3 and len(set(separators[:-1])) == 1 and separators[-1] != separators[0]
        and all(len(group) == 3 for group in groups[1:-1])
    ):
        return "".join(groups[:-1]) + "." + groups[-1]
    return token.replace(",", ".")


def _numbers(text: str) -> list[tuple[int, str, int]]:
    return [(m.start(), _canonical_number(m.group(0)), m.end()) for m in _NUMBER.finditer(text)]


def _dates(text: str) -> list[tuple[int, str, int]]:
    """Dates ``AAAA-MM-DD`` between non-digits; the span also covers an ISO time that follows (``T10:30:00Z``)."""
    found = []
    for m in _DATE.finditer(text):
        time = _ISO_TIME.match(text, m.end())
        found.append((m.start(), m.group(0), time.end() if time else m.end()))
    return found


def _hashes(text: str) -> list[tuple[int, str, int]]:
    """Lowercase hexadecimal tokens of 7 to 64 characters with at least a digit and a letter."""
    return [
        (m.start(), m.group(0), m.end())
        for m in _HASH.finditer(text)
        if any(c.isdigit() for c in m.group(0)) and any(c.isalpha() for c in m.group(0))
    ]


def _prereleases(text: str) -> list[tuple[int, str, int]]:
    return [(m.start(), m.group(0), m.end()) for m in _PRERELEASE.finditer(text)]


def extract_elements(text: str) -> list[dict[str, str]]:
    """Checkable elements of ``text`` by first appearance, without repeats."""
    work = unicodedata.normalize("NFC", text)
    hits: list[tuple[int, str, str]] = []
    for m in list(_SPAN.finditer(work)):
        value = m.group(1).strip()
        if value:
            hits.append((m.start(), "identifier", value))
        work = _blank(work, m.start(), m.end())
    for kind, finder in (
        ("path", _paths), ("date", _dates), ("hash", _hashes), ("version", _versions),
        ("version", _prereleases), ("number", _numbers),
    ):
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


def _hash_present(value: str, quote_hashes: set[str]) -> bool:
    """Either one is a prefix of the other (a full hash in the text, an abbreviated one in the quote, or the reverse)."""
    return any(
        min(len(value), len(other)) >= _HASH_MIN and (value.startswith(other) or other.startswith(value))
        for other in quote_hashes
    )


def check_elements(text: str, quotes: Iterable[str]) -> list[dict[str, Any]]:
    """Each element of ``text`` with ``present`` against the union of ``quotes``."""
    norm = [unicodedata.normalize("NFC", q) for q in quotes]
    dates: set[str] = set()
    masked: list[str] = []
    for q in norm:
        work = q
        for start, value, end in _dates(q):
            dates.add(value)
            work = _blank(work, start, end)
        masked.append(work)
    hashes = {h for q in norm for _, h, _ in _hashes(q)}
    numbers = {n for q in masked for _, n, _ in _numbers(q)}
    out = []
    for element in extract_elements(text):
        kind, value = element["type"], element["value"]
        if kind == "date":
            present = value in dates
        elif kind == "hash":
            present = _hash_present(value, hashes)
        elif kind == "number":
            present = value in numbers
        else:  # identifier, path, version: "substring" of some NFC quote (the rules' text)
            present = any(value in q for q in norm)
        out.append({**element, "present": present})
    return out


def coverage_from_elements(elements: Sequence[dict[str, Any]], mode: str = "fact") -> dict[str, Any]:
    """``coverage``, ``missing`` and ``missing_total`` of checked elements, in ``fact`` or ``state`` mode."""
    if mode not in MODES:
        raise ValueError("invalid_coverage_mode")
    counted = [e for e in elements if mode == "fact" or e["type"] in STATE_TYPES]
    total = len(counted)
    absent = [e for e in counted if not e["present"]]
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
        "missing": [{"type": e["type"], "value": e["value"]} for e in absent[:MISSING_MAX]],
        "missing_total": len(absent),
    }


def has_rules(item: Any) -> bool:
    """True if a served record or answer carries a coverage that says its rules: the trigger of the sparse schema versions."""
    return isinstance(item, dict) and isinstance(item.get("coverage"), dict) and "rules" in item["coverage"]


def coverage(text: str, quotes: Iterable[str], mode: str = "fact") -> dict[str, Any]:
    """What is stored and answered: the coverage of ``text`` against the anchor ``quotes``, saying which rules computed it."""
    result = coverage_from_elements(check_elements(text, list(quotes)), mode)
    result["coverage"] = {**result["coverage"], "rules": COVERAGE_RULES}
    return result
