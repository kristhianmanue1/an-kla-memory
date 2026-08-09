"""Deterministic temporary reference corpus for ADR-0025."""

from __future__ import annotations

from contextlib import ExitStack
from copy import deepcopy
from importlib.resources import files
import json
from pathlib import Path
import tempfile
from typing import Any

from .benchmark_provenance import validate_provenance_manifest
from .canonical import bare_digest, canonical_json, digest_json
from .evaluation_v2 import CATEGORIES, REFERENCE_STATES, evaluate_states_v2, read_queries_v2
from .index import INDEX_DIR_NAME, INDEX_PROFILE, build_index, detect_fts5
from .retrieval import TOKEN
from .store import MemoryStore, STREAMS


FIXTURE_VERSION = "retrieval-benchmark-v2/1"
FIXTURE_DIR = files("an_kla").joinpath("resources", "retrieval-benchmark-v2")
QUERIES_PATH = FIXTURE_DIR / "queries.jsonl"
PROVENANCE_PATH = FIXTURE_DIR / "provenance.json"

PROJECT_IDENTITY = {
    "schema": "an-kla/project-identity-v1",
    "project_uuid": "11111111-1111-4111-8111-111111111111",
    "created_by_version": "0.1.0-beta.11-reference",
}
STORE_IDENTITY = {
    "schema": "an-kla/store-identity-v1",
    "store_uuid": "22222222-2222-4222-8222-222222222222",
    "project_uuid": PROJECT_IDENTITY["project_uuid"],
    "project_identity": digest_json(PROJECT_IDENTITY),
    "canonical_project_root_at_init": "/an-kla/reference-fixture",
    "created_by_version": "0.1.0-beta.11-reference",
}
CHECKPOINT = {
    "schema": "an-kla/checkpoint-v1",
    "revision": 0,
    "goal": None,
    "next": None,
    "decisions": [],
    "blockers": [],
}

FACTS_R1 = [
    {"id": "f-short", "payload": {"text": "checkpoint handoff exact next step"}},
    {"id": "f-long", "payload": {"text": "checkpoint handoff exact " + "longcontext " * 460}},
    {"id": "f-distractor", "payload": {"text": "checkpoint handoff exact next step budget retrieval distractor"}},
    {"id": "f-kairos", "payload": {"text": "frescura memoria gobernanza siguiente paso"}},
    {"id": "f-summary", "payload": {"text": "detalle operacional " * 40, "summary": "resumen continuidad verificable"}},
    {"id": "f-chain-a", "payload": {"text": "cadena conocimiento vigente version antigua"}},
]
FACTS_R2 = [{"id": "f-chain-b", "payload": {"text": "cadena conocimiento vigente version intermedia"}}]
FACTS_R3 = [{"id": "f-chain-c", "payload": {"text": "cadena conocimiento vigente version final"}}]
EVENTS_R1 = [{"id": "e-continuity", "payload": {"summary": "evidencia continuidad evento durable"}}]
EPISODES_R1 = [{"id": "ep-continuity", "payload": {"summary": "evidencia continuidad episodio handoff"}}]

SEGMENT_DEFINITIONS = (
    ("facts", 1, FACTS_R1),
    ("events", 1, EVENTS_R1),
    ("episodes", 1, EPISODES_R1),
    ("facts", 2, FACTS_R2),
    ("facts", 3, FACTS_R3),
)
RECORD_ENTRIES = [
    {"stream": stream, "record": deepcopy(record)}
    for stream, _sequence, records in SEGMENT_DEFINITIONS
    for record in records
]


def _manifest(
    revision: int,
    parent: str | None,
    checkpoint: str,
    identity: str,
    segments: dict[str, list[str]],
    txid: str,
    supersedes: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    result = {
        "schema": "an-kla/revision-v1",
        "revision": revision,
        "parent": parent,
        "checkpoint": checkpoint,
        "facts_segments": list(segments["facts"]),
        "events_segments": list(segments["events"]),
        "episodes_segments": list(segments["episodes"]),
        "canonicalization": "canonical-json/v1",
        "integrity_claim": "content_identity_not_truth_or_authorship",
        "store_identity": identity,
        "transaction_id": txid,
    }
    if supersedes:
        result["supersedes_map"] = deepcopy(supersedes)
    return result


def build_reference_store(project_root: str | Path) -> tuple[MemoryStore, dict[str, Any]]:
    store = MemoryStore(project_root)
    store._make_layout()
    identity_id = store._write_json_object("identities", STORE_IDENTITY)
    checkpoint_id = store._write_json_object("checkpoints", CHECKPOINT)
    segment_ids: dict[tuple[str, int], str] = {}
    segment_core = []
    for stream, sequence, records in SEGMENT_DEFINITIONS:
        segment_ids[(stream, sequence)] = store._write_segment(stream, records)
        segment_core.append({"stream": stream, "sequence": sequence, "records": deepcopy(records)})
    empty = {stream: [] for stream in STREAMS}
    root_manifest = _manifest(
        0, None, checkpoint_id, identity_id, empty,
        "30000000-0000-4000-8000-000000000000",
    )
    root_id = store._write_json_object("revisions", root_manifest)
    r1_segments = {
        "facts": [segment_ids[("facts", 1)]],
        "events": [segment_ids[("events", 1)]],
        "episodes": [segment_ids[("episodes", 1)]],
    }
    r1_manifest = _manifest(
        1, root_id, checkpoint_id, identity_id, r1_segments,
        "30000000-0000-4000-8000-000000000001",
    )
    r1_id = store._write_json_object("revisions", r1_manifest)
    r2_segments = {**r1_segments, "facts": [*r1_segments["facts"], segment_ids[("facts", 2)]]}
    supersedes_r2 = [{"stream": "facts", "target_id": "f-chain-a", "sustituida_por": "f-chain-b"}]
    r2_manifest = _manifest(
        2, r1_id, checkpoint_id, identity_id, r2_segments,
        "30000000-0000-4000-8000-000000000002", supersedes_r2,
    )
    r2_id = store._write_json_object("revisions", r2_manifest)
    r3_segments = {**r2_segments, "facts": [*r2_segments["facts"], segment_ids[("facts", 3)]]}
    supersedes_r3 = [
        *supersedes_r2,
        {"stream": "facts", "target_id": "f-chain-b", "sustituida_por": "f-chain-c"},
    ]
    r3_manifest = _manifest(
        3, r2_id, checkpoint_id, identity_id, r3_segments,
        "30000000-0000-4000-8000-000000000003", supersedes_r3,
    )
    r3_id = store._write_json_object("revisions", r3_manifest)
    store._replace_current(r3_id)
    fixture_core = {
        "schema": "an-kla/retrieval-benchmark-fixture-core-v1",
        "store_identity": deepcopy(STORE_IDENTITY),
        "checkpoints": [deepcopy(CHECKPOINT)],
        "segments": segment_core,
        "manifests": [root_manifest, r1_manifest, r2_manifest, r3_manifest],
        "current": r3_id,
    }
    return store, {
        "schema": "an-kla/retrieval-benchmark-fixture-result-v1",
        "fixture_core": fixture_core,
        "fixture_sha256": digest_json(fixture_core),
        "records_sha256": digest_json(RECORD_ENTRIES),
        "revision": r3_id,
        "r2_revision": r2_id,
    }


def _selected_index(store: MemoryStore, result: dict[str, Any]) -> Path:
    relative = result.get("index")
    if not isinstance(relative, str):
        raise ValueError("fts5_required_for_reference_benchmark")
    return store.root / relative


def configure_index_state(store: MemoryStore, fixture: dict[str, Any], state: str) -> None:
    if state == "absent":
        return
    if state in {"fresh", "corrupt"}:
        result = build_index(store, revision_id=fixture["revision"])
        selected = _selected_index(store, result)
        if state == "corrupt":
            with selected.open("ab") as handle:
                handle.write(b"\x00")
        return
    if state != "stale":
        raise ValueError("invalid_evaluation_profile")
    stale = build_index(store, revision_id=fixture["r2_revision"])
    source = _selected_index(store, stale)
    payload = source.read_bytes()
    directory = store.root / "indexes" / bare_digest(fixture["revision"]) / INDEX_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / source.name
    store._write_immutable(target, payload)
    identifier = "sha256:" + source.stem
    store._atomic_write(directory / "CURRENT", (identifier + "\n").encode("ascii"))


def _reference_corpus(queries: list[dict[str, Any]], fixture: dict[str, Any]) -> dict[str, Any]:
    queries_hash = digest_json(queries)
    core = {
        "schema": "an-kla/reference-corpus-core-v1",
        "queries_sha256": queries_hash,
        "records_sha256": fixture["records_sha256"],
        "fixture_sha256": fixture["fixture_sha256"],
    }
    corpus_hash = digest_json(core)
    try:
        provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError("invalid_reference_provenance") from None
    provenance = validate_provenance_manifest(provenance, corpus_hash)
    return {
        "schema": "an-kla/reference-eval-corpus-v1",
        "fixture_version": FIXTURE_VERSION,
        "queries_sha256": queries_hash,
        "records_sha256": fixture["records_sha256"],
        "fixture_sha256": fixture["fixture_sha256"],
        "corpus_sha256": corpus_hash,
        "provenance_manifest_sha256": digest_json(provenance),
    }


def run_reference_retrieval_benchmark(*, measure_latency: bool = False) -> dict[str, Any]:
    if not detect_fts5():
        raise ValueError("fts5_required_for_reference_benchmark")
    queries = read_queries_v2(QUERIES_PATH)
    if set(query["category"] for query in queries) != set(CATEGORIES):
        raise ValueError("invalid_reference_corpus")
    if any(not TOKEN.findall(query["query"]) for query in queries):
        raise ValueError("invalid_reference_query_terms")
    with ExitStack() as stack:
        stores: dict[str, MemoryStore] = {}
        fixtures = []
        for state in REFERENCE_STATES:
            directory = stack.enter_context(tempfile.TemporaryDirectory())
            store, fixture = build_reference_store(directory)
            configure_index_state(store, fixture, state)
            stores[state] = store
            fixtures.append(fixture)
        if any(canonical_json(item["fixture_core"]) != canonical_json(fixtures[0]["fixture_core"]) for item in fixtures[1:]):
            raise ValueError("reference_fixture_not_deterministic")
        corpus = _reference_corpus(queries, fixtures[0])
        report = evaluate_states_v2(
            stores, queries, (256, 512, 1024, 4096), (1, 3, 5, 10), corpus,
            measure_latency=measure_latency,
        )
    expected = {
        "absent": ("scan-fallback/v1", "index_unavailable"),
        "fresh": (INDEX_PROFILE, "none"),
        "corrupt": ("scan-fallback/v1", "index_hash_mismatch"),
        "stale": ("scan-fallback/v1", "index_unresolvable"),
    }
    for row in report["rows"]:
        for run in row["runs"]:
            state = run["index_fixture_state"]
            if state == "not_applicable":
                continue
            wanted = expected[state]
            observations = [(run["actual_profile"], run["degradation"])] + [
                (item["actual_profile"], item["degradation"]) for item in run["budgets"]
            ]
            if any(item != wanted for item in observations):
                raise ValueError("reference_index_state_mismatch")
    return report


def run_reference_benchmark(*, measure_latency: bool = False) -> dict[str, Any]:
    retrieval_report = run_reference_retrieval_benchmark(
        measure_latency=measure_latency
    )
    queries = read_queries_v2(QUERIES_PATH)
    from .evaluation_strategies import evaluate_all_strategies

    with tempfile.TemporaryDirectory() as directory:
        store, _fixture = build_reference_store(directory)
        strategy_reports = evaluate_all_strategies(
            store,
            queries,
            (256, 512, 1024, 4096),
            (1, 3, 5, 10),
            retrieval_report["corpus"],
        )
    overlap = strategy_reports[0]
    for retrieval_row, strategy_row in zip(
        retrieval_report["rows"], overlap["rows"]
    ):
        scan = retrieval_row["runs"][0]
        if scan["ranking"]["ranked_ids"] != strategy_row["ranking"]["ranked_ids"]:
            raise ValueError("overlap_baseline_mismatch")
        if any(
            left["selected_ids"] != right["selected_ids"]
            for left, right in zip(scan["budgets"], strategy_row["budgets"])
        ):
            raise ValueError("overlap_baseline_mismatch")
    return {
        "schema": "an-kla/reference-benchmark-v1",
        "untrusted_memory_data": True,
        "retrieval_report": retrieval_report,
        "strategy_reports": strategy_reports,
        "conclusion": {
            "ranking_change_authorized": False,
            "reason": "metrics_require_future_adr",
        },
    }


__all__ = [
    "FIXTURE_VERSION", "PROVENANCE_PATH", "QUERIES_PATH", "RECORD_ENTRIES",
    "build_reference_store", "configure_index_state",
    "run_reference_benchmark", "run_reference_retrieval_benchmark",
]
