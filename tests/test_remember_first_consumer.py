"""Primer consumidor (E1.a, fase B): ``remember`` desde otro repo Git sobre una COPIA del store de la beta.35.

``--project-root`` es el repo del consumidor y ``--store-root`` la copia del store del fixture. Sólo
copias en el directorio temporal; nunca un store real del usuario.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from an_kla import inbox
from an_kla.store import MemoryStore
from tests.inbox_support import make_project
from tests.legacy_store_goldens import extract_store
from tests.remember_support import cli, remember

MUTABLE_POINTERS = {"memory/refs/CURRENT", "memory/watermarks/CURRENT"}


def tree(root: Path) -> dict[str, tuple[str, int]]:
    """``ruta relativa -> (sha256, modo)`` de cada archivo (sin seguir enlaces)."""

    files = {}
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        if stat.S_ISREG(info.st_mode):
            files[path.relative_to(root).as_posix()] = (hashlib.sha256(path.read_bytes()).hexdigest(), stat.S_IMODE(info.st_mode))
    return files


class FirstConsumerTests(unittest.TestCase):
    def test_remember_from_another_repo_commits_on_a_copy_of_the_beta35_store(self) -> None:
        with tempfile.TemporaryDirectory(prefix="primer-consumidor-") as temp:
            base = Path(temp).resolve()
            holder = base / "copia"
            holder.mkdir()
            extract_store(holder)
            vault = base / "vault"
            (holder / ".an-kla").rename(vault)
            consumer = make_project(_mkdir(base / "consumidor"))
            old_revision = json.loads(cli(consumer, "status", store_root=vault).stdout)["revision"]
            before_files = tree(vault)
            before_inventory = cli(consumer, "inventory", "--revision", old_revision, store_root=vault).stdout
            before_retrieve = json.loads(cli(consumer, "retrieve", "--query", "golden", "--budget", "400", store_root=vault).stdout)["selected"]
            self.assertFalse((vault / "memory" / "inbox").exists())

            rc, result = remember(consumer, "el consumidor guarda su primer hecho en el store beta.35", store_root=vault)
            print("\nFIRST-CONSUMER " + json.dumps(result, sort_keys=True))

            self.assertEqual((rc, result["state"], result["outcome"]), (0, "committed", "known"))
            after_files = tree(vault)
            changed = {p for p, v in before_files.items() if after_files.get(p) != v}
            self.assertEqual(changed, MUTABLE_POINTERS)  # sólo los dos punteros mutables; el resto conserva bytes y sha256
            self.assertTrue(set(before_files) < set(after_files))
            added = sorted(set(after_files) - set(before_files))
            self.assertTrue(any(p.startswith("memory/segments/facts/") for p in added))
            self.assertTrue(all(p.startswith("memory/") for p in added))
            self.assertEqual(json.loads(cli(consumer, "verify", store_root=vault).stdout)["ok"], True)
            # Las órdenes de datos existentes dan lo mismo para los records anteriores.
            self.assertEqual(cli(consumer, "inventory", "--revision", old_revision, store_root=vault).stdout, before_inventory)
            after_retrieve = json.loads(cli(consumer, "retrieve", "--query", "golden", "--budget", "400", store_root=vault).stdout)
            self.assertEqual(after_retrieve["selected"], before_retrieve)  # los mismos records; el nuevo sólo suma `zero_score`
            snapshot = MemoryStore(consumer, store_root=vault).snapshot()
            self.assertEqual(len(snapshot.records["facts"]), 4)
            self.assertEqual([r["id"] for r in snapshot.records["facts"][:3]], ["f-golden-1", "f-golden-2", "f-golden-3"])
            found = cli(consumer, "retrieve", "--query", "primer", "--budget", "2000", store_root=vault).stdout
            self.assertIn("primer hecho", found)
            # Sin migración de formato: ningún archivo de identidad ni de formato cambió.
            for path in before_files:
                if path not in MUTABLE_POINTERS:
                    self.assertEqual(after_files[path], before_files[path], path)
            writer = snapshot.records["facts"][3]["an_kla_envelope"]["writer"]
            self.assertEqual(writer["repo"]["id"][:6], "local:")
            self.assertEqual(inbox.read_status(MemoryStore(consumer, store_root=vault))["pending"]["count"], 0)


def _mkdir(path: Path) -> Path:
    path.mkdir()
    return path


if __name__ == "__main__":
    unittest.main()
