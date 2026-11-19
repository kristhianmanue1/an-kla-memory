"""`inbox purge-rejected` (ADR-0068, #234): purga con respaldo obligatorio fuera del store."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from an_kla import inbox, inbox_drain, inbox_purge
from an_kla.inbox_purge import purge_rejected
from an_kla.inbox_rejected import file_digest, requeue
from tests.rejected_support import POLICY, RejectedCase, validates
from tests.remember_support import cli


class Crash(Exception):
    """El corte inyectado entre el respaldo y el borrado."""


class PurgeCase(RejectedCase):
    def setUp(self) -> None:
        super().setUp()
        temp = tempfile.TemporaryDirectory(prefix="respaldo-")
        self.addCleanup(temp.cleanup)
        self.backup = Path(temp.name).resolve() / "copias"

    def purge(self, *names: str, everything: bool = True, backup: Path | str | None = None) -> dict:
        result = purge_rejected(self.store, names, everything=everything and not names, backup=str(backup or self.backup))
        validates(result, "inbox-purge-result-v1")
        return result

    def assert_backup_matches(self, files: list[dict]) -> None:
        for item in files:
            self.assertEqual(file_digest(self.backup / item["name"]), item["sha256"])


class PurgeTests(PurgeCase):
    def test_without_backup_the_cli_refuses_and_nothing_is_purged(self) -> None:
        self.reject_valid("sin respaldo")
        done = cli(self.project, "inbox", "purge-rejected", "--all")
        self.assertEqual(done.returncode, 2, (done.stdout, done.stderr))
        self.assertEqual(len(self.names(self.paths.rejected)), 2)
        with self.assertRaises(inbox.InboxError) as caught:
            purge_rejected(self.store, [], everything=True, backup=None)
        self.assertEqual(caught.exception.code, "inbox_purge_backup_invalid")

    def test_a_backup_inside_the_store_or_relative_is_invalid(self) -> None:
        self.reject_valid("respaldo dentro")
        for bad in (
            Path(self.store.root) / "respaldo", self.project / ".an-kla" / "x", Path(self.store.root), "relativo/x", "",
        ):
            with self.assertRaises(inbox.InboxError) as caught:
                purge_rejected(self.store, [], everything=True, backup=str(bad))
            self.assertEqual(caught.exception.code, "inbox_purge_backup_invalid", str(bad))
        self.assertEqual(len(self.names(self.paths.rejected)), 2)
        self.assertFalse((Path(self.store.root) / "respaldo").exists())

    def test_a_valid_backup_matches_by_sha256_and_empties_rejected(self) -> None:
        first = self.reject_valid("uno")
        second = self.reject_valid("dos", POLICY)
        originals = {name: file_digest(self.paths.rejected / name) for name in self.names(self.paths.rejected)}
        result = self.purge()
        self.assertEqual((len(result["purged"]), result["failed"], result["remaining"]), (2, [], 0))
        self.assertEqual(self.names(self.paths.rejected), [])
        self.assertEqual(sorted(self.names(self.backup)), sorted(originals))
        for name, digest in originals.items():
            self.assertEqual(file_digest(self.backup / name), digest)
        self.assertEqual({i["rejected_name"] for i in result["purged"]}, {first, second})
        for item in result["purged"]:
            self.assert_backup_matches(item["files"])
            self.assertEqual(len(item["files"]), 2)
        self.assertEqual(stat.S_IMODE(os.lstat(self.backup).st_mode), 0o700)
        self.assertNotIn(str(self.backup), json.dumps(result))
        self.assertEqual(inbox.read_status(self.store)["rejected"]["count"], 0)

    def test_a_reason_only_rejection_is_purged_with_its_reason_backed_up(self) -> None:
        unsafe = self.reject_unsafe()
        self.assertEqual(self.names(self.paths.rejected), [unsafe])
        result = self.purge(unsafe)
        self.assertEqual([i["result"] for i in result["purged"]], ["purged"])
        self.assertEqual([f["name"] for f in result["purged"][0]["files"]], [unsafe])
        self.assertEqual(self.names(self.backup), [unsafe])
        self.assertEqual(self.names(self.paths.rejected), [])

    def test_a_cut_after_copying_resumes_with_the_same_backup(self) -> None:
        self.reject_valid("corte uno")
        self.reject_valid("corte dos")
        before = self.names(self.paths.rejected)
        real_unlink = os.unlink

        def unlink(path, *args, **kwargs):
            if Path(path).parent == self.paths.rejected:
                raise Crash()
            return real_unlink(path, *args, **kwargs)

        with mock.patch.object(os, "unlink", unlink):
            with self.assertRaises(Crash):
                self.purge()
        self.assertEqual(self.names(self.paths.rejected), before)  # nada se perdió: el original sigue
        self.assertTrue(self.names(self.backup))
        result = self.purge()
        self.assertEqual((len(result["purged"]), result["failed"]), (2, []))
        self.assertEqual(self.names(self.paths.rejected), [])
        self.assertEqual(sorted(self.names(self.backup)), before)

    def test_a_cut_between_the_entry_and_its_reason_resumes(self) -> None:
        name = self.reject_valid("entre entrada y motivo")
        real_unlink = os.unlink
        calls = []

        def unlink(path, *args, **kwargs):
            calls.append(Path(path).name)
            if len(calls) == 2:
                raise Crash()
            return real_unlink(path, *args, **kwargs)

        with mock.patch.object(os, "unlink", unlink):
            with self.assertRaises(Crash):
                self.purge()
        self.assertEqual(self.names(self.paths.rejected), [name + ".reason"])
        result = self.purge()
        self.assertEqual([i["result"] for i in result["purged"]], ["purged"])
        self.assertEqual(self.names(self.paths.rejected), [])

    def test_120_rejections_are_purged_in_three_invocations_with_one_backup(self) -> None:
        for index in range(120):
            self.put_valid(f"lote {index}")
        sizes = []
        for expected_remaining in (70, 20, 0):
            result = self.purge()
            sizes.append((len(result["purged"]), result["remaining"]))
            self.assertEqual(result["remaining"], expected_remaining)
        self.assertEqual(sizes, [(50, 70), (50, 20), (20, 0)])
        self.assertEqual(self.names(self.paths.rejected), [])
        self.assertEqual(len(self.names(self.backup)), 240)

    def test_an_invalid_backup_purges_nothing(self) -> None:
        name = self.reject_valid("respaldo inválido")
        self.backup.mkdir(mode=0o700)
        cases = {
            "extraño": lambda: (self.backup / "notas.txt").write_text("x"),
            "directorio": lambda: (self.backup / "carpeta").mkdir(),
            "enlace": lambda: os.symlink("x", self.backup / "enlace"),
            "otro sha": lambda: (self.backup / name).write_bytes(b"distinto"),
        }
        for label, make in cases.items():
            with self.subTest(label):
                make()
                with self.assertRaises(inbox.InboxError) as caught:
                    self.purge()
                self.assertEqual(caught.exception.code, "inbox_purge_backup_invalid")
                self.assertEqual(len(self.names(self.paths.rejected)), 2)
                for leftover in self.backup.iterdir():
                    if leftover.is_dir() and not leftover.is_symlink():
                        leftover.rmdir()
                    else:
                        leftover.unlink()

    def test_orphan_tmp_copies_are_removed_and_redone(self) -> None:
        name = self.reject_valid("tmp huérfano")
        self.backup.mkdir(mode=0o700)
        (self.backup / f".{name}.tmp").write_bytes(b"truncado")
        result = self.purge()
        self.assertEqual([i["result"] for i in result["purged"]], ["purged"])
        self.assertEqual(sorted(self.names(self.backup)), [name, name + ".reason"])

    def test_copies_of_earlier_purges_of_names_no_longer_in_rejected_are_left_alone(self) -> None:
        self.reject_valid("anterior")
        self.purge()
        before = self.names(self.backup)
        self.reject_valid("posterior")
        self.purge()
        self.assertEqual(len(self.names(self.backup)), len(before) + 2)
        self.assertEqual(self.names(self.paths.rejected), [])

    def test_a_failed_copy_deletes_nothing_of_that_rejection(self) -> None:
        bad = self.reject_valid("falla la copia")
        good = self.reject_valid("copia bien")
        real = inbox_purge._copy

        def copy(source, directory, name):
            if name.startswith(bad):
                raise OSError("disco lleno")
            return real(source, directory, name)

        with mock.patch.object(inbox_purge, "_copy", copy):
            result = self.purge()
        self.assertEqual([i["rejected_name"] for i in result["failed"]], [bad])
        self.assertEqual(result["failed"][0]["result"], "backup_failed")
        self.assertEqual([i["rejected_name"] for i in result["purged"]], [good])
        self.assertEqual(sorted(self.names(self.paths.rejected)), [bad, bad + ".reason"])

    def test_a_different_sha256_after_copying_deletes_nothing(self) -> None:
        name = self.reject_valid("copia corrupta")

        def copy(source, directory, target):
            (directory / target).write_bytes(b"corrupta")

        with mock.patch.object(inbox_purge, "_copy", copy):
            result = self.purge()
        self.assertEqual([i["result"] for i in result["failed"]], ["backup_failed"])
        self.assertEqual(result["purged"], [])
        self.assertEqual(sorted(self.names(self.paths.rejected)), [name, name + ".reason"])

    def test_selection_and_name_errors(self) -> None:
        for bad in ("../x", "/etc/passwd", "x.json"):
            with self.assertRaises(inbox.InboxError) as caught:
                purge_rejected(self.store, [bad], backup=str(self.backup))
            self.assertEqual(caught.exception.code, "inbox_entry_name_invalid", bad)
        with self.assertRaises(inbox.InboxError) as caught:
            purge_rejected(self.store, [], backup=str(self.backup))
        self.assertEqual(caught.exception.code, "inbox_purge_target_missing")
        with self.assertRaises(inbox.InboxError) as caught:
            purge_rejected(self.store, [self.factory.fresh_name()], backup=str(self.backup))
        self.assertEqual(caught.exception.code, "inbox_purge_target_missing")
        self.assertFalse(self.backup.exists())

    def test_a_missing_parent_of_the_backup_is_invalid_and_nothing_is_purged(self) -> None:
        self.reject_valid("sin padre")
        with self.assertRaises(inbox.InboxError) as caught:
            self.purge(backup=self.backup / "a" / "b")
        self.assertEqual(caught.exception.code, "inbox_purge_backup_invalid")
        self.assertEqual(len(self.names(self.paths.rejected)), 2)

    def test_the_orphan_reason_of_a_requeue_cut_is_backed_up_and_purged(self) -> None:
        name = self.reject_valid("huérfano")
        real_unlink = os.unlink

        def unlink(path, *args, **kwargs):
            if str(path).endswith(".reason"):
                raise Crash()
            return real_unlink(path, *args, **kwargs)

        with mock.patch.object(os, "unlink", unlink):
            with self.assertRaises(Crash):
                requeue(self.store, [], all_format=True)
        result = self.purge()
        self.assertEqual([i["rejected_name"] for i in result["purged"]], [name + ".reason"])
        self.assertEqual(self.names(self.backup), [name + ".reason"])
        self.assertEqual(self.names(self.paths.rejected), [])
        self.assertEqual(self.names(self.paths.pending), [name])  # la entrada sigue en pending y se vaciará
        self.assertEqual(inbox_drain.drain(self.store)["committed"]["count"], 1)

    def test_nothing_to_purge_creates_no_backup(self) -> None:
        self.assertEqual(self.purge()["purged"], [])
        self.assertFalse(self.backup.exists())

    def test_cli_purges_and_reports_backup_failures_with_rc_3(self) -> None:
        self.reject_valid("por la CLI")
        done = cli(self.project, "inbox", "purge-rejected", "--all", "--backup", str(self.backup))
        self.assertEqual(done.returncode, 0, (done.stdout, done.stderr))
        result = json.loads(done.stdout)
        validates(result, "inbox-purge-result-v1")
        self.assertEqual((len(result["purged"]), self.names(self.paths.rejected)), (1, []))
        self.assertNotIn(str(self.backup), done.stdout)
        self.reject_valid("otra")
        (self.backup / "extraño.txt").write_text("x")
        done = cli(self.project, "inbox", "purge-rejected", "--all", "--backup", str(self.backup))
        self.assertEqual(done.returncode, 1)
        self.assertIn("inbox_purge_backup_invalid", done.stderr)


class CapabilitiesTests(unittest.TestCase):
    def test_capabilities_announce_both_commands(self) -> None:
        from an_kla.capabilities import capabilities

        text = json.dumps(capabilities())
        self.assertIn("inbox requeue", text)
        self.assertIn("inbox purge-rejected", text)
        self.assertIn("an-kla/inbox-requeue-result-v1", text)
        self.assertIn("an-kla/inbox-purge-result-v1", text)


if __name__ == "__main__":
    unittest.main()
