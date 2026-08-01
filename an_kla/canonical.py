"""Canonical JSON and content-addressing helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def exact_sized_payload(
    build: Callable[[int], dict[str, Any]],
    *,
    max_iterations: int = 16,
) -> tuple[dict[str, Any], int]:
    """Build a payload whose embedded size equals its canonical UTF-8 size."""
    used = 0
    observed: set[int] = set()
    for _ in range(max_iterations):
        payload = build(used)
        measured = len(canonical_json(payload))
        if measured == used:
            return payload, measured
        if measured in observed:
            raise ValueError("payload_size_not_converged")
        observed.add(measured)
        used = measured
    raise ValueError("payload_size_not_converged")


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
