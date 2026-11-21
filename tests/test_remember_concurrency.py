"""Criterio 2 (ADR-0063) con la orden real: 8 procesos hacen 200 ``remember`` mientras ``inbox drain`` corre en bucle.

Cada ``remember`` es una invocación nueva del CLI. Un ``inbox drain`` final cierra. Se exige: 200
records distintos, 0 perdidos, 0 duplicados, ``pending/``, ``rejected/``, ``tmp/`` e ``inflight/``
vacíos, ``verify`` ok, 0 conflictos CAS, 0 ``write_lock_busy`` en ``inbox drain`` con un solo
vaciador y 0 errores de encolado. El p95 de ``remember`` y el número de respuestas ``queued`` se
reportan (``AN_KLA_REMEMBER_CONC_REPORT`` escribe el resumen; ``-v`` los muestra).
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

from an_kla import inbox
from an_kla.store import MemoryStore
from tests import proc_support
from tests.inbox_support import make_project
from tests.remember_support import ROOT, cli, cli_env

CLIENTS, PER_CLIENT = 8, 25
DRAIN_DEADLINE = "1200"  # el plazo propio del vaciador en bucle (ADR-0074 §1)
REPORT = os.environ.get("AN_KLA_REMEMBER_CONC_REPORT")


def spawn(test: unittest.TestCase, *args: str) -> subprocess.Popen:
    return proc_support.spawn_for(test,
        [sys.executable, "-m", "tests.remember_conc_worker", *args], cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=cli_env(),
    )


def lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


class RememberConcurrencyTests(unittest.TestCase):
    clients, per_client = CLIENTS, PER_CLIENT

    def after_spawn(self) -> None:
        """Punto de inyección de un fallo en la prueba de limpieza; aquí no hace nada."""

    def test_eight_processes_200_remembers_a_looping_drain_and_a_final_drain(self) -> None:
        temp = tempfile.mkdtemp(prefix="rconc-")  # todo vive aquí dentro, registros incluidos, y se borra al acabar la prueba, falle o no
        self.addCleanup(shutil.rmtree, temp, True)
        project = Path(temp).resolve() / "proj"
        project.mkdir()
        make_project(project)
        self.assertEqual(cli(project, "init").returncode, 0)
        store = MemoryStore(project)
        logs = Path(temp).resolve() / "logs"
        logs.mkdir()
        stop = logs / "STOP"
        self.addCleanup(lambda: stop.parent.exists() and stop.write_text("x"))  # el vaciador en bucle para aunque algo falle
        clients = [spawn(self, str(project), f"c{c}", str(self.per_client), str(logs / f"rem{c}.jsonl")) for c in range(self.clients)]
        drainer = spawn(self, "drain_loop", str(project), str(logs / "drain.jsonl"), str(stop), DRAIN_DEADLINE)
        self.after_spawn()
        started = time.monotonic()
        for client in clients:
            _, err = client.communicate(timeout=900)
            self.assertEqual(client.returncode, 0, err[-500:])
        wall = time.monotonic() - started
        stop.write_text("x")
        _, err = drainer.communicate(timeout=300)
        self.assertEqual(drainer.returncode, 0, err[-500:])
        finals = []
        for _ in range(6):
            done = cli(project, "inbox", "drain")
            finals.append(json.loads(done.stdout))
            if finals[-1]["state"] == "drained" and not finals[-1]["batches"]:
                break
        rows = [row for c in range(CLIENTS) for row in lines(logs / f"rem{c}.jsonl")]
        confirmed = [r["text"] for r in rows if r["state"] in ("committed", "queued")]
        errors = Counter((r["state"], r.get("code")) for r in rows if r["state"] not in ("committed", "queued"))
        counts = Counter(str(r["text"]) for r in store.snapshot().records["facts"])
        drains = lines(logs / "drain.jsonl")
        latency = sorted(r["elapsed"] for r in rows)
        p95 = latency[int(len(latency) * 0.95) - 1] * 1000
        status = inbox.read_status(store)
        drain_errors = Counter(d.get("drain_error") for d in drains + finals if d.get("drain_error"))
        summary = {
            "remember_calls": len(rows), "committed_in_call": sum(r["state"] == "committed" for r in rows),
            "queued_responses_of_remember": sum(r["state"] == "queued" for r in rows),
            "remember_errors": {f"{k[0]}:{k[1]}": v for k, v in errors.items()},
            "remember_drain_errors": dict(Counter(r["drain_error"] for r in rows if r.get("drain_error"))),
            "committed_distinct": len(counts), "lost": sorted(set(confirmed) - set(counts)),
            "duplicates": sum(1 for c in counts.values() if c > 1), "verify_ok": store.verify()["ok"],
            "cas_conflicts": drain_errors.get("write_plan_base_changed", 0)
            + sum(1 for r in rows if r.get("drain_error") == "write_plan_base_changed"),
            "drain_write_lock_busy": drain_errors.get("write_lock_busy", 0), "drain_errors": dict(drain_errors),
            "drain_queued_responses": sum(d["state"] == "queued" for d in drains + finals),
            "drain_calls": len(drains), "drain_commits": sum(1 for d in drains if d.get("batches")),
            "remember_p95_ms": round(p95, 1), "remember_p50_ms": round(latency[len(latency) // 2] * 1000, 1),
            "wall_seconds": round(wall, 1),
            "pending": status["pending"]["count"], "rejected": status["rejected"]["count"],
            "tmp": status["tmp"]["count"], "inflight": status["inflight"]["count"],
            "final_states": [f["state"] for f in finals],
        }
        print("\nREMEMBER-CONC " + json.dumps(summary, sort_keys=True))
        if REPORT:
            Path(REPORT).write_text(json.dumps(summary, indent=1, sort_keys=True))
        self.assertEqual(summary["remember_errors"], {})
        self.assertEqual(summary["remember_calls"], CLIENTS * PER_CLIENT)
        self.assertEqual(summary["committed_distinct"], CLIENTS * PER_CLIENT)
        self.assertEqual((summary["lost"], summary["duplicates"]), ([], 0))
        self.assertTrue(summary["verify_ok"])
        self.assertEqual((summary["cas_conflicts"], summary["drain_write_lock_busy"]), (0, 0))
        # R1-03: `queued` es un desenlace correcto (cada `remember` también vacía y compite por `write_lock`):
        # se reporta, no se exige 0; lo que no puede haber es ningún `drain_error`.
        self.assertEqual(summary["remember_drain_errors"], {})
        self.assertEqual(summary["drain_errors"], {})
        self.assertEqual((summary["pending"], summary["rejected"], summary["tmp"], summary["inflight"]), (0, 0, 0, 0))
        self.assertEqual(summary["final_states"][-1], "drained")


if __name__ == "__main__":
    unittest.main()
