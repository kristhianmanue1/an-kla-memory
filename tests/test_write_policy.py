from __future__ import annotations

import ast
from copy import deepcopy
import math
from pathlib import Path
import unittest

from an_kla.canonical import canonical_json, digest_json
from an_kla.write_policy import (
    WritePolicyError,
    build_write_plan,
    evaluate_write,
    policy_configuration,
    policy_fingerprint,
    validate_write_authority,
    validate_write_decision,
    validate_write_plan,
    validate_write_proposal,
    verify_write_plan,
)


DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64


def proposal(
    *,
    representation: str = "full",
    operation: str = "add",
    derived: bool = False,
    record: dict | None = None,
) -> dict:
    return {
        "schema": "an-kla/write-proposal-v1",
        "base_revision": DIGEST_A,
        "stream": "facts",
        "operation": operation,
        "requested_representation": representation,
        "record": record or {"id": "f-new", "payload": {"text": "decisión durable"}},
        "lineage": {"derived_from_retrieval": derived, "refs": []},
    }


def authority(
    candidate: dict,
    *,
    authority_class: str = "channel_confirmed",
    evidence: list | None = None,
    operations: list | None = None,
    representations: list | None = None,
) -> dict:
    issuer_kind = {
        "tool_observed": "tool",
        "channel_confirmed": "channel",
        "model_derived": "model",
        "derived_from_retrieval": "model",
        "unresolved": "unknown",
    }[authority_class]
    return {
        "schema": "an-kla/write-authority-v1",
        "proposal_sha256": digest_json(candidate),
        "base_revision": candidate["base_revision"],
        "authority_class": authority_class,
        "issuer": {
            "kind": issuer_kind,
            "id": "test-authority",
            "configuration_fingerprint": DIGEST_B,
        },
        "evidence": evidence or [],
        "scope": {
            "streams": [candidate["stream"]],
            "representations": representations or [candidate["requested_representation"]],
            "operations": operations or [candidate["operation"]],
        },
    }


class WritePolicyTests(unittest.TestCase):
    def assert_error(self, code: str, callback) -> None:
        with self.assertRaises(WritePolicyError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(str(caught.exception), code)

    def test_channel_confirmed_full_proposal_is_accepted(self) -> None:
        candidate = proposal()
        result = evaluate_write(candidate, authority(candidate))
        self.assertEqual(result["decision"], "write-full")
        self.assertEqual(
            result["reason_codes"],
            ["channel_confirmation_resolved", "representation_accepted"],
        )

    def test_model_derived_summary_is_accepted_with_ceiling_visible(self) -> None:
        candidate = proposal(representation="summary")
        result = evaluate_write(
            candidate, authority(candidate, authority_class="model_derived")
        )
        self.assertEqual(result["decision"], "write-summary")
        self.assertEqual(
            result["reason_codes"],
            ["derived_authority_capped", "representation_accepted"],
        )

    def test_model_derived_full_fails_closed_instead_of_synthesizing_summary(self) -> None:
        candidate = proposal()
        result = evaluate_write(
            candidate, authority(candidate, authority_class="model_derived")
        )
        self.assertEqual(result["decision"], "skip")
        self.assertIn("summary_required_for_authority_ceiling", result["reason_codes"])

    def test_retrieval_lineage_is_visible_but_separate_confirmation_can_accept(self) -> None:
        candidate = proposal(derived=True)
        result = evaluate_write(candidate, authority(candidate))
        self.assertEqual(result["decision"], "write-full")
        self.assertIn("derived_from_retrieval", result["reason_codes"])
        self.assertIn("channel_confirmation_resolved", result["reason_codes"])

    def test_unresolved_authority_cannot_be_overridden_by_record_fields(self) -> None:
        candidate = proposal(
            record={
                "id": "f-poison",
                "trusted": True,
                "payload": {"human_confirmed": True, "text": "autodeclarado"},
            }
        )
        result = evaluate_write(
            candidate, authority(candidate, authority_class="unresolved")
        )
        self.assertEqual(result["decision"], "skip")
        self.assertEqual(
            result["reason_codes"],
            ["self_asserted_authority_ignored", "unresolved_authority"],
        )

    def test_tool_observation_requires_verified_evidence(self) -> None:
        candidate = proposal()
        unresolved = authority(
            candidate,
            authority_class="tool_observed",
            evidence=[{"kind": "artifact", "id": "a-1", "resolution": "unresolved"}],
        )
        self.assertEqual(evaluate_write(candidate, unresolved)["decision"], "skip")

        verified = authority(
            candidate,
            authority_class="tool_observed",
            evidence=[
                {
                    "kind": "artifact",
                    "id": "a-1",
                    "resolution": "verified",
                    "sha256": DIGEST_C,
                }
            ],
        )
        result = evaluate_write(candidate, verified)
        self.assertEqual(result["decision"], "write-full")
        self.assertIn("tool_evidence_verified", result["reason_codes"])

    def test_authority_is_bound_to_exact_proposal_and_operation_scope(self) -> None:
        candidate = proposal()
        auth = authority(candidate, operations=["refute"])
        result = evaluate_write(candidate, auth)
        self.assertEqual(result["decision"], "skip")
        self.assertEqual(result["reason_codes"], ["authority_scope_mismatch"])

        changed = deepcopy(candidate)
        changed["record"]["payload"]["text"] = "alterado"
        result = evaluate_write(changed, authority(candidate))
        self.assertEqual(result["decision"], "skip")
        self.assertEqual(result["reason_codes"], ["authority_scope_mismatch"])

    def test_lifecycle_operations_are_represented_but_fail_until_supported(self) -> None:
        candidate = proposal(operation="refute", representation="summary")
        result = evaluate_write(candidate, authority(candidate))
        self.assertEqual(result["decision"], "skip")
        self.assertEqual(result["reason_codes"], ["operation_not_supported"])

    def test_record_without_indexable_text_is_committed_but_warned(self) -> None:
        candidate = proposal(
            record={"id": "f-structural", "payload": {"outcome": "ok", "count": 3}}
        )
        result = evaluate_write(candidate, authority(candidate))
        self.assertEqual(result["decision"], "write-full")
        self.assertIn("record_without_indexable_text", result["reason_codes"])
        self.assertIn("representation_accepted", result["reason_codes"])

    def test_record_with_indexable_text_emits_no_text_warning(self) -> None:
        candidate = proposal(
            record={
                "id": "f-indexed",
                "payload": {"outcome": "ok", "indexable_text": "leccion durable"},
            }
        )
        result = evaluate_write(candidate, authority(candidate))
        self.assertNotIn("record_without_indexable_text", result["reason_codes"])

    def test_skip_decisions_do_not_carry_the_no_text_warning(self) -> None:
        candidate = proposal(
            record={"id": "f-structural", "payload": {"outcome": "ok"}}
        )
        result = evaluate_write(candidate, authority(candidate, authority_class="unresolved"))
        self.assertEqual(result["decision"], "skip")
        self.assertNotIn("record_without_indexable_text", result["reason_codes"])

    def test_no_text_warning_flows_through_build_write_plan(self) -> None:
        candidate = proposal(
            record={"id": "f-structural", "payload": {"outcome": "ok"}}
        )
        auth = authority(candidate)
        plan = build_write_plan(candidate, auth)
        decision = evaluate_write(candidate, auth)
        self.assertIn("record_without_indexable_text", decision["reason_codes"])
        self.assertIn(
            "record_without_indexable_text",
            plan["records"][1]["record"]["payload"]["reason_codes"],
        )
        verify_write_plan(plan, candidate, auth, decision)

    def test_plan_binds_decision_operation_representation_and_record(self) -> None:
        candidate = proposal(representation="summary")
        auth = authority(candidate)
        plan = build_write_plan(candidate, auth)
        self.assertEqual(plan["core"]["decision"], "write-summary")
        self.assertEqual(plan["records"][0]["operation"], "add")
        self.assertEqual(plan["records"][0]["representation"], "summary")
        self.assertEqual(plan["records"][1]["stream"], "events")
        self.assertEqual(
            plan["records"][1]["record"]["type"], "write_policy_decision"
        )
        self.assertNotIn("issuer", plan["records"][1]["record"]["payload"])
        self.assertEqual(plan["core"]["planned_records_sha256"], digest_json(plan["records"]))
        self.assertEqual(plan["plan_fingerprint"], digest_json(plan["core"]))
        decision = evaluate_write(candidate, auth)
        validate_write_decision(decision)
        validate_write_plan(plan)
        verify_write_plan(plan, candidate, auth, decision)

    def test_skipped_plan_contains_no_records(self) -> None:
        candidate = proposal()
        auth = authority(candidate, authority_class="unresolved")
        plan = build_write_plan(candidate, auth)
        self.assertEqual(plan["core"]["decision"], "skip")
        self.assertEqual(plan["records"], [])

    def test_tampered_plan_is_rejected(self) -> None:
        candidate = proposal()
        auth = authority(candidate)
        plan = build_write_plan(candidate, auth)
        plan["records"][0]["record"]["payload"]["text"] = "tampered"
        self.assert_error(
            "write_content_hash_mismatch", lambda: verify_write_plan(plan, candidate, auth)
        )

    def test_decision_is_revalidated_against_policy_and_content(self) -> None:
        candidate = proposal()
        auth = authority(candidate)
        decision = evaluate_write(candidate, auth)
        plan = build_write_plan(candidate, auth, decision)

        wrong_policy = deepcopy(decision)
        wrong_policy["policy_fingerprint"] = DIGEST_C
        self.assert_error(
            "write_policy_fingerprint_mismatch",
            lambda: verify_write_plan(plan, candidate, auth, wrong_policy),
        )

        wrong_content = deepcopy(decision)
        wrong_content["proposal_sha256"] = DIGEST_C
        self.assert_error(
            "write_content_hash_mismatch",
            lambda: verify_write_plan(plan, candidate, auth, wrong_content),
        )

        wrong_reasons = deepcopy(decision)
        wrong_reasons["reason_codes"] = ["representation_accepted"]
        self.assert_error(
            "invalid_write_decision",
            lambda: verify_write_plan(plan, candidate, auth, wrong_reasons),
        )

    def test_plan_core_fingerprint_is_checked_independently(self) -> None:
        candidate = proposal()
        auth = authority(candidate)
        plan = build_write_plan(candidate, auth)
        plan["plan_fingerprint"] = DIGEST_C
        self.assert_error(
            "write_plan_hash_mismatch", lambda: verify_write_plan(plan, candidate, auth)
        )

    def test_inputs_are_not_mutated_and_key_order_does_not_change_output(self) -> None:
        candidate = proposal(record={"payload": {"text": "x", "z": 2}, "id": "f-order"})
        candidate_reordered = proposal(
            record={"id": "f-order", "payload": {"z": 2, "text": "x"}}
        )
        auth = authority(candidate)
        auth_reordered = authority(candidate_reordered)
        before_candidate = deepcopy(candidate)
        before_authority = deepcopy(auth)
        first = build_write_plan(candidate, auth)
        second = build_write_plan(candidate_reordered, auth_reordered)
        self.assertEqual(canonical_json(first), canonical_json(second))
        self.assertEqual(candidate, before_candidate)
        self.assertEqual(auth, before_authority)

    def test_invalid_json_and_envelopes_fail_with_stable_codes(self) -> None:
        candidate = proposal()
        candidate["record"]["payload"]["bad"] = math.nan
        self.assert_error(
            "invalid_write_proposal", lambda: validate_write_proposal(candidate)
        )
        valid = proposal()
        invalid_authority = authority(valid)
        invalid_authority["extra"] = True
        self.assert_error(
            "invalid_write_authority",
            lambda: validate_write_authority(invalid_authority),
        )
        spoofed = authority(valid)
        spoofed["issuer"]["kind"] = "model"
        self.assert_error(
            "invalid_write_authority", lambda: validate_write_authority(spoofed)
        )

    def test_policy_configuration_is_detached_and_fingerprint_is_stable(self) -> None:
        first = policy_configuration()
        first["supported_operations"].append("refute")
        second = policy_configuration()
        self.assertEqual(second["supported_operations"], ["add", "supersede"])
        self.assertEqual(policy_fingerprint(), digest_json(second))

    def test_policy_fingerprint_binds_reason_and_terminal_code_catalogs(self) -> None:
        configuration = policy_configuration()
        self.assertEqual(
            configuration["reason_codes"],
            [
                "authority_scope_mismatch",
                "channel_confirmation_resolved",
                "derived_authority_capped",
                "derived_from_retrieval",
                "operation_not_supported",
                "record_without_indexable_text",
                "representation_accepted",
                "self_asserted_authority_ignored",
                "summary_required_for_authority_ceiling",
                "supersede_requires_non_derived_authority",
                "tool_evidence_verified",
                "unresolved_authority",
            ],
        )
        self.assertEqual(
            configuration["terminal_error_codes"],
            [
                "invalid_supersede_target",
                "invalid_write_authority",
                "invalid_write_decision",
                "invalid_write_plan",
                "invalid_write_proposal",
                "write_content_hash_mismatch",
                "write_plan_base_changed",
                "write_plan_hash_mismatch",
                "write_policy_fingerprint_mismatch",
            ],
        )

    def test_module_has_no_io_or_nondeterministic_imports(self) -> None:
        path = Path(__file__).resolve().parents[1] / "an_kla" / "write_policy.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertTrue(
            imported.isdisjoint(
                {"os", "pathlib", "random", "secrets", "socket", "subprocess", "time", "urllib"}
            )
        )


class ErrorDetailTests(unittest.TestCase):
    """``WritePolicyError.detail`` names the offending field (issue #18).

    ``code`` and ``str(error)`` stay equal to the stable code; ``detail`` is the
    informative, evolutive part.
    """

    def _assert_detail(self, code: str, expected_detail: str, callback) -> None:
        with self.assertRaises(WritePolicyError) as caught:
            callback()
        err = caught.exception
        self.assertEqual(err.code, code)
        self.assertEqual(str(err), code)
        self.assertEqual(err.detail, expected_detail)

    def test_proposal_stream_detail(self) -> None:
        bad = proposal()
        bad["stream"] = "not-a-stream"
        self._assert_detail("invalid_write_proposal", "stream", lambda: validate_write_proposal(bad))

    def test_proposal_base_revision_detail(self) -> None:
        bad = proposal()
        bad["base_revision"] = "sha256:short"
        self._assert_detail(
            "invalid_write_proposal", "base_revision:not_digest", lambda: validate_write_proposal(bad)
        )

    def test_proposal_record_id_detail(self) -> None:
        bad = proposal()
        bad["record"] = {"id": ""}
        self._assert_detail("invalid_write_proposal", "record.id", lambda: validate_write_proposal(bad))

    def test_proposal_keys_detail(self) -> None:
        bad = proposal()
        bad["extra_key"] = "noise"
        self._assert_detail(
            "invalid_write_proposal", "proposal:keys", lambda: validate_write_proposal(bad)
        )

    def test_proposal_lineage_detail(self) -> None:
        bad = proposal()
        bad["lineage"]["derived_from_retrieval"] = "not-bool"
        self._assert_detail(
            "invalid_write_proposal",
            "lineage.derived_from_retrieval:not_bool",
            lambda: validate_write_proposal(bad),
        )

    def test_authority_class_detail(self) -> None:
        bad = authority(proposal())
        bad["authority_class"] = "privileged"
        self._assert_detail(
            "invalid_write_authority", "authority_class", lambda: validate_write_authority(bad)
        )

    def test_authority_issuer_mismatch_detail(self) -> None:
        bad = authority(proposal(), authority_class="model_derived")
        bad["issuer"]["kind"] = "channel"
        self._assert_detail(
            "invalid_write_authority",
            "issuer.kind:authority_class_mismatch",
            lambda: validate_write_authority(bad),
        )

    def test_authority_scope_streams_detail(self) -> None:
        bad = authority(proposal())
        bad["scope"]["streams"] = ["not-a-stream"]
        self._assert_detail(
            "invalid_write_authority", "scope.streams", lambda: validate_write_authority(bad)
        )

    def test_error_without_detail_is_backward_compatible(self) -> None:
        # Codes that already name a single cause are raised without detail; the
        # constructor keeps ``.detail is None`` and ``str == code`` for them.
        err = WritePolicyError("write_policy_fingerprint_mismatch")
        self.assertEqual(err.code, "write_policy_fingerprint_mismatch")
        self.assertIsNone(err.detail)
        self.assertEqual(str(err), "write_policy_fingerprint_mismatch")


class SupersedePolicyTests(unittest.TestCase):
    """ADR-0019: operation=supersede policy core (PR-A, pure policy layer)."""

    def _supersede_proposal(self, target_id: str = "f-old") -> dict:
        candidate = proposal(operation="supersede", representation="summary")
        candidate["supersedes"] = target_id
        return candidate

    def test_model_derived_supersede_summary_is_accepted(self) -> None:
        candidate = self._supersede_proposal()
        result = evaluate_write(
            candidate, authority(candidate, authority_class="model_derived")
        )
        self.assertEqual(result["decision"], "write-summary")

    def test_channel_confirmed_supersede_full_is_accepted(self) -> None:
        candidate = proposal(operation="supersede", representation="full")
        candidate["supersedes"] = "f-old"
        result = evaluate_write(candidate, authority(candidate))
        self.assertEqual(result["decision"], "write-full")

    def test_derived_from_retrieval_cannot_supersede(self) -> None:
        # ADR-0019 decision 4: derived_from_retrieval must not silence a current
        # fact (memory-recovered data is untrusted).
        candidate = self._supersede_proposal()
        result = evaluate_write(
            candidate, authority(candidate, authority_class="derived_from_retrieval")
        )
        self.assertEqual(result["decision"], "skip")
        self.assertIn("supersede_requires_non_derived_authority", result["reason_codes"])

    def test_supersede_requires_supersedes_field(self) -> None:
        bad = proposal(operation="supersede", representation="summary")  # no supersedes
        with self.assertRaises(WritePolicyError) as caught:
            validate_write_proposal(bad)
        self.assertEqual(caught.exception.code, "invalid_write_proposal")
        self.assertEqual(caught.exception.detail, "supersedes:missing_for_supersede")

    def test_supersedes_forbidden_without_supersede_operation(self) -> None:
        bad = proposal()
        bad["supersedes"] = "f-old"
        with self.assertRaises(WritePolicyError) as caught:
            validate_write_proposal(bad)
        self.assertEqual(caught.exception.detail, "supersedes:present_without_supersede")

    def test_supersedes_self_reference_forbidden(self) -> None:
        bad = proposal(operation="supersede", representation="summary")
        bad["supersedes"] = bad["record"]["id"]
        with self.assertRaises(WritePolicyError) as caught:
            validate_write_proposal(bad)
        self.assertEqual(caught.exception.detail, "supersedes:self_reference_forbidden")

    def test_supersede_with_non_dict_record_raises_stable_error(self) -> None:
        # Regression (adversarial): record not a dict must surface as the stable
        # invalid_write_proposal code (detail record:not_object), never an
        # AttributeError leaking from the self-reference check.
        bad = proposal(operation="supersede", representation="summary")
        bad["record"] = None
        bad["supersedes"] = "f-old"
        with self.assertRaises(WritePolicyError) as caught:
            validate_write_proposal(bad)
        self.assertEqual(caught.exception.code, "invalid_write_proposal")
        self.assertEqual(caught.exception.detail, "record:not_object")

    def test_validate_write_plan_rejects_supersede_self_reference(self) -> None:
        candidate = proposal(operation="supersede", representation="summary")
        candidate["supersedes"] = "f-old"
        plan = build_write_plan(
            candidate, authority(candidate, authority_class="model_derived")
        )
        plan["records"][0]["supersedes"] = plan["records"][0]["record"]["id"]
        with self.assertRaises(WritePolicyError) as caught:
            validate_write_plan(plan)
        self.assertEqual(caught.exception.code, "invalid_write_plan")
        self.assertEqual(
            caught.exception.detail, "records[]:supersedes:self_reference_forbidden"
        )

    def test_build_write_plan_carries_supersedes_to_planned_item(self) -> None:
        candidate = self._supersede_proposal()
        plan = build_write_plan(candidate, authority(candidate, authority_class="model_derived"))
        target_items = [r for r in plan["records"] if r["stream"] == candidate["stream"]]
        self.assertEqual(len(target_items), 1)
        self.assertEqual(target_items[0]["operation"], "supersede")
        self.assertEqual(target_items[0]["supersedes"], "f-old")
        # The audit event stays an `add` and carries no supersedes.
        events = [r for r in plan["records"] if r["stream"] == "events"]
        self.assertEqual(len(events), 1)
        self.assertNotIn("supersedes", events[0])


if __name__ == "__main__":
    unittest.main()
