"""Canonical JSON and content-addressing helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def digest_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def digest_json(value: Any) -> str:
    return digest_bytes(canonical_json(value))


def bare_digest(identifier: str) -> str:
    if not identifier.startswith("sha256:") or len(identifier) != 71:
        raise ValueError("invalid_sha256_identifier")
    value = identifier[7:]
    if any(char not in "0123456789abcdef" for char in value):
        raise ValueError("invalid_sha256_identifier")
    return value
