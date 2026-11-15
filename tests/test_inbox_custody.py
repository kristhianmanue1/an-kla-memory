"""La bandeja fuera de la custodia (ADR-0063 D1 «La bandeja no es estado durable», criterios 5, 7 y 9).

Las entradas se crean con ``inbox.enqueue`` (``remember`` aún no existe): la custodia no depende de él.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest import mock

from an_kla import export_restore, inbox, lock_order, relocate, relocate_back
from an_kla.compaction import commit_compaction, plan_compaction
from an_kla.custody import read_pointer
from an_kla.export_restore import create_export
from an_kla.identity import identity_lock
from an_kla.relocate import commit_relocation, plan_relocation, project_anchor_residue
from an_kla.relocate_back import plan_back
from an_kla.sealed import bundle as sealed_bundle
from an_kla.sealed.cli_dispatch import dispatch_export_create
from an_kla.store import MemoryStore
from tests.inbox_support import AGENT_ENV, InboxCase
from tests.test_export_sealed_cli import FakeAdapter, _cryptography_importable

HAS_FLOCK = inbox.fcntl is not None
MARKER = "0a92bdfb-286a-44b5-8c24-8d7a1332c6b6.json"


class CustodyCase(InboxCase):
    def setUp(self) -> None:
        super().setUp()
        self.revision = self.commit_record("f-custodia")
        scratch = tempfile.TemporaryDirectory(prefix="custodia-")
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name).resolve()
        self.bundle = self.scratch / "bundle"
        self.vault = self.scratch / "vaults" / "vault"

    def queue(self, store: MemoryStore | None = None, text: str = "pendiente") -> str:
        return inbox.enqueue(store or self.store, text, env=AGENT_ENV)["entry"]

    def drain_by_hand(self, store: MemoryStore | None = None) -> None:
        paths = inbox.inbox_paths(store or self.store)
        for directory in (paths.pending, paths.inflight):
            for child in directory.iterdir():
                child.unlink()

    def create(self, kind: str) -> dict:
        if kind == "v1":
            return create_export(self.store, self.bundle)
        return dispatch_export_create(
            self.store, self.bundle, seal=sealed_bundle.SEALED_PROFILE, key_adapter="x",
            key_adapter_args=(), _runner_override=FakeAdapter(),
        )

    def assert_code(self, code: str, call, *args) -> None:
        with self.assertRaises(Exception) as caught:
            call(*args)
        self.assertEqual(str(caught.exception), code)

    def tree(self, root: Path) -> list[tuple[str, int]]:
        return sorted((p.relative_to(root).as_posix(), p.lstat().st_size) for p in root.rglob("*"))


class ExportCustodyTests(CustodyCase):
    def test_pending_entries_stop_export_and_seal_before_creating_anything(self) -> None:
        self.queue()
        before = self.tree(Path(self.store.root))
        for kind in ("v1", "sealed"):
            with self.subTest(kind=kind):
                self.assert_code("inbox_pending", self.create, kind)
                self.assertFalse(self.bundle.exists())
        self.assertEqual(self.tree(Path(self.store.root)), before)

    def test_a_marker_alone_is_inbox_inflight_and_pending_is_checked_first(self) -> None:
        paths = inbox.inbox_paths(self.store)
        inbox.enqueue(self.store, "x", env=AGENT_ENV)
        self.drain_by_hand()
        (paths.inflight / MARKER).write_bytes(b"{}")
        for kind in ("v1", "sealed"):
            with self.subTest(kind=kind):
                self.assert_code("inbox_inflight", self.create, kind)
                self.assertFalse(self.bundle.exists())
        self.queue()
        self.assert_code("inbox_pending", self.create, "v1")

    def test_the_error_carries_the_drain_hint(self) -> None:
        self.queue()
        with self.assertRaises(inbox.InboxError) as caught:
            create_export(self.store, self.bundle)
        self.assertIn("inbox drain", caught.exception.detail)

    def test_an_empty_inbox_exports_without_it_and_leaves_it_alone(self) -> None:
        self.queue()
        self.drain_by_hand()
        for kind in ("v1", "sealed"):
            if kind == "sealed" and not _cryptography_importable():
                continue
            with self.subTest(kind=kind):
                self.create(kind)
                manifest = json.loads((self.bundle / "manifest.json").read_bytes())
                self.assertFalse([e for e in manifest["core"]["entries"] if "inbox" in e["path"]])
                self.assertFalse((self.bundle / "entries" / "anchor" / "memory" / "inbox").exists())
                shutil.rmtree(self.bundle)
        self.assertTrue((self.inbox / ".lock").exists())

    def test_a_store_without_an_inbox_takes_todays_path_and_creates_nothing(self) -> None:
        self.assertFalse(self.inbox.exists())
        with mock.patch.object(inbox, "inbox_lock", side_effect=AssertionError("no debe tomar el candado")):
            create_export(self.store, self.bundle)
        self.assertFalse(self.inbox.exists())

    def test_a_busy_lock_is_inbox_busy(self) -> None:
        self.queue()
        self.drain_by_hand()
        self.hold_lock("sh")
        with mock.patch.object(inbox, "CUSTODY_LOCK_WAIT_SECONDS", 0.05):
            for kind in ("v1", "sealed"):
                with self.subTest(kind=kind):
                    self.assert_code("inbox_busy", self.create, kind)
                    self.assertFalse(self.bundle.exists())

    def test_links_and_special_files_under_the_inbox_still_fail_the_export(self) -> None:
        self.queue()
        self.drain_by_hand()
        paths = inbox.inbox_paths(self.store)
        outside = self.scratch / "fuera.txt"
        outside.write_bytes(b"x")
        cases = {
            "export_unsafe_link": lambda: os.symlink(outside, paths.tmp / "enlace"),
            "export_unsafe_file": lambda: os.link(outside, paths.tmp / "duro"),
        }
        for code, plant in cases.items():
            for kind in ("v1", "sealed"):
                if kind == "sealed" and not _cryptography_importable():
                    continue  # sin `cryptography` el perfil sellado falla antes de recorrer el ancla
                with self.subTest(code=code, kind=kind):
                    plant_path = paths.tmp / ("enlace" if "link" in code else "duro")
                    plant()
                    try:
                        self.assert_code(code, self.create, kind)
                        self.assertFalse(self.bundle.exists())
                    finally:
                        plant_path.unlink()
        os.mkfifo(paths.tmp / "fifo")
        self.assert_code("export_unsafe_file", self.create, "v1")

    def test_a_link_named_like_an_entry_does_not_block_custody_but_the_export_rejects_it(self) -> None:
        paths = inbox.inbox_paths(self.store)
        inbox.enqueue(self.store, "x", env=AGENT_ENV)
        self.drain_by_hand()
        os.symlink("/etc/hostname", paths.pending / "1-1-0000000000000006-00000006.json")
        self.assertTrue(inbox.pending_is_empty(self.store))
        self.assert_code("export_unsafe_link", self.create, "v1")

    def test_something_already_under_the_inbox_path_moves_from_unrecognized_to_the_new_rule(self) -> None:
        """Punto 5 del ADR: antes, `export_unrecognized_durable_path`; ahora la regla de bandeja."""

        stray = Path(self.store.root) / "inbox" / "ajeno.txt"
        stray.parent.mkdir()
        stray.write_bytes(b"algo")
        self.assertEqual(export_restore._allowed("anchor/memory/inbox/ajeno.txt"), False)
        create_export(self.store, self.bundle)
        manifest = json.loads((self.bundle / "manifest.json").read_bytes())
        self.assertFalse([e for e in manifest["core"]["entries"] if "inbox" in e["path"]])
        # y fuera de la bandeja la regla de siempre sigue en pie
        shutil.rmtree(self.bundle)
        outsider = Path(self.store.root) / "otra-cosa.txt"
        outsider.write_bytes(b"x")
        self.assert_code("export_unrecognized_durable_path", self.create, "v1")

    def test_an_inbox_directory_without_lock_gets_its_layout_completed(self) -> None:
        self.inbox.mkdir()
        create_export(self.store, self.bundle)
        self.assertTrue((self.inbox / ".lock").exists())
        self.assertTrue((self.inbox / "pending").is_dir())

    def test_a_directory_with_an_entry_name_does_not_block_custody(self) -> None:
        """R3-01: sólo un archivo regular cuenta como entrada o marcador."""

        self.queue()
        self.drain_by_hand()
        paths = inbox.inbox_paths(self.store)
        (paths.pending / "1-2-0123456789abcdef-01234567.json").mkdir()
        (paths.inflight / MARKER).mkdir()
        os.mkfifo(paths.pending / "1-3-0123456789abcdef-01234567.json")
        self.assertTrue(inbox.pending_is_empty(self.store))
        self.assertTrue(inbox.inflight_is_empty(self.store))
        self.assertEqual(inbox.entry_names(self.store), [])
        status = inbox.read_status(self.store)
        self.assertEqual(status["pending"]["count"], 0)
        self.assertEqual(status["inflight"]["count"], 0)
        self.assertEqual(status["ignored"]["pending"]["count"], 2)
        self.assertEqual(status["ignored"]["inflight"]["names"], [MARKER])
        # la custodia pasa por la definición; la orden la rechaza por el FIFO (archivo especial), no por la bandeja
        self.assert_code("export_unsafe_file", self.create, "v1")
        os.unlink(paths.pending / "1-3-0123456789abcdef-01234567.json")
        create_export(self.store, self.bundle)


class CompactCustodyTests(CustodyCase):
    @unittest.skipUnless(HAS_FLOCK, "compactación no soportada sin fcntl (ADR-0028)")
    def test_compact_leaves_the_inbox_untouched(self) -> None:
        import uuid

        base = self.commit_record("f-inactivo", status="inactive")
        exported = create_export(self.store, self.bundle)
        self.queue()
        listing = self.tree(self.inbox)
        proposal = {
            "schema": "an-kla/compaction-proposal-v1", "base_revision": base,
            "epoch_id": str(uuid.uuid4()), "transaction_id": str(uuid.uuid4()),
            "export_manifest_sha256": exported["manifest_sha256"],
        }
        planning = plan_compaction(self.store, proposal, self.bundle)
        result = commit_compaction(self.store, planning, base, self.bundle)
        self.assertEqual(result["outcome"]["state"], "committed", result["outcome"])
        self.assertEqual(self.tree(self.inbox), listing)
        self.assertEqual(len(inbox.entry_names(self.store)), 1)


class RelocateCustodyTests(CustodyCase):
    def forward(self) -> dict:
        return plan_relocation(self.store, self.vault)

    def test_plan_passes_but_commit_fails_with_pending_and_creates_nothing(self) -> None:
        self.queue()
        plan = self.forward()
        before = self.tree(self.project)
        self.assert_code("inbox_pending", commit_relocation, self.store, plan, self.revision)
        self.assertFalse(self.vault.exists())
        self.assertFalse(self.vault.parent.exists())
        self.assertIsNone(read_pointer(self.project))
        self.assertEqual(self.tree(self.project), before)
        self.assertFalse(list((self.project / ".an-kla" / "relocations").glob("*")))

    def test_a_marker_alone_is_inbox_inflight(self) -> None:
        self.queue()
        plan = self.forward()
        self.drain_by_hand()
        (inbox.inbox_paths(self.store).inflight / MARKER).write_bytes(b"{}")
        self.assert_code("inbox_inflight", commit_relocation, self.store, plan, self.revision)
        self.assertFalse(self.vault.exists())

    def test_an_empty_inbox_relocates_and_doctor_reports_no_residue(self) -> None:
        self.queue()
        self.drain_by_hand()
        plan = self.forward()
        result = commit_relocation(self.store, plan, self.revision)
        self.assertEqual(result["stage"], "cleaned")
        self.assertEqual(result["cleanup"]["residue"], [])
        self.assertFalse((self.vault / "memory" / "inbox").exists())
        self.assertEqual(project_anchor_residue(self.project / ".an-kla"), [])
        doctor = MemoryStore(self.project, store_root=self.vault).doctor()
        self.assertEqual(self.residue_of(doctor), 0)
        self.assertTrue((self.project / ".an-kla" / "memory" / "inbox" / ".lock").exists())

    @staticmethod
    def residue_of(doctor: dict) -> int | None:
        found = []

        def walk(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == "project_local_residue":
                        found.append(value)
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(doctor)
        return found[0] if found else None

    def test_the_inbox_files_left_in_the_origin_are_not_residue(self) -> None:
        anchor = self.project / ".an-kla"
        (anchor / "memory" / "inbox" / "rejected").mkdir(parents=True)
        (anchor / "memory" / "inbox" / "rejected" / "x.json").write_bytes(b"{}")
        (anchor / "memory" / "inbox" / ".lock").write_bytes(b"")
        self.assertFalse([p for p in project_anchor_residue(anchor) if "inbox" in p])

    def test_back_with_pending_fails_and_with_an_empty_inbox_passes(self) -> None:
        plan = self.forward()
        commit_relocation(self.store, plan, self.revision)
        external = MemoryStore(self.project, store_root=self.vault)
        self.queue(external)
        back = plan_back(external)
        self.assert_code("inbox_pending", commit_relocation, external, back, self.revision)
        self.assertIsNotNone(read_pointer(self.project))
        self.assertFalse((self.project / ".an-kla" / "memory" / "refs").exists())
        self.drain_by_hand(external)
        result = commit_relocation(external, back, self.revision)
        self.assertEqual(result["stage"], "cleaned")
        self.assertIsNone(read_pointer(self.project))

    def test_back_with_a_marker_alone_is_inbox_inflight(self) -> None:
        commit_relocation(self.store, self.forward(), self.revision)
        external = MemoryStore(self.project, store_root=self.vault)
        self.queue(external)
        self.drain_by_hand(external)
        (inbox.inbox_paths(external).inflight / MARKER).write_bytes(b"{}")
        back = plan_back(external)
        self.assert_code("inbox_inflight", commit_relocation, external, back, self.revision)

    def test_a_replayed_commit_does_not_ask_for_an_empty_inbox(self) -> None:
        plan = self.forward()
        commit_relocation(self.store, plan, self.revision)
        external = MemoryStore(self.project, store_root=self.vault)
        self.queue(external)
        replay = commit_relocation(external, plan, self.revision)
        self.assertTrue(replay["replayed"])

    def test_a_store_without_an_inbox_relocates_without_creating_one(self) -> None:
        with mock.patch.object(inbox, "inbox_lock", side_effect=AssertionError("no debe tomar el candado")):
            result = commit_relocation(self.store, self.forward(), self.revision)
        self.assertEqual(result["stage"], "cleaned")
        self.assertFalse((self.project / ".an-kla" / "memory" / "inbox").exists())
        self.assertFalse((self.vault / "memory" / "inbox").exists())

    def test_a_concurrent_enqueue_never_leaves_an_entry_in_the_abandoned_anchor(self) -> None:
        """Criterio 7: el encolador espera el candado, ve la custodia cambiada y falla; nada queda en el ancla vieja."""

        self.queue()
        self.drain_by_hand()
        plan = self.forward()
        stale = MemoryStore(self.project)  # abierto antes del relocate, como un `remember` en vuelo
        passed_first_preflight = threading.Event()
        outcome: dict = {}

        def first_preflight_then_signal(store):
            result = inbox._mutation_preflight_with_context(store)
            passed_first_preflight.set()
            return result

        def racer() -> None:
            try:
                outcome["result"] = inbox.enqueue(
                    stale, "concurrente", env=AGENT_ENV, wait_seconds=10.0,
                    preflight=first_preflight_then_signal,
                )
            except Exception as exc:  # el código estable es lo que se comprueba
                outcome["error"] = str(exc)

        thread = threading.Thread(target=racer)

        def fault(name: str) -> None:
            if name == "journal_staging":  # con identity_lock y write_lock tomados, bandeja exclusiva viva
                thread.start()
                self.assertTrue(passed_first_preflight.wait(20))

        relocate._fault = fault
        self.addCleanup(setattr, relocate, "_fault", None)
        result = commit_relocation(self.store, plan, self.revision)
        thread.join(30)
        self.assertEqual(result["stage"], "cleaned")
        # `store_identity_invalid`: el preflight lee la identidad (ya movida) antes de comparar la custodia
        self.assertIn(
            outcome.get("error"),
            {"inbox_busy", "store_root_divergence", "store_identity_changed", "store_identity_invalid"},
            outcome,
        )
        old = self.project / ".an-kla" / "memory" / "inbox"
        self.assertEqual([p for p in old.rglob("*.json")], [])
        self.assertEqual(inbox.entry_names(MemoryStore(self.project, store_root=self.vault)), [])
        self.assertEqual(self.residue_of(MemoryStore(self.project, store_root=self.vault).doctor()), 0)


class LockOrderCustodyTests(CustodyCase):
    """Criterio 9 en estos caminos: la bandeja es lo único tomado cuando se pide `identity_lock`."""

    def record_identity_lock(self, module):
        seen: list[tuple[str, ...]] = []
        real = module.identity_lock

        def spy(store):
            seen.append(lock_order.held())
            return real(store)

        return seen, mock.patch.object(module, "identity_lock", spy)

    def test_export_seal_and_relocate_take_the_inbox_before_the_identity_lock(self) -> None:
        self.queue()
        self.drain_by_hand()
        cases = [("v1", export_restore), ("sealed", sealed_bundle)]
        for kind, module in cases:
            if kind == "sealed" and not _cryptography_importable():
                continue
            with self.subTest(kind=kind):
                seen, patch = self.record_identity_lock(module)
                with patch:
                    self.create(kind)
                self.assertEqual(seen, [(lock_order.INBOX,)])
                shutil.rmtree(self.bundle)
        seen, patch = self.record_identity_lock(relocate)
        with patch:
            commit_relocation(self.store, plan_relocation(self.store, self.vault), self.revision)
        self.assertEqual(seen[-1:], [(lock_order.INBOX,)])
        self.assertTrue(all(held == (lock_order.INBOX,) for held in seen[-1:]))

    def test_back_takes_the_inbox_before_the_identity_lock(self) -> None:
        self.queue()
        self.drain_by_hand()
        commit_relocation(self.store, plan_relocation(self.store, self.vault), self.revision)
        external = MemoryStore(self.project, store_root=self.vault)
        self.queue(external)
        self.drain_by_hand(external)
        back = plan_back(external)
        seen, patch = self.record_identity_lock(relocate_back)
        with patch:
            commit_relocation(external, back, self.revision)
        self.assertEqual(seen, [(lock_order.INBOX,)])

    def test_the_guard_fails_closed_under_identity_lock_even_without_an_inbox(self) -> None:
        for prepare in (lambda: None, self.queue):
            prepare()
            with self.subTest(inbox=self.inbox.exists()):
                with identity_lock(self.store):
                    with self.assertRaises(lock_order.LockOrderError):
                        with inbox.custody_guard(self.store):
                            pass

    def test_the_guard_fails_closed_under_write_lock(self) -> None:
        self.queue()
        with self.store.write_lock():
            with self.assertRaises(lock_order.LockOrderError):
                with inbox.custody_guard(self.store):
                    pass


if __name__ == "__main__":
    unittest.main()
