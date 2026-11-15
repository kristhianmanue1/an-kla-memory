"""Criterio 3 (ADR-0063): corte brusco del encolado y del vaciado en los ocho puntos del ADR.

``InProcessCutTests`` corre cada punto con un corte simulado (``raise Crash``) y es rápida: está
en el ``unittest discover`` normal. ``Kill9MatrixTests`` es la prueba real: ``kill -9`` sobre un
proceso trabajador, 20 repeticiones por punto (los ocho del ADR y un corte dentro del último
recurso uno a uno). Es **lenta**: se salta salvo con ``AN_KLA_SLOW_KILL9=1`` y ``scripts/ci_local.py``
tiene un paso propio que la corre con esa variable. Escribe su resumen en
``AN_KLA_KILL9_REPORT`` (por defecto, en el directorio temporal).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from an_kla import inbox, inbox_drain
from an_kla import transactions as tx
from an_kla.store import MemoryStore
from tests import inbox_cuts
from tests.inbox_support import AGENT_ENV, GIT_ENV, EntryFactory, InboxCase, make_project

ROOT = Path(__file__).resolve().parents[1]
SLOW = os.environ.get("AN_KLA_SLOW_KILL9") == "1"
REPETITIONS = int(os.environ.get("AN_KLA_KILL9_REPS", "20"))
ENTRIES = 5


class Crash(BaseException):
    """Corte simulado: ningún ``except Exception`` lo absorbe."""


def raise_crash() -> None:
    raise Crash()


def measure(store: MemoryStore, acked: list[str]) -> dict:
    """Estado tras la recuperación: lo que el criterio 3 exige en cada corte."""

    texts = [str(row["text"]) for row in store.snapshot(store.read_current()).records["facts"]]
    counts = Counter(texts)
    open_current = durability = 0
    for path in sorted((Path(store.root) / "transactions").glob("*.json")):
        info = tx.inspect_transaction(store, path.stem)
        journal = json.loads(path.read_bytes())
        if journal.get("stage") != "committed" and info.get("candidate_relation") in ("current", "ancestor"):
            open_current += 1
        if info.get("committed") is True and info.get("durability_state") != "complete":
            durability += 1
    status = inbox.read_status(store)
    return {
        "lost": sorted(text for text in acked if text not in counts),
        "duplicates": sum(1 for count in counts.values() if count > 1),
        "verify_ok": store.verify()["ok"] is True,
        "open_journals_current": open_current,
        "durability_incomplete": durability,
        "markers": status["inflight"]["count"],
        "pending": status["pending"]["count"],
        "tmp": status["tmp"]["count"],
        "ignored": status["ignored"]["pending"]["count"] + status["ignored"]["inflight"]["count"],
        "rejected": status["rejected"]["count"],
    }


class InProcessCutTests(InboxCase):
    def prepare(self) -> tuple[EntryFactory, list[str]]:
        factory = EntryFactory(self.store)
        texts = [f"recuerdo {index}" for index in range(ENTRIES)]
        for text in texts:
            factory.write(text)
        return factory, texts

    def check_recovery(self, acked: list[str]) -> None:
        second = inbox_drain.drain(self.store)
        self.assertNotEqual(second["state"], "aborted", second)
        third = inbox_drain.drain(self.store)
        self.assertEqual((third["state"], third["batches"], third.get("drain_error")), ("drained", [], None))
        state = measure(self.store, acked)
        self.assertEqual(state["lost"], [])
        self.assertEqual(state["duplicates"], 0)
        self.assertTrue(state["verify_ok"])
        for key in ("open_journals_current", "durability_incomplete", "markers", "pending", "tmp", "rejected"):
            self.assertEqual(state[key], 0, (key, state))

    def test_every_drain_cut_point_recovers_with_nothing_lost_or_duplicated(self) -> None:
        for point in (*inbox_cuts.POINTS[1:], *inbox_cuts.EXTRA_POINTS):
            with self.subTest(point=point):
                self.tearDown_project()
                factory, texts = self.prepare()
                with inbox_cuts.install(self.store, point, raise_crash):
                    with self.assertRaises(Crash):
                        inbox_drain.drain(self.store)
                self.check_recovery(texts)

    def test_cut_between_fsync_and_publish_leaves_an_orphan_that_the_drain_collects(self) -> None:
        factory, texts = self.prepare()
        with self.assertRaises(Crash):
            inbox.enqueue(self.store, "no confirmada", env=AGENT_ENV, replace=inbox_cuts.enqueue_replace(raise_crash))
        self.assertEqual(len(list((self.inbox / "tmp").iterdir())), 1)
        self.check_recovery(texts)
        self.assertNotIn("no confirmada", [r["text"] for r in self.store.snapshot().records["facts"]])

    def test_the_points_are_the_eight_of_the_adr_plus_one_by_one(self) -> None:
        self.assertEqual(len(inbox_cuts.POINTS), 8)
        self.assertEqual(inbox_cuts.EXTRA_POINTS, ("one_by_one",))

    def tearDown_project(self) -> None:
        """Proyecto limpio entre puntos (los subTests comparten el ``setUp``)."""

        import shutil

        shutil.rmtree(self.project / ".an-kla", ignore_errors=True)
        self.store = MemoryStore(self.project)
        self.store.initialize()
        self.inbox = Path(self.store.root) / "inbox"


def worker(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "tests.inbox_crash_worker", *args],
        cwd=ROOT, capture_output=True, text=True, timeout=180,
        env={**os.environ, **GIT_ENV, **AGENT_ENV, "AN_KLA_NO_UPDATE_CHECK": "1", "PYTHONDONTWRITEBYTECODE": "1"},
    )


def one_repetition(point: str, index: int, base: Path) -> dict:
    (base / f"{point}-{index}").mkdir(parents=True)
    project = make_project((base / f"{point}-{index}").resolve())
    store = MemoryStore(project)
    store.initialize()
    factory = EntryFactory(store)
    texts = [f"{point}-{index}-{n}" for n in range(ENTRIES)]
    for text in texts:
        factory.write(text)
    if point == "enq_tmp":
        killed = worker(project, "enqueue", str(project), f"{point}-{index}-sin-confirmar", "corte").returncode == -9
    else:
        killed = worker(project, "drain", str(project), point).returncode == -9
    second = worker(project, "drain", str(project), "-")
    third = worker(project, "drain", str(project), "-")
    try:
        second_state = json.loads(second.stdout)
        third_state = json.loads(third.stdout)
    except ValueError:
        second_state = third_state = {"state": "unreadable", "stderr": (second.stderr + third.stderr)[-300:]}
    store = MemoryStore(project)
    result = {
        "point": point, "index": index, "killed": killed, "second_state": second_state.get("state"),
        "second_branches": sorted({c["branch"] for c in second_state.get("closed_journals", [])}),
        "third_state": third_state.get("state"), "third_batches": len(third_state.get("batches", [])),
        **measure(store, texts),
    }
    return result


def summarize(rows: list[dict]) -> dict:
    summary: dict = {}
    for point in (*inbox_cuts.POINTS, *inbox_cuts.EXTRA_POINTS):
        mine = [r for r in rows if r["point"] == point]
        summary[point] = {
            "repetitions": len(mine),
            "killed": sum(r["killed"] for r in mine),
            "lost": sum(len(r["lost"]) for r in mine),
            "duplicates": sum(r["duplicates"] for r in mine),
            "verify_failures": sum(not r["verify_ok"] for r in mine),
            "open_journals_current": sum(r["open_journals_current"] for r in mine),
            "durability_incomplete": sum(r["durability_incomplete"] for r in mine),
            "residues": {key: sum(r[key] for r in mine) for key in ("markers", "pending", "tmp", "rejected")},
            "third_not_drained": sum(r["third_state"] != "drained" or r["third_batches"] != 0 for r in mine),
            "second_states": dict(Counter(r["second_state"] for r in mine)),
            "second_branches": dict(Counter(b for r in mine for b in r["second_branches"])),
        }
    return summary


@unittest.skipUnless(SLOW, "prueba lenta: define AN_KLA_SLOW_KILL9=1 (la corre scripts/ci_local.py)")
class Kill9MatrixTests(unittest.TestCase):
    def test_kill9_matrix_eight_points_plus_one_by_one(self) -> None:
        points = (*inbox_cuts.POINTS, *inbox_cuts.EXTRA_POINTS)
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="kill9-") as temp:
            jobs = [(point, index) for point in points for index in range(REPETITIONS)]
            with ThreadPoolExecutor(max_workers=int(os.environ.get("AN_KLA_KILL9_JOBS", "4"))) as pool:
                rows = list(pool.map(lambda job: one_repetition(job[0], job[1], Path(temp)), jobs))
        summary = summarize(rows)
        report = Path(os.environ.get("AN_KLA_KILL9_REPORT") or Path(tempfile.gettempdir()) / "an-kla-kill9-summary.json")
        report.write_text(json.dumps({"repetitions_per_point": REPETITIONS, "seconds": round(time.monotonic() - started, 1),
                                      "points": summary}, indent=1, sort_keys=True))
        for point, row in summary.items():
            with self.subTest(point=point):
                self.assertEqual(row["repetitions"], REPETITIONS)
                self.assertEqual(row["killed"], REPETITIONS, "el punto de corte no se alcanzó siempre")
                self.assertEqual((row["lost"], row["duplicates"], row["verify_failures"]), (0, 0, 0))
                self.assertEqual((row["open_journals_current"], row["durability_incomplete"]), (0, 0))
                self.assertEqual(row["residues"], {"markers": 0, "pending": 0, "tmp": 0, "rejected": 0})
                self.assertEqual(row["third_not_drained"], 0)


if __name__ == "__main__":
    unittest.main()
