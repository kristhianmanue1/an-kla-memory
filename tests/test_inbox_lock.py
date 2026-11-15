"""Candado de bandeja, recolector de ``tmp/`` y orden total de candados (ADR-0063 D1, criterio 9)."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from an_kla import inbox, lock_order, store_locks
from an_kla.identity import identity_lock
from tests.inbox_support import AGENT_ENV, InboxCase
from tests.legacy_store_goldens import ROOT

HAS_FLOCK = inbox.fcntl is not None


class InboxLockTests(InboxCase):
    @unittest.skipUnless(HAS_FLOCK, "sin fcntl no hay candado compartido: siempre exclusivo")
    def test_shared_holders_coexist_and_exclusive_excludes(self) -> None:
        self.hold_lock("sh")
        with inbox.inbox_lock(self.store, exclusive=False) as exclusive:
            self.assertFalse(exclusive)
        with self.assertRaises(inbox.InboxError) as caught:
            with inbox.inbox_lock(self.store, exclusive=True):
                pass
        self.assertEqual(caught.exception.code, "inbox_busy")

    @unittest.skipUnless(HAS_FLOCK, "el modo exclusivo forzado se prueba donde hay fcntl; en Windows es el único")
    def test_without_shared_support_a_shared_request_takes_exclusive(self) -> None:
        child = self.hold_lock("sh")
        with mock.patch.object(inbox, "SHARED_SUPPORTED", False):
            with self.assertRaises(inbox.InboxError) as caught:
                with inbox.inbox_lock(self.store, exclusive=False):
                    pass
            self.assertEqual(caught.exception.code, "inbox_busy")
        self.release(child)
        with mock.patch.object(inbox, "SHARED_SUPPORTED", False):
            with inbox.inbox_lock(self.store, exclusive=False) as exclusive:
                self.assertTrue(exclusive)

    @unittest.skipUnless(inbox.msvcrt is not None, "sólo Windows: msvcrt.locking es exclusivo por construcción")
    def test_windows_locking_is_exclusive_only(self) -> None:  # pragma: no cover - sólo Windows
        with inbox.inbox_lock(self.store, exclusive=False) as exclusive:
            self.assertTrue(exclusive)

    def test_lock_is_released_on_exit_and_layout_is_created(self) -> None:
        with inbox.inbox_lock(self.store, exclusive=True):
            for name in ("tmp", "pending", "inflight", "rejected"):
                self.assertTrue((self.inbox / name).is_dir())
        with inbox.inbox_lock(self.store, exclusive=True):
            pass

    def test_symlinked_layout_fails_closed(self) -> None:
        self.inbox.mkdir()
        target = self.project / "afuera"
        target.mkdir()
        os.symlink(target, self.inbox / "pending")
        with self.assertRaises(inbox.InboxError) as caught:
            with inbox.inbox_lock(self.store, exclusive=False):
                pass
        self.assertEqual(caught.exception.code, "inbox_unsafe_path")
        with self.assertRaises(inbox.InboxError):
            inbox.pending_is_empty(self.store)

    def test_emptiness_definitions_count_only_matching_names(self) -> None:
        self.assertTrue(inbox.pending_is_empty(self.store))
        self.assertTrue(inbox.inflight_is_empty(self.store))
        paths = inbox.inbox_paths(self.store)
        for directory in (paths.pending, paths.inflight):
            directory.mkdir(parents=True)
        (paths.pending / "algo.txt").write_bytes(b"")
        (paths.pending / "1-2-0123456789abcdef-01234567.json").mkdir()  # el patrón es por nombre
        (paths.pending / "1-2-0123456789abcdef-0123456.json").write_bytes(b"")  # un dígito corto: ignorado
        (paths.inflight / "no-es-uuid.json").write_bytes(b"")
        self.assertEqual(inbox.entry_names(self.store), ["1-2-0123456789abcdef-01234567.json"])
        self.assertFalse(inbox.pending_is_empty(self.store))
        self.assertTrue(inbox.inflight_is_empty(self.store))
        marker = "0a92bdfb-286a-44b5-8c24-8d7a1332c6b6.json"
        (paths.inflight / marker).write_bytes(b"{}")
        self.assertEqual(inbox.marker_names(self.store), [marker])
        self.assertFalse(inbox.inflight_is_empty(self.store))


# Cada hijo espera a que exista `go` y entonces pide el candado sobre una bandeja que aún no existe.
RACER = (
    "import os, sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "from an_kla import inbox\n"
    "from an_kla.store import MemoryStore\n"
    "store = MemoryStore(sys.argv[2])\n"
    "print('listo', flush=True)\n"
    "while not os.path.exists(sys.argv[3]):\n"
    "    pass\n"
    "with inbox.inbox_lock(store, exclusive=False, wait_seconds=10.0):\n"
    "    pass\n"
)


class LayoutRaceTests(unittest.TestCase):
    """R1-02: 12 procesos crean a la vez la bandeja de un store que no la tiene."""

    ROUNDS, PROCESSES = 6, 12

    def test_concurrent_first_creation_never_fails(self) -> None:
        failures: list[str] = []
        with tempfile.TemporaryDirectory(prefix="inbox-carrera-") as temp:
            base = Path(temp)
            project = base / "proyecto"
            (project / ".an-kla" / "memory").mkdir(parents=True)
            for round_number in range(self.ROUNDS):
                shutil.rmtree(project / ".an-kla" / "memory" / "inbox", ignore_errors=True)
                go = base / f"go-{round_number}"
                children = [
                    subprocess.Popen(
                        [sys.executable, "-c", RACER, str(ROOT), str(project), str(go)],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    )
                    for _ in range(self.PROCESSES)
                ]
                for child in children:  # nadie arranca hasta que todos están importados y listos
                    self.assertEqual(child.stdout.readline().strip(), "listo")
                go.write_bytes(b"")
                for child in children:
                    _out, err = child.communicate(timeout=60)
                    if child.returncode != 0:
                        failures.append(err.strip().splitlines()[-1] if err.strip() else "sin stderr")
        self.assertEqual(failures, [])


class LockFileSafetyTests(InboxCase):
    """R1-04: `.lock` se inspecciona como `reader_gate._open_gate` (regular, no enlace, un solo enlace)."""

    def assert_unsafe(self) -> None:
        for create in (True, False):
            with self.subTest(create=create):
                with self.assertRaises(inbox.InboxError) as caught:
                    with inbox.inbox_lock(self.store, exclusive=False, create=create):
                        pass
                self.assertEqual(caught.exception.code, "inbox_unsafe_path")
                self.assertNotIn(str(self.project), str(caught.exception))
                self.assertNotIn(str(self.project), repr(caught.exception.hint))

    def prepare(self) -> Path:
        with inbox.inbox_lock(self.store, exclusive=False):
            pass
        lock = self.inbox / ".lock"
        lock.unlink()
        return lock

    def test_symlinked_lock_is_unsafe(self) -> None:
        lock = self.prepare()
        target = self.project / "otro"
        target.write_bytes(b"")
        os.symlink(target, lock)
        self.assert_unsafe()

    def test_directory_lock_is_unsafe(self) -> None:
        self.prepare().mkdir()
        self.assert_unsafe()

    def test_hardlinked_lock_is_unsafe(self) -> None:
        lock = self.prepare()
        lock.write_bytes(b"")
        os.link(lock, self.project / "otro-nombre")
        self.assert_unsafe()

    def test_collect_tmp_also_refuses_an_unsafe_lock(self) -> None:
        self.prepare().mkdir()
        with self.assertRaises(inbox.InboxError) as caught:
            inbox.collect_tmp(self.store)
        self.assertEqual(caught.exception.code, "inbox_unsafe_path")


class RootSafetyTests(InboxCase):
    """R2-01, R2-02, R2-05: una sola inspección de la raíz y de sus padres para todo lo que B2/B4 reutilizan."""

    def outside(self, with_entry: bool = True) -> Path:
        """Un directorio fuera del ancla con una bandeja completa (y una entrada ajena)."""

        outside = self.project.parent / (self.project.name + "-fuera")
        self.addCleanup(shutil.rmtree, outside, True)
        (outside / "pending").mkdir(parents=True)
        for name in ("tmp", "inflight", "rejected"):
            (outside / name).mkdir()
        if with_entry:
            (outside / "pending" / "1-1-0123456789abcdef-01234567.json").write_bytes(b"ajeno")
        return outside

    def link_root_to_dir(self) -> Path:
        outside = self.outside()
        os.symlink(outside, self.inbox)
        return outside

    def root_is_file(self) -> None:
        self.inbox.write_bytes(b"no soy un directorio")

    def root_links_to_file(self) -> None:
        target = self.project / "archivo"
        target.write_bytes(b"x")
        os.symlink(target, self.inbox)

    def memory_is_a_link(self) -> Path:
        outside = self.project.parent / (self.project.name + "-memoria")
        self.addCleanup(shutil.rmtree, outside, True)
        os.rename(self.store.root, outside)
        os.symlink(outside, self.store.root)
        return outside

    def anchor_is_a_link(self) -> Path:
        outside = self.project.parent / (self.project.name + "-ancla")
        self.addCleanup(shutil.rmtree, outside, True)
        os.rename(self.store.store_root, outside)
        os.symlink(outside, self.store.store_root)
        return outside

    def unsafe_setups(self):
        return {
            "raiz_enlace_a_directorio": self.link_root_to_dir,
            "raiz_archivo": self.root_is_file,
            "raiz_enlace_a_archivo": self.root_links_to_file,
            "memory_enlazado": self.memory_is_a_link,
            "ancla_enlazada": self.anchor_is_a_link,
        }

    def each_unsafe(self):
        """Prepara cada escenario en un store limpio (se rehace el proyecto entre casos)."""

        for name, setup in self.unsafe_setups().items():
            self.setUp()
            with self.subTest(setup=name):
                setup()
                yield name

    def test_definitions_of_empty_never_claim_empty_behind_a_link(self) -> None:
        for _ in self.each_unsafe():
            for call in (inbox.pending_is_empty, inbox.inflight_is_empty, inbox.entry_names, inbox.marker_names):
                with self.assertRaises(inbox.InboxError) as caught:
                    call(self.store)
                self.assertEqual(caught.exception.code, "inbox_unsafe_path")
                self.assertNotIn(str(self.project), str(caught.exception))

    def test_absent_root_is_still_empty(self) -> None:
        self.assertEqual(inbox.root_state(self.store), "absent")
        self.assertTrue(inbox.pending_is_empty(self.store))
        self.assertTrue(inbox.inflight_is_empty(self.store))

    def test_collect_and_lock_distinguish_unsafe_from_absent(self) -> None:
        for _ in self.each_unsafe():
            with self.assertRaises(inbox.InboxError) as caught:
                inbox.collect_tmp(self.store)
            self.assertEqual(caught.exception.code, "inbox_unsafe_path")
            for create in (True, False):
                with self.assertRaises(inbox.InboxError) as caught:
                    with inbox.inbox_lock(self.store, exclusive=False, create=create):
                        pass
                self.assertEqual(caught.exception.code, "inbox_unsafe_path")
        self.setUp()
        with self.assertRaises(inbox.InboxError) as caught:
            with inbox.inbox_lock(self.store, exclusive=False, create=False):
                pass
        self.assertEqual(caught.exception.code, "inbox_absent")

    def test_nothing_is_created_outside_the_anchor_through_a_linked_component(self) -> None:
        outside = self.memory_is_a_link()
        with self.assertRaises(inbox.InboxError):
            with inbox.inbox_lock(self.store, exclusive=False):
                pass
        self.assertFalse((outside / "inbox").exists())
        self.setUp()
        outside = self.anchor_is_a_link()
        with self.assertRaises(inbox.InboxError):
            # el preflight de identidad ya rechaza un ancla enlazada; aquí se prueba la capa de bandeja sola
            inbox.enqueue(self.store, "x", env=AGENT_ENV, preflight=lambda _store: None)
        self.assertFalse((outside / "memory" / "inbox").exists())

    def test_lock_file_is_normalized_to_0600(self) -> None:
        """R2-07: como `reader_gate._open_gate`, un `.lock` preexistente más permisivo se estrecha."""

        with inbox.inbox_lock(self.store, exclusive=False):
            pass
        os.chmod(self.inbox / ".lock", 0o666)
        with inbox.inbox_lock(self.store, exclusive=False):
            self.assertEqual(os.stat(self.inbox / ".lock").st_mode & 0o777, 0o600)


class CollectTmpTests(InboxCase):
    def orphans(self, count: int = 2) -> list[str]:
        """Temporales huérfanos reales: un encolado que falla al publicar los deja en ``tmp/``."""

        def failing(src, dst):
            raise OSError(28, "ENOSPC")

        for index in range(count):
            with self.assertRaises(OSError):
                inbox.enqueue(self.store, f"huérfano {index}", env=AGENT_ENV, replace=failing)
        return sorted(os.listdir(self.inbox / "tmp"))

    def test_absent_inbox_creates_nothing(self) -> None:
        self.assertEqual(inbox.collect_tmp(self.store), {"state": "absent", "removed": 0, "errors": 0})
        self.assertFalse(self.inbox.exists())

    def test_orphans_without_a_live_enqueuer_are_deleted(self) -> None:
        names = self.orphans(3)
        self.assertEqual(len(names), 3)
        (self.inbox / "tmp" / "carpeta").mkdir()
        (self.inbox / "tmp" / "carpeta" / "x").write_bytes(b"x")
        result = inbox.collect_tmp(self.store)
        self.assertEqual(result, {"state": "collected", "removed": 4, "errors": 0})
        self.assertEqual(os.listdir(self.inbox / "tmp"), [])

    def test_pending_entries_are_never_touched(self) -> None:
        entry = inbox.enqueue(self.store, "confirmado", env=AGENT_ENV)["entry"]
        self.orphans(1)
        inbox.collect_tmp(self.store)
        self.assertEqual(inbox.entry_names(self.store), [entry])

    @unittest.skipUnless(HAS_FLOCK, "el encolador vivo toma el compartido; sin fcntl no hay compartido")
    def test_a_live_enqueuer_in_another_process_blocks_collection(self) -> None:
        names = self.orphans(2)
        self.hold_lock("sh")
        result = inbox.collect_tmp(self.store)
        self.assertEqual(result, {"state": "busy", "removed": 0, "errors": 0})
        self.assertEqual(sorted(os.listdir(self.inbox / "tmp")), names)


class LockOrderTests(InboxCase):
    """Criterio 9: ningún camino pide el candado de bandeja teniendo identidad o write_lock."""

    def assert_refused(self, call) -> None:
        with self.assertRaises(lock_order.LockOrderError) as caught:
            call()
        self.assertEqual(caught.exception.code, "lock_order_violation")
        self.assertFalse(self.inbox.exists(), "el camino prohibido no debe crear nada")

    def paths(self):
        return {
            "inbox_lock": lambda: inbox.inbox_lock(self.store, exclusive=False).__enter__(),
            "inbox_lock_exclusive": lambda: inbox.inbox_lock(self.store, exclusive=True).__enter__(),
            "enqueue": lambda: inbox.enqueue(self.store, "x", env=AGENT_ENV),
            "collect_tmp": lambda: inbox.collect_tmp(self.store),
        }

    def test_every_inbox_path_refuses_while_holding_identity_lock(self) -> None:
        for name, call in self.paths().items():
            with self.subTest(path=name), identity_lock(self.store):
                self.assertEqual(lock_order.held(), (lock_order.IDENTITY,))
                self.assert_refused(call)

    def test_every_inbox_path_refuses_while_holding_write_lock(self) -> None:
        for name, call in self.paths().items():
            with self.subTest(path=name), self.store.write_lock():
                self.assert_refused(call)

    def test_every_inbox_path_refuses_while_holding_the_module_level_write_lock(self) -> None:
        """R2-03: `hook_runs` usa `store_locks.write_lock(root)` sin pasar por `MemoryStore.write_lock`."""

        for name, call in self.paths().items():
            with self.subTest(path=name), store_locks.write_lock(self.store.root):
                self.assertIsNone(self.store._active_write_lock)
                self.assertIn(lock_order.WRITE, lock_order.held())
                self.assert_refused(call)
        self.assertEqual(lock_order.held(), ())

    def test_allowed_order_inbox_then_identity_then_write(self) -> None:
        with inbox.inbox_lock(self.store, exclusive=True):
            self.assertEqual(lock_order.held(), (lock_order.INBOX,))
            with identity_lock(self.store):
                with self.store.write_lock():
                    self.assertEqual(lock_order.held(), (lock_order.INBOX, lock_order.IDENTITY, lock_order.WRITE))
        self.assertEqual(lock_order.held(), ())

    def test_registry_is_restored_after_an_error_inside_the_lock(self) -> None:
        with self.assertRaises(RuntimeError):
            with identity_lock(self.store):
                raise RuntimeError("falla dentro")
        self.assertEqual(lock_order.held(), ())
        with inbox.inbox_lock(self.store, exclusive=False):
            pass


if __name__ == "__main__":
    unittest.main()
