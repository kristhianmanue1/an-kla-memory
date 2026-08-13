from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

from an_kla.canonical import canonical_json
from an_kla.store import MemoryStore


REVISION = "sha256:" + "a" * 64
SUBJECT = "an-kla:subject:v1:service:p-" + "b" * 32 + ":billing"


def _invoke_cli(argv: list[str]) -> tuple[int, bytes, str]:
    from an_kla.__main__ import main

    stdout_buf = io.BytesIO()
    stderr_buf = io.StringIO()

    class _Stdout:
        buffer = stdout_buf

        def write(self, *_args: object, **_kwargs: object) -> None:
            pass

        def flush(self) -> None:
            pass

    old_out, old_err, old_argv = sys.stdout, sys.stderr, sys.argv
    sys.stdout, sys.stderr, sys.argv = _Stdout(), stderr_buf, argv
    try:
        try:
            main()
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
        else:
            code = 0
    finally:
        sys.stdout, sys.stderr, sys.argv = old_out, old_err, old_argv
    return code, stdout_buf.getvalue(), stderr_buf.getvalue()


def _argv(root: str, *extra: str) -> list[str]:
    return [
        "an-kla",
        "--no-update-check",
        "--project-root",
        root,
        "view",
        "context",
        "--revision",
        REVISION,
        *extra,
    ]


class ContextViewCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_success_is_canonical_stdout_exit_zero_and_maps_all_inputs(self) -> None:
        success = {
            "schema": "an-kla/context-view-v1",
            "subjects": [],
        }
        with patch("an_kla.__main__.context_view", return_value=success) as view:
            code, out, err = _invoke_cli(
                _argv(
                    self._tmp.name,
                    "--subject",
                    SUBJECT,
                    "--streams",
                    "episodes,facts",
                    "--projection",
                    "full",
                    "--limit",
                    "7",
                    "--budget",
                    "9000",
                    "--cursor",
                    "opaque",
                    "--now",
                    "2026-08-12T00:00:00Z",
                    "--stale-after-days",
                    "30",
                )
            )
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, canonical_json(success))
        self.assertEqual(
            view.call_args.kwargs,
            {
                "revision": REVISION,
                "streams": ("episodes", "facts"),
                "subject_filter": SUBJECT,
                "projection": "full",
                "limit": 7,
                "budget_bytes": 9000,
                "cursor": "opaque",
                "now": "2026-08-12T00:00:00Z",
                "stale_after_days": 30,
            },
        )

    def test_real_initialized_store_returns_canonical_view(self) -> None:
        revision = MemoryStore(self._tmp.name).initialize()
        argv = _argv(self._tmp.name)
        argv[argv.index(REVISION)] = revision
        code, out, err = _invoke_cli(argv)
        self.assertEqual((code, err), (0, ""))
        result = json.loads(out)
        self.assertEqual(result["schema"], "an-kla/context-view-v1")
        self.assertEqual(result["revision"], revision)
        self.assertEqual(out, canonical_json(result))

    def test_defaults_are_forwarded_to_core(self) -> None:
        success = {"schema": "an-kla/context-view-v1"}
        with patch("an_kla.__main__.context_view", return_value=success) as view:
            code, _, _ = _invoke_cli(_argv(self._tmp.name))
        self.assertEqual(code, 0)
        self.assertEqual(view.call_args.kwargs["streams"], None)
        self.assertEqual(view.call_args.kwargs["projection"], "text")
        self.assertEqual(view.call_args.kwargs["limit"], 50)
        self.assertEqual(view.call_args.kwargs["budget_bytes"], 65536)

    def test_invalid_inputs_are_sanitized_stderr_exit_two(self) -> None:
        result = {
            "schema": "an-kla/view-error-v1",
            "ok": False,
            "code": "view_invalid_inputs",
            "retryable": False,
            "untrusted_memory_data": True,
            "detail": "subject_filter",
        }
        with patch("an_kla.__main__.context_view", return_value=result):
            code, out, err = _invoke_cli(_argv(self._tmp.name))
        self.assertEqual((code, out), (2, b""))
        self.assertEqual(err, "an-kla error: view_invalid_inputs (subject_filter)\n")

    def test_catalogued_operational_error_is_canonical_stdout_exit_three(self) -> None:
        result = {
            "schema": "an-kla/view-error-v1",
            "ok": False,
            "code": "view_revision_not_available",
            "retryable": False,
            "untrusted_memory_data": True,
        }
        with patch("an_kla.__main__.context_view", return_value=result):
            code, out, err = _invoke_cli(_argv(self._tmp.name))
        self.assertEqual((code, err), (3, ""))
        self.assertEqual(out, canonical_json(result))
        self.assertEqual(json.loads(out)["code"], "view_revision_not_available")

    def test_internal_error_is_sanitized_stderr_exit_one(self) -> None:
        result = {
            "schema": "an-kla/view-error-v1",
            "ok": False,
            "code": "view_internal_error",
            "retryable": False,
            "untrusted_memory_data": True,
        }
        with patch("an_kla.__main__.context_view", return_value=result):
            code, out, err = _invoke_cli(_argv(self._tmp.name))
        self.assertEqual((code, out), (1, b""))
        self.assertEqual(err, "an-kla error: view_internal_error\n")


if __name__ == "__main__":
    unittest.main()
