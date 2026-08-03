from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from an_kla import VERSION, capabilities
from an_kla.canonical import canonical_json, digest_bytes
from an_kla.schemas import schema_bytes, schema_catalog, schema_names


ROOT = Path(__file__).resolve().parents[1]
SOURCE_SCHEMAS = ROOT / "docs" / "schemas"


class InstalledSchemaTests(unittest.TestCase):
    expected_names = (
        "cost-certificate-v1",
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


class AgentCapabilityTests(unittest.TestCase):
    def test_capabilities_are_deterministic_and_describe_facts_only_v1(self) -> None:
        first = capabilities()
        second = capabilities()
        self.assertEqual(canonical_json(first), canonical_json(second))
        self.assertEqual(first["product"]["version"], VERSION)
        self.assertEqual(first["retrieval"]["default_profile"], "scan-fallback/v1")
        self.assertTrue(
            all(
                item["streams_searched"] == ["facts"]
                for item in first["retrieval"]["profiles"]
            )
        )
        self.assertTrue(first["mcp"]["read_only"])
        self.assertFalse(first["limits"]["writable_mcp"])
        self.assertFalse(first["cost"]["exact_tokens"])
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
