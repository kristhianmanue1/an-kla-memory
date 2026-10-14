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


def run_reads_diagnostic(
    ws: Path, th: dict[str, Any], overrides: dict[str, Any] | None = None
) -> dict[str, Any]:
    cfg = th["reads_diagnostic"]
    ov = overrides or {}
    points = ov.get("records_points", cfg["records_points"])
    subjects = ov.get("subjects", cfg["subjects"])
    batch = ov.get("batch", cfg["batch"])

    diag_ws = ws / "reads-diagnostic"
    diag_ws.mkdir(parents=True, exist_ok=True)
    store, cur = make_store(diag_ws)
    refs = subject_refs(store, subjects)

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
                "store_bytes": dir_size_bytes(diag_ws),
            }
        )
    measurements = dict(rows=rows)
    measurements.update(_measure_reads(store, cur))
    return {
        "schema": "an-kla/scale-battery-scenario/v1",
        "scenario": "reads_diagnostic",
        "internal_commit_diagnostic": True,
        "label": "columna interna (MemoryStore.commit): diagnóstico, no vía pública",
        "params": {"records_points": points, "subjects": subjects, "batch": batch},
        "ok": True,
        "measurements": measurements,
        "wall_s": time.perf_counter() - t_all,
    }
