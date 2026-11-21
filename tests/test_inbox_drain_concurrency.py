"""Criterio 2 (ADR-0063): 8 procesos encolan 200 recuerdos mientras un vaciador corre en bucle.

Un vaciado final deja ``pending/``, ``rejected/`` y ``tmp/`` vacíos; ``verify`` ok; 0 perdidos,
0 duplicados, 0 conflictos CAS (``write_plan_base_changed``), 0 ``write_lock_busy`` con un solo
vaciador y 0 errores de encolado. Se reportan el p95 de encolado y el número de ``queued``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from collections import Counter
from pathlib import Path

from an_kla import inbox, inbox_drain
from an_kla.store import MemoryStore
from tests import proc_support
from tests.inbox_support import AGENT_ENV, GIT_ENV, make_project

ROOT = Path(__file__).resolve().parents[1]
CLIENTS, PER_CLIENT = 8, 25
REPORT = os.environ.get("AN_KLA_CONC_REPORT")


def spawn(test: unittest.TestCase, *args: str) -> subprocess.Popen:
    return proc_support.spawn_for(test,
        [sys.executable, "-m", "tests.inbox_conc_worker", *args], cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={**os.environ, **GIT_ENV, **AGENT_ENV, "AN_KLA_NO_UPDATE_CHECK": "1", "PYTHONDONTWRITEBYTECODE": "1"},
    )


def lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


class ConcurrencyTests(unittest.TestCase):
    def test_eight_enqueuers_one_looping_drainer_and_a_final_drain(self) -> None:
        temp = tempfile.mkdtemp(prefix="conc-")  # todo vive aquí dentro, registros incluidos, y se borra al acabar la prueba, falle o no
        self.addCleanup(shutil.rmtree, temp, True)
        project = Path(temp).resolve() / "proj"
        project.mkdir()
        make_project(project)
        store = MemoryStore(project)
        store.initialize()
        logs = Path(temp).resolve() / "logs"
        logs.mkdir()
        stop = logs / "STOP"
        self.addCleanup(lambda: stop.parent.exists() and stop.write_text("x"))  # el vaciador en bucle para aunque algo falle
        clients = [spawn(self, "enqueue", str(project), f"c{c}", str(PER_CLIENT), str(logs / f"enq{c}.jsonl")) for c in range(CLIENTS)]
        drainer = spawn(self, "drain_loop", str(project), str(logs / "drain.jsonl"), str(stop))
        started = time.monotonic()
        for client in clients:
            _, err = client.communicate(timeout=300)
            self.assertEqual(client.returncode, 0, err[-500:])
        wall = time.monotonic() - started
        stop.write_text("x")
        _, err = drainer.communicate(timeout=120)
        self.assertEqual(drainer.returncode, 0, err[-500:])
        finals = []
        for _ in range(6):
            finals.append(inbox_drain.drain(store))
            if finals[-1]["state"] == "drained" and not finals[-1]["batches"]:
                break
        rows = [row for c in range(CLIENTS) for row in lines(logs / f"enq{c}.jsonl")]
        acked = [row["text"] for row in rows if row["state"] == "queued"]
        errors = Counter(row.get("code") for row in rows if row["state"] != "queued")
        texts = [str(r["text"]) for r in store.snapshot().records["facts"]]
        counts = Counter(texts)
        drains = lines(logs / "drain.jsonl")
        latency = sorted(row["elapsed"] for row in rows if row["state"] == "queued")
        p95 = latency[int(len(latency) * 0.95) - 1] * 1000
        status = inbox.read_status(store)
        cas = sum(1 for d in drains + finals if d.get("drain_error") == "write_plan_base_changed")
        busy = sum(1 for d in drains + finals if d.get("drain_error") == "write_lock_busy")
        queued = sum(1 for d in drains if d["state"] == "queued") + sum(1 for d in finals if d["state"] == "queued")
        summary = {
            "enqueued_acked": len(acked), "enqueue_errors": dict(errors), "committed_distinct": len(counts),
            "lost": sorted(set(acked) - set(counts)), "duplicates": sum(1 for c in counts.values() if c > 1),
            "verify_ok": store.verify()["ok"], "cas_conflicts": cas, "write_lock_busy": busy,
            "queued_responses": queued, "drain_calls": len(drains),
            "drain_commits": sum(1 for d in drains if d["batches"]),
            "enqueue_p95_ms": round(p95, 2), "wall_seconds": round(wall, 2),
            "max_write_lock_seconds": max([d["max_lock"] for d in drains] + [f["metrics"]["max_write_lock_seconds"] for f in finals]),
            "pending": status["pending"]["count"], "rejected": status["rejected"]["count"],
            "tmp": status["tmp"]["count"], "inflight": status["inflight"]["count"],
            "final_states": [f["state"] for f in finals],
        }
        if REPORT:
            Path(REPORT).write_text(json.dumps(summary, indent=1, sort_keys=True))
        self.assertEqual(summary["enqueue_errors"], {})
        self.assertEqual(summary["enqueued_acked"], CLIENTS * PER_CLIENT)
        self.assertEqual(summary["committed_distinct"], CLIENTS * PER_CLIENT)
        self.assertEqual((summary["lost"], summary["duplicates"]), ([], 0))
        self.assertTrue(summary["verify_ok"])
        self.assertEqual((summary["cas_conflicts"], summary["write_lock_busy"]), (0, 0))
        self.assertEqual((summary["pending"], summary["rejected"], summary["tmp"], summary["inflight"]), (0, 0, 0, 0))
        self.assertEqual(summary["queued_responses"], 0)  # un solo vaciador: nadie más pide write_lock


if __name__ == "__main__":
    unittest.main()
