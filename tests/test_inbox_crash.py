"""Criterio 3 (ADR-0063): corte brusco del encolado y del vaciado en los ocho puntos del ADR.

``InProcessCutTests`` corre cada punto con un corte simulado (``raise Crash``) y es rápida: está
en el ``unittest discover`` normal. ``Kill9MatrixTests`` es la prueba real: ``kill -9`` sobre un
proceso trabajador, 20 repeticiones por punto (los ocho del ADR y un corte dentro del último
recurso uno a uno). Es **lenta**: se salta salvo con ``AN_KLA_SLOW_KILL9=1`` y ``scripts/ci_local.py``
tiene un paso propio que la corre con esa variable. Escribe su resumen en
``AN_KLA_KILL9_REPORT`` (por defecto, en el directorio temporal).

La «siguiente invocación de escritura» del criterio 3 es ``inbox drain`` **y** ``remember`` (la orden
real del CLI): ``AN_KLA_KILL9_NEXT`` (por defecto ``drain,remember``) elige cuáles; las dos corren con
la misma variable y en el mismo paso de ``ci_local``.
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
from tests.remember_support import cli as run_cli

ROOT = Path(__file__).resolve().parents[1]
SLOW = os.environ.get("AN_KLA_SLOW_KILL9") == "1"
REPETITIONS = int(os.environ.get("AN_KLA_KILL9_REPS", "20"))
ENTRIES = 5
NEXT_INVOCATIONS = tuple(n for n in os.environ.get("AN_KLA_KILL9_NEXT", "drain,remember").split(",") if n)


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
        self.assertEqual((second["state"], second.get("drain_error")), ("drained", None), second)
        state = measure(self.store, acked)  # R1-06: el criterio 3 mide tras la 2.ª invocación
        third = inbox_drain.drain(self.store)  # la 3.ª sólo comprueba que no se atasca
        self.assertEqual((third["state"], third["batches"], third.get("drain_error")), ("drained", [], None))
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


def second_invocation(project: Path, nxt: str, tag: str) -> tuple[dict, str | None]:
    """La 2.ª invocación de escritura: ``inbox drain`` (trabajador) o ``remember`` (CLI real).

    Devuelve su resultado JSON y, con ``remember``, el texto confirmado (``committed`` o ``queued``)."""

    if nxt == "drain":
        done = worker(project, "drain", str(project), "-")
        stdout, stderr = done.stdout, done.stderr
        text = None
    else:
        text = f"{tag}-remember"
        done = run_cli(project, "remember", "--text-file", "-", stdin=text, timeout=180)
        stdout, stderr = done.stdout, done.stderr
    try:
        return json.loads(stdout), text
    except ValueError:
        return {"state": "unreadable", "stderr": stderr[-300:]}, None


def one_repetition(point: str, index: int, base: Path, nxt: str = "drain") -> dict:
    tag = f"{point}-{index}"
    (base / f"{nxt}-{tag}").mkdir(parents=True)
    project = make_project((base / f"{nxt}-{tag}").resolve())
    store = MemoryStore(project)
    store.initialize()
    factory = EntryFactory(store)
    texts = [f"{tag}-{n}" for n in range(ENTRIES)]
    for text in texts:
        factory.write(text)
    if point == "enq_tmp":
        killed = worker(project, "enqueue", str(project), f"{tag}-sin-confirmar", "corte").returncode == -9
    else:
        killed = worker(project, "drain", str(project), point).returncode == -9
    second_state, remembered = second_invocation(project, nxt, tag)
    acked = texts + ([remembered] if remembered and second_state.get("state") in ("committed", "queued") else [])
    measured = measure(MemoryStore(project), acked)  # R1-06: tras la 2.ª invocación (criterio 3)
    third = worker(project, "drain", str(project), "-")  # la 3.ª sólo comprueba que no se atasca
    try:
        third_state = json.loads(third.stdout)
    except ValueError:
        third_state = {"state": "unreadable"}
    return {
        "point": point, "index": index, "next": nxt, "killed": killed, "second_state": second_state.get("state"),
        "second_error": second_state.get("drain_error"),
        "second_branches": sorted({c["branch"] for c in second_state.get("closed_journals", [])}),
        "third_state": third_state.get("state"), "third_batches": len(third_state.get("batches", [])),
        **measured,
    }


def summarize(rows: list[dict], nxt: str = "drain") -> dict:
    summary: dict = {}
    for point in (*inbox_cuts.POINTS, *inbox_cuts.EXTRA_POINTS):
        mine = [r for r in rows if r["point"] == point and r["next"] == nxt]
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
            "second_drain_errors": dict(Counter(r["second_error"] for r in mine if r["second_error"])),
        }
    return summary


@unittest.skipUnless(SLOW, "prueba lenta: define AN_KLA_SLOW_KILL9=1 (la corre scripts/ci_local.py)")
class Kill9MatrixTests(unittest.TestCase):
    def test_kill9_matrix_eight_points_plus_one_by_one(self) -> None:
        points = (*inbox_cuts.POINTS, *inbox_cuts.EXTRA_POINTS)
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="kill9-") as temp:
            jobs = [(point, index, nxt) for nxt in NEXT_INVOCATIONS for point in points for index in range(REPETITIONS)]
            with ThreadPoolExecutor(max_workers=int(os.environ.get("AN_KLA_KILL9_JOBS", "4"))) as pool:
                rows = list(pool.map(lambda job: one_repetition(job[0], job[1], Path(temp), job[2]), jobs))
        summaries = {nxt: summarize(rows, nxt) for nxt in NEXT_INVOCATIONS}
        report = Path(os.environ.get("AN_KLA_KILL9_REPORT") or Path(tempfile.gettempdir()) / "an-kla-kill9-summary.json")
        # La clave `points` conserva el resumen de la siguiente invocación `drain` (formato de B2).
        document = {"repetitions_per_point": REPETITIONS, "seconds": round(time.monotonic() - started, 1),
                    "next_invocations": list(NEXT_INVOCATIONS), "by_next": summaries}
        if "drain" in summaries:
            document["points"] = summaries["drain"]
        report.write_text(json.dumps(document, indent=1, sort_keys=True))
        for nxt, summary in summaries.items():
            ok_state = "drained" if nxt == "drain" else "committed"
            for point, row in summary.items():
                with self.subTest(next=nxt, point=point):
                    self.assertEqual(row["repetitions"], REPETITIONS)
                    self.assertEqual(row["killed"], REPETITIONS, "el punto de corte no se alcanzó siempre")
                    self.assertEqual((row["lost"], row["duplicates"], row["verify_failures"]), (0, 0, 0))
                    self.assertEqual((row["open_journals_current"], row["durability_incomplete"]), (0, 0))
                    self.assertEqual(row["residues"], {"markers": 0, "pending": 0, "tmp": 0, "rejected": 0})
                    self.assertEqual(row["second_states"], {ok_state: REPETITIONS})  # R1-06
                    self.assertEqual(row["second_drain_errors"], {})
                    self.assertEqual(row["third_not_drained"], 0)


if __name__ == "__main__":
    unittest.main()
