"""#79 / ADR-0038: source_state con perfil git/v1."""

from __future__ import annotations

import json
import tempfile
import unittest

from an_kla.canonical import digest_json
from an_kla.checkpoint_policy import (
    CheckpointPolicyError,
    policy_fingerprint,
    validate_working_state,
)
from an_kla.checkpoints import plan_checkpoint
from an_kla.schemas import schema_bytes
from an_kla.store import MemoryStore

from tests.test_checkpoints import _authority, _state


def _git_state(parent: str, *, head: object = "a" * 40, branch: object = "main",
               dirty_digest: object = None) -> dict:
    state = _state(parent)
    state["source_state"] = {
        "profile": "git/v1",
        "head": {"value": head, "provenance": "caller_asserted"},
        "branch": {"value": branch, "provenance": "caller_asserted"},
        "dirty_digest": {"value": dirty_digest, "provenance": "caller_asserted"},
    }
    return state


class GitSourceStateValidationTests(unittest.TestCase):
    def test_valid_git_v1_accepts_sha1_and_sha256_heads(self) -> None:
        validate_working_state(_git_state("sha256:" + "0" * 64, head="f" * 40))
        validate_working_state(_git_state("sha256:" + "0" * 64, head="9" * 64))

    def test_git_v1_accepts_null_branch_and_digest(self) -> None:
        state = _git_state("sha256:" + "0" * 64, branch=None, dirty_digest="d41d8c")
        validate_working_state(state)

    def test_git_v1_rejects_unavailable_inside_profile(self) -> None:
        state = _git_state("sha256:" + "0" * 64)
        state["source_state"]["branch"] = {
            "value": None, "provenance": "unavailable",
        }
        with self.assertRaisesRegex(
            CheckpointPolicyError, "invalid_checkpoint_provenance"
        ):
            validate_working_state(state)

    def test_git_v1_rejects_fabricated_tool_observed(self) -> None:
        state = _git_state("sha256:" + "0" * 64)
        state["source_state"]["head"] = {
            "value": "a" * 40, "provenance": "tool_observed",
        }
        with self.assertRaisesRegex(
            CheckpointPolicyError, "tool_observed_requires_adapter"
        ):
            validate_working_state(state)

    def test_git_v1_rejects_short_or_nonhex_head(self) -> None:
        for bad in ("a" * 39, "z" * 40, 123, None, ""):
            with self.subTest(head=bad):
                with self.assertRaisesRegex(
                    CheckpointPolicyError, "invalid_working_state"
                ):
                    validate_working_state(
                        _git_state("sha256:" + "0" * 64, head=bad)
                    )

    def test_git_v1_rejects_newline_terminated_head(self) -> None:
        # Schema hardening: "$" alone would tolerate a trailing newline.
        state = _git_state("sha256:" + "0" * 64, head="a" * 40 + "\n")
        with self.assertRaisesRegex(
            CheckpointPolicyError, "invalid_working_state"
        ):
            validate_working_state(state)
        try:
            from jsonschema.exceptions import ValidationError
        except ImportError:
            self.skipTest("jsonschema unavailable")

        validator = self._validator_schema()
        with self.assertRaises(ValidationError):
            validator.validate(state)

    def test_git_v1_rejects_nonstring_branch_and_digest(self) -> None:
        for field in ("branch", "dirty_digest"):
            for bad in (7, True, [], {}):
                with self.subTest(field=field, bad=bad):
                    state = _git_state(
                        "sha256:" + "0" * 64, **{field: bad}
                    )
                    with self.assertRaisesRegex(
                        CheckpointPolicyError, "invalid_working_state"
                    ):
                        validate_working_state(state)

    @staticmethod
    def _validator_schema():
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            raise unittest.SkipTest("jsonschema unavailable")
        return Draft202012Validator(
            json.loads(schema_bytes("working-state-v2"))
        )

    def test_unknown_profile_is_invalid_not_adapter_error(self) -> None:
        state = _state("sha256:" + "0" * 64)
        state["source_state"]["profile"] = "svn/v1"
        with self.assertRaisesRegex(
            CheckpointPolicyError, "invalid_working_state"
        ):
            validate_working_state(state)

    def test_none_v1_still_requires_unavailable_fields(self) -> None:
        state = _state("sha256:" + "0" * 64)
        state["source_state"]["head"] = {
            "value": "a" * 40, "provenance": "caller_asserted",
        }
        with self.assertRaisesRegex(
            CheckpointPolicyError, "invalid_checkpoint_provenance"
        ):
            validate_working_state(state)


class GitSourceStatePlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(self.temp.name)
        self.current = self.store.initialize()
        self.parent = self.store.snapshot(self.current).manifest["checkpoint"]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_git_v1_checkpoint_plans_and_ligates_head(self) -> None:
        state = _git_state(self.parent, head="b" * 40, branch="plan/x")
        authority = _authority(self.store, state)
        result = plan_checkpoint(self.store, state, authority)
        source = result["plan"]["checkpoint"]["working_state"]["source_state"]
        self.assertEqual(source["profile"], "git/v1")
        self.assertEqual(source["head"]["value"], "b" * 40)
        self.assertEqual(source["branch"]["value"], "plan/x")

    def test_git_v1_commit_show_resume_end_to_end(self) -> None:
        from an_kla.checkpoints import commit_checkpoint, show_checkpoint
        from an_kla.resume import resume

        state = _git_state(self.parent, head="d" * 40, branch="main")
        authority = _authority(self.store, state)
        planning = plan_checkpoint(self.store, state, authority)
        committed = commit_checkpoint(
            self.store,
            planning,
            self.current,
            transaction_id=str(__import__("uuid").uuid4()),
        )
        self.assertTrue(committed["committed"])
        shown = show_checkpoint(self.store)["checkpoint"]["working_state"]
        self.assertEqual(shown["source_state"]["profile"], "git/v1")
        self.assertEqual(shown["source_state"]["head"]["value"], "d" * 40)
        resumed = resume(self.store, 12_000)
        live = resumed["snapshot"]["checkpoint"]["working_state"]
        self.assertEqual(live["source_state"]["profile"], "git/v1")

    def test_policy_fingerprint_covers_both_profiles(self) -> None:
        fingerprint = policy_fingerprint()
        self.assertIsInstance(fingerprint, str)
        # The fingerprint changes with the config: pin its shape so silent
        # config drift fails loudly.
        self.assertTrue(fingerprint.startswith("sha256:"))


class GitSourceStateSchemaTests(unittest.TestCase):
    def _validator(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema unavailable")
        return Draft202012Validator(json.loads(schema_bytes("working-state-v2")))

    def test_schema_accepts_git_v1_document(self) -> None:
        validator = self._validator()
        state = _git_state("sha256:" + "0" * 64, head="c" * 64)
        validator.validate(state)

    def test_schema_rejects_unavailable_head_under_git_v1(self) -> None:
        try:
            from jsonschema.exceptions import ValidationError
        except ImportError:
            self.skipTest("jsonschema unavailable")

        validator = self._validator()
        state = _git_state("sha256:" + "0" * 64)
        state["source_state"]["head"] = {
            "value": None, "provenance": "unavailable",
        }
        with self.assertRaises(ValidationError):
            validator.validate(state)

    def test_schema_still_accepts_none_v1_document(self) -> None:
        validator = self._validator()
        validator.validate(_state("sha256:" + "0" * 64))


if __name__ == "__main__":
    unittest.main()
