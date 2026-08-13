from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from an_kla import VERSION, capabilities
from an_kla.canonical import canonical_json, digest_bytes
from an_kla.context_view import (
    CONTRACT_VERSION as VIEW_CONTRACT_VERSION,
    DEFAULT_BUDGET_BYTES as VIEW_DEFAULT_BUDGET_BYTES,
    DEFAULT_LIMIT as VIEW_DEFAULT_LIMIT,
    DEFAULT_STREAMS as VIEW_DEFAULT_STREAMS,
    ERROR_CODES as VIEW_ERROR_CODES,
    ERROR_SCHEMA as VIEW_ERROR_SCHEMA,
    MAX_BUDGET_BYTES as VIEW_MAX_BUDGET_BYTES,
    MAX_CURSOR_CHARS as VIEW_MAX_CURSOR_CHARS,
    OPERATION as VIEW_OPERATION,
    PROFILE as VIEW_PROFILE,
    PROJECTIONS as VIEW_PROJECTIONS,
    READ_COORDINATION_SIDE_EFFECT as VIEW_READ_COORDINATION_SIDE_EFFECT,
    SUCCESS_SCHEMA as VIEW_SUCCESS_SCHEMA,
    SURFACES as VIEW_SURFACES,
    WARNING_CODES as VIEW_WARNING_CODES,
)
from an_kla.schemas import schema_bytes, schema_catalog, schema_document, schema_names
from an_kla.write_policy import policy_configuration, policy_fingerprint


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
        "context-view-v1",
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
        "subject-namespace-result-v1",
        "transaction-archived-v1",
        "transaction-attempt-v1",
        "upgrade-plan-v1",
        "verify-revision-v1",
        "view-error-v1",
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
    expected_view = {
        "profile": VIEW_PROFILE,
        "contract_version": VIEW_CONTRACT_VERSION,
        "canonicality": "non-authoritative",
        "untrusted_memory_data": True,
        "requires_explicit_revision": True,
        "resolves_current": False,
        "operations": [VIEW_OPERATION],
        "surfaces": dict(VIEW_SURFACES),
        "schemas": {
            "success": VIEW_SUCCESS_SCHEMA,
            "error": VIEW_ERROR_SCHEMA,
        },
        "projections": list(VIEW_PROJECTIONS),
        "default_streams": list(VIEW_DEFAULT_STREAMS),
        "limits": {
            "default_limit": VIEW_DEFAULT_LIMIT,
            "default_budget_bytes": VIEW_DEFAULT_BUDGET_BYTES,
            "maximum_budget_bytes": VIEW_MAX_BUDGET_BYTES,
            "maximum_cursor_chars": VIEW_MAX_CURSOR_CHARS,
            "subject_atomic_pagination": True,
        },
        "purity": {
            "level": "L2",
            "substrate_mutation": False,
            "write_lock": False,
            "persistent_cache": False,
        },
        "read_coordination_side_effect": VIEW_READ_COORDINATION_SIDE_EFFECT,
        "warnings": list(VIEW_WARNING_CODES),
        "terminal_codes": list(VIEW_ERROR_CODES),
    }

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
                "available": False,
                "removed_in": "v0.1.0-beta.11",
            },
        )
        self.assertEqual(
            [item["name"] for item in first["schemas"]], list(schema_names())
        )
        self.assertEqual(first["view"], self.expected_view)

    def test_view_capability_is_unshared_and_does_not_observe_project_data(self) -> None:
        subject_kinds = {
            "actor", "api", "decision", "dependency", "doc", "environment",
            "integration", "issue", "project", "service", "system",
        }
        first = capabilities()
        first["view"]["projections"].append("MUTATED")
        first["view"]["terminal_codes"].clear()
        second = capabilities()
        self.assertEqual(second["view"], self.expected_view)
        def walk(value: object) -> None:
            if isinstance(value, dict):
                for key, nested in value.items():
                    self.assertNotIn("namespace", key.lower())
                    self.assertNotIn("kind", key.lower())
                    walk(nested)
            elif isinstance(value, list):
                for nested in value:
                    walk(nested)
            elif isinstance(value, str):
                if value == "multiple_namespaces_observed":
                    return
                self.assertNotIn(value, subject_kinds)
                self.assertNotIn("an-kla:subject:v1:", value)
                self.assertNotRegex(value, r"^p-[0-9a-f]{32}$")
                self.assertNotIn("actor|api|decision", value)

        walk(second["view"])

    def test_view_discovery_constants_match_normative_contract(self) -> None:
        self.assertEqual(VIEW_PROFILE, "derived-context-view/v1")
        self.assertEqual(VIEW_OPERATION, "context")
        self.assertEqual(
            dict(VIEW_SURFACES),
            {"cli": "view context", "mcp": "an_kla_view_context"},
        )
        self.assertEqual(
            VIEW_WARNING_CODES,
            ("legacy_records_without_subject_ref", "multiple_namespaces_observed"),
        )
        success_schema = schema_document("context-view-v1")
        schema_warnings = tuple(
            success_schema["properties"]["warnings"]["items"]["enum"]
        )
        self.assertEqual(VIEW_WARNING_CODES, schema_warnings)
        error_schema = schema_document("view-error-v1")
        schema_codes = tuple(
            branch["properties"]["code"]["const"]
            for branch in error_schema["oneOf"]
        )
        self.assertEqual(set(VIEW_ERROR_CODES), set(schema_codes))
        self.assertEqual(len(VIEW_ERROR_CODES), len(schema_codes))

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


class SubjectNamespaceSchemaTests(unittest.TestCase):
    def test_schema_catalog_includes_subject_namespace_result_v1(self) -> None:
        names = schema_names()
        self.assertIn("subject-namespace-result-v1", names)
        catalog = schema_catalog()
        entry = next(
            item for item in catalog["schemas"]
            if item["name"] == "subject-namespace-result-v1"
        )
        self.assertEqual(
            entry["id"], "urn:an-kla:schema:subject-namespace-result:v1"
        )
        self.assertEqual(
            entry["sha256"], digest_bytes(schema_bytes("subject-namespace-result-v1"))
        )

    def test_schema_copies_are_byte_identical(self) -> None:
        installed = schema_bytes("subject-namespace-result-v1")
        source = (SOURCE_SCHEMAS / "subject-namespace-result-v1.schema.json").read_bytes()
        self.assertEqual(installed, source)

    def test_schema_is_closed_with_conditional_namespace(self) -> None:
        document = schema_document("subject-namespace-result-v1")
        self.assertFalse(document.get("additionalProperties", True))
        self.assertEqual(
            document["properties"]["schema"]["const"],
            "an-kla/subject-namespace-result-v1",
        )
        self.assertEqual(
            document["properties"]["result"]["enum"],
            ["namespace_available", "namespace_unavailable"],
        )
        branches = {
            branch["if"]["properties"]["result"]["const"]: branch
            for branch in document["allOf"]
        }
        self.assertEqual(
            set(branches),
            {"namespace_available", "namespace_unavailable"},
        )
        available_namespace = branches["namespace_available"]["then"]["properties"]["namespace"]
        self.assertEqual(available_namespace["pattern"], "^p-[0-9a-f]{32}$")
        # Phase C L-1: redundant defensive maxLength next to the pattern.
        # ``p-`` (2) + 32 hex = 34 chars; the regex already constrains this,
        # but the explicit cap hardens against future regex drift.
        self.assertEqual(available_namespace["maxLength"], 34)
        self.assertEqual(
            branches["namespace_unavailable"]["then"]["properties"]["namespace"]["type"],
            "null",
        )
        self.assertNotIn("project_identity_sha256", document["properties"])


class RecordValidatorsCapabilityTests(unittest.TestCase):
    expected_record_validators = {
        "subject_ref": "an-kla-subject-ref/v1",
        "verified_at": "an-kla-verified-at/v1",
    }

    def test_capabilities_exposes_record_validators_mapping(self) -> None:
        cap = capabilities()
        self.assertIn("record_validators", cap["write_policy"])
        self.assertEqual(
            cap["write_policy"]["record_validators"],
            self.expected_record_validators,
        )

    def test_record_validators_serialization_is_deterministic(self) -> None:
        first = capabilities()
        second = capabilities()
        self.assertEqual(
            canonical_json(first["write_policy"]["record_validators"]),
            canonical_json(second["write_policy"]["record_validators"]),
        )
        self.assertEqual(canonical_json(first), canonical_json(second))

    def test_capabilities_do_not_expose_subject_view_or_kinds_or_namespaces(
        self,
    ) -> None:
        cap = capabilities()
        write_policy = cap["write_policy"]
        self.assertNotIn("subject_view", write_policy)
        self.assertNotIn("kinds", write_policy)
        self.assertNotIn("subject_kinds", write_policy)
        self.assertNotIn("namespaces", write_policy)
        self.assertNotIn("subject_namespaces", write_policy)
        serialized = canonical_json(cap).decode("utf-8")
        self.assertNotIn("subject_view", serialized)
        self.assertNotIn("subject_kinds", serialized)
        self.assertNotIn('"namespaces":', serialized)
        self.assertNotIn("an-kla:subject:v1:", serialized)
        self.assertNotIn("actor|api|decision", serialized)
        self.assertNotIn("p-[0-9a-f]{32}", serialized)

    def test_record_validators_returned_mapping_is_unshared(self) -> None:
        policy_before = policy_configuration()
        fingerprint_before = policy_fingerprint()
        first = capabilities()
        first["write_policy"]["record_validators"]["subject_ref"] = "MUTATED"
        first["write_policy"]["record_validators"]["injected"] = "x"
        second = capabilities()
        self.assertEqual(
            second["write_policy"]["record_validators"],
            self.expected_record_validators,
        )
        self.assertEqual(policy_configuration(), policy_before)
        self.assertEqual(policy_fingerprint(), fingerprint_before)


if __name__ == "__main__":
    unittest.main()
