"""Fail closed on private/source-shaped content in the ADR-0025 corpus."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from an_kla.benchmark_fixture import (  # noqa: E402
    PROVENANCE_PATH,
    QUERIES_PATH,
    RECORD_ENTRIES,
    build_reference_store,
)
from an_kla.benchmark_provenance import (  # noqa: E402
    contains_forbidden_content,
    scan_configuration_sha256,
    validate_provenance_manifest,
)
from an_kla.canonical import digest_json  # noqa: E402
from an_kla.evaluation_v2 import read_queries_v2  # noqa: E402


def configuration_sha256() -> str:
    return scan_configuration_sha256()


def main() -> int:
    try:
        queries = read_queries_v2(QUERIES_PATH)
        provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"check_benchmark_corpus: FAIL — {type(exc).__name__}")
        return 1
    if contains_forbidden_content(queries, RECORD_ENTRIES):
        print("check_benchmark_corpus: FAIL — forbidden_content")
        return 1
    identifiers = [query["id"] for query in queries] + [
        identifier for query in queries for identifier in query["relevant"]
    ] + [
        entry["record"].get("id") for entry in RECORD_ENTRIES
    ]
    if any(
        not isinstance(identifier, str)
        or not identifier.startswith(("q-", "f-", "e-", "ep-"))
        for identifier in identifiers
    ):
        print("check_benchmark_corpus: FAIL — non_synthetic_identifier")
        return 1
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        _store, fixture = build_reference_store(directory)
    core = {
        "schema": "an-kla/reference-corpus-core-v1",
        "queries_sha256": digest_json(queries),
        "records_sha256": fixture["records_sha256"],
        "fixture_sha256": fixture["fixture_sha256"],
    }
    corpus_sha256 = digest_json(core)
    try:
        validate_provenance_manifest(provenance, corpus_sha256)
    except ValueError:
        print("check_benchmark_corpus: FAIL — invalid_provenance")
        return 1
    print("check_benchmark_corpus: OK — corpus saneado y ligado; human_review=pending")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
