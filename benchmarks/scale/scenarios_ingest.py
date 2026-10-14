"""Escenarios de ingesta y lecturas — columna gobernada (issue #149 P0).

Vía gobernada pública (`plan_write` + `commit_write_plan`) con aborto por
umbral; cada celda registra su punto de aborto como resultado falsable.
"""
from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Any

from benchmarks.scale.core import (
    RARE_TERM,
    TEXT,
    dir_size_bytes,
    governed_write,
    make_store,
    stats,
    subject_refs,
    timed,
)
from an_kla.context_view import context_view
from an_kla.index import build_index
from an_kla.retrieval import INDEX_PROFILE, SCAN_PROFILE, retrieve
from an_kla.store import MemoryStore


def _new_cell(ws: Path, name: str) -> tuple[Path, MemoryStore, str]:
    cell_ws = ws / name
    cell_ws.mkdir(parents=True, exist_ok=True)
    store, root = make_store(cell_ws)
    return cell_ws, store, root


def run_ingest_cell(
    ws: Path,
    th: dict[str, Any],
    *,
    subjects: int,
    supersede_ratio: float,
    n_target: int,
    read_points: list[int],
    seed: int = 7,
) -> dict[str, Any]:
    cfg = th["ingest_governed"]
    name = f"ingest-s{subjects}-r{int(supersede_ratio * 100)}"
    cell_ws, store, cur = _new_cell(ws, name)
    refs = subject_refs(store, subjects)
    rng = random.Random(seed)
    written: list[str] = []
    latencies: list[float] = []
    supersedes_done = 0
    abort: dict[str, Any] | None = None
    snapshots: list[dict[str, Any]] = []
    t_cell = time.perf_counter()

    for i in range(n_target):
        do_supersede = (
            supersede_ratio > 0 and written and rng.random() < supersede_ratio
        )
        if do_supersede:
            target = rng.choice(written)
            record = {
                "id": f"f-{i}",
                "subject_ref": refs[i % len(refs)],
                "payload": {"text": TEXT.format(i=i)},
            }
            cur, elapsed, _ = governed_write(
                store, cur, record, operation="supersede", supersedes=target
            )
            supersedes_done += 1
        else:
            record = {
                "id": f"f-{i}",
                "subject_ref": refs[i % len(refs)],
                "payload": {"text": TEXT.format(i=i)},
            }
            cur, elapsed, _ = governed_write(store, cur, record)
            written.append(record["id"])
        latencies.append(elapsed)

        window = latencies[-cfg["sustained_window"]:]
        if len(window) == cfg["sustained_window"]:
            ordered = sorted(window)
            median = ordered[len(ordered) // 2]
            if median > cfg["abort_sustained_latency_s"]:
                abort = {
                    "abort_reason": "sustained_latency",
                    "at_n": i + 1,
                    "window_median_s": median,
                }
                break
        if time.perf_counter() - t_cell > cfg["cell_max_wall_s"]:
            abort = {"abort_reason": "cell_budget", "at_n": i + 1}
            break

        if (i + 1) in read_points:
            snapshots.append(
                {
                    "n": i + 1,
                    "snapshot_s": timed(store.snapshot),
                    "read_current_s": timed(store.read_current),
                }
            )

    result: dict[str, Any] = {
        "schema": "an-kla/scale-battery-cell/v1",
        "scenario": name,
        "internal_commit_diagnostic": False,
        "params": {
            "subjects": subjects,
            "supersede_ratio": supersede_ratio,
            "n_target": n_target,
            "seed": seed,
        },
        "n_written": len(latencies),
        "records_added": len(written),
        "supersedes_done": supersedes_done,
        "abort": abort,
        "write_latency_s": stats(latencies),
        "snapshot_points": snapshots,
        "store_bytes": dir_size_bytes(cell_ws),
        "wall_s": time.perf_counter() - t_cell,
    }

    if latencies and not abort:
        result["reads"] = _measure_reads(store, cur)
    result["ok"] = True
    return result


def _measure_reads(store: MemoryStore, cur: str) -> dict[str, Any]:
    # Término raro: sólo un registro de cada 500 lo menciona.
    build_index(store)
    return {
        "retrieve_scan_common_s": timed(
            lambda: retrieve(store, "quetzal", 4096, profile=SCAN_PROFILE)
        ),
        "retrieve_scan_rare_s": timed(
            lambda: retrieve(store, RARE_TERM, 4096, profile=SCAN_PROFILE)
        ),
        "retrieve_index_rare_s": timed(
            lambda: retrieve(store, RARE_TERM, 4096, profile=INDEX_PROFILE)
        ),
        "context_view_limit50_s": timed(
            lambda: context_view(store, revision=cur, limit=50)
        ),
    }


def run_ingest_governed(
    ws: Path, th: dict[str, Any], overrides: dict[str, Any] | None = None
) -> dict[str, Any]:
    cfg = th["ingest_governed"]
    ov = overrides or {}
    n_target = ov.get("n_target", cfg["n_target"])
    read_points = [p for p in ov.get("read_points", cfg["read_points"]) if p <= n_target]
    cells: list[dict[str, Any]] = []
    for cell in cfg["cells"]:
        cells.append(
            run_ingest_cell(
                ws,
                th,
                subjects=cell["subjects"],
                supersede_ratio=cell["supersede_ratio"],
                n_target=n_target,
                read_points=read_points,
            )
        )
    return {
        "schema": "an-kla/scale-battery-scenario/v1",
        "scenario": "ingest_governed",
        "ok": all(c["ok"] for c in cells),
        "cells": cells,
    }


def _rare_payload(i: int) -> str:
    # 1 de cada 500 menciona el término raro; el resto, texto común.
    if i % 500 == 0:
        return TEXT.format(i=i) + " " + RARE_TERM
    return TEXT.format(i=i)


def seed_rare_records(store: MemoryStore, cur: str, total: int, refs: list[str]) -> str:
    """Siembra término-raro en stores internos: 1/500 registros."""
    batch_size = 500
    facts: list[dict[str, Any]] = []
    for i in range(total):
        facts.append(
            {
                "id": f"f-{i}",
                "subject_ref": refs[i % len(refs)],
                "payload": {"text": _rare_payload(i)},
            }
        )
        if len(facts) == batch_size:
            cur = store.commit(
                expected_current_hash=cur, checkpoint_patch={}, facts=facts
            )
            facts = []
    if facts:
        cur = store.commit(expected_current_hash=cur, checkpoint_patch={}, facts=facts)
    return cur
