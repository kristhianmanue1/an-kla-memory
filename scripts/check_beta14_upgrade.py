"""Exercise a beta.14 consumer upgraded to the candidate wheel."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_TAG = "v0.1.0-beta.14"


def _run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(command, capture_output=True, **kwargs)
    if result.returncode:
        sys.stderr.buffer.write(result.stdout)
        sys.stderr.buffer.write(result.stderr)
        raise SystemExit(result.returncode)
    return result


def _wheel(source: Path, destination: Path, error: str) -> Path:
    _run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            str(destination),
        ],
        cwd=source,
    )
    wheels = list(destination.glob("*.whl"))
    if len(wheels) != 1:
        raise SystemExit(error)
    return wheels[0]


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        archive = temporary / "beta14.zip"
        _run(
            ["git", "archive", "--format=zip", "--output", str(archive), PREVIOUS_TAG],
            cwd=ROOT,
        )
        previous_source = temporary / "previous-source"
        previous_source.mkdir()
        with zipfile.ZipFile(archive) as bundle:
            for name in bundle.namelist():
                path = Path(name)
                if path.is_absolute() or ".." in path.parts:
                    raise SystemExit("beta14_upgrade_unsafe_archive")
            bundle.extractall(previous_source)

        previous_dir = temporary / "previous-wheel"
        candidate_dir = temporary / "candidate-wheel"
        previous_dir.mkdir()
        candidate_dir.mkdir()
        previous_wheel = _wheel(
            previous_source, previous_dir, "beta14_upgrade_invalid_previous_wheel_count"
        )
        candidate_wheel = _wheel(
            ROOT, candidate_dir, "beta14_upgrade_invalid_candidate_wheel_count"
        )

        environment_dir = temporary / "venv"
        _run([sys.executable, "-m", "venv", str(environment_dir)])
        scripts = environment_dir / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        cli = scripts / ("an-kla.exe" if os.name == "nt" else "an-kla")
        _run([str(python), "-m", "pip", "install", "--no-deps", str(previous_wheel)])
        if _run([str(cli), "--version"]).stdout.decode().strip() != "an-kla-memory 0.1.0b14":
            raise SystemExit("beta14_upgrade_wrong_previous_version")

        consumer = temporary / "consumer"
        consumer.mkdir()
        command = [str(cli), "--no-update-check", "--project-root", str(consumer)]
        _run([*command, "init"])
        _run([*command, "context", "plan", "--operation", "install"])
        _run([*command, "context", "install"])
        before = json.loads(_run([*command, "verify"]).stdout)
        revision = before.get("revision")
        if before.get("ok") is not True or not isinstance(revision, str):
            raise SystemExit("beta14_upgrade_invalid_baseline")

        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--upgrade",
                str(candidate_wheel),
            ]
        )
        if _run([str(cli), "--version"]).stdout.decode().strip() != "an-kla-memory 0.1.0b16":
            raise SystemExit("beta14_upgrade_wrong_candidate_version")
        after = json.loads(_run([*command, "verify"]).stdout)
        if after.get("ok") is not True or after.get("revision") != revision:
            raise SystemExit("beta14_upgrade_revision_changed")
        context = json.loads(_run([*command, "context", "status"]).stdout)
        if context.get("ok") is not True or context.get("template_version") != "0.1.0-beta.11":
            raise SystemExit("beta14_upgrade_context_changed")

        diagnostic = json.loads(
            _run([*command, "startup-diagnostic"]).stdout
        )
        if (
            diagnostic.get("schema") != "an-kla/startup-diagnostic-v1"
            or diagnostic.get("repo_context") not in {
                "main_checkout", "linked_worktree", "not_a_repo", "git_unavailable",
            }
        ):
            raise SystemExit("beta14_upgrade_startup_diagnostic_missing")

        capabilities = json.loads(_run([*command, "capabilities"]).stdout)
        surface = capabilities.get("cli_error_surface", {}).get("unexpected_failure")
        if not surface or surface.get("exit_code") != 1:
            raise SystemExit("beta14_upgrade_cli_error_surface_missing")

    print(
        "check_beta14_upgrade: OK — revisión y contexto beta.14 preservados; "
        "startup-diagnostic y cli_error_surface presentes en wheel candidato 0.1.0b16"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
