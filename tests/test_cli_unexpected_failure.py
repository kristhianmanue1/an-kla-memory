"""Red de resguardo del CLI ante excepciones no previstas (issue #84)."""

from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stderr
from pathlib import Path

from an_kla import cli_error_log
from an_kla.__main__ import main

ROOT = Path(__file__).resolve().parents[1]

_DRIVER = (
    "import sys; sys.path.insert(0, {root!r})\n"
    "from unittest import mock\n"
    "import an_kla.cli_error_log as log\n"
    "import an_kla.__main__ as cli\n"
    "mock.patch.object(log, 'error_log_path', "
    "return_value=__import__('pathlib').Path({target!r})).start()\n"
    "cli._run = mock.Mock(side_effect=RuntimeError('kaboom'))\n"
    "cli.main()\n"
)


class CliErrorLogTest(unittest.TestCase):
    def test_display_path_masks_home(self) -> None:
        path = Path.home() / ".cache" / "an-kla" / "cli-errors.log"
        rendered = cli_error_log.display_path(path)
        self.assertEqual(rendered, "~/.cache/an-kla/cli-errors.log")
        self.assertFalse(rendered.startswith(str(Path.home())))

    def test_display_path_renders_relative_tail_outside_home(self) -> None:
        rendered = cli_error_log.display_path(Path("/tmp/xdg/an-kla/cli-errors.log"))
        self.assertEqual(rendered, "an-kla/cli-errors.log")
        self.assertFalse(Path(rendered).is_absolute())

    def test_display_path_never_raises(self) -> None:
        with unittest.mock.patch.object(
            Path, "home", side_effect=KeyError("no passwd entry")
        ):
            self.assertEqual(
                cli_error_log.display_path(Path("/x/an-kla/cli-errors.log")),
                "<unavailable>",
            )

    def test_write_error_log_appends_private_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "logs" / "cli-errors.log"
            with unittest.mock.patch.object(
                cli_error_log, "error_log_path", return_value=target
            ):
                first = cli_error_log.write_error_log("boom-one", argv=["an_kla", "x"])
                second = cli_error_log.write_error_log("boom-two", argv=["an_kla", "y"])
            self.assertEqual(first, target)
            self.assertEqual(second, target)
            content = target.read_text(encoding="utf-8")
            self.assertIn("boom-one", content)
            self.assertIn("boom-two", content)
            self.assertIn("argv: an_kla x", content)
            self.assertEqual(os.stat(target).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(target.parent).st_mode & 0o777, 0o700)

    def test_write_error_log_resets_on_overflow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "cli-errors.log"
            target.write_text("x" * (cli_error_log.MAX_LOG_BYTES + 1), encoding="utf-8")
            with unittest.mock.patch.object(
                cli_error_log, "error_log_path", return_value=target
            ):
                result = cli_error_log.write_error_log("boom", argv=["an_kla"])
            self.assertEqual(result, target)
            content = target.read_text(encoding="utf-8")
            self.assertNotIn("xxxx", content)
            self.assertIn("boom", content)

    def test_write_error_log_survives_surrogate_argv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "cli-errors.log"
            with unittest.mock.patch.object(
                cli_error_log, "error_log_path", return_value=target
            ):
                result = cli_error_log.write_error_log(
                    "boom", argv=["an_kla", "\udcff\udcfe"]
                )
            self.assertEqual(result, target)
            self.assertIn("boom", target.read_text(encoding="utf-8"))

    def test_write_error_log_disabled_by_env(self) -> None:
        with unittest.mock.patch.dict(
            os.environ, {cli_error_log.DISABLE_LOG_ENV: "1"}
        ):
            self.assertIsNone(cli_error_log.write_error_log("boom"))

    def test_write_error_log_never_raises(self) -> None:
        with unittest.mock.patch.object(
            cli_error_log,
            "error_log_path",
            side_effect=OSError("disk full"),
        ):
            self.assertIsNone(cli_error_log.write_error_log("boom"))


class UnexpectedFailureSafetyNetTest(unittest.TestCase):
    def _run_main(
        self, debug: str | None = None, log_target: Path | None = None
    ) -> tuple[object, str, str]:
        env: dict[str, str] = {}
        if debug is not None:
            env[cli_error_log.DEBUG_ENV] = debug
        stderr = io.StringIO()
        target = log_target or Path(tempfile.mkdtemp()) / "an-kla" / "cli-errors.log"
        with unittest.mock.patch.dict(os.environ, env, clear=False):
            with unittest.mock.patch.object(
                cli_error_log, "error_log_path", return_value=target
            ):
                with unittest.mock.patch(
                    "an_kla.__main__._run",
                    side_effect=RuntimeError("kaboom"),
                ):
                    with redirect_stderr(stderr):
                        with self.assertRaises(SystemExit) as ctx:
                            main()
        log_text = target.read_text(encoding="utf-8") if target.exists() else ""
        return ctx.exception.code, stderr.getvalue(), log_text

    def test_unexpected_failure_message_is_stable_and_relative(self) -> None:
        code, _stderr_text, log_text = self._run_main()
        self.assertEqual(
            code,
            "an-kla error: cli_unexpected_failure "
            "(traceback: an-kla/cli-errors.log)",
        )
        self.assertNotIn("Traceback", str(code))
        self.assertFalse("/tmp" in str(code) or "/var" in str(code))
        self.assertIn("RuntimeError: kaboom", log_text)

    def test_debug_env_restores_stderr_traceback(self) -> None:
        code, stderr_text, log_text = self._run_main(debug="1")
        self.assertEqual(code, 1)
        self.assertIn("Traceback", stderr_text)
        self.assertIn("RuntimeError: kaboom", stderr_text)
        self.assertIn("RuntimeError: kaboom", log_text)

    def test_safety_net_does_not_catch_system_exit(self) -> None:
        stderr = io.StringIO()
        with unittest.mock.patch(
            "an_kla.__main__._run", side_effect=SystemExit(3)
        ):
            with redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as ctx:
                    main()
        self.assertEqual(ctx.exception.code, 3)


class UnexpectedFailureEndToEndTest(unittest.TestCase):
    """Validate the real process stderr path (SystemExit(str) printing)."""

    def test_subprocess_stderr_has_no_traceback_or_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "nested" / "cli-errors.log"
            driver = _DRIVER.format(root=str(ROOT), target=str(target))
            completed = subprocess.run(
                [sys.executable, "-c", driver],
                capture_output=True,
                text=True,
                env={**os.environ, "AN_KLA_NO_UPDATE_CHECK": "1"},
                cwd=ROOT,
            )
            self.assertEqual(completed.returncode, 1, completed.stderr)
            self.assertEqual(
                completed.stderr,
                "an-kla error: cli_unexpected_failure "
                f"(traceback: {target.parent.name}/{target.name})\n",
            )
            self.assertNotIn("Traceback", completed.stderr)
            self.assertNotIn(str(ROOT), completed.stderr)
            self.assertIn("RuntimeError: kaboom", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
