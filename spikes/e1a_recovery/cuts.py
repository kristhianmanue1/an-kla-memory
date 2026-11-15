"""Matriz de cortes ``kill -9``: ``python -m spikes.e1a_recovery.cuts <reps> <salida.json>``."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

from an_kla import transactions as tx
from an_kla.store import MemoryStore

BASE = Path("/var/tmp/ankla-spike-b2/cuts")
PY = sys.executable
POINTS = [
    "enq_tmp",               # (i)
    "pre_replace_current",   # (ii)
    "post_replace_current",  # (iii-a) tras _replace_current, antes del recibo current-durable
    "pre_committed_journal", # (iii-b) recibos listos, antes del journal committed
    "post_journal",          # (iv)
    "post_marker",           # extra: marcador sin journal prepared
    "mid_delete",            # extra: pending a medio borrar
    "post_entries_deleted",  # extra: entradas borradas, marcador vivo
]
CONFIGS = {
    "A_adr_literal": ("noop", "drop"),
    "B_r4_sin_cierre": ("noop", "abort"),
    "C_r4_con_cierre": ("write", "abort"),
    "D_spike": ("write", "smart"),
    "E_spike_repair": ("write+repair", "smart"),
}
N_ENTRIES = 5


def run(args: list[str], env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "AN_KLA_NO_UPDATE_CHECK": "1", "PYTHONDONTWRITEBYTECODE": "1",
           "TMPDIR": "/var/tmp/ankla-spike-b2", **(env_extra or {})}
    return subprocess.run([PY, "-m", "spikes.e1a_recovery.worker", *args],
                          capture_output=True, text=True, env=env, timeout=120)


def measure(project: Path, acked: list[str]) -> dict:
    store = MemoryStore(str(project))
    root = Path(store.root)
    verify = store.verify()
    texts = [r["text"] for r in store.snapshot(store.read_current()).records["facts"]]
    counts = Counter(texts)
    journals = Counter()
    open_committed = 0
    open_uncommitted = 0
    receipts_missing_current = 0
    for path in sorted((root / "transactions").glob("*.json")):
        j = json.loads(path.read_bytes())
        journals[j.get("stage")] += 1
        info = tx.inspect_transaction(store, path.stem)
        if j.get("stage") != "committed":
            if info.get("committed") is True:
                open_committed += 1
            else:
                open_uncommitted += 1
        if info.get("committed") is True and info.get("durability_state") != "complete":
            receipts_missing_current += 1
    inbox = root / "inbox"
    ls = lambda d: len([p for p in (inbox / d).iterdir()]) if (inbox / d).exists() else 0  # noqa: E731
    return {
        "lost": sorted(t for t in acked if t not in counts),
        "duplicates": sum(1 for t, c in counts.items() if c > 1),
        "committed_texts": len(counts),
        "verify_ok": verify["ok"] is True,
        "journals": dict(journals),
        "journals_open_but_committed": open_committed,
        "journals_open_uncommitted": open_uncommitted,
        "committed_without_current_receipt": receipts_missing_current,
        "markers": ls("inflight"), "pending": ls("pending"), "tmp": ls("tmp"),
    }


def one(config: str, point: str, i: int) -> dict:
    close_mode, none_mode = CONFIGS[config]
    project = BASE / f"{config}-{point}-{i}"
    shutil.rmtree(project, ignore_errors=True)
    project.mkdir(parents=True)
    MemoryStore(str(project)).initialize()
    acked = []
    for k in range(N_ENTRIES):
        r = run(["enqueue1", str(project), f"{point}-{i}-{k}"])
        assert r.returncode == 0, r.stderr
        acked.append(f"{point}-{i}-{k}")
    first = None
    if point == "enq_tmp":
        first = run(["enqueue1", str(project), f"{point}-{i}-killed"], {"SPIKE_CUT": point})
    else:
        first = run(["drain", str(project), close_mode, none_mode], {"SPIKE_CUT": point})
    killed = first.returncode == -9
    inbox = Path(MemoryStore(str(project)).root) / "inbox"
    before = {d: len(list((inbox / d).iterdir())) for d in ("tmp", "pending", "inflight")}
    jr = Path(MemoryStore(str(project)).root) / "transactions"
    before["journal_stages"] = dict(Counter(
        json.loads(p.read_bytes()).get("stage") for p in jr.glob("*.json")))
    second = run(["drain", str(project), close_mode, none_mode])
    second_out = json.loads(second.stdout) if second.stdout.strip() else {"error": second.stderr[-300:]}
    third = run(["drain", str(project), close_mode, none_mode])
    third_out = json.loads(third.stdout) if third.stdout.strip() else {"error": third.stderr[-300:]}
    result = {"config": config, "point": point, "i": i, "killed": killed,
              "before_second_drain": before, "second": second_out, "third_state": third_out.get("state"),
              **measure(project, acked)}
    shutil.rmtree(project, ignore_errors=True)
    return result


def main() -> None:
    reps, out = int(sys.argv[1]), sys.argv[2]
    configs = sys.argv[3].split(",") if len(sys.argv) > 3 else list(CONFIGS)
    results = []
    for config in configs:
        for point in POINTS:
            for i in range(reps):
                results.append(one(config, point, i))
    Path(out).write_text(json.dumps(results, indent=1, default=str))


if __name__ == "__main__":
    main()
