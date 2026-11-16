"""Arreglos de la ronda 4 de B4: ``export`` y ``--seal`` releen la bandeja bajo ``identity_lock`` (R4-01)."""

from __future__ import annotations

import unittest
from unittest import mock

from an_kla import export_restore, inbox
from an_kla.sealed import bundle as sealed_bundle
from tests.inbox_support import AGENT_ENV
from tests.test_export_sealed_cli import _cryptography_importable
from tests.test_inbox_custody import CustodyCase


class BundleWindowTests(CustodyCase):
    def publish_in_the_window(self, module):
        """Sustituye `identity_lock` del módulo: justo antes de tomarlo, un encolado publica (como en R2-01)."""

        real = module.identity_lock
        calls: list[str] = []

        def window(target, **kwargs):
            if not calls:
                calls.append(inbox.enqueue(self.store, "en la ventana", env=AGENT_ENV)["entry"])
            return real(target, **kwargs)

        return calls, mock.patch.object(module, "identity_lock", window)

    def check(self, kind: str, module) -> None:
        self.assertFalse(inbox.inbox_paths(self.store).root.exists())  # la bandeja no existe: el guardián no toma candado
        calls, patch = self.publish_in_the_window(module)
        with patch:
            self.assert_code("inbox_pending", self.create, kind)
        self.assertEqual(len(calls), 1)
        self.assertFalse(self.bundle.exists())
        self.assertEqual(inbox.entry_names(self.store), calls)  # la entrada sigue en pending/

    def test_an_entry_published_before_identity_lock_stops_export_create(self) -> None:
        self.check("v1", export_restore)

    def test_an_entry_published_before_identity_lock_stops_the_sealed_export(self) -> None:
        """Con o sin el extra: sin él la CEK y las subclaves se sustituyen, porque la orden falla antes de usarlas."""

        if _cryptography_importable():
            return self.check("sealed", sealed_bundle)
        with mock.patch.object(sealed_bundle, "generate_cek", lambda: b"\0" * 32), mock.patch.object(
            sealed_bundle, "derive_subkeys", lambda cek: mock.Mock()
        ):
            self.check("sealed", sealed_bundle)


if __name__ == "__main__":
    unittest.main()
