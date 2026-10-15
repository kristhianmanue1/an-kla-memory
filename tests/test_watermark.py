"""Watermark de verificación incremental (ADR-0053, issue #149 P1).

Equivalencia de resultado ante watermark sano, corrupto, atrasado, ajeno o
de epoch equivocada; refresco por el escritor dentro del commit; auditoría
completa (`verify`) que ignora el watermark y expone corrupción bajo el
punto de parada.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from an_kla.canonical import canonical_json
from an_kla.store import MemoryStore
from an_kla.watermark import WATERMARK_SCHEMA, watermark_path, write_watermark

DIGEST_B = "sha256:" + "b" * 64
TEXT = "registro {i} sobre quetzal y memoria de trabajo"


def authority(candidate: dict) -> dict:
    from an_kla.canonical import digest_json

    return {
        "schema": "an-kla/write-authority-v1",
        "proposal_sha256": digest_json(candidate),
        "base_revision": candidate["base_revision"],
        "authority_class": "model_derived",
        "issuer": {"kind": "model", "id": "wm-test",
                   "configuration_fingerprint": DIGEST_B},
        "evidence": [],
        "scope": {
            "streams": [candidate["stream"]],
            "representations": [candidate["requested_representation"]],
            "operations": [candidate["operation"]],
        },
    }


def governed_write(store, cur: str, i: int) -> str:
    candidate = {
        "schema": "an-kla/write-proposal-v1",
        "base_revision": cur,
        "stream": "facts",
        "operation": "add",
        "requested_representation": "summary",
        "record": {"id": f"f-{i}", "payload": {"text": TEXT.format(i=i)}},
        "lineage": {"derived_from_retrieval": False, "refs": []},
    }
    planning = store.plan_write(candidate, authority(candidate))
    result = store.commit_write_plan(
        expected_current_hash=cur, proposal=candidate,
        authority=authority(candidate),
        decision=planning["decision"], plan=planning["plan"],
    )
    return result["revision"]


def build(ws: Path, n: int) -> tuple[MemoryStore, str, list[str]]:
    store = MemoryStore(str(ws))
    cur = store.initialize()
    revisions = [cur]
    for i in range(n):
        cur = governed_write(store, cur, i)
        revisions.append(cur)
    return store, cur, revisions


class WatermarkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store, self.cur, self.revisions = build(Path(self.temp.name), 6)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _records(self, use_watermark: bool = True):
        snap = self.store.snapshot(use_watermark=use_watermark)
        return {
            stream: [dict(row) for row in snap.records[stream]]
            for stream in ("facts", "events", "episodes")
        }

    def test_writer_refreshes_watermark_on_commit(self) -> None:
        raw = watermark_path(self.store).read_bytes()
        import json

        wm = json.loads(raw)
        self.assertEqual(wm["schema"], WATERMARK_SCHEMA)
        self.assertEqual(wm["revision"], self.cur)
        parent_manifest = self.store._read_json_object(
            "revisions", self.revisions[-2]
        )
        self.assertEqual(wm["parent"], self.revisions[-2])
        self.assertIsNone(wm["epoch_id"])
        self.assertIsNotNone(parent_manifest)

    def test_equivalence_with_and_without_watermark(self) -> None:
        self.assertEqual(self._records(True), self._records(False))

    def test_corrupt_watermark_degrades_to_full_walk(self) -> None:
        watermark_path(self.store).write_bytes(b"garbage {{{")
        self.assertEqual(self._records(True), self._records(False))
        watermark_path(self.store).write_bytes(
            canonical_json({
                "schema": WATERMARK_SCHEMA, "revision": "sha256:" + "9" * 64,
                "parent": None, "epoch_id": None,
            })
        )
        self.assertEqual(self._records(True), self._records(False))

    def test_stale_watermark_still_serves_same_records(self) -> None:
        manifest = self.store._read_json_object("revisions", self.revisions[2])
        write_watermark(self.store, self.revisions[2], manifest)
        self.assertEqual(self._records(True), self._records(False))

    def test_wrong_binding_is_ignored(self) -> None:
        # parent mal ligado: el recorrido no se detiene y el resultado es el
        # del camino completo.
        manifest = dict(self.store._read_json_object("revisions", self.revisions[4]))
        stale = {
            "schema": WATERMARK_SCHEMA,
            "revision": self.revisions[4],
            "parent": "sha256:" + "0" * 64,
            "epoch_id": None,
        }
        watermark_path(self.store).write_bytes(canonical_json(stale))
        self.assertNotEqual(manifest.get("parent"), stale["parent"])
        self.assertEqual(self._records(True), self._records(False))

    def test_verify_full_exposes_corruption_below_watermark(self) -> None:
        # Corromper un manifiesto ANCESTRO (bajo el punto de parada): la
        # lectura normal confía en el prefijo cacheado; la auditoría
        # completa debe levantar el error.
        ancestor = self.revisions[1]
        victim = self.store._path_for("revisions", ancestor)
        victim.write_text('{"tampered": true}', encoding="utf-8")
        with self.assertRaises(Exception):
            self.store.snapshot(use_watermark=False)
        # La lectura con watermark sigue sirviendo el estado vigente.
        snap = self.store.snapshot()
        self.assertEqual(snap.revision_id, self.cur)
        self.temp.cleanup()

    def test_epoch_mismatch_is_ignored(self) -> None:
        stale = {
            "schema": WATERMARK_SCHEMA,
            "revision": self.revisions[5],
            "parent": self.revisions[4],
            "epoch_id": "not-an-epoch-uuid",
        }
        watermark_path(self.store).write_bytes(canonical_json(stale))
        self.assertEqual(self._records(True), self._records(False))


if __name__ == "__main__":
    unittest.main()
