"""#147: the bind-intent marker closes the twin after a crash between the
external bootstrap and the pointer (m1), and the pointer view is re-read on
every access in long-lived processes (m4)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from an_kla import relocate
from an_kla import store as store_module
from an_kla.custody import CustodyError, bind_intent_path, pointer_path, read_pointer
from an_kla.relocate import SimulatedCrash, commit_relocation, plan_relocation
from an_kla.relocate_attach import attach_store
from an_kla.store import MemoryStore
from an_kla.store_resolution import open_resolved_store
from tests.test_custody_root import _commit_fact


def _crash(*_args, **_kwargs):
    raise SimulatedCrash("before_pointer")


class BindIntentTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name).resolve()
        self.project = self.base / "project"
        self.project.mkdir()
        self.vault = self.base / "vaults" / "vault"

    def _crash_before_pointer(self) -> None:
        with mock.patch.object(store_module, "write_custody_pointer", _crash):
            with self.assertRaises(SimulatedCrash):
                MemoryStore(self.project, store_root=self.vault).initialize()
        self.assertTrue((self.vault / "project-identity.json").exists())
        self.assertIsNone(read_pointer(self.project))
        self.assertTrue(bind_intent_path(self.project).exists())

    def _assert_no_twin(self) -> None:
        anchor = self.project / ".an-kla"
        self.assertFalse((anchor / "project-identity.json").exists())
        self.assertFalse((anchor / "memory" / "refs" / "CURRENT").exists())

    def test_bare_init_after_crash_fails_closed_and_flag_init_recovers(self) -> None:
        self._crash_before_pointer()
        bare = open_resolved_store(self.project, environ={})
        self.assertFalse(bare.store_external)
        with self.assertRaises(CustodyError) as caught:
            bare.initialize()
        self.assertEqual(str(caught.exception), "store_root_bind_pending")
        self._assert_no_twin()
        revision = MemoryStore(self.project, store_root=self.vault).initialize()
        self.assertFalse(bind_intent_path(self.project).exists())
        resolved = open_resolved_store(self.project, environ={})
        self.assertTrue(resolved.store_external)
        self.assertEqual(resolved.verify()["revision"], revision)

    def test_positive_control_without_marker_the_twin_reappears(self) -> None:
        # Shows the test above depends on the marker, not on another guard.
        self._crash_before_pointer()
        bind_intent_path(self.project).unlink()
        MemoryStore(self.project).initialize()
        self.assertTrue((self.project / ".an-kla" / "project-identity.json").exists())

    def test_pending_bind_blocks_another_vault_and_attach_finishes_the_same(self) -> None:
        self._crash_before_pointer()
        other = self.base / "vaults" / "other"
        with self.assertRaises(CustodyError) as caught:
            MemoryStore(self.project, store_root=other).initialize()
        self.assertEqual(str(caught.exception), "store_root_bind_pending")
        self.assertFalse(other.exists())
        vault_store = MemoryStore(self.project, store_root=self.vault)
        result = attach_store(vault_store, vault_store.read_current())
        self.assertIsNone(result["relocation_receipt"])
        self.assertFalse(bind_intent_path(self.project).exists())
        self.assertTrue(pointer_path(self.project).exists())

    def test_unreadable_marker_fails_closed(self) -> None:
        bind_intent_path(self.project).parent.mkdir(parents=True)
        bind_intent_path(self.project).write_bytes(b"not json")
        with self.assertRaises(CustodyError) as caught:
            MemoryStore(self.project).initialize()
        self.assertEqual(str(caught.exception), "store_root_bind_pending")
        self._assert_no_twin()

    def test_completed_external_init_leaves_no_marker(self) -> None:
        MemoryStore(self.project, store_root=self.vault).initialize()
        self.assertFalse(bind_intent_path(self.project).exists())
        MemoryStore(self.project, store_root=self.vault).initialize()
        self.assertFalse(bind_intent_path(self.project).exists())


class PointerViewTests(unittest.TestCase):
    def test_store_opened_before_relocate_stops_serving_the_origin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            project = base / "project"
            project.mkdir()
            local = MemoryStore(project)
            local.initialize()
            revision = _commit_fact(local, "f-local")
            long_lived = MemoryStore(project)
            self.assertEqual(long_lived.read_current(), revision)
            plan = plan_relocation(local, base / "vault")
            # Crash after the pointer, before cleanup: the origin CURRENT
            # still exists, so only the pointer check can stop the read.
            relocate._fault = lambda name: _crash() if name == "after_pointer" else None
            try:
                with self.assertRaises(SimulatedCrash):
                    commit_relocation(local, plan, revision)
            finally:
                relocate._fault = None
            self.assertTrue((project / ".an-kla" / "memory" / "refs" / "CURRENT").exists())
            with self.assertRaises(CustodyError) as caught:
                long_lived.read_current()
            self.assertEqual(str(caught.exception), "store_root_divergence")


if __name__ == "__main__":
    unittest.main()
