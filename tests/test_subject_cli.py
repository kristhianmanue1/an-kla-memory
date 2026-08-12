from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from an_kla.canonical import canonical_json
from an_kla.identity import IdentityError, identity_status, read_binding
from an_kla.store import IntegrityError, MemoryStore, StoreError
from an_kla.subject_ref import derive_namespace


ROOT = Path(__file__).resolve().parents[1]


NON_COMPLETE_STATES = (
    "absent",
    "legacy_unadopted",
    "intent_only",
    "store_only",
    "project_only",
    "partial_consistent",
    "identities_ready_root_pending",
    "conflict",
)

# Controlled IdentityError catalogue from read_binding after a complete status
# (ADR-0033 §10 / plan §8): identity migrated between the two read-only calls.
BINDING_DRIFT_CODES = (
    "project_identity_missing",
    "project_identity_invalid",
    "store_identity_missing",
    "store_identity_invalid",
    "project_identity_mismatch",
)


def _invoke_cli(argv: list[str]) -> tuple[int, bytes, str]:
    """Invoke the CLI entrypoint in-process; return (code, stdout_bytes, stderr_text)."""

    from an_kla.__main__ import main

    stdout_buf = io.BytesIO()
    stderr_buf = io.StringIO()

    class _Stdout:
        buffer = stdout_buf

        def write(self, *_args: object, **_kwargs: object) -> None:
            pass

        def flush(self) -> None:
            pass

    class _Stderr:
        def write(self, text: str) -> int:
            return stderr_buf.write(text)

        def flush(self) -> None:
            pass

    old_out, old_err, old_argv = sys.stdout, sys.stderr, sys.argv
    sys.stdout, sys.stderr, sys.argv = _Stdout(), _Stderr(), argv
    try:
        try:
            main()
        except SystemExit as exc:
            if isinstance(exc.code, int):
                code = exc.code
            else:
                stderr_buf.write(str(exc.code))
                code = 1
        else:
            code = 0
    finally:
        sys.stdout, sys.stderr, sys.argv = old_out, old_err, old_argv
    return code, stdout_buf.getvalue(), stderr_buf.getvalue()


def _subject_argv(project_root: str) -> list[str]:
    return [
        "an-kla",
        "--no-update-check",
        "--project-root",
        str(project_root),
        "subject",
        "namespace",
    ]


class SubjectNamespaceUnitTests(unittest.TestCase):
    """resolve_namespace logic: state mapping, drift catalogue, error layering."""

    def test_unavailable_for_each_non_complete_state(self) -> None:
        from an_kla.subject import resolve_namespace

        for state in NON_COMPLETE_STATES:
            with self.subTest(state=state):
                fake_store = object()
                with patch(
                    "an_kla.subject.identity_status",
                    return_value={"identity_status": state},
                ):
                    result = resolve_namespace(fake_store)
                self.assertEqual(result["schema"], "an-kla/subject-namespace-result-v1")
                self.assertEqual(result["result"], "namespace_unavailable")
                self.assertIsNone(result["namespace"])

    def test_available_when_complete_uses_real_binding_digest(self) -> None:
        from an_kla.subject import resolve_namespace

        project_bytes = b'{"schema":"an-kla/project-identity-v1"}'
        fake_store = object()
        with patch(
            "an_kla.subject.identity_status",
            return_value={"identity_status": "complete"},
        ), patch(
            "an_kla.subject.read_binding",
            return_value={"project_bytes": project_bytes},
        ):
            result = resolve_namespace(fake_store)
        self.assertEqual(result["result"], "namespace_available")
        self.assertEqual(result["namespace"], derive_namespace(project_bytes))
        self.assertRegex(result["namespace"], r"^p-[0-9a-f]{32}$")

    def test_controlled_identity_error_drift_returns_unavailable(self) -> None:
        from an_kla.subject import resolve_namespace

        for code in BINDING_DRIFT_CODES:
            with self.subTest(code=code):
                with patch(
                    "an_kla.subject.identity_status",
                    return_value={"identity_status": "complete"},
                ), patch(
                    "an_kla.subject.read_binding",
                    side_effect=IdentityError(code),
                ):
                    result = resolve_namespace(object())
                self.assertEqual(result["result"], "namespace_unavailable")
                self.assertIsNone(result["namespace"])

    def test_unexpected_identity_error_propagates(self) -> None:
        """IdentityError outside the controlled catalogue is NOT swallowed."""

        from an_kla.subject import resolve_namespace

        with patch(
            "an_kla.subject.identity_status",
            return_value={"identity_status": "complete"},
        ), patch(
            "an_kla.subject.read_binding",
            side_effect=IdentityError("some_unexpected_code"),
        ):
            with self.assertRaisesRegex(IdentityError, "some_unexpected_code"):
                resolve_namespace(object())

    def test_integrity_error_from_read_binding_propagates(self) -> None:
        from an_kla.subject import resolve_namespace

        with patch(
            "an_kla.subject.identity_status",
            return_value={"identity_status": "complete"},
        ), patch(
            "an_kla.subject.read_binding",
            side_effect=IntegrityError("corrupt_segment"),
        ):
            with self.assertRaises(IntegrityError):
                resolve_namespace(object())

    def test_store_error_from_read_binding_propagates(self) -> None:
        from an_kla.subject import resolve_namespace

        with patch(
            "an_kla.subject.identity_status",
            return_value={"identity_status": "complete"},
        ), patch(
            "an_kla.subject.read_binding",
            side_effect=StoreError("io_failure"),
        ):
            with self.assertRaises(StoreError):
                resolve_namespace(object())

    def test_oserror_from_identity_status_propagates(self) -> None:
        from an_kla.subject import resolve_namespace

        with patch(
            "an_kla.subject.identity_status",
            side_effect=OSError("EIO"),
        ):
            with self.assertRaises(OSError):
                resolve_namespace(object())


class SubjectNamespaceCliExitCodeTests(unittest.TestCase):
    """CLI exit-code mapping via in-process invocation with mocked layering."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project_root = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_cli_exit_0_for_complete_with_canonical_stdout(self) -> None:
        project_bytes = b'{"schema":"an-kla/project-identity-v1"}'
        with patch(
            "an_kla.subject.identity_status",
            return_value={"identity_status": "complete"},
        ), patch(
            "an_kla.subject.read_binding",
            return_value={"project_bytes": project_bytes},
        ):
            code, out, err = _invoke_cli(_subject_argv(self.project_root))
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        result = json.loads(out)
        self.assertEqual(result["schema"], "an-kla/subject-namespace-result-v1")
        self.assertEqual(result["result"], "namespace_available")
        self.assertEqual(result["namespace"], derive_namespace(project_bytes))
        self.assertEqual(out, canonical_json(result))

    def test_cli_exit_3_for_each_non_complete_state(self) -> None:
        for state in NON_COMPLETE_STATES:
            with self.subTest(state=state):
                with patch(
                    "an_kla.subject.identity_status",
                    return_value={"identity_status": state},
                ):
                    code, out, err = _invoke_cli(
                        _subject_argv(self.project_root)
                    )
                self.assertEqual(code, 3)
                self.assertEqual(err, "")
                result = json.loads(out)
                self.assertEqual(result["result"], "namespace_unavailable")
                self.assertIsNone(result["namespace"])
                self.assertEqual(out, canonical_json(result))

    def test_cli_exit_3_for_controlled_drift_after_complete(self) -> None:
        for code in BINDING_DRIFT_CODES:
            with self.subTest(code=code):
                with patch(
                    "an_kla.subject.identity_status",
                    return_value={"identity_status": "complete"},
                ), patch(
                    "an_kla.subject.read_binding",
                    side_effect=IdentityError(code),
                ):
                    code_val, out, err = _invoke_cli(
                        _subject_argv(self.project_root)
                    )
                self.assertEqual(code_val, 3)
                self.assertEqual(err, "")
                result = json.loads(out)
                self.assertEqual(result["result"], "namespace_unavailable")
                self.assertIsNone(result["namespace"])

    def test_cli_exit_1_for_oserror_from_identity_status(self) -> None:
        with patch(
            "an_kla.subject.identity_status",
            side_effect=OSError("EIO"),
        ):
            code, out, err = _invoke_cli(_subject_argv(self.project_root))
        self.assertEqual(code, 1)
        self.assertEqual(out, b"")
        self.assertIn("an-kla error:", err)

    def test_cli_exit_1_for_integrity_error_from_read_binding(self) -> None:
        with patch(
            "an_kla.subject.identity_status",
            return_value={"identity_status": "complete"},
        ), patch(
            "an_kla.subject.read_binding",
            side_effect=IntegrityError("corrupt"),
        ):
            code, out, err = _invoke_cli(_subject_argv(self.project_root))
        self.assertEqual(code, 1)
        self.assertEqual(out, b"")
        self.assertIn("an-kla error:", err)

    def test_cli_exit_1_for_store_error_from_read_binding(self) -> None:
        with patch(
            "an_kla.subject.identity_status",
            return_value={"identity_status": "complete"},
        ), patch(
            "an_kla.subject.read_binding",
            side_effect=StoreError("io"),
        ):
            code, out, err = _invoke_cli(_subject_argv(self.project_root))
        self.assertEqual(code, 1)
        self.assertEqual(out, b"")
        self.assertIn("an-kla error:", err)

    def test_cli_exit_1_for_unexpected_identity_error(self) -> None:
        with patch(
            "an_kla.subject.identity_status",
            return_value={"identity_status": "complete"},
        ), patch(
            "an_kla.subject.read_binding",
            side_effect=IdentityError("non_catalogue_code"),
        ):
            code, out, err = _invoke_cli(_subject_argv(self.project_root))
        self.assertEqual(code, 1)
        self.assertEqual(out, b"")


class SubjectNamespaceRealStoreTests(unittest.TestCase):
    """End-to-end with a real MemoryStore: complete path, absent path, no mutation."""

    def test_real_complete_identity_exit_0_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            store = MemoryStore(project)
            store.initialize()
            self.assertEqual(identity_status(store)["identity_status"], "complete")
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "an_kla",
                    "--no-update-check",
                    "--project-root",
                    project,
                    "subject",
                    "namespace",
                ],
                cwd=ROOT,
                capture_output=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr.decode())
            self.assertEqual(completed.stderr, b"")
            result = json.loads(completed.stdout)
            self.assertEqual(result["schema"], "an-kla/subject-namespace-result-v1")
            self.assertEqual(result["result"], "namespace_available")
            self.assertRegex(result["namespace"], r"^p-[0-9a-f]{32}$")
            self.assertEqual(completed.stdout, canonical_json(result))
            binding = read_binding(store)
            self.assertEqual(result["namespace"], derive_namespace(binding["project_bytes"]))

    def test_real_absent_root_exit_3_without_creating_an_kla(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            root = Path(project)
            self.assertFalse((root / ".an-kla").exists())
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "an_kla",
                    "--no-update-check",
                    "--project-root",
                    project,
                    "subject",
                    "namespace",
                ],
                cwd=ROOT,
                capture_output=True,
            )
            self.assertEqual(completed.returncode, 3, completed.stderr.decode())
            self.assertEqual(completed.stderr, b"")
            result = json.loads(completed.stdout)
            self.assertEqual(result["result"], "namespace_unavailable")
            self.assertIsNone(result["namespace"])
            self.assertEqual(completed.stdout, canonical_json(result))
            self.assertFalse((root / ".an-kla").exists())

    def test_real_legacy_unadopted_exit_3(self) -> None:
        from an_kla.initialization import initialize_locked
        import uuid

        with tempfile.TemporaryDirectory() as project:
            store = MemoryStore(project)
            store._make_layout()
            with store.write_lock():
                root_revision, outcome = initialize_locked(
                    store, transaction_id=str(uuid.uuid4())
                )
            self.assertIsNotNone(root_revision)
            self.assertTrue(outcome["committed"])
            self.assertEqual(
                identity_status(store)["identity_status"], "legacy_unadopted"
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "an_kla",
                    "--no-update-check",
                    "--project-root",
                    project,
                    "subject",
                    "namespace",
                ],
                cwd=ROOT,
                capture_output=True,
            )
            self.assertEqual(completed.returncode, 3, completed.stderr.decode())
            self.assertEqual(completed.stderr, b"")
            result = json.loads(completed.stdout)
            self.assertEqual(result["result"], "namespace_unavailable")

    def test_does_not_mutate_current(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            store = MemoryStore(project)
            store.initialize()
            current_before = store.read_current()
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "an_kla",
                    "--no-update-check",
                    "--project-root",
                    project,
                    "subject",
                    "namespace",
                ],
                cwd=ROOT,
                capture_output=True,
            )
            self.assertEqual(completed.returncode, 0)
            store_after = MemoryStore(project)
            self.assertEqual(store_after.read_current(), current_before)


class SubjectNamespaceSchemaValidationTests(unittest.TestCase):
    """Validate real stdout against the published schema (Draft 2020-12)."""

    def test_outputs_validate_against_draft_2020_12(self) -> None:
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema unavailable")
        from an_kla.schemas import schema_document

        validator = Draft202012Validator(schema_document("subject-namespace-result-v1"))
        with tempfile.TemporaryDirectory() as project:
            MemoryStore(project).initialize()
            available = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "an_kla",
                    "--no-update-check",
                    "--project-root",
                    project,
                    "subject",
                    "namespace",
                ],
                cwd=ROOT,
                capture_output=True,
                check=True,
            )
            validator.validate(json.loads(available.stdout))
        with tempfile.TemporaryDirectory() as empty:
            unavailable = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "an_kla",
                    "--no-update-check",
                    "--project-root",
                    empty,
                    "subject",
                    "namespace",
                ],
                cwd=ROOT,
                capture_output=True,
            )
            self.assertEqual(unavailable.returncode, 3)
            validator.validate(json.loads(unavailable.stdout))


if __name__ == "__main__":
    unittest.main()
