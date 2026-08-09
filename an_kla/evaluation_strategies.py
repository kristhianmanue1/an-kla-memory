"""Evaluation-only ranking experiments; never imported by retrieval.py."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import math
import platform
import sys
from statistics import mean
from typing import Any, Mapping, Sequence

from .canonical import digest_json
from .evaluation_v2 import (
    CATEGORIES,
    RANKING_BUDGET_METHOD,
    _budget_metrics,
    _eligible,
    _integer_list,
    _ranking_metrics,
    _validate_queries_v2,
    external_corpus,
)
from .retrieval import TOKEN
from .store import MemoryStore


OVERLAP = {
    "schema": "an-kla/retrieval-strategy-v1",
    "name": "overlap/v1",
    "parameters": {
        "tokenizer": "unicode-word-casefold/v1",
        "query_terms": "distinct",
        "score": "distinct-term-overlap",
        "score_encoding": "integer",
        "tie_break": "id-utf8-ascending",
    },
}
BM25 = {
    "schema": "an-kla/retrieval-strategy-v1",
    "name": "bm25-experiment/v1",
    "parameters": {
        "tokenizer": "unicode-word-casefold-list/v1",
        "query_terms": "distinct",
        "document_scope": "eligible-requested-streams",
        "k1": 1.2,
        "b": 0.75,
        "formula": "okapi-bm25/v1",
        "score_encoding": "float-hex",
        "tie_break": "score-desc-id-utf8-ascending",
    },
}
SUMMARY = {
    "schema": "an-kla/retrieval-strategy-v1",
    "name": "summary-indexed-experiment/v1",
    "parameters": {
        "tokenizer": "unicode-word-casefold/v1",
        "query_terms": "distinct",
        "fields": [
            "payload.indexable_text", "record.indexable_text",
            "payload.summary", "record.summary",
        ],
        "score": "distinct-term-overlap",
        "score_encoding": "integer",
        "selection_cost": "record-text-utf8-bytes",
        "tie_break": "id-utf8-ascending",
    },
}
STRATEGIES = (OVERLAP, BM25, SUMMARY)


def _tokens(text: str) -> list[str]:
    return [match.casefold() for match in TOKEN.findall(text)]


def _summary_text(record: Mapping[str, Any]) -> str:
    payload = record.get("payload")
    locations = (
        payload.get("indexable_text") if isinstance(payload, dict) else None,
        record.get("indexable_text"),
        payload.get("summary") if isinstance(payload, dict) else None,
        record.get("summary"),
    )
    return next((value.strip() for value in locations if isinstance(value, str) and value.strip()), "")


def _overlap_rank(eligible: list[tuple[str, dict[str, Any], str]], query: str, summary: bool) -> list[dict[str, Any]]:
    query_terms = set(_tokens(query))
    ranked = []
    for stream, record, rendered in eligible:
        source = _summary_text(record) if summary else rendered
        if not source:
            continue
        score = len(query_terms & set(_tokens(source)))
        if score:
            ranked.append({
                "id": record["id"], "stream": stream, "score_value": score,
                "score": score, "cost_bytes": len(rendered.encode("utf-8")),
            })
    return sorted(ranked, key=lambda item: (-item["score_value"], item["id"]))


def _bm25_rank(eligible: list[tuple[str, dict[str, Any], str]], query: str) -> list[dict[str, Any]]:
    documents = [(stream, record, rendered, _tokens(rendered)) for stream, record, rendered in eligible]
    count = len(documents)
    average = sum(len(tokens) for _stream, _record, _rendered, tokens in documents) / count if count else 0.0
    if count == 0 or average == 0:
        return []
    query_terms = sorted(
        set(_tokens(query)), key=lambda value: value.encode("utf-8")
    )
    document_frequency = {
        term: sum(term in set(tokens) for _stream, _record, _rendered, tokens in documents)
        for term in query_terms
    }
    ranked = []
    for stream, record, rendered, tokens in documents:
        frequencies = Counter(tokens)
        score = 0.0
        for term in query_terms:
            tf = frequencies[term]
            if not tf:
                continue
            df = document_frequency[term]
            inverse = math.log(1.0 + (count - df + 0.5) / (df + 0.5))
            denominator = tf + 1.2 * (1.0 - 0.75 + 0.75 * len(tokens) / average)
            score += inverse * tf * (1.2 + 1.0) / denominator
        if score > 0 and math.isfinite(score):
            ranked.append({
                "id": record["id"], "stream": stream, "score_value": score,
                "score_hex": score.hex(), "cost_bytes": len(rendered.encode("utf-8")),
            })
    return sorted(ranked, key=lambda item: (-item["score_value"], item["id"]))


def _rank(strategy: Mapping[str, Any], eligible: list[tuple[str, dict[str, Any], str]], query: str) -> list[dict[str, Any]]:
    if strategy["name"] == "overlap/v1":
        return _overlap_rank(eligible, query, False)
    if strategy["name"] == "summary-indexed-experiment/v1":
        return _overlap_rank(eligible, query, True)
    return _bm25_rank(eligible, query)


def _score_entries(ranked: Sequence[Mapping[str, Any]], bm25: bool) -> list[dict[str, Any]]:
    field = "score_hex" if bm25 else "score"
    return [{"id": item["id"], field: item[field]} for item in ranked]


def _strategy_row(
    snapshot: Any,
    query: Mapping[str, Any],
    strategy: Mapping[str, Any],
    budgets: list[int],
    k_values: list[int],
) -> dict[str, Any]:
    eligible = _eligible(snapshot, query["streams"])
    ranked = _rank(strategy, eligible, query["query"])
    ids = [item["id"] for item in ranked]
    bm25 = strategy["name"] == "bm25-experiment/v1"
    ranking = {
        "ranking_budget": sum(len(rendered.encode("utf-8")) for _stream, _record, rendered in eligible),
        "ranked_ids": ids,
        "ranked_scores": _score_entries(ranked, bm25),
        **_ranking_metrics(ids, query["relevant"], k_values),
    }
    budget_rows = []
    for budget in budgets:
        selected = []
        used = 0
        excluded = 0
        for item in ranked:
            if used + item["cost_bytes"] > budget:
                excluded += 1
                continue
            selected.append(item)
            used += item["cost_bytes"]
        selected_ids = [item["id"] for item in selected]
        budget_rows.append({
            "budget_bytes": budget,
            "selected_ids": selected_ids,
            "selected_scores": _score_entries(selected, bm25),
            **_budget_metrics(selected_ids, ids, query["relevant"]),
            "used_bytes": used,
            "excluded_summary": {"budget": excluded} if excluded else {},
        })
    return {
        "id": query["id"],
        "category": query["category"],
        "query_sha256": digest_json(query),
        "relevant": list(query["relevant"]),
        "streams": list(query["streams"]),
        "ranking": ranking,
        "budgets": budget_rows,
    }


def _strategy_aggregate(rows: list[dict[str, Any]], budgets: list[int], k_values: list[int]) -> dict[str, Any]:
    categories = ["all", *(category for category in CATEGORIES if any(row["category"] == category for row in rows))]
    groups = []
    for category in categories:
        chosen = [row for row in rows if category == "all" or row["category"] == category]
        groups.append({
            "category": category,
            "query_count": len(chosen),
            "mrr_macro": mean(row["ranking"]["mrr"]["value"] for row in chosen),
            "precision_at_k_macro": [
                {"k": k, "value": mean(row["ranking"]["precision_at_k"][index]["metric"]["value"] for row in chosen)}
                for index, k in enumerate(k_values)
            ],
            "recall_at_k_macro": [
                {"k": k, "value": mean(row["ranking"]["recall_at_k"][index]["metric"]["value"] for row in chosen)}
                for index, k in enumerate(k_values)
            ],
            "budgets": [
                {
                    "budget_bytes": budget,
                    "precision_at_budget_macro": mean(row["budgets"][index]["precision_at_budget"]["value"] for row in chosen),
                    "budget_recall_macro": mean(row["budgets"][index]["budget_recall"]["value"] for row in chosen),
                    "excluded_relevant_by_budget_total": sum(len(row["budgets"][index]["excluded_relevant_by_budget"]) for row in chosen),
                }
                for index, budget in enumerate(budgets)
            ],
        })
    return {"groups": groups}


def _strategy_report(
    snapshot: Any,
    revision: str,
    queries: list[dict[str, Any]],
    checked_budgets: list[int],
    checked_k: list[int],
    strategy: Mapping[str, Any],
    corpus: Mapping[str, Any],
) -> dict[str, Any]:
    if strategy not in STRATEGIES:
        raise ValueError("invalid_evaluation_strategy")
    rows = [_strategy_row(snapshot, query, strategy, checked_budgets, checked_k) for query in queries]
    strategy_hash = digest_json(strategy)
    config_core = {
        "schema": "an-kla/retrieval-strategy-config-v1",
        "budgets": checked_budgets,
        "k_values": checked_k,
        "ranking_budget_method": RANKING_BUDGET_METHOD,
        "strategy_sha256": strategy_hash,
    }
    is_bm25 = strategy["name"] == "bm25-experiment/v1"
    runtime = None
    if is_bm25:
        runtime = {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
            "platform": sys.platform,
            "math_backend": "system-libm",
        }
    return {
        "schema": "an-kla/retrieval-strategy-report-v1",
        "untrusted_memory_data": True,
        "revision": revision,
        "corpus": deepcopy(dict(corpus)),
        "configuration": {**config_core, "config_sha256": digest_json(config_core)},
        "strategy": deepcopy(dict(strategy)),
        "reproducibility": {
            "cross_runtime_byte_stable": not is_bm25,
            "runtime_descriptor": runtime,
        },
        "query_count": len(rows),
        "rows": rows,
        "aggregate": _strategy_aggregate(rows, checked_budgets, checked_k),
        "latency": None,
    }


def evaluate_strategy(
    store: MemoryStore,
    queries: Sequence[Mapping[str, Any]],
    budgets: Sequence[int],
    k_values: Sequence[int],
    strategy: Mapping[str, Any],
    corpus: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    checked_queries = _validate_queries_v2(queries)
    checked_budgets = _integer_list(budgets, "invalid_evaluation_budget")
    checked_k = _integer_list(k_values, "invalid_evaluation_k")
    revision = store.read_current()
    snapshot = store.snapshot(revision)
    corpus_value = (
        external_corpus(snapshot, checked_queries)
        if corpus is None
        else deepcopy(dict(corpus))
    )
    return _strategy_report(
        snapshot, revision, checked_queries, checked_budgets, checked_k,
        strategy, corpus_value,
    )


def evaluate_all_strategies(
    store: MemoryStore,
    queries: Sequence[Mapping[str, Any]],
    budgets: Sequence[int],
    k_values: Sequence[int],
    corpus: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    checked_queries = _validate_queries_v2(queries)
    checked_budgets = _integer_list(budgets, "invalid_evaluation_budget")
    checked_k = _integer_list(k_values, "invalid_evaluation_k")
    revision = store.read_current()
    snapshot = store.snapshot(revision)
    corpus_value = (
        external_corpus(snapshot, checked_queries)
        if corpus is None
        else deepcopy(dict(corpus))
    )
    return [
        _strategy_report(
            snapshot, revision, checked_queries, checked_budgets, checked_k,
            strategy, corpus_value,
        )
        for strategy in STRATEGIES
    ]


__all__ = [
    "BM25", "OVERLAP", "STRATEGIES", "SUMMARY", "evaluate_all_strategies",
    "evaluate_strategy",
]
