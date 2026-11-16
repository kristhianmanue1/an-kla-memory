"""Arreglos de la ronda 2 del vaciado (ADR-0063 D1, B2): prefiltro, enumeración propia, gemelas, directorios y listados acotados."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from an_kla import inbox, inbox_drain
from an_kla.store import MemoryStore
from tests.inbox_support import EntryFactory
from tests.test_inbox_drain import DrainCase, facts, policy_skip, validates


class Round2Tests(DrainCase):
    def committed_target(self) -> str:
        self.factory.write("objetivo")
        return self.drain()["committed"]["entries"][0]["record_id"]

    def test_r2_01_a_policy_rejected_supersede_never_blocks_a_valid_one(self) -> None:
        target = self.committed_target()
        skipped = self.factory.write("sustituye A", target_id=target)
        valid = self.factory.write("sustituye B", target_id=target)
        with policy_skip("sustituye A"):
            result = self.drain()
        self.assertEqual([i["entry"] for i in result["committed"]["entries"]], [valid])
        self.assertEqual([(i["entry"], i["code"]) for i in result["rejected"]["entries"]], [(skipped, "remember_policy_skip")])
        self.assertEqual(facts(self.store)[target]["status"], "sustituida")

    def test_r2_01_among_those_that_passed_the_oldest_wins(self) -> None:
        target = self.committed_target()
        older = self.factory.write("uno", target_id=target)
        newer = self.factory.write("dos", target_id=target)
        result = self.drain()
        self.assertEqual([i["entry"] for i in result["committed"]["entries"]], [older])
        self.assertEqual([(i["entry"], i["code"]) for i in result["rejected"]["entries"]], [(newer, "supersedes:duplicate_target")])

    def test_r2_02_unsafe_names_are_rejected_with_any_entry_names_semantics(self) -> None:
        real = inbox.entry_names
        only_regular = lambda store: [n for n in real(store) if (self.paths.pending / n).is_file() and not (self.paths.pending / n).is_symlink()]  # noqa: E731
        no_dirs = lambda store: [n for n in real(store) if not (self.paths.pending / n).is_dir()]  # noqa: E731
        for label, lister in (("B1", real), ("sin directorios", no_dirs), ("sólo regulares", only_regular), ("vacío", lambda store: [])):
            with self.subTest(label=label), mock.patch.object(inbox, "entry_names", lister), \
                    mock.patch.object(inbox_drain, "entry_names", lister, create=True):
                self.tearDown_project()
                fifo = self.factory.fresh_name()
                self.paths.pending.mkdir(parents=True, exist_ok=True)
                os.mkfifo(self.paths.pending / fifo)
                link = self.factory.fresh_name()
                os.symlink(self.project / "fuera", self.paths.pending / link)
                hard = self.factory.write("enlace duro")
                os.link(self.paths.pending / hard, self.project / "otro-nombre")
                result = self.drain()
                self.assertEqual(
                    {i["entry"]: i["code"] for i in result["rejected"]["entries"]},
                    {fifo: "inbox_entry_unsafe", link: "inbox_entry_unsafe", hard: "inbox_entry_unsafe"},
                )
                self.assertEqual(self.names(self.paths.pending), [])

    def tearDown_project(self) -> None:
        import shutil

        shutil.rmtree(self.project / ".an-kla", ignore_errors=True)
        shutil.rmtree(self.project / "otro-nombre", ignore_errors=True)
        (self.project / "otro-nombre").unlink(missing_ok=True)
        self.store = MemoryStore(self.project)
        self.store.initialize()
        self.factory = EntryFactory(self.store)
        self.paths = inbox.inbox_paths(self.store)

    def test_r2_03_twin_of_a_rejected_entry_is_rejected_not_removed(self) -> None:
        first = self.factory.write("gemela")
        twin = self.factory.write("gemela")
        with policy_skip("gemela"):
            result = self.drain()
        self.assertEqual(
            sorted((i["entry"], i["code"]) for i in result["rejected"]["entries"]),
            sorted([(first, "remember_policy_skip"), (twin, "remember_policy_skip")]),
        )
        self.assertEqual(result["duplicates_removed"], {"count": 0, "names": [], "truncated": False})
        self.assertEqual(len(self.names(self.paths.rejected)), 4)  # dos entradas + dos .reason
        self.assertEqual((self.names(self.paths.pending), len(facts(self.store))), ([], 0))

    def test_r2_03_twin_of_a_committed_entry_is_removed_only_after_the_commit(self) -> None:
        first = self.factory.write("gemela")
        twin = self.factory.write("gemela")
        result = self.drain()
        self.assertEqual([i["entry"] for i in result["committed"]["entries"]], [first])
        self.assertEqual(result["duplicates_removed"]["names"], [twin])
        self.assertEqual(result["rejected"]["count"], 0)

    def test_r2_03_twin_stays_pending_when_the_conserved_one_is_not_committed(self) -> None:
        first = self.factory.write("gemela")
        twin = self.factory.write("gemela")
        with mock.patch.object(self.store, "_write_segment", side_effect=OSError(5, "io")):
            result = self.drain()
        self.assertEqual(result["state"], "aborted")
        self.assertEqual(self.names(self.paths.pending), sorted([first, twin]))
        self.assertEqual(result["duplicates_removed"]["count"], 0)
        again = self.drain()
        self.assertEqual((again["committed"]["count"], again["duplicates_removed"]["names"]), (1, [twin]))

    def test_r2_04_pending_with_only_a_directory_named_like_an_entry_is_idle(self) -> None:
        folder = self.factory.fresh_name()
        self.paths.pending.mkdir(parents=True, exist_ok=True)
        (self.paths.pending / folder).mkdir()
        with mock.patch.object(MemoryStore, "write_lock", side_effect=AssertionError("no debía pedir write_lock")):
            result = self.drain()
        self.assertEqual((result["state"], result["metrics"]["attempts"], result["metrics"]["ignored"]), ("drained", 1, 1))
        self.assertEqual(result["batches"], [])
        self.assertTrue((self.paths.pending / folder).is_dir())

    def test_r2_05_duplicates_removed_is_capped_with_truncated(self) -> None:
        run = inbox_drain.Run()
        run.duplicates_removed = [f"{n}.json" for n in range(inbox_drain.MAX_LISTED + 5)]
        body = inbox_drain._result(run, "drained", "present")
        self.assertEqual(body["duplicates_removed"]["count"], inbox_drain.MAX_LISTED + 5)
        self.assertEqual(len(body["duplicates_removed"]["names"]), inbox_drain.MAX_LISTED)
        self.assertTrue(body["duplicates_removed"]["truncated"])
        validates(body)
        run.duplicates_removed = ["a.json"]
        self.assertFalse(inbox_drain._result(run, "drained", "present")["duplicates_removed"]["truncated"])


if __name__ == "__main__":
    unittest.main()
