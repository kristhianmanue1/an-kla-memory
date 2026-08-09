"""Closed provenance validation for the sanitized ADR-0025 fixture."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Mapping

from .canonical import canonical_json, digest_json


FORBIDDEN_CONTENT = ["hashes", "ids", "logs", "paths", "quotes", "urls", "usernames"]
SCAN_CONFIG = {
    "schema": "an-kla/benchmark-corpus-scan-config-v1",
    "patterns": [
        "credential-token",
        "email",
        "hash-identifier",
        "pem-private-key",
        "posix-user-path",
        "url",
        "windows-user-path",
    ],
    "id_policy": "synthetic-prefix-v1",
    "source_specific_denylist": "operator-local-not-versioned",
}
_PATTERNS = (
    re.compile(rb"\b(?:sk|ghp|github_pat|xox[baprs])[-_][A-Za-z0-9_-]{12,}"),
    re.compile(rb"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(rb"\bsha256:[0-9a-fA-F]{64}\b"),
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(rb"/(?:Users|home)/[^/\s]+/"),
    re.compile(rb"https?://", re.IGNORECASE),
    re.compile(rb"[A-Za-z]:\\\\Users\\\\[^\\\\\s]+\\\\"),
)


def scan_configuration_sha256() -> str:
    return digest_json(SCAN_CONFIG)


def contains_forbidden_content(queries: Any, records: Any) -> bool:
    payload = canonical_json({"queries": queries, "records": records})
    return any(pattern.search(payload) for pattern in _PATTERNS)


def validate_provenance_manifest(
    value: Mapping[str, Any], corpus_sha256: str
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "schema", "corpus_sha256", "source_kind", "sanitization",
        "forbidden_content", "source_specific_denylist", "human_review",
        "scanner",
    }:
        raise ValueError("invalid_reference_provenance")
    if value.get("schema") != "an-kla/provenance-manifest-v1":
        raise ValueError("invalid_reference_provenance")
    if value.get("corpus_sha256") != corpus_sha256:
        raise ValueError("invalid_reference_provenance")
    if value.get("source_kind") != "local-untrusted-memory-sanitized/v1":
        raise ValueError("invalid_reference_provenance")
    if value.get("sanitization") != {
        "method": "manual-paraphrase/v1",
        "retains_verbatim_source": False,
    }:
        raise ValueError("invalid_reference_provenance")
    if value.get("forbidden_content") != FORBIDDEN_CONTENT:
        raise ValueError("invalid_reference_provenance")
    if value.get("source_specific_denylist") != {
        "location": "operator-local-not-versioned",
        "required_before_publication": True,
    }:
        raise ValueError("invalid_reference_provenance")
    review = value.get("human_review")
    if review not in (
        {"status": "pending", "corpus_sha256": corpus_sha256, "reviewer": None},
        {"status": "passed", "corpus_sha256": corpus_sha256, "reviewer": "maintainer"},
    ):
        raise ValueError("invalid_reference_provenance")
    if value.get("scanner") != {
        "status": "passed",
        "tool": "check_benchmark_corpus/v1",
        "configuration_sha256": scan_configuration_sha256(),
    }:
        raise ValueError("invalid_reference_provenance")
    return deepcopy(value)


__all__ = [
    "FORBIDDEN_CONTENT", "SCAN_CONFIG", "contains_forbidden_content",
    "scan_configuration_sha256", "validate_provenance_manifest",
]
