from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from an_kla import VERSION, capabilities
from an_kla.canonical import canonical_json, digest_bytes
from an_kla.schemas import schema_bytes, schema_catalog, schema_document, schema_names


ROOT = Path(__file__).resolve().parents[1]
SOURCE_SCHEMAS = ROOT / "docs" / "schemas"


class InstalledSchemaTests(unittest.TestCase):
    expected_names = (
        "checkpoint-authority-v1",
        "checkpoint-decision-v1",
        "checkpoint-plan-v1",
        "checkpoint-proposal-v1",
        "checkpoint-v2",
        "commit-outcome-v2",
        "compaction-cleanup-receipt-v1",
        "compaction-epoch-v1",
        "compaction-plan-v1",
        "compaction-planning-result-v1",
        "compaction-policy-config-v1",
        "compaction-proposal-v1",
        "compaction-restore-proof-v1",
        "compaction-result-v1",
        "compaction-tombstone-catalog-v1",
        "context-assembly-v2",
        "cost-certificate-v1",
        "durability-receipt-v1",
        "export-manifest-v1",
        "export-result-v1",
        "export-verify-result-v1",
        "identity-adoption-plan-v1",
        "identity-durability-receipt-v1",
        "identity-intent-v1",
        "identity-operation-result-v1",
        "identity-status-v1",
        "mcp-retrieve-v2",
        "project-identity-v1",
        "provenance-manifest-v1",
        "reference-benchmark-v1",
        "refutation-v1",
        "refute-authority-attestation-v1",
        "refute-authority-claim-v1",
        "refute-commit-result-v1",
        "refute-decision-v1",
        "refute-inspect-v1",
        "refute-observations-v1",
        "refute-plan-v1",
        "refute-planning-result-v1",
        "refute-policy-config-v1",
        "refute-policy-transaction-v1",
        "refute-proposal-v1",
        "restore-result-v1",
        "resume-evidence-v1",
        "resume-v1",
        "retrieval-eval-query-v2",
        "retrieval-eval-report-v2",
        "retrieval-result-v2",
        "retrieval-strategy-report-v1",
        "revision-v2",
        "revision-v3",
        "store-identity-v1",
        "transaction-archived-v1",
        "transaction-attempt-v1",
        "upgrade-plan-v1",
        "verify-revision-v1",
        "working-state-v2",
        "write-authority-v1",
        "write-decision-v1",
        "write-plan-v1",
        "write-proposal-v1",
    )

    def test_installed_resources_match_normative_source_bytes(self) -> None:
        self.assertEqual(schema_names(), self.expected_names)
        for name in self.expected_names:
            with self.subTest(name=name):
                source = (SOURCE_SCHEMAS / f"{name}.schema.json").read_bytes()
                self.assertEqual(schema_bytes(name), source)

    def test_catalog_is_content_addressed_and_canonicalizable(self) -> None:
        catalog = schema_catalog()
        self.assertEqual(catalog["schema"], "an-kla/schema-list-v1")
        self.assertEqual(
            [item["name"] for item in catalog["schemas"]], list(self.expected_names)
        )
        for item in catalog["schemas"]:
            self.assertEqual(item["sha256"], digest_bytes(schema_bytes(item["name"])))
            self.assertTrue(item["id"].startswith("urn:an-kla:schema:"))
        self.assertEqual(json.loads(canonical_json(catalog)), catalog)

    def test_unknown_schema_fails_with_stable_code(self) -> None:
        with self.assertRaisesRegex(ValueError, "^unknown_schema$"):
            schema_bytes("unknown")

        completed = subprocess.run(
            [sys.executable, "-m", "an_kla", "schema", "show", "unknown"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "")
        self.assertIn("an-kla error: unknown_schema", completed.stderr)
        self.assertNotIn(str(ROOT), completed.stderr)

    def test_refute_schemas_are_closed_and_do_not_publish_raw_target_id(self) -> None:
        names = [name for name in self.expected_names if name.startswith("refut") or name == "revision-v2"]
        for name in names:
            with self.subTest(name=name):
                self.assertFalse(schema_document(name).get("additionalProperties", True))
        refutation = schema_document("refutation-v1")
        self.assertNotIn("target_id", refutation["properties"])
        revision = schema_document("revision-v2")
        entry = revision["$defs"]["refutation_entry"]
        self.assertEqual(
            set(entry["required"]),
            {"stream", "target_record_sha256", "refutation_id"},
        )
        attempt = schema_document("transaction-attempt-v1")
        self.assertIn("refute", attempt["oneOf"][0]["properties"]["operation"]["enum"])

    def test_checkpoint_nested_schemas_are_closed_and_conditional(self) -> None:
        working = schema_document("working-state-v2")
        self.assertIn("oneOf", working["$defs"]["field"])
        self.assertEqual(
            working["$defs"]["unavailable"]["properties"]["value"]["type"],
            "null",
        )
        timestamp = working["$defs"]["timefield"]["oneOf"][0]["properties"][
            "value"
        ]["oneOf"][0]
        self.assertEqual(timestamp["format"], "date-time")
        self.assertIn("pattern", timestamp)
        authority = schema_document("checkpoint-authority-v1")
        self.assertEqual(
            authority["$defs"]["evidence"]["allOf"][0]["then"]["required"],
            ["sha256"],
        )
        issuer_pairs = {
            (
                item["if"]["properties"]["authority_class"]["const"],
                item["then"]["properties"]["issuer"]["properties"]["kind"]["const"],
            )
            for item in authority["allOf"]
        }
        self.assertEqual(
            issuer_pairs,
            {
                ("tool_observed", "tool"),
                ("channel_confirmed", "channel"),
                ("model_derived", "model"),
                ("unresolved", "unknown"),
            },
        )
        resume_schema = schema_document("resume-v1")
        self.assertIn("oneOf", resume_schema["properties"]["snapshot"])
        for name in ("v1snapshot", "v2snapshot", "memory", "provenance"):
            self.assertFalse(resume_schema["$defs"][name]["additionalProperties"])
        retrieval = resume_schema["$defs"]["retrieval"]["oneOf"]
        self.assertTrue(all(not item["additionalProperties"] for item in retrieval))


class AgentCapabilityTests(unittest.TestCase):
    def test_capabilities_are_deterministic_and_describe_facts_only_v1(self) -> None:
        first = capabilities()
        second = capabilities()
        self.assertEqual(canonical_json(first), canonical_json(second))
        self.assertEqual(first["product"]["version"], VERSION)
        self.assertEqual(first["retrieval"]["default_profile"], "scan-fallback/v1")
        self.assertEqual(
            first["retrieval"]["freshness"]["semantics"],
            "self_asserted_timestamp",
        )
        self.assertTrue(first["retrieval"]["freshness"]["data_not_authority"])
        self.assertTrue(
            all(
                item["streams_searched"] == ["facts"]
                for item in first["retrieval"]["profiles"]
            )
        )
        self.assertTrue(first["mcp"]["read_only"])
        self.assertFalse(first["limits"]["writable_mcp"])
        self.assertFalse(first["cost"]["exact_tokens"])
        self.assertFalse(first["upgrade"]["package_self_update"])
        self.assertTrue(first["upgrade"]["requires_exact_installed_target"])
        self.assertEqual(
            first["write_policy"]["legacy_unguarded_cli"],
            {
                "command": "write",
                "requires_flag": "--allow-legacy-unguarded-write",
                "warning": "legacy_unguarded_write_enabled",
                "removal_target": "v0.1.0-beta.10",
            },
        )
        self.assertEqual(
            [item["name"] for item in first["schemas"]], list(schema_names())
        )

    def test_discovery_cli_is_canonical_and_does_not_create_project_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capabilities_run = subprocess.run(
                [sys.executable, "-m", "an_kla", "--project-root", directory, "capabilities"],
                cwd=ROOT,
                capture_output=True,
                check=True,
            )
            schema_list_run = subprocess.run(
                [sys.executable, "-m", "an_kla", "--project-root", directory, "schema", "list"],
                cwd=ROOT,
                capture_output=True,
                check=True,
            )
            schema_show_run = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "an_kla",
                    "--project-root",
                    directory,
                    "schema",
                    "show",
                    "write-proposal-v1",
                ],
                cwd=ROOT,
                capture_output=True,
                check=True,
            )
            self.assertEqual(capabilities_run.stdout, canonical_json(capabilities()))
            self.assertEqual(schema_list_run.stdout, canonical_json(schema_catalog()))
            self.assertEqual(
                schema_show_run.stdout, schema_bytes("write-proposal-v1")
            )
            self.assertFalse((root / ".an-kla").exists())


if __name__ == "__main__":
    unittest.main()
