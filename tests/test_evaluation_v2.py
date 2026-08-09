from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from an_kla.benchmark_fixture import (
    PROVENANCE_PATH,
    QUERIES_PATH,
    build_reference_store,
    run_reference_benchmark,
    run_reference_retrieval_benchmark,
)
from an_kla.benchmark_provenance import (
    contains_forbidden_content,
    validate_provenance_manifest,
)
from an_kla.capabilities import capabilities
from an_kla.canonical import canonical_json
from an_kla.evaluation_v2 import (
    _ranking_metrics,
    evaluate_states_v2,
    evaluate_retrieval_v2,
    read_queries_v2,
)
from an_kla.evaluation_strategies import evaluate_all_strategies
from an_kla.schemas import schema_document, schema_names
from an_kla.store import MemoryStore


ROOT = Path(__file__).resolve().parents[1]


def _write_queries(path: Path, rows: list[dict]) -> None:
    path.write_bytes(b"".join(canonical_json(row) + b"\n" for row in rows))


class RetrievalEvaluationV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.reference = run_reference_retrieval_benchmark()
        cls.bundle = run_reference_benchmark()

    def test_reference_fixture_is_byte_and_revision_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as left, tempfile.TemporaryDirectory() as right:
            left_store, left_result = build_reference_store(left)
            right_store, right_result = build_reference_store(right)
            self.assertEqual(left_result, right_result)
            left_files = {
                str(path.relative_to(left_store.root)): path.read_bytes()
                for path in left_store.root.rglob("*") if path.is_file()
            }
            right_files = {
                str(path.relative_to(right_store.root)): path.read_bytes()
                for path in right_store.root.rglob("*") if path.is_file()
            }
            self.assertEqual(left_files, right_files)
            self.assertEqual(
                left_result["revision"],
                "sha256:ddc8ffd48427ce0f5b2b2742469c04e5743eabc7c695278bdc30bbf15b57519e",
            )

    def test_reference_matrix_has_exact_parity_and_degradation_cardinality(self) -> None:
        report = self.reference
        self.assertEqual(report["query_count"], 5)
        self.assertEqual(
            report["configuration"]["index_fixture_states"],
            ["absent", "fresh", "corrupt", "stale"],
        )
        summaries = {item["index_fixture_state"]: item for item in report["parity_summary"]["by_state"]}
        for state, item in summaries.items():
            self.assertEqual(item["ranking"]["total"], 5)
            self.assertEqual(item["ranking"]["mismatches"], 0)
            self.assertEqual(item["budgets"]["total"], 20)
            self.assertEqual(item["budgets"]["mismatches"], 0)
            expected_index = 5 if state == "fresh" else 0
            self.assertEqual(item["ranking"]["actual_index"], expected_index)
            self.assertEqual(item["budgets"]["actual_index"], expected_index * 4)

    def test_ranking_is_not_contaminated_by_4096_budget_and_chain_is_inactive(self) -> None:
        by_id = {row["id"]: row for row in self.reference["rows"]}
        handoff = by_id["q-handoff-next-step"]["runs"][0]
        self.assertIn("f-long", handoff["ranking"]["ranked_ids"])
        self.assertGreater(handoff["ranking"]["ranking_budget"], 4096)
        self.assertNotIn("f-long", handoff["budgets"][-1]["selected_ids"])
        chain = by_id["q-chain-active"]["runs"][0]["ranking"]["ranked_ids"]
        self.assertIn("f-chain-c", chain)
        self.assertNotIn("f-chain-a", chain)
        self.assertNotIn("f-chain-b", chain)

    def test_manual_metrics_preserve_order_and_denominators(self) -> None:
        metrics = _ranking_metrics(["x", "relevant", "later"], ["relevant"], [1, 2])
        self.assertEqual(metrics["first_relevant_rank"], 2)
        self.assertEqual(metrics["mrr"], {"numerator": 1, "denominator": 2, "value": 0.5})
        self.assertEqual(metrics["precision_at_k"][0]["metric"]["denominator"], 1)
        self.assertEqual(metrics["recall_at_k"][1]["metric"]["value"], 1.0)

    def test_strategy_reports_are_separate_and_overlap_matches_product(self) -> None:
        names = [item["strategy"]["name"] for item in self.bundle["strategy_reports"]]
        self.assertEqual(
            names,
            ["overlap/v1", "bm25-experiment/v1", "summary-indexed-experiment/v1"],
        )
        overlap, bm25, summary = self.bundle["strategy_reports"]
        self.assertTrue(overlap["reproducibility"]["cross_runtime_byte_stable"])
        self.assertFalse(bm25["reproducibility"]["cross_runtime_byte_stable"])
        self.assertIsNotNone(bm25["reproducibility"]["runtime_descriptor"])
        self.assertTrue(summary["reproducibility"]["cross_runtime_byte_stable"])
        self.assertFalse(self.bundle["conclusion"]["ranking_change_authorized"])
        advertised = json.dumps(capabilities(), sort_keys=True)
        self.assertNotIn("experimental_strategies", advertised)
        self.assertNotIn("bm25-experiment/v1", advertised)
        self.assertNotIn("summary-indexed-experiment/v1", advertised)
        with tempfile.TemporaryDirectory() as directory:
            store, fixture = build_reference_store(directory)
            original = store.read_current
            with patch.object(store, "read_current", wraps=original) as observed:
                reports = evaluate_all_strategies(
                    store, read_queries_v2(QUERIES_PATH), [256], [1]
                )
            self.assertEqual(observed.call_count, 1)
            self.assertEqual(
                {report["revision"] for report in reports}, {fixture["revision"]}
            )

    def test_bm25_rows_are_stable_across_hash_seeds(self) -> None:
        command = (
            "from an_kla.benchmark_fixture import run_reference_benchmark;"
            "from an_kla.canonical import digest_json;"
            "print(digest_json(run_reference_benchmark()"
            "['strategy_reports'][1]['rows']))"
        )
        digests = []
        for seed in ("1", "2", "42"):
            result = subprocess.run(
                [sys.executable, "-c", command],
                cwd=ROOT,
                env={
                    **os.environ,
                    "AN_KLA_NO_UPDATE_CHECK": "1",
                    "PYTHONHASHSEED": seed,
                },
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            digests.append(result.stdout.strip())
        self.assertEqual(len(set(digests)), 1)

    def test_general_evaluation_uses_external_corpus_and_rejects_ambiguous_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(directory)
            root = store.initialize()
            store.commit(
                expected_current_hash=root,
                checkpoint_patch={},
                facts=[{"id": "same", "payload": {"text": "needle"}}],
                events=[{"id": "same", "payload": {"summary": "needle"}}],
            )
            queries = Path(directory) / "queries.jsonl"
            row = {
                "schema": "an-kla/retrieval-eval-query-v2",
                "id": "q",
                "category": "synthetic",
                "query": "needle",
                "relevant": ["same"],
                "streams": ["facts", "events"],
            }
            _write_queries(queries, [row])
            with self.assertRaisesRegex(ValueError, "ambiguous_evaluation_record_id"):
                evaluate_retrieval_v2(store, queries, [256])

    def test_general_evaluation_reads_current_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(directory)
            root = store.initialize()
            store.commit(
                expected_current_hash=root,
                checkpoint_patch={},
                facts=[{"id": "f-one", "payload": {"text": "needle"}}],
            )
            queries = Path(directory) / "queries.jsonl"
            _write_queries(queries, [{
                "schema": "an-kla/retrieval-eval-query-v2",
                "id": "q",
                "category": "synthetic",
                "query": "needle",
                "relevant": ["f-one"],
                "streams": ["facts"],
            }])
            original = store.read_current
            with patch.object(store, "read_current", wraps=original) as observed:
                report = evaluate_retrieval_v2(store, queries, [256])
            self.assertEqual(observed.call_count, 1)
            self.assertEqual(report["revision"], store.read_current())

    def test_query_validation_is_closed_sorted_and_nonempty(self) -> None:
        self.assertEqual(len(read_queries_v2(QUERIES_PATH)), 5)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "queries.jsonl"
            path.write_text("", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid_evaluation_query"):
                read_queries_v2(path)
            bad = {
                "schema": "an-kla/retrieval-eval-query-v2",
                "id": "q",
                "category": "synthetic",
                "query": "x",
                "relevant": ["z", "a"],
                "streams": ["facts"],
            }
            _write_queries(path, [bad])
            with self.assertRaisesRegex(ValueError, "invalid_evaluation_query"):
                read_queries_v2(path)
        with self.assertRaisesRegex(ValueError, "invalid_evaluation_query"):
            evaluate_states_v2({}, [], [256], [1], None)

    def test_latency_is_descriptive_and_does_not_change_config_digest(self) -> None:
        without = self.reference
        with_latency = run_reference_retrieval_benchmark(measure_latency=True)
        self.assertIsNone(without["latency"])
        self.assertTrue(with_latency["latency"]["non_contractual"])
        self.assertEqual(
            without["configuration"]["config_sha256"],
            with_latency["configuration"]["config_sha256"],
        )

    def test_reference_outputs_validate_against_packaged_schemas(self) -> None:
        try:
            from jsonschema import Draft202012Validator
            from jsonschema.exceptions import ValidationError
            from referencing import Registry, Resource
        except ImportError:
            self.skipTest("jsonschema unavailable")
        documents = [schema_document(name) for name in schema_names()]
        registry = Registry().with_resources(
            [(item["$id"], Resource.from_contents(item)) for item in documents]
        )
        report_validator = Draft202012Validator(
            schema_document("retrieval-eval-report-v2"), registry=registry
        )
        benchmark_validator = Draft202012Validator(
            schema_document("reference-benchmark-v1"), registry=registry
        )
        strategy_validator = Draft202012Validator(
            schema_document("retrieval-strategy-report-v1"), registry=registry
        )
        provenance_validator = Draft202012Validator(
            schema_document("provenance-manifest-v1"), registry=registry
        )
        report_validator.validate(self.reference)
        benchmark_validator.validate(self.bundle)
        for strategy in self.bundle["strategy_reports"]:
            strategy_validator.validate(strategy)
        provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
        provenance_validator.validate(provenance)

        wrong_order = deepcopy(self.bundle)
        wrong_order["strategy_reports"][0:2] = reversed(
            wrong_order["strategy_reports"][0:2]
        )
        with self.assertRaises(ValidationError):
            benchmark_validator.validate(wrong_order)

        wrong_score = deepcopy(self.bundle["strategy_reports"][1])
        score = wrong_score["rows"][0]["ranking"]["ranked_scores"][0]
        score.clear()
        score.update({"id": "wrong", "score": 1})
        with self.assertRaises(ValidationError):
            strategy_validator.validate(wrong_score)

        wrong_review = deepcopy(provenance)
        wrong_review["human_review"]["reviewer"] = "agent"
        with self.assertRaises(ValidationError):
            provenance_validator.validate(wrong_review)

        with self.assertRaisesRegex(ValueError, "invalid_reference_provenance"):
            validate_provenance_manifest(wrong_review, provenance["corpus_sha256"])
        wrong_sanitization = deepcopy(provenance)
        wrong_sanitization["sanitization"]["method"] = "unknown"
        with self.assertRaisesRegex(ValueError, "invalid_reference_provenance"):
            validate_provenance_manifest(
                wrong_sanitization, provenance["corpus_sha256"]
            )
        self.assertTrue(contains_forbidden_content([], [{
            "stream": "facts",
            "record": {"id": "f-private", "payload": {"text": "/Users/alice/private"}},
        }]))

    def test_corpus_scan_and_cli_are_executable(self) -> None:
        scan = subprocess.run(
            [sys.executable, "scripts/check_benchmark_corpus.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(scan.returncode, 0, scan.stderr)
        self.assertIn("human_review=passed", scan.stdout)
        cli = subprocess.run(
            [
                sys.executable, "-m", "an_kla", "--no-update-check",
                "benchmark-reference",
            ],
            cwd=ROOT,
            env={**os.environ, "AN_KLA_NO_UPDATE_CHECK": "1"},
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(cli.returncode, 0, cli.stderr.decode())
        payload = json.loads(cli.stdout)
        self.assertEqual(payload["schema"], "an-kla/reference-benchmark-v1")
        self.assertEqual(cli.stdout, canonical_json(payload))

        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(directory)
            root = store.initialize()
            store.commit(
                expected_current_hash=root,
                checkpoint_patch={},
                facts=[{"id": "f-cli", "payload": {"text": "needle"}}],
            )
            queries = Path(directory) / "queries.jsonl"
            _write_queries(queries, [{
                "schema": "an-kla/retrieval-eval-query-v2",
                "id": "q-cli",
                "category": "synthetic",
                "query": "needle",
                "relevant": ["f-cli"],
                "streams": ["facts"],
            }])
            external = subprocess.run(
                [
                    sys.executable, "-m", "an_kla", "--no-update-check",
                    "--project-root", directory, "evaluate-v2",
                    "--queries", str(queries), "--budgets", "256,512",
                ],
                cwd=ROOT,
                env={**os.environ, "AN_KLA_NO_UPDATE_CHECK": "1"},
                capture_output=True,
                timeout=30,
            )
            self.assertEqual(external.returncode, 0, external.stderr.decode())
            external_payload = json.loads(external.stdout)
            self.assertEqual(
                external_payload["corpus"]["schema"],
                "an-kla/external-eval-corpus-v1",
            )
            self.assertEqual(external.stdout, canonical_json(external_payload))

            invalid_queries = Path(directory) / "invalid-queries.jsonl"
            _write_queries(invalid_queries, [{
                "schema": "an-kla/retrieval-eval-query-v2",
                "id": "q-invalid",
                "category": "synthetic",
                "query": "needle",
                "relevant": ["f-cli"],
                "streams": [{}],
            }])
            invalid = subprocess.run(
                [
                    sys.executable, "-m", "an_kla", "--no-update-check",
                    "--project-root", directory, "evaluate-v2",
                    "--queries", str(invalid_queries), "--budgets", "256",
                ],
                cwd=ROOT,
                env={**os.environ, "AN_KLA_NO_UPDATE_CHECK": "1"},
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("an-kla error: invalid_evaluation_query", invalid.stderr)
            self.assertNotIn("Traceback", invalid.stderr)


if __name__ == "__main__":
    unittest.main()
