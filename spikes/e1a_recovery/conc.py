"""8 clientes concurrentes: ``python -m spikes.e1a_recovery.conc <clean|kill|twodrain> <salida.json>``."""

from __future__ import annotations

import json
import os
import random
import shutil
import signal
import statistics
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from an_kla.store import MemoryStore

PY = sys.executable
ENV = {**os.environ, "AN_KLA_NO_UPDATE_CHECK": "1", "PYTHONDONTWRITEBYTECODE": "1",
       "TMPDIR": "/var/tmp/ankla-spike-b2"}
BASE = Path("/var/tmp/ankla-spike-b2/conc")


def spawn(*args: str) -> subprocess.Popen:
    return subprocess.Popen([PY, "-m", "spikes.e1a_recovery.worker", *args],
                            env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def main() -> None:
    mode, out = sys.argv[1], sys.argv[2]
    tag = sys.argv[3] if len(sys.argv) > 3 else ""
    n_clients, per = 8, 25
    project = BASE / (mode + tag)
    shutil.rmtree(project, ignore_errors=True)
    project.mkdir(parents=True)
    MemoryStore(str(project)).initialize()
    logs = project / "logs"
    logs.mkdir()
    stop = logs / "STOP"
    t0 = time.time()
    workers = [spawn("enqueue", str(project), f"c{c}", str(per), str(logs / f"enq{c}.jsonl"))
               for c in range(n_clients)]
    drainers: list[subprocess.Popen] = []
    kills = 0
    if mode in ("clean", "twodrain"):
        for d in range(2 if mode == "twodrain" else 1):
            drainers.append(spawn("drain_loop", str(project), str(logs / f"drain{d}.jsonl"), str(stop)))
        for w in workers:
            w.wait()
    else:  # kill: un vaciador que muere a SIGKILL en instantes aleatorios
        serial = 0
        while any(w.poll() is None for w in workers):
            p = spawn("drain_loop", str(project), str(logs / f"drain-k{serial}.jsonl"), str(stop))
            serial += 1
            time.sleep(random.uniform(0.02, 0.2))
            p.send_signal(signal.SIGKILL)  # siempre: un vaciador no termina solo
            kills += 1
            p.wait()
        for w in workers:
            w.wait()
    stop.write_text("x")
    for d in drainers:
        d.wait()
    t_workers = time.time() - t0
    finals = []
    for _ in range(6):  # vaciado final (hasta dejar pending vacío)
        r = subprocess.run([PY, "-m", "spikes.e1a_recovery.worker", "drain", str(project)],
                           env=ENV, capture_output=True, text=True)
        finals.append(json.loads(r.stdout))
        if finals[-1]["state"] == "idle":
            break
    store = MemoryStore(str(project))
    texts = [r["text"] for r in store.snapshot(store.read_current()).records["facts"]]
    acked, lat, queued_err = [], [], Counter()
    for f in sorted(logs.glob("enq*.jsonl")):
        for line in f.read_text().splitlines():
            row = json.loads(line)
            if row["state"] == "queued":
                acked.append(row["text"])
                lat.append(row["elapsed"])
            else:
                queued_err[row.get("code")] += 1
    drains = []
    for f in sorted(logs.glob("drain*.jsonl")):
        for line in f.read_text().splitlines():
            try:
                drains.append(json.loads(line))
            except ValueError:
                pass  # última línea de un vaciador muerto
    counts = Counter(texts)
    root = Path(store.root) / "inbox"
    lat.sort()
    result = {
        "mode": mode, "clients": n_clients, "enqueued_acked": len(acked), "enqueue_errors": dict(queued_err),
        "committed_distinct": len(counts), "lost": sorted(set(acked) - set(counts)),
        "duplicates": sum(1 for c in counts.values() if c > 1),
        "verify_ok": store.verify()["ok"], "kills": kills,
        "cas_conflicts": sum(d.get("cas_conflicts", 0) for d in drains + finals),
        "write_lock_busy_responses": sum(1 for d in drains + finals if d.get("lock_busy")),
        "drain_calls": len(drains), "drains_committed": sum(1 for d in drains if d.get("state") == "committed"),
        "drain_aborted": Counter(d.get("drain_error") for d in drains + finals if d.get("state") == "aborted"),
        "enqueue_p50_ms": round(statistics.median(lat) * 1000, 2) if lat else None,
        "enqueue_p95_ms": round(lat[int(len(lat) * 0.95) - 1] * 1000, 2) if lat else None,
        "enqueue_max_ms": round(max(lat) * 1000, 2) if lat else None,
        "max_lock_hold_s": round(max((d.get("lock_hold", 0) for d in drains + finals), default=0), 4),
        "pending": len(list((root / "pending").iterdir())), "tmp": len(list((root / "tmp").iterdir())),
        "inflight": len(list((root / "inflight").iterdir())),
        "rejected": len(list((root / "rejected").iterdir())),
        "final_drains": [f.get("state") for f in finals], "wall_s": round(t_workers, 2),
    }
    result["drain_aborted"] = dict(result["drain_aborted"])
    Path(out).write_text(json.dumps(result, indent=1, default=str))
    print(json.dumps(result, default=str))
    shutil.rmtree(project, ignore_errors=True)


if __name__ == "__main__":
    main()
