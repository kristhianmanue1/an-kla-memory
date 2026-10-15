"""Poda de índices derivados huérfanos (ADR-0055, issue #149 P2c)."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from an_kla.index import build_index
from an_kla.index_maintenance import prune_indexes
from an_kla.retrieval import INDEX_PROFILE, SCAN_PROFILE, retrieve
from an_kla.store import MemoryStore

TEXT = "registro {i} sobre quetzal y memoria de trabajo"


def _seed(store: MemoryStore, cur: str, i: int) -> str:
    return store.commit(
        expected_current_hash=cur, checkpoint_patch={},
        facts=[{
            "id": f"f-{i}",
            "payload": {"text": TEXT.format(i=i)},
        }],
    )


class PruneIndexesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(self.temp.name)
        self.rev_a = _seed(self.store, self.store.initialize(), 0)
        self.rev_b = _seed(self.store, self.rev_a, 1)
        build_index(self.store, revision_id=self.rev_a)
        build_index(self.store, revision_id=self.rev_b)
        self.indexes = Path(self.store.root) / "indexes"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _dirs(self) -> set[str]:
        return {p.name for p in self.indexes.iterdir() if p.is_dir()}

    def test_prune_keeps_only_current(self) -> None:
        self.assertEqual(len(self._dirs()), 2)
        result = prune_indexes(self.store)
        self.assertEqual(result["pruned_count"], 1)
        self.assertEqual(result["pruned_revisions"], [self.rev_a])
        self.assertGreater(result["bytes_freed"], 0)
        remaining = self._dirs()
        self.assertEqual(len(remaining), 1)
        self.assertIn(self.rev_b.removeprefix("sha256:"), remaining)

    def test_prune_with_explicit_keep(self) -> None:
        result = prune_indexes(self.store, keep_revision=self.rev_a)
        self.assertEqual(result["pruned_revisions"], [self.rev_b])
        self.assertIn(self.rev_a.removeprefix("sha256:"), self._dirs())

    def test_retrieve_survives_prune(self) -> None:
        prune_indexes(self.store)
        scan = retrieve(self.store, "quetzal", 65536, profile=SCAN_PROFILE)
        index = retrieve(self.store, "quetzal", 65536, profile=INDEX_PROFILE)
        self.assertGreaterEqual(len(scan.get("selected", [])), 2)
        self.assertGreaterEqual(len(index.get("selected", [])), 2)

    def test_cli_prune_reports_counts(self) -> None:
        out = subprocess.run(
            [sys.executable, "-m", "an_kla", "--project-root", self.temp.name,
             "rebuild-index", "--prune"],
            capture_output=True, text=True,
            env={"AN_KLA_NO_UPDATE_CHECK": "1", "PATH": "/usr/bin:/bin"},
        )
        self.assertEqual(out.returncode, 0, out.stderr[-400:])
        self.assertIn("pruned_count", out.stdout)
        self.assertEqual(len(self._dirs()), 1)


if __name__ == "__main__":
    unittest.main()
