from __future__ import annotations

import ast
import json
from pathlib import Path
import unittest

from an_kla.canonical import digest_bytes
from an_kla.subject_ref import (
    SUBJECT_REF_PATTERN,
    SubjectRefError,
    derive_namespace,
    parse_subject_ref,
)


NAMESPACE = "p-" + "0" * 32
PREFIX = "an-kla:subject:v1:"
KINDS = (
    "actor",
    "api",
    "decision",
    "dependency",
    "doc",
    "environment",
    "integration",
    "issue",
    "project",
    "service",
    "system",
)
VALID_BY_KIND = {
    "actor": "team-platform",
    "api": "users-rest-v1",
    "decision": "adr-0033",
    "dependency": "lib-foo-1.2.3",
    "doc": "readme",
    "environment": "prod",
    "integration": "oauth-google",
    "issue": "gh-59",
    "project": "an-kla-memory",
    "service": "billing-svc",
    "system": "platform-x",
}


def ref(kind: str, namespace: str = NAMESPACE, subject_id: str = "gh-59") -> str:
    return f"{PREFIX}{kind}:{namespace}:{subject_id}"


class SubjectRefPatternTests(unittest.TestCase):
    def test_subject_ref_pattern_accepts_valid(self) -> None:
        for kind in KINDS:
            value = ref(kind, NAMESPACE, VALID_BY_KIND[kind])
            with self.subTest(kind=kind, value=value):
                self.assertIsNotNone(parse_subject_ref(value))
                self.assertEqual(len(value), len(value.encode("utf-8")))

    def test_subject_ref_pattern_rejects_invalid(self) -> None:
        valid = ref("actor")
        cases = {
            "none": None,
            "int": 7,
            "empty": "",
            "namespace_uppercase_P": ref("actor", "P-" + "0" * 32),
            "kind_uppercase": ref("ACTOR"),
            "id_non_ascii": ref("actor", NAMESPACE, "café"),
            "extra_colon": valid + ":extra",
            "namespace_33_hex": ref("actor", "p-" + "0" * 33),
            "namespace_31_hex": ref("actor", "p-" + "0" * 31),
            "namespace_hex_g": ref("actor", "p-" + "g" * 32),
            "version_v2": "an-kla:subject:v2:actor:" + NAMESPACE + ":gh-59",
            "kind_outside_enum": ref("widget"),
            "id_too_long_65": ref("environment", NAMESPACE, "a" * 65),
            "id_slash": ref("actor", NAMESPACE, "a/b"),
            "id_backslash": ref("actor", NAMESPACE, "a\\b"),
            "id_at": ref("actor", NAMESPACE, "a@b"),
            "id_question": ref("actor", NAMESPACE, "a?b"),
            "id_hash": ref("actor", NAMESPACE, "a#b"),
            "id_space": ref("actor", NAMESPACE, "a b"),
            "trailing_newline": valid + "\n",
            "leading_newline": "\n" + valid,
        }
        for name, value in cases.items():
            with self.subTest(name=name, value=value):
                with self.assertRaises(SubjectRefError) as caught:
                    parse_subject_ref(value)
                self.assertEqual(caught.exception.code, "invalid_subject_ref")
                self.assertEqual(str(caught.exception), "invalid_subject_ref")

    def test_max_length_129_is_accepted_and_130_rejected(self) -> None:
        # ADR-0033 §1: valid length 58-129 bytes. Longest kind (11) + id 64 =
        # 129 total; id 65 = 130 and must be rejected by the {1,64} quantifier.
        accepted = ref("environment", NAMESPACE, "a" * 64)
        self.assertEqual(len(accepted), 129)
        parse_subject_ref(accepted)
        rejected = ref("environment", NAMESPACE, "a" * 65)
        self.assertEqual(len(rejected), 130)
        with self.assertRaises(SubjectRefError):
            parse_subject_ref(rejected)


class ParseSubjectRefTests(unittest.TestCase):
    def test_parse_subject_ref_returns_typed_components(self) -> None:
        parsed = parse_subject_ref(ref("decision", NAMESPACE, "adr-0033"))
        self.assertEqual(parsed, {"kind": "decision", "namespace": NAMESPACE, "id": "adr-0033"})

    def test_parse_subject_ref_malformed_raises_subject_ref_error(self) -> None:
        # Regression (ADR-0033 §3 / plan H-5): malformed input must surface a
        # stable SubjectRefError, never an IndexError from naked split indexing.
        for value in ("", "no:colons", "a:b:c", "an-kla:subject:v1:only"):
            with self.subTest(value=value):
                try:
                    parse_subject_ref(value)
                except SubjectRefError:
                    continue
                self.fail("expected SubjectRefError, not success or IndexError")


class DeriveNamespaceTests(unittest.TestCase):
    def test_derive_namespace_matches_project_bytes_digest(self) -> None:
        project_bytes = b'{"project_uuid":"00000000-0000-4000-8000-000000000000"}'
        expected = "p-" + digest_bytes(project_bytes)[7:39]
        self.assertEqual(derive_namespace(project_bytes), expected)
        self.assertRegex(derive_namespace(project_bytes), r"^p-[0-9a-f]{32}$")

    def test_derive_namespace_is_deterministic(self) -> None:
        project_bytes = b"canonical-project-identity-bytes"
        self.assertEqual(
            derive_namespace(project_bytes), derive_namespace(project_bytes)
        )


class SubjectRefPatternIdentityTests(unittest.TestCase):
    def test_subject_ref_pattern_identical_in_code_and_both_schemas(self) -> None:
        docs_path = (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "schemas"
            / "write-proposal-v1.schema.json"
        )
        docs = json.loads(docs_path.read_text(encoding="utf-8"))
        from an_kla.schemas import schema_document

        pkg = schema_document("write-proposal-v1")
        pattern_docs = docs["properties"]["record"]["properties"]["subject_ref"]["pattern"]
        pattern_pkg = pkg["properties"]["record"]["properties"]["subject_ref"]["pattern"]
        self.assertEqual(pattern_docs, SUBJECT_REF_PATTERN)
        self.assertEqual(pattern_pkg, SUBJECT_REF_PATTERN)

    def test_subject_ref_pattern_has_no_backslashes(self) -> None:
        # No backslashes => identical byte-for-byte as Python raw string and as
        # JSON ``pattern`` value (no escaping ambiguity).
        self.assertNotIn("\\", SUBJECT_REF_PATTERN)


class SubjectRefImportBoundaryTests(unittest.TestCase):
    def test_subject_ref_does_not_import_write_policy_or_store(self) -> None:
        path = Path(__file__).resolve().parents[1] / "an_kla" / "subject_ref.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertTrue(
            imported.isdisjoint({"write_policy", "store", "identity"}),
            f"subject_ref.py must not import write_policy/store/identity; found {imported}",
        )
        self.assertIn("canonical", imported)


if __name__ == "__main__":
    unittest.main()
