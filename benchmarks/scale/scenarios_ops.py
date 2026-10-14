"""Escenarios operacionales P0 (#149): concurrencia, crash, compactación.

Todos sobre stores efímeros del workspace. Concurrencia y crash usan
subprocesos reales; la compactación ejercita la ceremonia gobernada completa
(export create → proposal → compact plan → compact commit) vía CLI público.
"""
from __future__ import annotations

import json
import multiprocessing
import os
import random
import signal
import time
import uuid
from pathlib import Path
from typing import Any

from benchmarks.scale.core import (
    TEXT,
    cli,
    dir_size_bytes,
    internal_commit,
    make_store,
    subject_refs,
    timed,
)

def _preload(ws: Path, records: int) -> str:
    store, cur = make_store(ws)
    refs = subject_refs(store, 1)
    facts = [
        {
            "id": f"seed-{i}",
            "subject_ref": refs[0],
            "payload": {"text": TEXT.format(i=i)},
        }
        for i in range(records)
    ]
    return internal_commit(store, cur, facts)


def _writer_loop(ws: Path, duration_s: float, tag: str, queue: Any) -> None:
    from an_kla.store import LockBusyError, MemoryStore
    from an_kla.write_policy import WritePolicyError

    from benchmarks.scale.core import governed_write

    store = MemoryStore(str(ws))
    ok = busy = cas = 0
    latencies: list[float] = []
    deadline = time.time() + duration_s
    i = 0
    while time.time() < deadline:
        record = {
            "id": f"w-{tag}-{os.getpid()}-{i}",
            "payload": {"text": TEXT.format(i=i)},
        }
        try:
            _cur, elapsed, _ = governed_write(store, store.read_current(), record)
            latencies.append(elapsed)
            ok += 1
            i += 1
        except LockBusyError:
            busy += 1
        except WritePolicyError as exc:
            if exc.code == "write_plan_base_changed":
                cas += 1
            else:
                raise
    queue.put(
        {"role": "writer", "tag": tag, "ok": ok, "busy": busy, "cas": cas,
         "latency_s": latencies}
    )


def _reader_loop(ws: Path, duration_s: float, tag: str, queue: Any) -> None:
    from an_kla.context_view import context_view
    from an_kla.retrieval import SCAN_PROFILE, retrieve
    from an_kla.store import MemoryStore

    store = MemoryStore(str(ws))
    ops = 0
    latencies: list[float] = []
    deadline = time.time() + duration_s
    while time.time() < deadline:
        cur = store.read_current()
        t0 = time.perf_counter()
        retrieve(store, "quetzal", 1024, profile=SCAN_PROFILE)
        retrieve(store, "xochimilco-xenicus-ferrovial", 1024, profile=SCAN_PROFILE)
        context_view(store, revision=cur, limit=50)
        latencies.append(time.perf_counter() - t0)
        ops += 1
    queue.put({"role": "reader", "tag": tag, "ops": ops, "latency_s": latencies})


def run_concurrency(
    ws: Path, th: dict[str, Any], overrides: dict[str, Any] | None = None
) -> dict[str, Any]:
    cfg = th["concurrency"]
    ov = overrides or {}
    writers = ov.get("writers", cfg["writers"])
    readers = ov.get("readers", cfg["readers"])
    duration_s = ov.get("duration_s", cfg["duration_s"])
    preload = ov.get("preload_records", cfg["preload_records"])

    conc_ws = ws / "concurrency"
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
    while not queue.empty():
        item = queue.get()
        item["latency_s"] = _summarize(item.pop("latency_s"))
        (writers_out if item["role"] == "writer" else readers_out).append(item)

    from benchmarks.scale.core import stats

    return {
        "schema": "an-kla/scale-battery-scenario/v1",
        "scenario": "concurrency",
        "internal_commit_diagnostic": False,
        "params": {
            "writers": writers, "readers": readers,
            "duration_s": duration_s, "preload_records": preload,
            "lock_deadline_s": cfg["lock_deadline_s"],
        },
        "writers": sorted(writers_out, key=lambda x: x["tag"]),
        "readers": sorted(readers_out, key=lambda x: x["tag"]),
        "totals": {
            "governed_writes_ok": sum(w["ok"] for w in writers_out),
            "lock_busy_total": sum(w["busy"] for w in writers_out),
            "cas_conflicts_total": sum(w["cas"] for w in writers_out),
            "reader_op_rounds": sum(r["ops"] for r in readers_out),
            "writer_latency_s": stats(
                [s for w in writers_out for s in [w["latency_s"].get("p50")]]
                if writers_out and all(w["latency_s"] for w in writers_out) else []
            ),
        },
        "wall_s": wall,
        "ok": len(writers_out) == writers and len(readers_out) == readers,
    }


def _summarize(latencies: list[float]) -> dict[str, Any]:
    from benchmarks.scale.core import stats

    return stats(latencies)


def _crash_writer(ws: Path) -> None:
    from an_kla.store import MemoryStore

    from benchmarks.scale.core import governed_write

    store = MemoryStore(str(ws))
    i = 0
    while True:
        record = {
            "id": f"c-{os.getpid()}-{i}",
            "payload": {"text": TEXT.format(i=i)},
        }
        governed_write(store, store.read_current(), record)
        i += 1


def run_crash(
    ws: Path, th: dict[str, Any], overrides: dict[str, Any] | None = None
) -> dict[str, Any]:
    cfg = th["crash"]
    ov = overrides or {}
    attempts = ov.get("attempts", cfg["attempts"])
    preload = ov.get("preload_records", cfg["preload_records"])
    delay_min = ov.get("kill_delay_min_s", cfg["kill_delay_min_s"])
    delay_max = ov.get("kill_delay_max_s", cfg["kill_delay_max_s"])
    rng = random.Random(11)

    crash_ws = ws / "crash"
    crash_ws.mkdir(parents=True, exist_ok=True)
    _preload(crash_ws, preload)

    kills: list[dict[str, Any]] = []
    for k in range(attempts):
        p = multiprocessing.Process(target=_crash_writer, args=(crash_ws,))
        p.start()
        time.sleep(rng.uniform(delay_min, delay_max))
        os.kill(p.pid, signal.SIGKILL)
        p.join(10)
        verify = cli(crash_ws, "verify")
        status = cli(crash_ws, "status")
        kills.append(
            {
                "attempt": k + 1,
                "delay_s": None,
                "verify_ok": bool(verify.get("ok")),
                "revision_after": status.get("revision"),
                "revision_number": status.get("revision_number"),
            }
        )
    recover = cli(crash_ws, "recover")
    doctor = cli(crash_ws, "doctor")
    return {
        "schema": "an-kla/scale-battery-scenario/v1",
        "scenario": "crash",
        "internal_commit_diagnostic": False,
        "method": "SIGKILL con retardos sembrados; probabilístico, declarado",
        "params": {"attempts": attempts, "preload_records": preload},
        "kills": kills,
        "verify_all_ok": all(k["verify_ok"] for k in kills),
        "recover": recover,
        "doctor": doctor,
        "ok": all(k["verify_ok"] for k in kills),
    }


def run_compaction(
    ws: Path, th: dict[str, Any], overrides: dict[str, Any] | None = None
) -> dict[str, Any]:
    cfg = th["compaction"]
    ov = overrides or {}
    target_revisions = ov.get("target_revisions", cfg["target_revisions"])

    comp_ws = ws / "compaction"
    comp_ws.mkdir(parents=True, exist_ok=True)
    store, cur = make_store(comp_ws)
    refs = subject_refs(store, 1)
    t_build = time.perf_counter()
    for i in range(target_revisions):
        cur = internal_commit(
            store,
            cur,
            [{
                "id": f"k-{i}",
                "subject_ref": refs[0],
                "payload": {"text": TEXT.format(i=i)},
            }],
        )
    build_s = time.perf_counter() - t_build
    snapshot_before_s = timed(store.snapshot)
    bytes_before = dir_size_bytes(comp_ws)

    bundle = comp_ws / "bundle.tar"
    t0 = time.perf_counter()
    export = cli(comp_ws, "export", "create", "--bundle", str(bundle))
    export_s = time.perf_counter() - t0
    manifest_sha = next(
        (v for k, v in export.items()
         if "manifest" in k and isinstance(v, str) and v.startswith("sha256:")),
        None,
    )
    proposal = {
        "schema": "an-kla/compaction-proposal-v1",
        "base_revision": cur,
        "epoch_id": str(uuid.uuid4()),
        "transaction_id": str(uuid.uuid4()),
        "export_manifest_sha256": manifest_sha,
    }
    proposal_path = comp_ws / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")

    t0 = time.perf_counter()
    plan = cli(comp_ws, "compact", "plan",
               "--proposal", str(proposal_path), "--bundle", str(bundle))
    plan_s = time.perf_counter() - t0
    plan_path = comp_ws / "compact-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    t0 = time.perf_counter()
    commit = cli(comp_ws, "compact", "commit",
                 "--planning-result", str(plan_path), "--expected-current", cur,
                 "--bundle", str(bundle))
    commit_s = time.perf_counter() - t0

    snapshot_after_s = timed(store.snapshot)
    verify = cli(comp_ws, "verify")
    return {
        "schema": "an-kla/scale-battery-scenario/v1",
        "scenario": "compaction",
        "internal_commit_diagnostic": False,
        "deviation_declared": cfg["deviation_declared"],
        "params": {
            "target_revisions": target_revisions,
            "issue_target_revisions": cfg["issue_target_revisions"],
        },
        "timings_s": {
            "build": build_s,
            "export_create": export_s,
            "compact_plan": plan_s,
            "compact_commit": commit_s,
        },
        "bytes": {"before": bytes_before, "after": dir_size_bytes(comp_ws)},
        "snapshot_s": {"before": snapshot_before_s, "after": snapshot_after_s},
        "export_ok": bool(export.get("ok")),
        "plan_ok": bool(plan.get("ok")),
        "commit_ok": bool(commit.get("ok")),
        "commit_result": commit,
        "verify_after": verify,
        "ok": bool(export.get("ok") and plan.get("ok") and commit.get("ok")
                  and verify.get("ok")),
    }
