import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "docs" / "schemas"


def load_schema(name: str) -> dict:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


class F0ContractTests(unittest.TestCase):
    schema_names = (
        "write-proposal-v1.schema.json",
        "write-authority-v1.schema.json",
        "write-decision-v1.schema.json",
        "write-plan-v1.schema.json",
        "cost-certificate-v1.schema.json",
    )

    def test_all_schemas_are_local_strict_json_objects(self) -> None:
        for name in self.schema_names:
            with self.subTest(name=name):
                schema = load_schema(name)
                self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
                self.assertTrue(schema["$id"].startswith("urn:an-kla:schema:"))
                self.assertEqual(schema["type"], "object")
                self.assertFalse(schema["additionalProperties"])

    def test_write_proposal_separates_representation_from_lifecycle(self) -> None:
        schema = load_schema("write-proposal-v1.schema.json")
        representations = schema["properties"]["requested_representation"]["enum"]
        self.assertEqual(representations, ["full", "summary"])
        self.assertEqual(
            schema["properties"]["operation"]["enum"],
            ["add", "supersede", "refute", "decay"],
        )
        self.assertNotIn("decay", representations)
        self.assertNotIn("supersede", representations)
        self.assertNotIn("refute", representations)

    def test_write_authority_is_a_separate_scoped_object(self) -> None:
        proposal = load_schema("write-proposal-v1.schema.json")
        authority = load_schema("write-authority-v1.schema.json")
        self.assertNotIn("authority_class", proposal["properties"])
        self.assertIn("proposal_sha256", authority["required"])
        self.assertIn("scope", authority["required"])
        self.assertEqual(
            authority["properties"]["authority_class"]["enum"],
            [
                "tool_observed",
                "channel_confirmed",
                "model_derived",
                "derived_from_retrieval",
                "unresolved",
            ],
        )

    def test_write_decisions_do_not_include_lifecycle_transitions(self) -> None:
        schema = load_schema("write-decision-v1.schema.json")
        decisions = schema["properties"]["decision"]["enum"]
        self.assertEqual(decisions, ["skip", "write-full", "write-summary"])

    def test_write_plan_fingerprint_excludes_itself(self) -> None:
        schema = load_schema("write-plan-v1.schema.json")
        core = schema["properties"]["core"]
        self.assertIn("plan_fingerprint", schema["required"])
        self.assertNotIn("plan_fingerprint", core["properties"])
        self.assertIn("decision", core["required"])
        self.assertIn("planned_records_sha256", core["required"])
        planned = schema["properties"]["records"]["items"]
        self.assertIn("operation", planned["required"])
        self.assertIn("representation", planned["required"])

    def test_cost_contract_keeps_bytes_and_tokens_distinct(self) -> None:
        schema = load_schema("cost-certificate-v1.schema.json")
        self.assertEqual(schema["properties"]["cost_unit"]["enum"], ["bytes", "tokens"])
        self.assertEqual(
            schema["properties"]["cost_model_profile"]["enum"],
            ["utf8-bytes/v1", "tokenizer-callback/v1", "external-tokenizer/v1"],
        )
        token_condition = schema["allOf"][1]
        self.assertEqual(
            token_condition["if"]["properties"]["cost_unit"]["const"], "tokens"
        )
        self.assertIn("tokenizer", token_condition["then"]["required"])

    def test_write_policy_terminal_codes_are_frozen_in_adr(self) -> None:
        text = (ROOT / "docs" / "architecture" / "0007-write-policy-v1.md").read_text(
            encoding="utf-8"
        )
        for code in (
            "invalid_write_proposal",
            "write_plan_hash_mismatch",
            "write_plan_base_changed",
            "write_authority_scope_mismatch",
            "write_content_hash_mismatch",
            "write_lifecycle_as_representation",
            "summary_required_for_authority_ceiling",
            "tool_evidence_verified",
            "channel_confirmation_resolved",
            "representation_accepted",
        ):
            self.assertIn(f"`{code}`", text)
        self.assertIn("siguen pendientes", " ".join(text.split()))

    def test_cost_terminal_codes_and_host_boundary_are_frozen(self) -> None:
        text = (ROOT / "docs" / "architecture" / "0008-cost-model-v1.md").read_text(
            encoding="utf-8"
        )
        for code in (
            "cost_payload_hash_mismatch",
            "tokenizer_fingerprint_mismatch",
            "tokenizer_timeout",
            "cost_not_converged",
            "cost_fallback_not_authorized",
            "host_framing_unmeasured",
        ):
            self.assertIn(f"`{code}`", text)
        self.assertIn("no equivale al", text)

    def test_foundations_report_current_byte_and_token_guarantees(self) -> None:
        text = (ROOT / "docs" / "mathematical-foundations.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "| Presupuesto global del contexto ensamblado en bytes UTF-8 | Implementado",
            text,
        )
        self.assertIn(
            "| Presupuesto global exacto en tokens | Contrato `cost-model/v1`; implementación pendiente |",
            text,
        )


if __name__ == "__main__":
    unittest.main()
