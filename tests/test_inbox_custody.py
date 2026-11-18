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

from an_kla import export_restore, inbox, inbox_custody, lock_order, relocate, relocate_back
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
        with mock.patch.object(inbox_custody, "CUSTODY_LOCK_WAIT_SECONDS", 0.05):
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

    def test_a_non_directory_with_an_entry_name_counts_as_pending(self) -> None:
        """R1-04: FIFO, enlace, hardlink o archivo con nombre de entrada esperan al vaciado (que los rechaza)."""

        paths = inbox.inbox_paths(self.store)
        inbox.enqueue(self.store, "x", env=AGENT_ENV)
        self.drain_by_hand()
        name = "1-1-0000000000000006-00000006.json"
        outside = self.scratch / "fuera.txt"
        outside.write_bytes(b"x")
        plants = {
            "enlace": lambda: os.symlink(outside, paths.pending / name),
            "fifo": lambda: os.mkfifo(paths.pending / name),
            "hardlink": lambda: os.link(outside, paths.pending / name),
            "archivo": lambda: (paths.pending / name).write_bytes(b"{}"),
        }
        for label, plant in plants.items():
            for kind in ("v1", "sealed"):
                with self.subTest(label=label, kind=kind):
                    plant()
                    try:
                        self.assertEqual(inbox.entry_names(self.store), [name])
                        with self.assertRaises(inbox.InboxError) as caught:
                            self.create(kind)
                        self.assertEqual(str(caught.exception), "inbox_pending")
                        self.assertIn("inbox drain", caught.exception.detail)
                        self.assertFalse(self.bundle.exists())
                    finally:
                        os.unlink(paths.pending / name)

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

    def test_the_custody_never_creates_the_layout(self) -> None:
        """R1-02: con la raíz presente y la estructura incompleta, sólo puede crearse el `.lock`."""

        self.inbox.mkdir()
        for kind in ("v1", "sealed"):
            if kind == "sealed" and not _cryptography_importable():
                continue
            with self.subTest(kind=kind):
                self.create(kind)
                self.assertEqual(sorted(p.name for p in self.inbox.iterdir()), [".lock"])
                self.assertEqual((self.inbox / ".lock").stat().st_mode & 0o777, 0o600)
                shutil.rmtree(self.bundle)
        (self.inbox / ".lock").unlink()
        create_export(self.store, self.bundle)  # un `.lock` que falta se crea él solo
        self.assertEqual(sorted(p.name for p in self.inbox.iterdir()), [".lock"])

    def test_a_failing_custody_creates_nothing_even_with_an_incomplete_layout(self) -> None:
        paths = inbox.inbox_paths(self.store)
        paths.pending.mkdir(parents=True)
        (paths.pending / "1-1-0000000000000001-00000001.json").write_bytes(b"{}")
        for kind in ("v1", "sealed"):
            with self.subTest(kind=kind):
                self.assert_code("inbox_pending", self.create, kind)
        self.assertEqual(sorted(p.name for p in self.inbox.iterdir()), [".lock", "pending"])
        self.assertFalse(self.bundle.exists())

    def test_a_hardlinked_or_linked_lock_fails_the_custody_closed(self) -> None:
        self.inbox.mkdir()
        outside = self.scratch / "fuera.txt"
        outside.write_bytes(b"x")
        os.symlink(outside, self.inbox / ".lock")
        self.assert_code("inbox_unsafe_path", self.create, "v1")
        self.assertFalse(self.bundle.exists())

    def test_a_directory_with_an_entry_name_does_not_block_custody(self) -> None:
        """R1-04: un directorio (en `pending/` o `inflight/`) se ignora y `inbox status` lo informa aparte."""

        self.queue()
        self.drain_by_hand()
        paths = inbox.inbox_paths(self.store)
        (paths.pending / "1-2-0123456789abcdef-01234567.json").mkdir()
        (paths.inflight / MARKER).mkdir()
        self.assertTrue(inbox.pending_is_empty(self.store))
        self.assertTrue(inbox.inflight_is_empty(self.store))
        status = inbox.read_status(self.store)
        self.assertEqual(status["pending"]["count"], 0)
        self.assertEqual(status["inflight"]["count"], 0)
        self.assertEqual(status["ignored"]["pending"]["count"], 1)
        self.assertEqual(status["ignored"]["inflight"]["names"], [MARKER])
        create_export(self.store, self.bundle)

    def test_validations_come_before_the_custody_and_agree_between_profiles(self) -> None:
        """R1-03: mismo código para la misma situación, con la bandeja pendiente, en v1 y en sellado."""

        self.queue()
        self.bundle.mkdir()
        for kind in ("v1", "sealed"):
            with self.subTest(case="destino existe", kind=kind):
                self.assert_code("export_destination_exists", self.create, kind)
        shutil.rmtree(self.bundle)
        for kind in ("v1", "sealed"):
            with self.subTest(case="destino dentro del origen", kind=kind):
                self.bundle = Path(self.store.root) / "dentro"
                self.assert_code("export_destination_inside_source", self.create, kind)
                self.assertFalse(self.bundle.exists())

    def test_a_divergent_custody_is_reported_before_the_inbox(self) -> None:
        commit_relocation(self.store, plan_relocation(self.store, self.vault), self.revision)
        external = MemoryStore(self.project, store_root=self.vault)
        self.queue(external)
        stale = MemoryStore(self.project)  # puntero presente: la raíz local diverge
        left = inbox.inbox_paths(stale).pending  # una bandeja con entradas en el ancla abandonada
        left.mkdir(parents=True)
        (left / "1-1-0000000000000001-00000001.json").write_bytes(b"{}")
        for kind in ("v1", "sealed"):
            with self.subTest(kind=kind):
                self.store = stale
                self.assert_code("store_root_divergence", self.create, kind)

    def test_lock_order_violation_has_a_canonical_cli_code(self) -> None:
        """R1-07: sale por su código, no como `cli_unexpected_failure`."""

        import io
        from contextlib import redirect_stderr
        from an_kla import __main__ as cli

        error = lock_order.LockOrderError(lock_order.INBOX, (lock_order.IDENTITY,))
        buffer = io.StringIO()
        with mock.patch.object(cli, "_run", side_effect=error), redirect_stderr(buffer):
            with self.assertRaises(SystemExit) as caught:
                cli.main()
        self.assertEqual(caught.exception.code, 1)
        self.assertEqual(buffer.getvalue().strip(), "an-kla error: lock_order_violation")


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

    def race_enqueue_during_relocate(self, *, with_inbox: bool) -> dict:
        """Un encolador con el store anterior arranca cuando el commit ya tiene los candados de identidad y escritura."""

        if with_inbox:
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
            if name == "journal_staging":
                thread.start()
                self.assertTrue(passed_first_preflight.wait(20))
                thread.join(1.5)  # con R1-01 sigue bloqueado en `identity_lock`; sin él ya habría publicado

        relocate._fault = fault
        self.addCleanup(setattr, relocate, "_fault", None)
        outcome["relocation"] = commit_relocation(self.store, plan, self.revision)
        thread.join(30)
        return outcome

    def assert_nothing_abandoned(self, outcome: dict) -> None:
        self.assertEqual(outcome["relocation"]["stage"], "cleaned")
        old = self.project / ".an-kla" / "memory" / "inbox"
        self.assertEqual([p for p in old.rglob("*.json")], [], outcome)
        destination = MemoryStore(self.project, store_root=self.vault)
        self.assertEqual(inbox.entry_names(destination), [])
        self.assertEqual(self.residue_of(destination.doctor()), 0)

    def test_a_concurrent_enqueue_never_leaves_an_entry_in_the_abandoned_anchor(self) -> None:
        """Criterio 7 con la bandeja ya creada: sólo los tres códigos del ADR."""

        outcome = self.race_enqueue_during_relocate(with_inbox=True)
        self.assertIn(outcome.get("error"), {"inbox_busy", "store_root_divergence", "store_identity_changed"}, outcome)
        self.assert_nothing_abandoned(outcome)

    def test_a_concurrent_enqueue_with_the_inbox_absent_at_the_start_is_not_lost(self) -> None:
        """R1-01: la bandeja no existía al empezar la reubicación; el encolado toma `identity_lock` y espera."""

        self.assertFalse(self.inbox.exists())
        outcome = self.race_enqueue_during_relocate(with_inbox=False)
        self.assertIn(outcome.get("error"), {"store_root_divergence", "store_identity_changed"}, outcome)
        self.assert_nothing_abandoned(outcome)


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
                        with inbox_custody.custody_guard(self.store):
                            pass

    def test_the_guard_fails_closed_under_write_lock(self) -> None:
        self.queue()
        with self.store.write_lock():
            with self.assertRaises(lock_order.LockOrderError):
                with inbox_custody.custody_guard(self.store):
                    pass

class RoundTwoTests(CustodyCase):
    """Arreglos de la ronda 2 (R2-01 a R2-05)."""

    def publish_in_the_window(self, module, store: MemoryStore):
        """Sustituye `identity_lock` del módulo: justo antes de tomarlo, un encolado publica (orden inverso de R2-01)."""

        real = module.identity_lock
        calls: list[str] = []

        def window(target, **kwargs):
            if not calls:
                calls.append(inbox.enqueue(store, "en la ventana", env=AGENT_ENV)["entry"])
            return real(target, **kwargs)

        return calls, mock.patch.object(module, "identity_lock", window)

    def test_an_entry_published_between_the_guard_and_the_identity_lock_stops_the_relocation(self) -> None:
        """R2-01 (ida): con la bandeja ausente al empezar, la reubicación relee `pending/` bajo identidad."""

        self.assertFalse(self.inbox.exists())
        plan = plan_relocation(self.store, self.vault)
        calls, patch = self.publish_in_the_window(relocate, self.store)
        with patch:
            self.assert_code("inbox_pending", commit_relocation, self.store, plan, self.revision)
        self.assertEqual(len(calls), 1)
        self.assertFalse(self.vault.exists())
        self.assertIsNone(read_pointer(self.project))
        self.assertEqual(len(inbox.entry_names(self.store)), 1)  # la entrada sigue en el store vigente

    def test_an_entry_published_in_the_window_stops_the_back_relocation(self) -> None:
        """R2-01 (`--back`)."""

        commit_relocation(self.store, plan_relocation(self.store, self.vault), self.revision)
        external = MemoryStore(self.project, store_root=self.vault)
        back = plan_back(external)
        self.assertFalse(inbox.inbox_paths(external).root.exists())
        calls, patch = self.publish_in_the_window(relocate_back, external)
        with patch:
            self.assert_code("inbox_pending", commit_relocation, external, back, self.revision)
        self.assertEqual(len(calls), 1)
        self.assertIsNotNone(read_pointer(self.project))
        self.assertEqual(len(inbox.entry_names(external)), 1)
        for unit in relocate_back._units(back["core"]["entries"]):  # R4-02: no se publicó nada en el ancla destino
            self.assertFalse(os.path.lexists(Path(back["core"]["destination_store_root"]) / unit))

    def test_a_marker_in_the_window_is_inbox_inflight(self) -> None:
        plan = plan_relocation(self.store, self.vault)
        real = relocate.identity_lock

        def window(target, **kwargs):
            paths = inbox.inbox_paths(self.store)
            paths.inflight.mkdir(parents=True, exist_ok=True)
            (paths.inflight / MARKER).write_bytes(b"{}")
            return real(target, **kwargs)

        with mock.patch.object(relocate, "identity_lock", window):
            self.assert_code("inbox_inflight", commit_relocation, self.store, plan, self.revision)
        self.assertFalse(self.vault.exists())

    def relocated_external(self) -> MemoryStore:
        commit_relocation(self.store, plan_relocation(self.store, self.vault), self.revision)
        return MemoryStore(self.project, store_root=self.vault)

    def break_identity_on_second_preflight(self, store: MemoryStore):
        calls: list[int] = []

        def preflight(target):
            calls.append(1)
            if len(calls) == 2:
                (Path(target.store_root) / "memory" / "identity.json").write_bytes(b"")
            return inbox._mutation_preflight_with_context(target)

        return preflight

    def test_a_corrupt_identity_with_the_custody_intact_stays_store_identity_invalid(self) -> None:
        """R2-02: no se disfraza de `store_root_divergence` con sólo haber un puntero."""

        external = self.relocated_external()
        with self.assertRaises(Exception) as caught:
            inbox.enqueue(external, "x", env=AGENT_ENV, preflight=self.break_identity_on_second_preflight(external))
        self.assertEqual(str(caught.exception), "store_identity_invalid")
        self.assertEqual(inbox.entry_names(external), [])

    def test_a_changed_custody_still_reports_store_root_divergence(self) -> None:
        """La custodia vista por el segundo preflight difiere de la del primero: sí se traduce."""

        from an_kla.identity import IdentityError

        calls = {"n": 0}

        def preflight(target):
            calls["n"] += 1
            if calls["n"] == 2:
                raise IdentityError("store_identity_invalid")
            return inbox._mutation_preflight_with_context(target)

        views = iter([None, {"store_root": "otro"}])
        with mock.patch.object(inbox, "_custody_view", lambda store: next(views)):
            with self.assertRaises(Exception) as caught:
                inbox.enqueue(self.store, "x", env=AGENT_ENV, preflight=preflight)
        self.assertEqual(str(caught.exception), "store_root_divergence")
        self.assertEqual(inbox.entry_names(self.store), [])

    def test_enqueue_waits_for_the_identity_lock_only_within_its_deadline(self) -> None:
        """R2-03: `.identity.lock` ocupado por otro proceso; el encolado falla en plazo y no deja entrada."""

        import subprocess, sys, time
        from tests.inbox_support import HOLDER

        self.queue()
        self.drain_by_hand()
        lock = Path(self.store.store_root) / ".identity.lock"
        child = subprocess.Popen(
            [sys.executable, "-I", "-c", HOLDER, str(lock), "ex"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        )
        self.addCleanup(self.release, child)
        self.assertEqual(child.stdout.readline().strip(), "ready")
        threading.Timer(4.0, child.stdin.close).start()  # el ajeno lo suelta a los 4 s
        started = time.monotonic()
        with self.assertRaises(Exception) as caught:
            inbox.enqueue(self.store, "x", env=AGENT_ENV, identity_wait_seconds=0.3)
        self.assertEqual(str(caught.exception), "identity_lock_busy")
        self.assertLess(time.monotonic() - started, 2.5)
        self.assertEqual(inbox.entry_names(self.store), [])

    def test_status_keeps_separate_ignored_sets_for_pending_and_inflight(self) -> None:
        """R2-04: un nombre ignorado en `inflight/` no desaparece porque casa como entrada en `pending/`."""

        entry = self.queue()
        paths = inbox.inbox_paths(self.store)
        (paths.inflight / entry).mkdir()
        status = inbox.read_status(self.store)
        self.assertEqual(status["pending"]["names"], [entry])
        self.assertEqual(status["ignored"]["inflight"]["names"], [entry])
        marker_dir = paths.pending / MARKER
        marker_dir.write_bytes(b"x")
        (paths.inflight / MARKER).write_bytes(b"{}")
        status = inbox.read_status(self.store)
        self.assertIn(MARKER, status["ignored"]["pending"]["names"])
        self.assertEqual(status["inflight"]["names"], [MARKER])

    def test_a_file_exactly_at_the_inbox_root_is_an_unsafe_root_for_the_custody(self) -> None:
        """R2-05: `inbox_unsafe_path`, no `export_unrecognized_durable_path`; sin crear nada."""

        (Path(self.store.root) / "inbox").write_bytes(b"x")
        for kind in ("v1", "sealed"):
            with self.subTest(kind=kind):
                self.assert_code("inbox_unsafe_path", self.create, kind)
                self.assertFalse(self.bundle.exists())


class RoundThreeTests(CustodyCase):
    """Arreglos de la ronda 3: R3-01 (`relocate reconcile` revisa la bandeja) y R3-03 (`relocate plan`)."""

    def crash_at(self, point: str) -> None:
        def fault(name: str) -> None:
            if name == point:
                raise relocate.SimulatedCrash(name)

        relocate._fault = fault
        self.addCleanup(setattr, relocate, "_fault", None)

    def cut_commit(self, store: MemoryStore, plan: dict, point: str) -> str:
        self.crash_at(point)
        with self.assertRaises(relocate.SimulatedCrash):
            commit_relocation(store, plan, self.revision)
        relocate._fault = None
        return plan["core"]["transaction_id"]

    def test_reconcile_forward_refuses_while_an_entry_arrived_after_the_cut(self) -> None:
        for point in ("after_rename", "after_publish"):
            with self.subTest(point=point):
                self.setUp()
                plan = plan_relocation(self.store, self.vault)
                txid = self.cut_commit(self.store, plan, point)
                self.assertIsNone(read_pointer(self.project))
                self.queue()  # el store vigente sigue aceptando encolados entre el corte y el reconcile
                stage = relocate._read_journal(self.project, txid)["stage"]
                self.assert_code("inbox_pending", relocate.reconcile_relocation, self.project, txid)
                self.assertIsNone(read_pointer(self.project))
                self.assertEqual(len(inbox.entry_names(self.store)), 1)
                self.assertEqual(relocate._read_journal(self.project, txid)["stage"], stage)
                self.drain_by_hand()
                result = relocate.reconcile_relocation(self.project, txid)
                self.assertEqual(result["stage"], "cleaned")
                self.assertIsNotNone(read_pointer(self.project))

    def test_reconcile_forward_can_still_abort_with_a_pending_entry(self) -> None:
        plan = plan_relocation(self.store, self.vault)
        txid = self.cut_commit(self.store, plan, "after_rename")
        self.queue()
        result = relocate.reconcile_relocation(self.project, txid, abort=True)
        self.assertEqual(result["stage"], "aborted")
        self.assertEqual(len(inbox.entry_names(self.store)), 1)

    def test_reconcile_back_refuses_while_an_entry_arrived_after_the_cut(self) -> None:
        for point in ("after_rename", "after_publish"):
            with self.subTest(point=point):
                self.setUp()
                commit_relocation(self.store, plan_relocation(self.store, self.vault), self.revision)
                external = MemoryStore(self.project, store_root=self.vault)
                plan = plan_back(external)
                txid = self.cut_commit(external, plan, point)
                self.queue(external)
                stage = relocate._read_journal(self.project, txid)["stage"]
                self.assert_code("inbox_pending", relocate.reconcile_relocation, self.project, txid)
                self.assertEqual(relocate._read_journal(self.project, txid)["stage"], stage)  # R4-02: ni avanza el journal
                self.assertIsNotNone(read_pointer(self.project))
                self.assertEqual(len(inbox.entry_names(external)), 1)
                self.drain_by_hand(external)
                result = relocate.reconcile_relocation(self.project, txid)
                self.assertEqual(result["stage"], "cleaned")
                self.assertIsNone(read_pointer(self.project))

    def test_a_marker_after_the_cut_is_inbox_inflight(self) -> None:
        plan = plan_relocation(self.store, self.vault)
        txid = self.cut_commit(self.store, plan, "after_publish")
        paths = inbox.inbox_paths(self.store)
        paths.inflight.mkdir(parents=True)
        (paths.inflight / MARKER).write_bytes(b"{}")
        self.assert_code("inbox_inflight", relocate.reconcile_relocation, self.project, txid)
        self.assertIsNone(read_pointer(self.project))

    def test_relocate_plan_treats_a_file_at_the_inbox_root_as_unsafe(self) -> None:
        (Path(self.store.root) / "inbox").write_bytes(b"x")
        self.assert_code("inbox_unsafe_path", plan_relocation, self.store, self.vault)
        (Path(self.store.root) / "inbox").unlink()
        commit_relocation(self.store, plan_relocation(self.store, self.vault), self.revision)
        external = MemoryStore(self.project, store_root=self.vault)
        (Path(external.root) / "inbox").write_bytes(b"x")
        self.assert_code("inbox_unsafe_path", plan_back, external)


if __name__ == "__main__":
    unittest.main()
