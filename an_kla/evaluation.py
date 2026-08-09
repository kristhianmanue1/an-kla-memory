"""Small, reproducible retrieval evaluation for synthetic AN-KLA benchmarks."""

from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Any

from .retrieval import retrieve
from .store import MemoryStore
from .evaluation_v2 import evaluate_retrieval_v2


def read_queries(path: str | Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def evaluate_retrieval(store: MemoryStore, queries_path: str | Path, budget: int) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for query in read_queries(queries_path):
        result = retrieve(store, str(query["query"]), budget)
        selected = {item["id"] for item in result["selected"]}
        relevant = set(query.get("relevant", []))
        true_positive = len(selected & relevant)
        precision = true_positive / len(selected) if selected else (1.0 if not relevant else 0.0)
        recall = true_positive / len(relevant) if relevant else 1.0
        rows.append({
            "id": query["id"],
            "precision": precision,
            "recall": recall,
            "used_bytes": result["used_bytes"],
            "selected": sorted(selected),
        })
    return {
        "schema": "an-kla/retrieval-eval-v1",
        "query_count": len(rows),
        "macro": {
            "precision": mean(row["precision"] for row in rows) if rows else 0.0,
            "recall": mean(row["recall"] for row in rows) if rows else 0.0,
            "used_bytes": mean(row["used_bytes"] for row in rows) if rows else 0.0,
        },
        "rows": rows,
    }


__all__ = ["evaluate_retrieval", "evaluate_retrieval_v2", "read_queries"]
