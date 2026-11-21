"""#226: el encolado toma `identity_lock` en compartido; sólo un exclusivo de verdad lo frena.

Los encoladores no se excluyen entre sí (antes, 8 en cola serializados sobre el exclusivo agotaban el
plazo con la máquina cargada). Un tenedor exclusivo (reubicación, compactación, export/restore, identidad)
sigue excluyendo la publicación (R1-01), y `remember` lo declara reintentable: `identity_lock_busy`,
`retryable: true`, rc 3 y ninguna entrada.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from an_kla import inbox
from tests.inbox_support import AGENT_ENV, HOLDER, InboxCase
from tests.remember_support import cli
from tests import proc_support


class SharedIdentityLockTests(InboxCase):
    def hold_identity(self, mode: str) -> subprocess.Popen:
        lock = Path(self.store.store_root) / ".identity.lock"
        child = proc_support.spawn_for(self,
            [sys.executable, "-I", "-c", HOLDER, str(lock), mode],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        )
        self.addCleanup(self.release, child)
        self.assertEqual(child.stdout.readline().strip(), "ready")
        return child

    def test_two_enqueuers_hold_the_identity_lock_at_the_same_time(self) -> None:
        """Con el compartido los dos están dentro a la vez; con el exclusivo, el segundo no entra."""

        barrier = threading.Barrier(2, timeout=5)
        real = inbox._publish
        errors: list[BaseException] = []

        def publish(*args, **kwargs):
            barrier.wait()  # sólo pasa si el otro encolador también está dentro del candado
            return real(*args, **kwargs)

        def worker(text: str) -> None:
            try:
                inbox.enqueue(self.store, text, env=AGENT_ENV)
            except BaseException as exc:  # noqa: BLE001 - se reporta en el hilo principal
                errors.append(exc)

        with mock.patch.object(inbox, "_publish", publish):
            threads = [threading.Thread(target=worker, args=(f"hecho {n}",)) for n in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(30)
        self.assertEqual(errors, [])
        self.assertEqual(len(inbox.entry_names(self.store)), 2)

    def test_a_shared_holder_does_not_block_enqueuing(self) -> None:
        self.hold_identity("sh")
        inbox.enqueue(self.store, "con un compartido ajeno", env=AGENT_ENV, identity_wait_seconds=0.3)
        self.assertEqual(len(inbox.entry_names(self.store)), 1)

    def test_an_exclusive_holder_stops_every_enqueuer_and_nothing_is_published(self) -> None:
        """R1-01 intacto: con un exclusivo tomado ningún encolador publica."""

        self.hold_identity("ex")
        codes: list[str] = []

        def worker(text: str) -> None:
            try:
                inbox.enqueue(self.store, text, env=AGENT_ENV, identity_wait_seconds=0.3)
            except Exception as exc:  # noqa: BLE001
                codes.append(str(exc))

        threads = [threading.Thread(target=worker, args=(f"hecho {n}",)) for n in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        self.assertEqual(codes, ["identity_lock_busy"] * 3)
        self.assertEqual(inbox.entry_names(self.store), [])

    def test_remember_reports_identity_lock_busy_as_retryable_without_an_entry(self) -> None:
        """Reubicación simulada: un proceso retiene el exclusivo más que el plazo de espera."""

        child = self.hold_identity("ex")
        started = time.monotonic()
        done = cli(self.project, "remember", "--text-file", "-", stdin="durante la reubicación")
        self.assertLess(time.monotonic() - started, 30)
        self.assertEqual(done.returncode, 3, (done.stdout, done.stderr))
        error = json.loads(done.stdout)
        self.assertEqual(error["schema"], "an-kla/remember-error-v1")
        self.assertEqual((error["code"], error["retryable"], error["ok"]), ("identity_lock_busy", True, False))
        self.assertNotIn("durante la reubicación", done.stdout + done.stderr)
        self.assertEqual(inbox.entry_names(self.store), [])
        import jsonschema
        from an_kla.schemas import schema_document

        jsonschema.Draft202012Validator(schema_document("remember-error-v1")).validate(error)
        self.release(child)  # suelto el exclusivo: el reintento ya encola
        retry = cli(self.project, "remember", "--text-file", "-", stdin="durante la reubicación")
        self.assertEqual(retry.returncode, 0, (retry.stdout, retry.stderr))
        self.assertEqual(json.loads(retry.stdout)["state"], "committed")


if __name__ == "__main__":
    unittest.main()
