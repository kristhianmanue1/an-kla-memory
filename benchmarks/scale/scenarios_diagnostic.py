"""Columna diagnóstica interna (issue #149 P0): lecturas a gran escala.

Stores construidos con `MemoryStore.commit()` interno (etiquetado
`internal_commit_diagnostic=true`): reproduce las sondas del issue como
artefacto oficial de la batería, separado de la columna gobernada.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from benchmarks.scale.core import (
    dir_size_bytes,
    internal_commit,
    make_store,
    subject_refs,
    timed,
)
from benchmarks.scale.scenarios_ingest import _measure_reads, _rare_payload
from an_kla.context_view import context_view


def run_reads_diagnostic(
    ws: Path, th: dict[str, Any], overrides: dict[str, Any] | None = None
) -> dict[str, Any]:
    cfg = th["reads_diagnostic"]
    ov = overrides or {}
    points = ov.get("records_points", cfg["records_points"])
    subjects = ov.get("subjects", cfg["subjects"])
    batch = ov.get("batch", cfg["batch"])

    many = _diagnostic_pass(ws / "reads-diagnostic", points, subjects, batch, full=True)
    # Régimen patológico de la sonda del #149: un único sujeto acumula todo
    # el universo y context_view cae en view_subject_exceeds_budget tras
    # pagar la derivación completa. Eje sujetos de la matriz P0.
    single = _diagnostic_pass(
        ws / "reads-diagnostic-s1", points, 1, batch, full=False
    )
    return {
        "schema": "an-kla/scale-battery-scenario/v1",
        "scenario": "reads_diagnostic",
        "internal_commit_diagnostic": True,
        "label": "columna interna (MemoryStore.commit): diagnóstico, no vía pública",
        "params": {"records_points": points, "subjects": subjects, "batch": batch},
        "ok": bool(many.get("ok") and single.get("ok")),
        "subjects_many": many,
        "subjects_single": single,
    }


def _diagnostic_pass(
    diag_ws: Path,
    points: list[int],
    subjects: int,
    batch: int,
    *,
    full: bool,
) -> dict[str, Any]:
    diag_ws.mkdir(parents=True, exist_ok=True)
    store, cur = make_store(diag_ws)
    refs = subject_refs(store, max(subjects, 1))

    rows: list[dict[str, Any]] = []
    t_all = time.perf_counter()
    n = 0
    for target in points:
        t_build = time.perf_counter()
        while n < target:
            facts = [
                {
                    "id": f"f-{n + i}",
                    "subject_ref": refs[(n + i) % len(refs)],
                    "payload": {"text": _rare_payload(n + i)},
                }
                for i in range(min(batch, target - n))
            ]
            cur = internal_commit(store, cur, facts)
            n += len(facts)
        rows.append(
            {
                "n": n,
                "build_s": time.perf_counter() - t_build,
                "snapshot_s": timed(store.snapshot),
                "context_view_limit50_s": timed(
                    lambda: context_view(store, revision=cur, limit=50)
                ),
                "store_bytes": dir_size_bytes(diag_ws),
            }
        )
    measurements = dict(rows=rows)
    if full:
        measurements.update(_measure_reads(store, cur))
    else:
        view = context_view(store, revision=cur, limit=50)
        measurements["context_view_outcome_final"] = (
            view.get("code")
            if isinstance(view, dict) and not view.get("ok", True)
            else "ok"
        )
    measurements["wall_s"] = time.perf_counter() - t_all
    measurements["ok"] = True
    measurements["subjects"] = subjects
    return measurements
