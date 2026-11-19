"""How a quote is found in a source text (C3, "Cómo se busca la cita"; ADR-0066 §2).

Three profiles, tried in order: ``literal``, ``ws-nfc/v1`` (every run of white
space is one space) and ``ws-nfc-accents/v1`` (also each character's NFD without
its ``Mn`` marks, never recomposed).  Case is never folded.  The first
occurrence wins and ``matched_text`` is the stretch of the NFC source from the
character that produced the first matching character to the one that produced the
last.
"""

from __future__ import annotations

import unicodedata

from .anchors import WHITE_SPACE, normalize_quote

PROFILE_LITERAL = "literal"
PROFILE_WS = "ws-nfc/v1"
PROFILE_ACCENTS = "ws-nfc-accents/v1"


def _collapse(text: str) -> tuple[str, list[tuple[int, int]]]:
    """Runs of white space become one space; each output char keeps its source span."""
    out: list[str] = []
    spans: list[tuple[int, int]] = []
    index, size = 0, len(text)
    while index < size:
        if text[index] in WHITE_SPACE:
            end = index
            while end < size and text[end] in WHITE_SPACE:
                end += 1
            out.append(" ")
            spans.append((index, end))
            index = end
        else:
            out.append(text[index])
            spans.append((index, index + 1))
            index += 1
    return "".join(out), spans


def _strip_marks(text: str, spans: list[tuple[int, int]]) -> tuple[str, list[tuple[int, int]]]:
    out: list[str] = []
    out_spans: list[tuple[int, int]] = []
    for char, span in zip(text, spans):
        for part in unicodedata.normalize("NFD", char):
            if unicodedata.category(part) != "Mn":
                out.append(part)
                out_spans.append(span)
    return "".join(out), out_spans


def _profile_text(text: str, accents: bool) -> tuple[str, list[tuple[int, int]]]:
    collapsed, spans = _collapse(text)
    return _strip_marks(collapsed, spans) if accents else (collapsed, spans)


def find_quote(quote: str, source_text: str) -> tuple[str | None, str | None]:
    """Return ``(match, matched_text)``; ``(None, None)`` when no profile finds it.

    ``matched_text`` is ``None`` for ``literal``.
    """
    needle = unicodedata.normalize("NFC", quote)
    source = unicodedata.normalize("NFC", source_text)
    if needle and needle in source:
        return PROFILE_LITERAL, None
    for profile, accents in ((PROFILE_WS, False), (PROFILE_ACCENTS, True)):
        wanted, _ = _profile_text(normalize_quote(needle), accents)
        if not wanted:
            continue
        haystack, spans = _profile_text(source, accents)
        at = haystack.find(wanted)
        if at >= 0:
            return profile, source[spans[at][0] : spans[at + len(wanted) - 1][1]]
    return None, None
