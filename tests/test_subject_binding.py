from __future__ import annotations

import unittest

from an_kla.subject_binding import check_subject_ref_binding
from an_kla.subject_ref import derive_namespace
from an_kla.write_policy import WritePolicyError


PROJECT_BYTES = b'{"project_uuid":"11111111-2222-3333-4444-555555555555"}'
NAMESPACE = derive_namespace(PROJECT_BYTES)
PREFIX = "an-kla:subject:v1:"


def record_with(subject_ref: str | None) -> dict:
    record = {"id": "f-new", "payload": {"text": "contextual"}}
    if subject_ref is not None:
        record["subject_ref"] = subject_ref
    return record


def plan_with_records(*records: dict) -> dict:
    return {
        "schema": "an-kla/write-plan-v1",
        "records": [
            {
                "stream": "facts",
                "operation": "add",
                "representation": "full",
                "record": record,
            }
            for record in records
        ],
    }


def binding() -> dict:
    return {"project_bytes": PROJECT_BYTES}


def subject_ref(namespace: str, kind: str = "decision", subject_id: str = "adr-0033") -> str:
    return f"{PREFIX}{kind}:{namespace}:{subject_id}"


class CheckSubjectRefBindingTests(unittest.TestCase):
    def test_check_binding_accepts_matching_namespace(self) -> None:
        plan = plan_with_records(record_with(subject_ref(NAMESPACE)))
        check_subject_ref_binding(plan, binding())  # no raise

    def test_check_binding_accepts_record_without_subject_ref(self) -> None:
        plan = plan_with_records(record_with(None))
        check_subject_ref_binding(plan, binding())  # no raise

    def test_check_binding_rejects_mismatch(self) -> None:
        other = "p-" + "f" * 32
        plan = plan_with_records(record_with(subject_ref(other)))
        with self.assertRaises(WritePolicyError) as caught:
            check_subject_ref_binding(plan, binding())
        self.assertEqual(caught.exception.code, "subject_ref_namespace_mismatch")
        self.assertEqual(str(caught.exception), "subject_ref_namespace_mismatch")

    def test_check_binding_skips_records_without_subject_ref(self) -> None:
        # Mixed plan: a legacy record (no subject_ref) followed by a matching
        # one. No raise => legacy records are a no-op.
        plan = plan_with_records(
            record_with(None),
            record_with(subject_ref(NAMESPACE)),
        )
        check_subject_ref_binding(plan, binding())

    def test_check_binding_malformed_raises_write_policy_error_stable(self) -> None:
        # Regression (plan §6 Fase A): malformed subject_ref reaching the
        # binding guard must surface the stable WritePolicyError contract, never
        # a raw SubjectRefError or IndexError. The key is present in every case.
        for value in ("", "not-a-ref", "an-kla:subject:v1:only", None, 7):
            record = {"id": "f-new", "payload": {"text": "x"}, "subject_ref": value}
            plan = plan_with_records(record)
            with self.subTest(value=value):
                with self.assertRaises(WritePolicyError) as caught:
                    check_subject_ref_binding(plan, binding())
                self.assertEqual(caught.exception.code, "invalid_write_proposal")
                self.assertEqual(caught.exception.detail, "record.subject_ref")

    def test_check_binding_mismatch_short_circuits_before_subsequent_records(self) -> None:
        # First record mismatches; the guard raises without inspecting the rest.
        other = "p-" + "f" * 32
        plan = plan_with_records(
            record_with(subject_ref(other)),
            record_with(subject_ref(NAMESPACE)),
        )
        with self.assertRaises(WritePolicyError) as caught:
            check_subject_ref_binding(plan, binding())
        self.assertEqual(caught.exception.code, "subject_ref_namespace_mismatch")

    def test_check_binding_checks_each_record_even_when_first_matches(self) -> None:
        # Phase B M-1: a matching first record MUST NOT short-circuit. A later
        # record with the wrong namespace still triggers mismatch. This freezes
        # the "each record" invariant — binding is per-record, not first-only.
        other = "p-" + "f" * 32
        plan = plan_with_records(
            record_with(subject_ref(NAMESPACE)),
            record_with(subject_ref(other)),
        )
        with self.assertRaises(WritePolicyError) as caught:
            check_subject_ref_binding(plan, binding())
        self.assertEqual(caught.exception.code, "subject_ref_namespace_mismatch")
        self.assertEqual(str(caught.exception), "subject_ref_namespace_mismatch")

    def test_legacy_plan_without_subject_ref_and_empty_binding_is_noop(self) -> None:
        # Contraexample (auditoría integrador): a plan whose records carry no
        # subject_ref must be a no-op even when binding lacks "project_bytes".
        # Legacy records never trigger namespace derivation.
        legacy_plan = {
            "schema": "an-kla/write-plan-v1",
            "records": [
                {
                    "stream": "facts",
                    "operation": "add",
                    "representation": "full",
                    "record": {"id": "legacy"},
                }
            ],
        }
        check_subject_ref_binding(legacy_plan, {})  # no raise, no KeyError

    def test_malformed_subject_ref_with_empty_binding_keeps_stable_error(self) -> None:
        # Contraexample (auditoría integrador): a malformed subject_ref must map
        # to the stable WritePolicyError contract BEFORE namespace derivation,
        # so an empty binding never surfaces a raw KeyError. The parse-then-
        # derive ordering is the invariant.
        for value in ("", "not-a-ref", "an-kla:subject:v1:only", None, 7):
            record = {"id": "f-new", "payload": {"text": "x"}, "subject_ref": value}
            plan = plan_with_records(record)
            with self.subTest(value=value):
                with self.assertRaises(WritePolicyError) as caught:
                    check_subject_ref_binding(plan, {})
                self.assertEqual(caught.exception.code, "invalid_write_proposal")
                self.assertEqual(caught.exception.detail, "record.subject_ref")


if __name__ == "__main__":
    unittest.main()
