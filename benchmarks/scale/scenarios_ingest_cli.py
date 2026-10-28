"""Batería v2 (issue #167) — ingesta gobernada por CLI de producto.

A diferencia de la columna gobernada de #149 (que llama a `plan_write` +
`commit_write_plan` en proceso), cada escritura de este escenario atraviesa
el CLI público real: `plan-write` → stdout exacto a archivo →
`commit-write-plan`. El umbral de aborto pre-corrido (latencia sostenida con
mediana > umbral en la ventana) es idéntico en semántica al de #149.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from benchmarks.scale.core import (
    TEXT,
    build_authority,
    build_proposal,
    dir_size_bytes,
    make_store,
    stats,
    subject_refs,
)


def _cli_raw(ws: Path, *args: str, timeout: int = 300) -> tuple[int, str, str]:
    """CLI de producto sin parsear: (rc, stdout, stderr) crudos."""
    cmd = [sys.executable, "-m", "an_kla", "--project-root", str(ws), *args]
    out = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "AN_KLA_NO_UPDATE_CHECK": "1"},
    )
    return out.returncode, out.stdout, out.stderr


def _cli_write(
    ws: Path, queue: Path, cur: str, record: dict[str, Any]
) -> tuple[str, float, float, str]:
    """Una escritura por el CLI público; devuelve (rev, s_plan, s_commit, txid).

    Guarda el planning result byte a byte: el CLI exige el stdout exacto de
    `plan-write`, sin reconstrucción (ver --help de commit-write-plan).
    """
    proposal = build_proposal(cur, record)
    authority = build_authority(proposal)
    txid = str(uuid.uuid4())
    prop_path = queue / f"proposal-{txid}.json"
    auth_path = queue / f"authority-{txid}.json"
    plan_path = queue / f"planning-{txid}.json"
    prop_path.write_text(json.dumps(proposal), encoding="utf-8")
    auth_path.write_text(json.dumps(authority), encoding="utf-8")

    t0 = time.perf_counter()
    rc, stdout, stderr = _cli_raw(
        ws, "plan-write", "--proposal", str(prop_path),
        "--authority", str(auth_path),
    )
    plan_s = time.perf_counter() - t0
    if rc != 0:
        raise RuntimeError(f"plan-write rc={rc}: {stderr.strip()[-300:]}")
    plan_path.write_text(stdout, encoding="utf-8")

    t0 = time.perf_counter()
    rc, stdout, stderr = _cli_raw(
        ws, "commit-write-plan", "--expected-current", cur,
        "--proposal", str(prop_path), "--authority", str(auth_path),
        "--planning-result", str(plan_path), "--transaction-id", txid,
    )
    commit_s = time.perf_counter() - t0
    if rc != 0:
        raise RuntimeError(f"commit-write-plan rc={rc}: {stderr.strip()[-300:]}")
    result = json.loads(stdout)
    if not result.get("committed"):
        raise RuntimeError(f"commit no aplicado: {result}")
    for path in (prop_path, auth_path, plan_path):
        path.unlink(missing_ok=True)
    return str(result["revision"]), plan_s, commit_s, txid


def run_ingest_cli(
    ws: Path, th: dict[str, Any], overrides: dict[str, Any] | None = None
) -> dict[str, Any]:
    cfg = th["ingest_cli"]
    ov = overrides or {}
    n_target = ov.get("n_target", cfg["n_target"])

    cell_ws = ws / "ingest-cli"
    cell_ws.mkdir(parents=True, exist_ok=True)
    queue = cell_ws / "queue"
    queue.mkdir(exist_ok=True)
    store, cur = make_store(cell_ws)
    refs = subject_refs(store, 1)

    # Línea base del coste fijo del CLI (arranque de intérprete) para poder
    # separar overhead de subproceso de latencia de escritura al leer resultados.
    t0 = time.perf_counter()
    rc, _stdout, stderr = _cli_raw(cell_ws, "status")
    baseline_status_s = time.perf_counter() - t0
    if rc != 0:
        raise RuntimeError(f"status inicial rc={rc}: {stderr.strip()[-300:]}")

    latencies: list[float] = []
    plans: list[float] = []
    commits: list[float] = []
    abort: dict[str, Any] | None = None
    t_cell = time.perf_counter()
    for i in range(n_target):
        record = {
            "id": f"cli-{i}",
            "subject_ref": refs[0],
            "payload": {"text": TEXT.format(i=i)},
        }
        try:
            cur, plan_s, commit_s, _txid = _cli_write(cell_ws, queue, cur, record)
        except RuntimeError as exc:
            abort = {"abort_reason": "cli_error", "at_n": i + 1,
                     "detail": str(exc)}
            break
        latencies.append(plan_s + commit_s)
        plans.append(plan_s)
        commits.append(commit_s)

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

    return {
        "schema": "an-kla/scale-battery-scenario/v1",
        "scenario": "ingest_cli",
        "battery_phase": "v2-#167",
        "internal_commit_diagnostic": False,
        "method": "cada escritura atraviesa el CLI público (plan-write + "
                  "commit-write-plan) con umbral de aborto pre-corrido",
        "params": {
            "n_target": n_target,
            "abort_sustained_latency_s": cfg["abort_sustained_latency_s"],
            "sustained_window": cfg["sustained_window"],
        },
        "n_written": len(latencies),
        "abort": abort,
        "cli_baseline_status_s": baseline_status_s,
        "write_latency_s": stats(latencies),
        "plan_latency_s": stats(plans),
        "commit_latency_s": stats(commits),
        "store_bytes": dir_size_bytes(cell_ws),
        "wall_s": time.perf_counter() - t_cell,
        "ok": True,
    }
