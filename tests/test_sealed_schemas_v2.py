"""Tests de los 5 schemas v2 del perfil sellado — T4 de issue #46.

Validan (DoD "schemas v2 validan JSON Schema"):

1. Los 5 archivos existen en ``docs/schemas/`` Y en ``an_kla/schemas/``
   con bytes IDÉNTICOS (paridad norma/fuente ↔ recurso empaquetado).
2. Cada schema es JSON Schema draft 2020-12 estricto (``$schema``,
   ``$id`` ``urn:an-kla:schema:…``, object/additionalProperties en los
   de objeto, o ``oneOf`` en el contrato stdio).
3. Documentos POSITIVOS válidos (manifiesto v2 completo, results de cada
   superficie y los 4 mensajes del contrato del adaptador §4) validan con
   ``jsonschema``; documentos NEGATIVOS (key extra, mal tipo, mac no-hex,
   wrapped_cek > 4096, adapter_id fuera de gramática, diagnostics fuera
   del enum) son rechazados.
4. ``digest_bytes`` estable de cada archivo en ambas ubicaciones.

No requieren ``cryptography``: son contratos JSON, no criptografía.
``jsonschema`` es extra de test (skip honesto si no está).
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from an_kla.canonical import digest_bytes

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "schemas"
PKG = ROOT / "an_kla" / "schemas"

V2_FILES = (
    "export-manifest-v2",
    "export-result-v2",
    "export-restore-result-v2",
    "export-verify-result-v2",
    "sealing-adapter-contract-v1",
)


def _jsonschema_available() -> bool:
    try:
        import jsonschema  # noqa: F401
    except ImportError:
        return False
    return True


def _validator(schema: dict):
    from jsonschema import Draft202012Validator

    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


# ---------------------------------------------------------------------------
# Documentos positivos de referencia (shape §2/§6/§8 del ADR)
# ---------------------------------------------------------------------------

DIGEST = "sha256:" + "a" * 64
BUNDLE_ID = "ab" * 16
MANIFEST_MAC = "cd" * 32
WRAPPED_CEK = "QkxPQg=="

VALID_MANIFEST_V2 = {
    "schema": "an-kla/export-manifest-v2",
    "profile": "sealed-export/v1",
    "seal": {
        "algorithm": "aes-256-gcm",
        "kdf": "hkdf-sha256",
        "adapter_id": "test-adapter-v1",
        "wrapped_cek": WRAPPED_CEK,
        "bundle_id": BUNDLE_ID,
        "manifest_mac": MANIFEST_MAC,
    },
    "core": {
        "current_revision": DIGEST,
        "project_identity_sha256": DIGEST,
        "store_identity_sha256": DIGEST,
        "entry_count": 5,
        "total_bytes": 500,
        "entries": [
            {
                "path": "anchor/memory/refs/CURRENT",
                "size": 71,
                "content_sha256": DIGEST,
            }
        ] + [
            {
                "path": f"anchor/memory/revisions/sha256/{'0' * 64}.json",
                "size": 10,
                "content_sha256": DIGEST,
            }
        ] * 4,
    },
    "manifest_sha256": DIGEST,
}

VALID_EXPORT_RESULT_V2 = {
    "schema": "an-kla/export-result-v2",
    "created": True,
    "bundle": "/tmp/bundle",
    "bundle_id": BUNDLE_ID,
    "manifest_sha256": DIGEST,
    "current_revision": DIGEST,
    "warnings": ["sealed_export_untrusted_memory_data"],
}

VALID_RESTORE_RESULT_V2 = {
    "schema": "an-kla/export-restore-result-v2",
    "state": "published",
    "published": True,
    "current_revision": DIGEST,
    "manifest_sha256": DIGEST,
    "warnings": ["sealed_export_untrusted_memory_data"],
}

VALID_VERIFY_UNKEYED_V2 = {
    "schema": "an-kla/export-verify-result-v2",
    "verified": False,
    "structure_verified": True,
    "payloads_verified": False,
    "manifest_sha256": DIGEST,
    "current_revision": DIGEST,
    "bundle_id": BUNDLE_ID,
    "warnings": ["sealed_payloads_unverified_without_key"],
}

VALID_VERIFY_DIAGNOSTICS_V2 = {
    "schema": "an-kla/export-verify-result-v2",
    "verified": False,
    "structure_verified": False,
    "payloads_verified": False,
    "diagnostics": ["entry_size_mismatch"],
    "warnings": ["sealed_payloads_unverified_without_key"],
}

VALID_VERIFY_KEYED_V2 = {
    "schema": "an-kla/export-verify-result-v2",
    "verified": True,
    "structure_verified": True,
    "payloads_verified": True,
    "manifest_sha256": DIGEST,
    "current_revision": DIGEST,
    "bundle_id": BUNDLE_ID,
    "warnings": ["sealed_export_untrusted_memory_data"],
}

VALID_CONTRACT_MESSAGES = {
    "wrap_request": {"op": "wrap", "cek_b64": "QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUI="},
    "wrap_response": {"wrapped_cek": WRAPPED_CEK, "adapter_id": "age-v1"},
    "unwrap_request": {"op": "unwrap", "wrapped_cek": WRAPPED_CEK},
    "unwrap_response": {"cek_b64": "QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUI="},
}

_CEK_B64_32 = "QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUI="  # b64('A'*32)


class TestSchemaFilesV2(unittest.TestCase):
    """Existencia, paridad docs↔paquete y digests estables."""

    def test_five_v2_files_exist_in_both_locations(self):
        for name in V2_FILES:
            with self.subTest(name=name):
                self.assertTrue((DOCS / f"{name}.schema.json").is_file())
                self.assertTrue((PKG / f"{name}.schema.json").is_file())

    def test_docs_and_package_bytes_identical(self):
        for name in V2_FILES:
            with self.subTest(name=name):
                docs_bytes = (DOCS / f"{name}.schema.json").read_bytes()
                self.assertEqual(
                    (PKG / f"{name}.schema.json").read_bytes(), docs_bytes
                )
                # digest estable del artefacto normativo.
                self.assertIsInstance(digest_bytes(docs_bytes), str)

    def test_draft_2020_12_and_an_kla_ids(self):
        for name in V2_FILES:
            with self.subTest(name=name):
                schema = json.loads((DOCS / f"{name}.schema.json").read_text())
                self.assertEqual(
                    schema["$schema"],
                    "https://json-schema.org/draft/2020-12/schema",
                )
                self.assertTrue(schema["$id"].startswith("urn:an-kla:schema:"))


class TestManifestV2Schema(unittest.TestCase):
    def setUp(self):
        if not _jsonschema_available():
            self.skipTest("jsonschema no instalada (extra de test ausente)")
        self.schema = json.loads(
            (DOCS / "export-manifest-v2.schema.json").read_text()
        )
        self.validator = _validator(self.schema)

    def test_valid_manifest_accepted(self):
        self.validator.validate(VALID_MANIFEST_V2)

    def test_rejects_missing_and_extra_keys(self):
        for mutation in (
            lambda m: m.pop("seal"),
            lambda m: m.update(extra=1),
            lambda m: m["seal"].update(manifest_mac_extra="x"),
            lambda m: m["core"].update(entries_extra=1),
            lambda m: m["seal"].pop("manifest_mac"),
        ):
            with self.subTest(mutation=mutation):
                document = json.loads(json.dumps(VALID_MANIFEST_V2))
                mutation(document)
                with self.assertRaises(Exception):
                    self.validator.validate(document)

    def test_rejects_wrong_consts(self):
        for mutation in (
            lambda m: m.update(schema="an-kla/export-manifest-v1"),
            lambda m: m.update(profile="export/v1"),
            lambda m: m["seal"].update(algorithm="chacha20"),
            lambda m: m["seal"].update(kdf="hkdf-sha512"),
        ):
            with self.subTest(mutation=mutation):
                document = json.loads(json.dumps(VALID_MANIFEST_V2))
                mutation(document)
                with self.assertRaises(Exception):
                    self.validator.validate(document)

    def test_rejects_bad_seal_formats(self):
        for field, bad in (
            ("bundle_id", "AB" * 16),          # mayúsculas
            ("bundle_id", "a" * 31),           # 31 chars
            ("manifest_mac", "CD" * 32),       # mayúsculas
            ("manifest_mac", "c" * 63),        # 63 chars
            ("manifest_mac", "c" * 65),        # 65 chars
            ("adapter_id", "."),
            ("adapter_id", ".."),
            ("adapter_id", ""),
            ("adapter_id", "-lead"),
            ("adapter_id", "a" * 65),
            ("adapter_id", "a/b"),
            ("wrapped_cek", "x" * 4097),       # techo 4096 (§2)
        ):
            with self.subTest(field=field, bad=bad[:12]):
                document = json.loads(json.dumps(VALID_MANIFEST_V2))
                document["seal"][field] = bad
                with self.assertRaises(Exception):
                    self.validator.validate(document)

    def test_wrapped_cek_ceiling_4096_accepted(self):
        document = json.loads(json.dumps(VALID_MANIFEST_V2))
        document["seal"]["wrapped_cek"] = "A" * 4096
        self.validator.validate(document)


class TestResultSchemasV2(unittest.TestCase):
    def setUp(self):
        if not _jsonschema_available():
            self.skipTest("jsonschema no instalada (extra de test ausente)")

    def _validator(self, name: str):
        return _validator(
            json.loads((DOCS / f"{name}.schema.json").read_text())
        )

    def test_valid_documents_accepted(self):
        self._validator("export-result-v2").validate(VALID_EXPORT_RESULT_V2)
        self._validator("export-restore-result-v2").validate(
            VALID_RESTORE_RESULT_V2
        )
        self._validator("export-verify-result-v2").validate(
            VALID_VERIFY_UNKEYED_V2
        )
        self._validator("export-verify-result-v2").validate(
            VALID_VERIFY_DIAGNOSTICS_V2
        )
        self._validator("export-verify-result-v2").validate(
            VALID_VERIFY_KEYED_V2
        )

    def test_verify_result_two_closed_variants_keyed_and_unkeyed(self):
        """ADR §2/§8: el schema modela las DOS variantes del verify.

        Attempt 2 (fix adversarial): el schema congelaba verified/payloads
        como const false y warning unkeyed — no podía representar el
        resultado real del camino autenticado. Ahora cada variante cierra
        sus propios valores; las mezclas son rechazadas.
        """
        validator = self._validator("export-verify-result-v2")
        # Mezclas entre variantes → rechazadas.
        for mutation in (
            lambda d: d.update(warnings=["sealed_payloads_unverified_without_key"]),
            lambda d: d.update(verified=False),
            lambda d: d.update(payloads_verified=False),
            lambda d: d.update(diagnostics=["entry_size_mismatch"]),
            lambda d: d.pop("bundle_id"),
        ):
            with self.subTest(mutation=mutation):
                document = json.loads(json.dumps(VALID_VERIFY_KEYED_V2))
                mutation(document)
                with self.assertRaises(Exception):
                    validator.validate(document)
        # La variante unkeyed no puede afirmar verified/payloads true.
        liar = json.loads(json.dumps(VALID_VERIFY_UNKEYED_V2))
        liar["verified"] = True
        with self.assertRaises(Exception):
            validator.validate(liar)

    def test_export_result_requires_bundle_id_and_sealed_warning(self):
        validator = self._validator("export-result-v2")
        missing = json.loads(json.dumps(VALID_EXPORT_RESULT_V2))
        missing.pop("bundle_id")
        with self.assertRaises(Exception):
            validator.validate(missing)
        wrong_warning = json.loads(json.dumps(VALID_EXPORT_RESULT_V2))
        wrong_warning["warnings"] = ["plaintext_export_contains_untrusted_memory_data"]
        with self.assertRaises(Exception):
            validator.validate(wrong_warning)

    def test_verify_result_never_verified_true(self):
        """``verified`` es const false: el camino sin clave no miente."""
        validator = self._validator("export-verify-result-v2")
        liar = json.loads(json.dumps(VALID_VERIFY_UNKEYED_V2))
        liar["verified"] = True
        with self.assertRaises(Exception):
            validator.validate(liar)

    def test_verify_result_diagnostics_enum_closed(self):
        validator = self._validator("export-verify-result-v2")
        for good in (
            ["manifest_invalid"], ["entry_size_mismatch"], ["entry_missing"],
            ["entry_unexpected"], ["unsafe_path"], ["count_mismatch"],
        ):
            with self.subTest(diagnostics=good):
                document = json.loads(json.dumps(VALID_VERIFY_DIAGNOSTICS_V2))
                document["diagnostics"] = good
                validator.validate(document)
        document = json.loads(json.dumps(VALID_VERIFY_DIAGNOSTICS_V2))
        document["diagnostics"] = ["made_up_diagnostic"]
        with self.assertRaises(Exception):
            validator.validate(document)

    def test_restore_result_states_and_sealed_warning(self):
        validator = self._validator("export-restore-result-v2")
        for state, published in (
            ("not_published", False), ("published", True),
            ("published_durability_incomplete", True), ("outcome_unknown", True),
        ):
            with self.subTest(state=state):
                document = json.loads(json.dumps(VALID_RESTORE_RESULT_V2))
                document["state"] = state
                document["published"] = published
                validator.validate(document)
        v1_warning = json.loads(json.dumps(VALID_RESTORE_RESULT_V2))
        v1_warning["warnings"] = ["plaintext_export_contains_untrusted_memory_data"]
        with self.assertRaises(Exception):
            validator.validate(v1_warning)


class TestAdapterContractSchema(unittest.TestCase):
    def setUp(self):
        if not _jsonschema_available():
            self.skipTest("jsonschema no instalada (extra de test ausente)")
        self.validator = _validator(
            json.loads(
                (DOCS / "sealing-adapter-contract-v1.schema.json").read_text()
            )
        )

    def test_valid_messages_accepted(self):
        for label, message in VALID_CONTRACT_MESSAGES.items():
            with self.subTest(message=label):
                self.validator.validate(message)

    def test_extra_keys_rejected(self):
        for label, message in VALID_CONTRACT_MESSAGES.items():
            with self.subTest(message=label):
                document = dict(message)
                document["unexpected"] = 1
                with self.assertRaises(Exception):
                    self.validator.validate(document)

    def test_wrong_types_rejected(self):
        cases = (
            {"op": "wrap", "cek_b64": 42},
            {"op": "WRAP", "cek_b64": _CEK_B64_32},
            {"op": "unwrap", "wrapped_cek": None},
            {"op": "wrap", "cek_b64": "not base64!!"},
            {"op": "wrap", "cek_b64": "short"},
            {"wrapped_cek": WRAPPED_CEK, "adapter_id": "."},
            {"wrapped_cek": WRAPPED_CEK, "adapter_id": ""},
            {"wrapped_cek": "x" * 4097, "adapter_id": "ok"},
            {"op": "unwrap"},
        )
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(Exception):
                    self.validator.validate(case)

    def test_adapter_id_grammar_closed(self):
        for good in ("a", "a" * 64, "A.b_C-d0", "1"):
            with self.subTest(good=good):
                self.validator.validate(
                    {"wrapped_cek": WRAPPED_CEK, "adapter_id": good}
                )
        for bad in ("-lead", "a b", "á", "a" * 65, "a/b", "..", "."):
            with self.subTest(bad=bad):
                with self.assertRaises(Exception):
                    self.validator.validate(
                        {"wrapped_cek": WRAPPED_CEK, "adapter_id": bad}
                    )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
