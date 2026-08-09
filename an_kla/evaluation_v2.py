"""Ordered, budget-separated retrieval evaluation (ADR-0025)."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from statistics import mean, median
from time import perf_counter_ns
from typing import Any, Mapping, Sequence

from .canonical import digest_json
from .index import INDEX_PROFILE
from .record_text import record_text
from .retrieval import SCAN_PROFILE, TOKEN, retrieve
from .store import MemoryStore, STREAMS


CATEGORIES = ("synthetic", "kairos_sanitized", "handoff_exact")
REFERENCE_STATES = ("absent", "fresh", "corrupt", "stale")
RANKING_BUDGET_METHOD = "eligible-record-text-utf8-sum/v1"


def _utf8(values: Sequence[str]) -> list[str]:
    return sorted(values, key=lambda value: value.encode("utf-8"))


def _integer_list(value: Any, code: str) -> list[int]:
    if (
        not isinstance(value, (list, tuple))
        or not value
        or any(not isinstance(item, int) or isinstance(item, bool) or item <= 0 for item in value)
    ):
        raise ValueError(code)
    result = list(value)
    if result != sorted(set(result)):
        raise ValueError(code)
    return result


def _validate_queries_v2(raw_queries: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_queries, (list, tuple)) or not raw_queries:
        raise ValueError("invalid_evaluation_query")
    queries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_queries:
        if not isinstance(raw, dict) or set(raw) != {
            "schema", "id", "category", "query", "relevant", "streams"
        }:
            raise ValueError("invalid_evaluation_query")
        if raw["schema"] != "an-kla/retrieval-eval-query-v2":
            raise ValueError("invalid_evaluation_query")
        identifier = raw["id"]
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("invalid_evaluation_query")
        if identifier in seen:
            raise ValueError("duplicate_evaluation_query_id")
        seen.add(identifier)
        if raw["category"] not in CATEGORIES:
            raise ValueError("invalid_evaluation_query")
        if not isinstance(raw["query"], str) or not raw["query"]:
            raise ValueError("invalid_evaluation_query")
        relevant = raw["relevant"]
        if (
            not isinstance(relevant, list)
            or not relevant
            or any(not isinstance(item, str) or not item for item in relevant)
            or relevant != _utf8(relevant)
            or len(relevant) != len(set(relevant))
        ):
            raise ValueError("invalid_evaluation_query")
        streams = raw["streams"]
        if (
            not isinstance(streams, list)
            or not streams
            or any(not isinstance(item, str) or item not in STREAMS for item in streams)
            or len(streams) != len(set(streams))
        ):
            raise ValueError("invalid_evaluation_query")
        if streams != [stream for stream in STREAMS if stream in streams]:
            raise ValueError("invalid_evaluation_query")
        queries.append(deepcopy(raw))
    return sorted(queries, key=lambda item: item["id"].encode("utf-8"))


def read_queries_v2(path: str | Path) -> list[dict[str, Any]]:
    try:
        source = Path(path) if isinstance(path, (str, Path)) else path
        lines = source.read_text(encoding="utf-8").splitlines()
    except (OSError, TypeError, UnicodeError):
        raise ValueError("invalid_evaluation_query") from None
    raw_queries = []
    for line in lines:
        if not line.strip():
            continue
        try:
            raw_queries.append(json.loads(line))
        except json.JSONDecodeError:
            raise ValueError("invalid_evaluation_query") from None
    return _validate_queries_v2(raw_queries)


def _all_records(snapshot: Any) -> list[dict[str, Any]]:
    return [
        {"stream": stream, "record": deepcopy(dict(record))}
        for stream in STREAMS
        for record in snapshot.records[stream]
    ]


def external_corpus(snapshot: Any, queries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    queries_hash = digest_json(list(queries))
    records_hash = digest_json(_all_records(snapshot))
    core = {
        "schema": "an-kla/external-eval-corpus-v1",
        "revision": snapshot.revision_id,
        "queries_sha256": queries_hash,
        "records_sha256": records_hash,
    }
    return {**core, "corpus_sha256": digest_json(core)}


def _eligible(snapshot: Any, streams: Sequence[str]) -> list[tuple[str, dict[str, Any], str]]:
    result: list[tuple[str, dict[str, Any], str]] = []
    seen: set[str] = set()
    for stream in streams:
        for source in snapshot.records[stream]:
            record = dict(source)
            identifier = record.get("id")
            if not isinstance(identifier, str) or not identifier:
                continue
            if identifier in seen:
                raise ValueError("ambiguous_evaluation_record_id")
            seen.add(identifier)
            if record.get("status", record.get("nu", "vigente")) not in {
                "vigente", "active", None
            }:
                continue
            rendered = record_text(record)
            if rendered:
                result.append((stream, record, rendered))
    return result


def ranking_budget(snapshot: Any, streams: Sequence[str]) -> int:
    return sum(len(rendered.encode("utf-8")) for _stream, _record, rendered in _eligible(snapshot, streams))


def _ratio(numerator: int, denominator: int) -> dict[str, Any]:
    if denominator <= 0:
        raise ValueError("invalid_evaluation_denominator")
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator,
    }


def _ranking_metrics(ranked: list[str], relevant: list[str], k_values: list[int]) -> dict[str, Any]:
    wanted = set(relevant)
    first = next((index for index, identifier in enumerate(ranked, 1) if identifier in wanted), None)
    precision = []
    recall = []
    for k in k_values:
        hits = sum(identifier in wanted for identifier in ranked[:k])
        precision.append({"k": k, "metric": _ratio(hits, k)})
        recall.append({"k": k, "metric": _ratio(hits, len(relevant))})
    return {
        "precision_at_k": precision,
        "recall_at_k": recall,
        "first_relevant_rank": first,
        "mrr": _ratio(0, 1) if first is None else _ratio(1, first),
        "unretrieved_relevant": [item for item in relevant if item not in set(ranked)],
    }


def _budget_metrics(selected: list[str], ranked: list[str], relevant: list[str]) -> dict[str, Any]:
    wanted = set(relevant)
    hits = sum(identifier in wanted for identifier in selected)
    return {
        "precision_at_budget": _ratio(hits, len(selected) or 1),
        "budget_recall": _ratio(hits, len(relevant)),
        "excluded_relevant_by_budget": [
            identifier for identifier in ranked if identifier in wanted and identifier not in set(selected)
        ],
    }


def _scores(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [{"id": item["id"], "score": item["score"]} for item in items]


def _timed_call(durations: list[int] | None, *args: Any, **kwargs: Any) -> dict[str, Any]:
    if durations is None:
        return retrieve(*args, **kwargs)
    started = perf_counter_ns()
    result = retrieve(*args, **kwargs)
    durations.append(perf_counter_ns() - started)
    return result


def _profile_run(
    store: MemoryStore,
    revision: str,
    query: Mapping[str, Any],
    budgets: list[int],
    k_values: list[int],
    requested_profile: str,
    state: str,
    durations: list[int] | None,
) -> dict[str, Any]:
    frozen = store.snapshot(revision)
    ceiling = ranking_budget(frozen, query["streams"])
    baseline = _timed_call(
        durations, store, query["query"], ceiling,
        profile=requested_profile, streams=query["streams"], revision_id=revision,
    )
    if baseline["excluded_summary"].get("budget", 0) != 0 or baseline["used_bytes"] > ceiling:
        raise ValueError("evaluation_ranking_budget_incomplete")
    ranked = [item["id"] for item in baseline["selected"]]
    metrics = _ranking_metrics(ranked, query["relevant"], k_values)
    ranking = {
        "ranking_budget": ceiling,
        "ranked_ids": ranked,
        "ranked_scores": _scores(baseline["selected"]),
        **metrics,
    }
    budget_rows = []
    for budget in budgets:
        result = _timed_call(
            durations, store, query["query"], budget,
            profile=requested_profile, streams=query["streams"], revision_id=revision,
        )
        selected = [item["id"] for item in result["selected"]]
        budget_rows.append({
            "budget_bytes": budget,
            "actual_profile": result["profile"],
            "degradation": result["degradation"],
            "selected_ids": selected,
            "selected_scores": _scores(result["selected"]),
            **_budget_metrics(selected, ranked, query["relevant"]),
            "used_bytes": result["used_bytes"],
            "excluded_summary": deepcopy(result["excluded_summary"]),
        })
    return {
        "requested_profile": requested_profile,
        "index_fixture_state": state,
        "actual_profile": baseline["profile"],
        "degradation": baseline["degradation"],
        "ranking": ranking,
        "budgets": budget_rows,
        "parity": None,
    }


def _compare(
    left_ids: list[str], left_scores: list[dict[str, Any]],
    right_ids: list[str], right_scores: list[dict[str, Any]],
    budget: int | None, actual_profile: str, degradation: str,
) -> dict[str, Any]:
    common = set(left_ids) & set(right_ids)
    left_common = [item for item in left_ids if item in common]
    right_common = [item for item in right_ids if item in common]
    left_map = {item["id"]: item["score"] for item in left_scores if item["id"] in common}
    right_map = {item["id"]: item["score"] for item in right_scores if item["id"] in common}
    return {
        "budget_bytes": budget,
        "exact_selected_equal": left_ids == right_ids,
        "selected_id_set_equal": set(left_ids) == set(right_ids),
        "common_order_equal": left_common == right_common,
        "common_scores_equal": left_map == right_map,
        "comparable_as_index": actual_profile == INDEX_PROFILE and degradation == "none",
    }


def _attach_parity(scan: Mapping[str, Any], candidate: dict[str, Any]) -> None:
    ranking = _compare(
        scan["ranking"]["ranked_ids"], scan["ranking"]["ranked_scores"],
        candidate["ranking"]["ranked_ids"], candidate["ranking"]["ranked_scores"],
        None, candidate["actual_profile"], candidate["degradation"],
    )
    budgets = []
    for left, right in zip(scan["budgets"], candidate["budgets"]):
        budgets.append(_compare(
            left["selected_ids"], left["selected_scores"],
            right["selected_ids"], right["selected_scores"],
            right["budget_bytes"], right["actual_profile"], right["degradation"],
        ))
    candidate["parity"] = {"ranking": ranking, "budgets": budgets}


def _macro(runs: list[Mapping[str, Any]], field: str) -> float:
    return mean(run["ranking"][field]["value"] for run in runs)


def _aggregate(rows: list[dict[str, Any]], budgets: list[int], k_values: list[int]) -> dict[str, Any]:
    categories = ["all", *(category for category in CATEGORIES if any(row["category"] == category for row in rows))]
    run_keys = [
        (run["requested_profile"], run["index_fixture_state"])
        for run in rows[0]["runs"]
    ]
    groups = []
    for profile, state in run_keys:
        for category in categories:
            chosen = [row for row in rows if category == "all" or row["category"] == category]
            runs = [
                next(run for run in row["runs"] if run["requested_profile"] == profile and run["index_fixture_state"] == state)
                for row in chosen
            ]
            precision_at_k = []
            recall_at_k = []
            for index, k in enumerate(k_values):
                precision_at_k.append({"k": k, "value": mean(run["ranking"]["precision_at_k"][index]["metric"]["value"] for run in runs)})
                recall_at_k.append({"k": k, "value": mean(run["ranking"]["recall_at_k"][index]["metric"]["value"] for run in runs)})
            budget_groups = []
            for index, budget in enumerate(budgets):
                budget_groups.append({
                    "budget_bytes": budget,
                    "precision_at_budget_macro": mean(run["budgets"][index]["precision_at_budget"]["value"] for run in runs),
                    "budget_recall_macro": mean(run["budgets"][index]["budget_recall"]["value"] for run in runs),
                    "excluded_relevant_by_budget_total": sum(len(run["budgets"][index]["excluded_relevant_by_budget"]) for run in runs),
                })
            groups.append({
                "profile": profile,
                "index_fixture_state": state,
                "category": category,
                "query_count": len(runs),
                "mrr_macro": _macro(runs, "mrr"),
                "precision_at_k_macro": precision_at_k,
                "recall_at_k_macro": recall_at_k,
                "budgets": budget_groups,
            })
    return {"groups": groups}


def _counts(comparisons: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    matches = sum(all(item[key] for key in (
        "exact_selected_equal", "selected_id_set_equal",
        "common_order_equal", "common_scores_equal",
    )) for item in comparisons)
    return {
        "total": len(comparisons),
        "exact_matches": matches,
        "mismatches": len(comparisons) - matches,
        "actual_index": sum(item["comparable_as_index"] for item in comparisons),
        "degraded": sum(not item["comparable_as_index"] for item in comparisons),
    }


def _parity_summary(rows: list[dict[str, Any]], states: Sequence[str]) -> dict[str, Any]:
    by_state = []
    for state in states:
        runs = [
            next(run for run in row["runs"] if run["requested_profile"] == INDEX_PROFILE and run["index_fixture_state"] == state)
            for row in rows
        ]
        ranking = [run["parity"]["ranking"] for run in runs]
        budget = [item for run in runs for item in run["parity"]["budgets"]]
        rank_counts = _counts(ranking)
        budget_counts = _counts(budget)
        if rank_counts["mismatches"] or budget_counts["mismatches"]:
            raise ValueError("evaluation_parity_mismatch")
        by_state.append({
            "index_fixture_state": state,
            "ranking": rank_counts,
            "budgets": budget_counts,
        })
    return {"by_state": by_state}


def evaluate_states_v2(
    state_stores: Mapping[str, MemoryStore],
    queries: Sequence[Mapping[str, Any]],
    budgets: Sequence[int],
    k_values: Sequence[int],
    corpus: Mapping[str, Any] | None,
    *,
    measure_latency: bool = False,
) -> dict[str, Any]:
    checked_budgets = _integer_list(budgets, "invalid_evaluation_budget")
    checked_k = _integer_list(k_values, "invalid_evaluation_k")
    checked_queries = _validate_queries_v2(queries)
    states = list(state_stores)
    if not states or any(state not in {*REFERENCE_STATES, "external"} for state in states):
        raise ValueError("invalid_evaluation_profile")
    observed = [store.read_current() for store in state_stores.values()]
    revision = observed[0]
    if any(item != revision for item in observed[1:]):
        raise ValueError("evaluation_fixture_revision_mismatch")
    first_store = state_stores[states[0]]
    corpus_value = (
        external_corpus(first_store.snapshot(revision), checked_queries)
        if corpus is None
        else deepcopy(dict(corpus))
    )
    durations: list[int] | None = [] if measure_latency else None
    rows = []
    for query in checked_queries:
        scan = _profile_run(
            first_store, revision, query, checked_budgets, checked_k,
            SCAN_PROFILE, "not_applicable", durations,
        )
        runs = [scan]
        for state, store in state_stores.items():
            candidate = _profile_run(
                store, revision, query, checked_budgets, checked_k,
                INDEX_PROFILE, state, durations,
            )
            _attach_parity(scan, candidate)
            runs.append(candidate)
        rows.append({
            "id": query["id"],
            "category": query["category"],
            "query_sha256": digest_json(query),
            "relevant": list(query["relevant"]),
            "streams": list(query["streams"]),
            "runs": runs,
        })
    config_core = {
        "schema": "an-kla/retrieval-eval-config-v2",
        "budgets": checked_budgets,
        "k_values": checked_k,
        "profiles": [SCAN_PROFILE, INDEX_PROFILE],
        "index_fixture_states": states,
        "ranking_budget_method": RANKING_BUDGET_METHOD,
    }
    latency = None
    if durations is not None:
        latency = {
            "non_contractual": True,
            "clock": "monotonic_ns",
            "warmups": 0,
            "samples": durations,
            "min_ns": min(durations),
            "median_ns": median(durations),
            "max_ns": max(durations),
        }
    return {
        "schema": "an-kla/retrieval-eval-report-v2",
        "untrusted_memory_data": True,
        "revision": revision,
        "corpus": corpus_value,
        "configuration": {**config_core, "config_sha256": digest_json(config_core)},
        "query_count": len(rows),
        "rows": rows,
        "aggregate": _aggregate(rows, checked_budgets, checked_k),
        "parity_summary": _parity_summary(rows, states),
        "latency": latency,
    }


def evaluate_retrieval_v2(
    store: MemoryStore,
    queries_path: str | Path,
    budgets: Sequence[int],
    k_values: Sequence[int] = (1, 3, 5, 10),
    *,
    measure_latency: bool = False,
) -> dict[str, Any]:
    queries = read_queries_v2(queries_path)
    return evaluate_states_v2(
        {"external": store}, queries, budgets, k_values, None,
        measure_latency=measure_latency,
    )


__all__ = [
    "CATEGORIES", "REFERENCE_STATES", "RANKING_BUDGET_METHOD",
    "evaluate_retrieval_v2", "evaluate_states_v2", "external_corpus",
    "ranking_budget", "read_queries_v2",
]
