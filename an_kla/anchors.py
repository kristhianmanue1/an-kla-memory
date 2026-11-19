"""Anchors of C3 (``memoria/ancla/v1``): the pure core of what is stored (ADR-0066).

No I/O: normalisation of the quote, its size rules, ``quote_sha256``, the shape
of an anchor and the order in which a record's anchors are rejected.  Reading the
source (Git, sessions) lives elsewhere; this module only decides what an anchor
*is*.  The quote is untrusted data, never an instruction.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any, Mapping, Sequence

ANCHOR_SCHEMA = "memoria/ancla/v1"
MAX_ANCHORS = 16
MIN_USEFUL_BYTES = 8
MIN_USEFUL_BYTES_DOCUMENT = 40
MAX_QUOTE_BYTES = 300
SOURCE_KINDS = ("repo-file", "conversation", "document")
RECORD_TYPES = ("fact", "decision", "state")
MODALITIES = ("native_text", "ocr_text", "visual")
RESOLUTIONS = ("pending", "resolved", "not_found")

# Unicode ``White_Space`` and nothing else: U+001C..U+001F are not in it.
WHITE_SPACE = frozenset(
    chr(cp)
    for cp in (
        0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x20, 0x85, 0xA0, 0x1680,
        *range(0x2000, 0x200B), 0x2028, 0x2029, 0x202F, 0x205F, 0x3000,
    )
)
_HEX64 = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")

REJECTION_CODES = (
    "anchor_too_many",
    "anchor_schema_invalid",
    "anchor_quote_not_normalized",
    "anchor_quote_too_short",
    "anchor_quote_too_long",
    "anchor_path_invalid",
    "anchor_source_not_found",
    "anchor_quote_not_found",
    "anchor_integrity_not_found",
)


class AnchorRejected(ValueError):
    """An anchor (or the record's anchor list) that C3 refuses to store."""

    def __init__(self, code: str, anchor_index: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.anchor_index = anchor_index


def strip_white_space(text: str) -> str:
    start, end = 0, len(text)
    while start < end and text[start] in WHITE_SPACE:
        start += 1
    while end > start and text[end - 1] in WHITE_SPACE:
        end -= 1
    return text[start:end]


def normalize_quote(text: str) -> str:
    """NFC, then trim ``White_Space`` at both ends (before measuring or hashing)."""
    return strip_white_space(unicodedata.normalize("NFC", text))


def useful_bytes(quote: str) -> int:
    """UTF-8 bytes of the characters that are not white space."""
    return sum(len(ch.encode("utf-8")) for ch in quote if ch not in WHITE_SPACE)


def quote_sha256(stored_quote: str) -> str:
    return hashlib.sha256(stored_quote.encode("utf-8")).hexdigest()


def quote_size_rejection(stored_quote: str, kind: str) -> str | None:
    """``too_short`` is checked first, so a quote failing both reports it (E1)."""
    minimum = MIN_USEFUL_BYTES_DOCUMENT if kind == "document" else MIN_USEFUL_BYTES
    if useful_bytes(stored_quote) < minimum:
        return "anchor_quote_too_short"
    if len(stored_quote.encode("utf-8")) > MAX_QUOTE_BYTES:
        return "anchor_quote_too_long"
    return None


def prepare_quote(raw: str, kind: str) -> str:
    """What the writing tool stores for ``raw``; raises on a size rejection."""
    stored = normalize_quote(raw)
    code = quote_size_rejection(stored, kind)
    if code:
        raise AnchorRejected(code)
    return stored


def _is_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _shape_ok(anchor: Mapping[str, Any], record_type: str) -> bool:
    if not isinstance(anchor, Mapping) or anchor.get("schema") != ANCHOR_SCHEMA:
        return False
    if not isinstance(anchor.get("quote"), str):
        return False
    digest = anchor.get("quote_sha256")
    if digest is not None and not (isinstance(digest, str) and _HEX64.fullmatch(digest)):
        return False
    source = anchor.get("source")
    if not isinstance(source, Mapping):
        return False
    kind = source.get("kind")
    if kind == "repo-file":
        if not (_is_str(source.get("repo")) and _is_str(source.get("path"))):
            return False
        commit = source.get("commit")
        if commit is None:
            return record_type == "state" and "commit" in source
        return isinstance(commit, str) and bool(_COMMIT.fullmatch(commit))
    if kind == "conversation":
        if not _is_str(source.get("session")):
            return False
        if source.get("resolution") not in RESOLUTIONS:
            return False
        return all(source.get(key) is None or _is_str(source.get(key)) for key in ("turn_id", "seal"))
    if kind == "document":
        sha = source.get("document_sha256")
        if not (isinstance(sha, str) and _HEX64.fullmatch(sha)):
            return False
        derivation = source.get("derivation")
        if not isinstance(derivation, Mapping) or derivation.get("modality") not in MODALITIES:
            return False
        if not (_is_str(derivation.get("custodian")) and _is_str(derivation.get("derivation_id"))):
            return False
        return _is_str(derivation.get("manifest_sha256"))
    return False


def validate_anchor(anchor: Mapping[str, Any], record_type: str, index: int | None = None) -> dict[str, Any]:
    """Apply the per-anchor rejections in their order and return the stored form.

    The order is shape, not normalised, too short / too long (errata 2 and 3);
    the source-dependent rejections (``path_invalid``, ``not_found``) are decided
    where the source is read.  ``quote_sha256`` is recomputed; one that arrives
    and disagrees with the stored quote is a malformed anchor.
    """
    if not _shape_ok(anchor, record_type):
        raise AnchorRejected("anchor_schema_invalid", index)
    quote = anchor["quote"]
    if quote != normalize_quote(quote):
        raise AnchorRejected("anchor_quote_not_normalized", index)
    code = quote_size_rejection(quote, anchor["source"]["kind"])
    if code:
        raise AnchorRejected(code, index)
    digest = quote_sha256(quote)
    if anchor.get("quote_sha256") not in (None, digest):
        raise AnchorRejected("anchor_schema_invalid", index)
    stored = {key: value for key, value in anchor.items() if key != "quote_sha256"}
    stored["quote_sha256"] = digest
    return stored


def validate_anchors(
    anchors: Sequence[Mapping[str, Any]], record_type: str
) -> list[dict[str, Any]]:
    """The record-level order: the count first, then each anchor in stored order."""
    if len(anchors) > MAX_ANCHORS:
        raise AnchorRejected("anchor_too_many")
    return [validate_anchor(anchor, record_type, index) for index, anchor in enumerate(anchors)]


def source_identity(anchor: Mapping[str, Any]) -> list[Any]:
    """Canonical ``source`` of an anchor as the list that feeds the derived key.

    ``resolution`` state is left out on purpose: the anchor is the same one
    before and after the resolver annotates it.
    """
    source = anchor["source"]
    kind = source["kind"]
    if kind == "repo-file":
        return [kind, source["repo"], source.get("commit"), source["path"]]
    if kind == "conversation":
        return [kind, source["session"]]
    return [kind, source["document_sha256"], source["derivation"]["derivation_id"]]
