"""Tests for P3 (ADR-0015): excluded_detail transparency."""

from __future__ import annotations

import tempfile
import unittest

from an_kla.index import INDEX_PROFILE, build_index, detect_fts5
from an_kla.retrieval import EXCLUDED_DETAIL_CAP, retrieve
from an_kla.store import MemoryStore


class ExcludedDetailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(self.temp.name)
        self.base = self.store.initialize()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _seed_many_facts(self, n: int) -> None:
        facts = [
            {
                "id": f"f-big-{i:03d}",
                "schema": "an-kla/fact-v1",
                "payload": {"text": f"documento largo numero {i} " * 30},
            }
            for i in range(n)
        ]
        self.store.commit(
            expected_current_hash=self.base,
            checkpoint_patch={},
            facts=facts,
        )

    def test_budget_exclusion_lists_ids(self):
        self._seed_many_facts(3)
        out = retrieve(self.store, "documento", budget=200)
        self.assertIn("budget", out["excluded_summary"])
        self.assertGreaterEqual(out["excluded_summary"]["budget"], 1)
        self.assertIn("budget", out["excluded_detail"]["ids"])
        self.assertGreaterEqual(len(out["excluded_detail"]["ids"]["budget"]), 1)
        self.assertFalse(out["excluded_detail"]["truncated"]["budget"])

    def test_zero_score_exclusion_lists_ids(self):
        self._seed_many_facts(3)
        out = retrieve(self.store, "zzznmatch", budget=10000)
        self.assertEqual(out["excluded_summary"].get("zero_score", 0), 3)
        ids = out["excluded_detail"]["ids"]["zero_score"]
        self.assertEqual(len(ids), 3)
        self.assertIn("f-big-000", ids)

    def test_truncation_at_cap(self):
        # Seed more than EXCLUDED_DETAIL_CAP facts that all match the query
        # but blow the budget: only the first CAP budget-excluded IDs appear.
        self._seed_many_facts(EXCLUDED_DETAIL_CAP + 30)
        out = retrieve(self.store, "documento", budget=200)
        budget_count = out["excluded_summary"]["budget"]
        self.assertGreater(budget_count, EXCLUDED_DETAIL_CAP)
        self.assertEqual(len(out["excluded_detail"]["ids"]["budget"]), EXCLUDED_DETAIL_CAP)
        self.assertTrue(out["excluded_detail"]["truncated"]["budget"])
        self.assertEqual(out["excluded_detail"]["cap"], EXCLUDED_DETAIL_CAP)

    def test_no_text_records_are_tracked(self):
        self.store.commit(
            expected_current_hash=self.base,
            checkpoint_patch={},
            facts=[
                {"id": "f-empty", "schema": "an-kla/fact-v1", "payload": {}},
                {"id": "f-real", "schema": "an-kla/fact-v1", "payload": {"text": "documento real"}},
            ],
        )
        out = retrieve(self.store, "documento", budget=10000)
        self.assertEqual(out["excluded_summary"].get("no_text", 0), 1)
        self.assertEqual(out["excluded_detail"]["ids"]["no_text"], ["f-empty"])

    def test_inactive_records_are_tracked(self):
        self.store.commit(
            expected_current_hash=self.base,
            checkpoint_patch={},
            facts=[
                {
                    "id": "f-inactive",
                    "schema": "an-kla/fact-v1",
                    "status": "sustituida",
                    "payload": {"text": "documento inactivo"},
                },
                {"id": "f-real", "schema": "an-kla/fact-v1", "payload": {"text": "documento real"}},
            ],
        )
        out = retrieve(self.store, "documento", budget=10000)
        self.assertEqual(out["excluded_summary"].get("inactive", 0), 1)
        self.assertEqual(out["excluded_detail"]["ids"]["inactive"], ["f-inactive"])

    def test_empty_detail_keys_omitted(self):
        # Single happy path: one matching record, no exclusions at all.
        self.store.commit(
            expected_current_hash=self.base,
            checkpoint_patch={},
            facts=[{"id": "f-lone", "schema": "an-kla/fact-v1", "payload": {"text": "documento unico"}}],
        )
        out = retrieve(self.store, "documento", budget=10000)
        self.assertEqual(out["excluded_detail"]["ids"], {})


class ZeroScoreParityTests(unittest.TestCase):
    """#118/R3: contabilidad zero_score idéntica entre scan e índice.

    El diagnóstico (excluded_summary + excluded_detail) debe ser el mismo
    en ambos perfiles: la contabilidad es única, post-sort y previa al
    narrowing de fts5 (ADR-0049 §1).
    """

    def setUp(self) -> None:
        if not detect_fts5():
            self.skipTest("fts5 no disponible en este intérprete")
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(self.temp.name)
        self.base = self.store.initialize()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _seed_mixed(self) -> None:
        self.store.commit(
            expected_current_hash=self.base,
            checkpoint_patch={},
            facts=[
                {"id": "f-a", "schema": "an-kla/fact-v1", "payload": {"text": "deployment parser"}},
                {"id": "f-c", "schema": "an-kla/fact-v1", "payload": {"text": "otro deployment"}},
                {"id": "f-b", "schema": "an-kla/fact-v1", "payload": {"text": "skopos sin relacion"}},
            ],
        )

    def _both_profiles(self, query: str):
        scan = retrieve(self.store, query, 10000, profile="scan-fallback/v1")
        build_index(self.store)
        index = retrieve(self.store, query, 10000, profile=INDEX_PROFILE)
        return scan, index

    def test_parity_with_mixed_matches(self):
        self._seed_mixed()
        scan, index = self._both_profiles("deployment")
        self.assertEqual(index["profile"], INDEX_PROFILE)
        self.assertEqual(index["degradation"], "none")
        self.assertEqual(scan["excluded_summary"], index["excluded_summary"])
        self.assertEqual(scan["excluded_detail"], index["excluded_detail"])
        self.assertEqual(index["excluded_summary"].get("zero_score"), 1)

    def test_parity_when_everything_is_zero_score(self):
        # El caso de #133: query sin solape léxico con el store.
        self._seed_mixed()
        scan, index = self._both_profiles("quetzal pendiente")
        self.assertEqual(scan["selected"], [])
        self.assertEqual(index["selected"], [])
        self.assertEqual(index["excluded_summary"].get("zero_score"), 3)
        self.assertEqual(scan["excluded_summary"], index["excluded_summary"])
        self.assertEqual(scan["excluded_detail"], index["excluded_detail"])

    def test_parity_with_degraded_index(self):
        # fts5 degradado (sin narrowing) → el fallback escanea todo: el
        # conteo no se duplica ni desaparece. (El store auto-reindexa al
        # commitear, así que la degradación se fuerza desactivando fts5.)
        from unittest.mock import patch

        import an_kla.retrieval as retrieval_module

        self._seed_mixed()
        scan = retrieve(self.store, "deployment", 10000, profile="scan-fallback/v1")
        build_index(self.store)
        with patch.object(retrieval_module, "detect_fts5", return_value=False):
            index = retrieve(self.store, "deployment", 10000, profile=INDEX_PROFILE)
        self.assertEqual(index["degradation"], "fts5_unavailable")
        self.assertEqual(scan["excluded_summary"], index["excluded_summary"])
        self.assertEqual(scan["excluded_detail"], index["excluded_detail"])

    def test_parity_with_term_free_query(self):
        # Query sin tokens: clause None, sin narrowing en ningún perfil.
        self._seed_mixed()
        scan, index = self._both_profiles("!!!")
        self.assertEqual(scan["selected"], [])
        self.assertEqual(index["selected"], [])
        self.assertEqual(scan["excluded_summary"], index["excluded_summary"])

    def test_zero_score_detail_order_is_deterministic(self):
        # ADR-0015: el detalle hereda el orden determinista (-score, id),
        # no el orden de scan por stream.
        self.store.commit(
            expected_current_hash=self.base,
            checkpoint_patch={},
            facts=[
                {"id": "f-z", "schema": "an-kla/fact-v1", "payload": {"text": "zebra uno"}},
                {"id": "f-m", "schema": "an-kla/fact-v1", "payload": {"text": "mango dos"}},
                {"id": "f-a", "schema": "an-kla/fact-v1", "payload": {"text": "arpa tres"}},
            ],
        )
        out = retrieve(self.store, "nada-que-ver", 10000)
        self.assertEqual(
            out["excluded_detail"]["ids"]["zero_score"],
            ["f-a", "f-m", "f-z"],
        )


class EmptyReasonTests(unittest.TestCase):
    """#133 / ADR-0049 §3: tabla de verdad de ``empty_reason`` (v3 disperso)."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(self.temp.name)
        self.base = self.store.initialize()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _seed(self, facts):
        self.store.commit(expected_current_hash=self.base, checkpoint_patch={}, facts=facts)

    def _validate_v3(self, payload, schema_name):
        import json

        from jsonschema import Draft202012Validator

        from an_kla.schemas import schema_bytes

        validator = Draft202012Validator(json.loads(schema_bytes(schema_name)))
        validator.validate(payload)

    def test_zero_overlap_emits_v3_with_reason(self):
        # (i) overlap cero puro → v3 + empty_reason.
        self._seed([
            {"id": "f-a", "schema": "an-kla/fact-v1", "payload": {"text": "deployment parser"}},
        ])
        out = retrieve(self.store, "quetzal pendiente", 10000)
        self.assertEqual(out["schema"], "an-kla/retrieval-result-v3")
        self.assertEqual(out["empty_reason"], "no_lexical_overlap")
        self.assertEqual(out["selected"], [])
        self._validate_v3(out, "retrieval-result-v3")

    def test_zero_overlap_with_freshness_still_emits_v3(self):
        # (ii) freshness activo → v3 CON bloque freshness + empty_reason.
        self._seed([
            {"id": "f-a", "schema": "an-kla/fact-v1", "verified_at": "2026-08-01T00:00:00Z",
             "payload": {"text": "deployment parser"}},
        ])
        out = retrieve(
            self.store, "quetzal pendiente", 10000,
            freshness_profile="computed-age/v1", now=None, stale_after_days=30,
        )
        self.assertEqual(out["schema"], "an-kla/retrieval-result-v3")
        self.assertEqual(out["empty_reason"], "no_lexical_overlap")
        self.assertIn("freshness", out)
        self._validate_v3(out, "retrieval-result-v3")

    def test_all_inactive_does_not_emit_reason(self):
        # (iii) todos inactivos → v1 sin razón (la causa es vigencia).
        self._seed([
            {"id": "f-a", "schema": "an-kla/fact-v1", "status": "sustituida",
             "payload": {"text": "deployment parser"}},
        ])
        out = retrieve(self.store, "quetzal pendiente", 10000)
        self.assertEqual(out["schema"], "an-kla/retrieval-result-v1")
        self.assertNotIn("empty_reason", out)

    def test_budget_exclusion_does_not_emit_reason(self):
        # (iv) vacío por budget (scores > 0 que no cupieron) → sin razón.
        self._seed([
            {"id": "f-a", "schema": "an-kla/fact-v1", "payload": {"text": "documento " * 50}},
        ])
        out = retrieve(self.store, "documento", 64)
        self.assertEqual(out["selected"], [])
        self.assertIn("budget", out["excluded_summary"])
        self.assertEqual(out["schema"], "an-kla/retrieval-result-v1")
        self.assertNotIn("empty_reason", out)

    def test_empty_store_does_not_emit_reason(self):
        # (v) store sin registros → sin razón.
        out = retrieve(self.store, "quetzal", 10000)
        self.assertEqual(out["schema"], "an-kla/retrieval-result-v1")
        self.assertNotIn("empty_reason", out)

    def test_degraded_index_with_zero_overlap_emits_reason(self):
        # (vi) degradación de índice + overlap cero → el fallback escaneó
        # todo: la señal procede.
        from unittest.mock import patch

        import an_kla.retrieval as retrieval_module

        from an_kla.index import INDEX_PROFILE, build_index

        self._seed([
            {"id": "f-a", "schema": "an-kla/fact-v1", "payload": {"text": "deployment parser"}},
        ])
        build_index(self.store)
        with patch.object(retrieval_module, "detect_fts5", return_value=False):
            out = retrieve(self.store, "quetzal pendiente", 10000, profile=INDEX_PROFILE)
        self.assertEqual(out["degradation"], "fts5_unavailable")
        self.assertEqual(out["schema"], "an-kla/retrieval-result-v3")
        self.assertEqual(out["empty_reason"], "no_lexical_overlap")

    def test_matching_query_stays_on_v1(self):
        # La ruta no vacía permanece byte-idéntica (v3 es disperso).
        self._seed([
            {"id": "f-a", "schema": "an-kla/fact-v1", "payload": {"text": "deployment parser"}},
        ])
        out = retrieve(self.store, "deployment", 10000)
        self.assertEqual(out["schema"], "an-kla/retrieval-result-v1")
        self.assertNotIn("empty_reason", out)

    def test_resume_never_receives_v3(self):
        # F-PC2-4: resume-evidence-v1 congela source="retrieval-result-v1";
        # resume con selección vacía no estampa ninguna mentira de fuente.
        from an_kla.resume import resume

        self._seed([
            {"id": "f-a", "schema": "an-kla/fact-v1", "payload": {"text": "deployment parser"}},
        ])
        out = resume(self.store, 4096, query="quetzal pendiente")
        self.assertEqual(out["retrieved_evidence"], [])
        self.assertNotIn("empty_reason", out)

    def test_resume_stamps_truthful_v1_on_nonempty_evidence(self):
        # F-C1-3: la red de seguridad debe poder fallar — con selección
        # no vacía (ruta v1, sin freshness), cada evidence estampa
        # source="retrieval-result-v1" y es verdad verificable.
        from an_kla.resume import resume

        self._seed([
            {"id": "f-a", "schema": "an-kla/fact-v1", "payload": {"text": "deployment parser"}},
        ])
        direct = retrieve(self.store, "deployment", 10_000)
        self.assertEqual(direct["schema"], "an-kla/retrieval-result-v1")
        out = resume(self.store, 4096, query="deployment")
        self.assertGreaterEqual(len(out["retrieved_evidence"]), 1)
        for item in out["retrieved_evidence"]:
            self.assertEqual(item["source"], "retrieval-result-v1")

    def test_all_inactive_no_text_mixture_boundary(self):
        # (iii) F-C1-6: no_text-only no emite; mezcla zero_score+no_text
        # emite (la condición base sólo exige zero_score>=1 sin budget).
        self._seed([
            {"id": "f-empty", "schema": "an-kla/fact-v1", "payload": {}},
        ])
        out = retrieve(self.store, "quetzal pendiente", 10_000)
        self.assertEqual(out["schema"], "an-kla/retrieval-result-v1")
        self.assertNotIn("empty_reason", out)
        self.store.commit(
            expected_current_hash=self.store.read_current(),
            checkpoint_patch={},
            facts=[
                {"id": "f-b", "schema": "an-kla/fact-v1", "payload": {"text": "deployment parser"}},
                {"id": "f-empty2", "schema": "an-kla/fact-v1", "payload": {}},
            ],
        )
        out = retrieve(self.store, "quetzal pendiente", 10_000)
        self.assertEqual(out["schema"], "an-kla/retrieval-result-v3")
        self.assertEqual(out["empty_reason"], "no_lexical_overlap")

    def test_assembly_with_zero_overlap_and_freshness_stays_v2(self):
        # F-C1-2 (contexto): detector estructural — ensamblado con fuente
        # v3+freshness produce context-assembly-v2 sin error.
        from an_kla.context import assemble_context

        self._seed([
            {"id": "f-a", "schema": "an-kla/fact-v1", "verified_at": "2026-08-01T00:00:00Z",
             "payload": {"text": "deployment parser"}},
        ])
        from datetime import datetime, timezone

        out = assemble_context(
            self.store, "quetzal pendiente", 2400,
            new_information="solicitud actual",
            freshness_profile="computed-age/v1",
            now=datetime(2026, 9, 11, tzinfo=timezone.utc),
            stale_after_days=30,
        )
        self.assertEqual(out["schema"], "an-kla/context-assembly-v2")


if __name__ == "__main__":
    unittest.main()
