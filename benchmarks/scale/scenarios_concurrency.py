"""Batería v2 (issue #167) — concurrencia 4×8 y término raro índice sí/no.

`run_concurrency_v2`: misma mecánica de subprocesos reales que la v1
(#149) — reutiliza sus bucles de escritor/lector — pero reporta la **tasa**
de `LockBusyError` (fracción de intentos y por segundo) contra el deadline
de lock vigente (10 s), no sólo el total.

`run_rare_query_index`: consulta con término raro (1 de cada N registros)
en dos fases sobre el mismo store: **sin índice** (INDEX_PROFILE degrada a
scan porque nunca existió referencia de índice) y **con índice** (tras
`rebuild-index` por CLI). Control con SCAN_PROFILE en ambas fases.
"""
from __future__ import annotations

import multiprocessing
import queue as queue_mod
import time
from pathlib import Path
from typing import Any

from benchmarks.scale.core import (
    RARE_TERM,
    TEXT,
    cli,
    internal_commit,
    make_store,
    stats,
    subject_refs,
    timed,
)
from an_kla.retrieval import INDEX_PROFILE, SCAN_PROFILE, retrieve


def run_concurrency_v2(
    ws: Path, th: dict[str, Any], overrides: dict[str, Any] | None = None
) -> dict[str, Any]:
    # Bucles de trabajador compartidos con la v1: mismo régimen de carga,
    # agregación distinta (tasas, no sólo totales).
    from benchmarks.scale.scenarios_ops import (
        _preload,
        _reader_loop,
        _summarize,
        _writer_loop,
    )

    cfg = th["concurrency_v2"]
    ov = overrides or {}
    writers = ov.get("writers", cfg["writers"])
    readers = ov.get("readers", cfg["readers"])
    duration_s = ov.get("duration_s", cfg["duration_s"])
    preload = ov.get("preload_records", cfg["preload_records"])

    conc_ws = ws / "concurrency-v2"
    conc_ws.mkdir(parents=True, exist_ok=True)
    _preload(conc_ws, preload)

    queue: Any = multiprocessing.Queue()
    procs = [
        multiprocessing.Process(
            target=_writer_loop, args=(conc_ws, duration_s, f"w{k}", queue)
        )
        for k in range(writers)
    ] + [
        multiprocessing.Process(
            target=_reader_loop, args=(conc_ws, duration_s, f"r{k}", queue)
        )
        for k in range(readers)
    ]
    t0 = time.perf_counter()
    for p in procs:
        p.start()
    for p in procs:
        p.join(duration_s + 30)
    wall = time.perf_counter() - t0

    writers_out: list[dict[str, Any]] = []
    readers_out: list[dict[str, Any]] = []
    try:
        while True:
            item = queue.get_nowait()
            item["latency_s"] = _summarize(item.pop("latency_s"))
            (writers_out if item["role"] == "writer" else readers_out).append(item)
    except queue_mod.Empty:
        pass

    for w in writers_out:
        attempts = w["ok"] + w["busy"] + w["cas"]
        w["attempts"] = attempts
        w["lock_busy_rate"] = (w["busy"] / attempts) if attempts else None
        w["lock_busy_per_s"] = (w["busy"] / duration_s) if duration_s else None
    attempts_total = sum(w["attempts"] for w in writers_out)
    busy_total = sum(w["busy"] for w in writers_out)
    reader_rounds = sum(r["ops"] for r in readers_out)

    return {
        "schema": "an-kla/scale-battery-scenario/v1",
        "scenario": "concurrency_v2",
        "battery_phase": "v2-#167",
        "internal_commit_diagnostic": False,
        "params": {
            "writers": writers, "readers": readers,
            "duration_s": duration_s, "preload_records": preload,
            "lock_deadline_s": cfg["lock_deadline_s"],
        },
        "writers": sorted(writers_out, key=lambda x: x["tag"]),
        "readers": sorted(readers_out, key=lambda x: x["tag"]),
        "totals": {
            "writer_attempts_total": attempts_total,
            "governed_writes_ok": sum(w["ok"] for w in writers_out),
            "lock_busy_total": busy_total,
            # Tasa de LockBusyError (issue #167): fracción de intentos de
            # escritura que agotaron el deadline de lock (10 s vigente).
            "lock_busy_rate": (
                busy_total / attempts_total if attempts_total else None
            ),
            "lock_busy_per_s": busy_total / duration_s if duration_s else None,
            "cas_conflicts_total": sum(w["cas"] for w in writers_out),
            "reader_op_rounds": reader_rounds,
            "reader_rounds_per_s": reader_rounds / duration_s if duration_s else None,
            "writer_p50s_s": [
                w["latency_s"]["p50"]
                for w in writers_out
                if w["latency_s"].get("p50") is not None
            ],
        },
        "wall_s": wall,
        "ok": len(writers_out) == writers and len(readers_out) == readers,
    }


def _seed_rare_store(
    rq_ws: Path, records: int, subjects: int, batch: int, rare_every: int
) -> tuple[Any, str, float]:
    store, cur = make_store(rq_ws)
    refs = subject_refs(store, max(subjects, 1))

    def payload(i: int) -> str:
        text = TEXT.format(i=i)
        if rare_every > 0 and i % rare_every == 0:
            return text + " " + RARE_TERM
        return text

    t_build = time.perf_counter()
    n = 0
    while n < records:
        facts = [
            {
                "id": f"f-{n + i}",
                "subject_ref": refs[(n + i) % len(refs)],
                "payload": {"text": payload(n + i)},
            }
            for i in range(min(batch, records - n))
        ]
        cur = internal_commit(store, cur, facts)
        n += len(facts)
    return store, cur, time.perf_counter() - t_build


def _rare_phase(
    store: Any, budget: int, *, with_index: bool
) -> dict[str, Any]:
    def indexed() -> dict[str, Any]:
        return retrieve(store, RARE_TERM, budget, profile=INDEX_PROFILE)

    def scanned() -> dict[str, Any]:
        return retrieve(store, RARE_TERM, budget, profile=SCAN_PROFILE)

    rare_index = indexed()
    rare_scan = scanned()
    phase: dict[str, Any] = {
        "phase": "con_indice" if with_index else "sin_indice",
        "rare_profile": rare_index["profile"],
        "rare_degradation": rare_index["degradation"],
        "rare_selected": len(rare_index["selected"]),
        "scan_profile": rare_scan["profile"],
        "scan_selected": len(rare_scan["selected"]),
        "retrieve_index_rare_s": timed(indexed),
        "retrieve_scan_rare_s": timed(scanned),
    }
    if (
        rare_index["profile"] == INDEX_PROFILE
        and phase["retrieve_index_rare_s"] > 0
    ):
        phase["speedup_index_vs_scan"] = (
            phase["retrieve_scan_rare_s"] / phase["retrieve_index_rare_s"]
        )
    return phase


def run_rare_query_index(
    ws: Path, th: dict[str, Any], overrides: dict[str, Any] | None = None
) -> dict[str, Any]:
    from benchmarks.scale.core import fts5_available

    cfg = th["rare_query"]
    ov = overrides or {}
    records = ov.get("records", cfg["records"])
    subjects = ov.get("subjects", cfg["subjects"])
    batch = ov.get("batch", cfg["batch"])
    rare_every = ov.get("rare_every", cfg["rare_every"])
    budget = ov.get("budget", cfg["budget"])

    rq_ws = ws / "rare-query-index"
    rq_ws.mkdir(parents=True, exist_ok=True)
    store, cur, build_s = _seed_rare_store(rq_ws, records, subjects, batch, rare_every)

    # Fase sin índice: ningún commit de la siembra creó referencia de índice
    # para esta línea (maybe_reindex sólo propaga si el padre ya tiene una),
    # así que INDEX_PROFILE debe degradar a scan de forma observable.
    no_index = _rare_phase(store, budget, with_index=False)

    rebuild: dict[str, Any] = {}
    with_index: dict[str, Any] = {}
    fts5 = fts5_available()
    if fts5:
        t0 = time.perf_counter()
        rebuild = cli(rq_ws, "rebuild-index")
        rebuild_s = time.perf_counter() - t0
        with_index = _rare_phase(store, budget, with_index=True)
        with_index["rebuild_index_s"] = rebuild_s
        with_index["rebuild_ok"] = bool(rebuild.get("ok"))
    else:
        with_index = {
            "phase": "con_indice",
            "skipped": "fts5_unavailable",
            "rebuild_ok": False,
        }

    rare_found = no_index["rare_selected"] >= 1
    if fts5:
        degraded_no_index = no_index["rare_profile"] == SCAN_PROFILE
        indexed_con_index = (
            with_index.get("rare_profile") == INDEX_PROFILE
            and with_index.get("rare_degradation") == "none"
            and with_index.get("rare_selected", 0) >= 1
        )
        ok = bool(rare_found and degraded_no_index and indexed_con_index)
    else:
        ok = bool(rare_found)

    return {
        "schema": "an-kla/scale-battery-scenario/v1",
        "scenario": "rare_query_index",
        "battery_phase": "v2-#167",
        "internal_commit_diagnostic": True,
        "label": "siembra interna (MemoryStore.commit) etiquetada; consulta "
                 "término raro índice sí/no con rebuild-index por CLI",
        "params": {
            "records": records,
            "subjects": subjects,
            "batch": batch,
            "rare_every": rare_every,
            "budget": budget,
            "fts5": fts5,
        },
        "build_s": build_s,
        "phases": [no_index, with_index],
        "rebuild_index": rebuild or None,
        "ok": ok,
    }
