"""Arreglos de la ronda 2 del vaciado (ADR-0063 D1, B2): prefiltro, enumeración propia, gemelas, directorios y listados acotados."""

from __future__ import annotations

import json
import os
import stat
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


class UnsafeInodeTests(DrainCase):
    """ADENDA R3-02 (B4): un inodo inseguro no se mueve a `rejected/`; sólo queda su evidencia."""

    def plant(self) -> tuple[str, str, str, Path]:
        self.paths.pending.mkdir(parents=True, exist_ok=True)
        fifo = self.factory.fresh_name()
        os.mkfifo(self.paths.pending / fifo)
        link = self.factory.fresh_name()
        os.symlink("/etc/hostname-secreto-destino", self.paths.pending / link)
        hard = self.factory.write("enlace duro")
        elsewhere = self.project / "otro-nombre"
        os.link(self.paths.pending / hard, elsewhere)
        return fifo, link, hard, elsewhere

    def test_evidence_only_and_the_name_is_unlinked_from_pending(self) -> None:
        fifo, link, hard, elsewhere = self.plant()
        result = self.drain()
        self.assertEqual({i["entry"]: i["code"] for i in result["rejected"]["entries"]},
                         {n: "inbox_entry_unsafe" for n in (fifo, link, hard)})
        self.assertEqual(self.names(self.paths.pending), [])
        self.assertEqual(self.names(self.paths.rejected), sorted(f"{n}.reason" for n in (fifo, link, hard)))
        for name, kind in ((fifo, "fifo"), (link, "symlink"), (hard, "regular")):
            raw = (self.paths.rejected / f"{name}.reason").read_bytes()
            body = json.loads(raw)
            self.assertEqual((body["code"], body["lstat"]["type"]), ("inbox_entry_unsafe", kind))
            self.assertEqual(set(body["lstat"]), {"type", "mode", "st_nlink", "size"})
            self.assertNotIn(b"hostname-secreto", raw)  # nunca el destino de un enlace
        self.assertEqual(json.loads((self.paths.rejected / f"{hard}.reason").read_bytes())["lstat"]["st_nlink"], 2)
        self.assertTrue(elsewhere.exists())  # el hardlink sólo pierde el nombre de pending/
        self.assertEqual(elsewhere.read_bytes()[:1], b"{")
        status = inbox.read_status(self.store)
        self.assertEqual(status["pending"]["count"], 0)

    def test_regular_entries_rejected_for_another_reason_still_move(self) -> None:
        corrupt = self.factory.write_raw(b"{roto")
        self.drain()
        self.assertEqual(self.names(self.paths.rejected), sorted([corrupt, corrupt + ".reason"]))
        self.assertEqual(json.loads((self.paths.rejected / (corrupt + ".reason")).read_bytes()).get("lstat"), None)

    def test_rejected_holds_only_regular_single_name_files_so_walkers_do_not_fail(self) -> None:
        from an_kla import export_restore
        from an_kla.compaction_inventory import validate_no_links

        self.plant()
        self.factory.write_raw(b"{roto")
        self.drain()
        for path in self.paths.rejected.rglob("*"):
            info = path.lstat()
            self.assertTrue(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, path)
        validate_no_links(self.store)  # el recorrido de `compact` no falla por rejected/
        original = export_restore._allowed  # B4 excluye la bandeja; aquí se acepta para probar sólo el recorrido
        with mock.patch.object(export_restore, "_allowed", lambda p: p.startswith("anchor/memory/inbox/") or original(p)):
            rows = export_restore._files(self.store.store_root)  # sin export_unsafe_link / export_unsafe_file
        self.assertTrue(any("/rejected/" in relative for relative, _ in rows))
        with mock.patch.object(export_restore, "_allowed", lambda p: p.startswith("anchor/memory/inbox/") or original(p)):
            done = export_restore.create_export(self.store, self.project.parent / (self.project.name + "-bundle"))
        self.assertEqual(done["schema"], "an-kla/export-result-v1")


if __name__ == "__main__":
    unittest.main()
