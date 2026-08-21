"""Exercise a beta.15 consumer upgraded to the candidate wheel."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_TAG = "v0.1.0-beta.16"


def _run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(command, capture_output=True, **kwargs)
    if result.returncode:
        sys.stderr.buffer.write(result.stdout)
        sys.stderr.buffer.write(result.stderr)
        raise SystemExit(result.returncode)
    return result


def _wheel(source: Path, destination: Path, error: str) -> Path:
    _run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation",
         "--outdir", str(destination)],
        cwd=source,
    )
    wheels = list(destination.glob("*.whl"))
    if len(wheels) != 1:
        raise SystemExit(error)
    return wheels[0]


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        archive = temporary / "beta15.zip"
        _run(["git", "archive", "--format=zip", "--output", str(archive), PREVIOUS_TAG], cwd=ROOT)
        previous_source = temporary / "previous-source"
        previous_source.mkdir()
        with zipfile.ZipFile(archive) as bundle:
            for name in bundle.namelist():
                path = Path(name)
                if path.is_absolute() or ".." in path.parts:
                    raise SystemExit("beta16_upgrade_unsafe_archive")
            bundle.extractall(previous_source)

        previous_wheel = _wheel(previous_source, temporary / "prev", "beta15_prev_wheel")
        candidate_wheel = _wheel(ROOT, temporary / "cand", "beta15_cand_wheel")

        environment = temporary / "venv"
        _run([sys.executable, "-m", "venv", str(environment)])
        scripts = environment / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        cli = scripts / ("an-kla.exe" if os.name == "nt" else "an-kla")
        _run([str(python), "-m", "pip", "install", "--no-deps", str(previous_wheel)])
        if _run([str(cli), "--version"]).stdout.decode().strip() != "an-kla-memory 0.1.0b16":
            raise SystemExit("beta16_upgrade_wrong_previous_version")

        consumer = temporary / "consumer"
        consumer.mkdir()
        command = [str(cli), "--no-update-check", "--project-root", str(consumer)]
        _run([*command, "init"])
        _run([*command, "context", "plan", "--operation", "install"])
        _run([*command, "context", "install"])
        _run([str(python), "-m", "pip", "install", "--no-deps", "--upgrade", str(candidate_wheel)])
        if _run([str(cli), "--version"]).stdout.decode().strip() != "an-kla-memory 0.1.0b17":
            raise SystemExit("beta16_upgrade_wrong_candidate_version")
        before = json.loads(_run([*command, "verify"]).stdout)
        if before.get("ok") is not True:
            raise SystemExit("beta16_upgrade_invalid_baseline")
        context = json.loads(_run([*command, "context", "status"]).stdout)
        if context.get("ok") is not True or context.get("template_version") != "0.1.0-beta.11":
            raise SystemExit("beta16_upgrade_context_changed")

        # beta.16 features present on the upgraded consumer:
        integration = json.loads(_run([*command, "integration", "status"]).stdout)
        if integration.get("schema") != "an-kla/integration-status-v1":
            raise SystemExit("beta16_upgrade_integration_status_missing")
        capabilities = json.loads(_run([*command, "capabilities"]).stdout)
        if "source_state_profiles" not in capabilities.get("storage", {}).get("checkpoint", {}):
            raise SystemExit("beta16_upgrade_git_v1_not_declared")
        if not capabilities.get("write_policy", {}).get("context_diagnostics_in_init_result"):
            raise SystemExit("beta16_upgrade_init_signal_not_declared")
        retrieve = json.loads(_run([
            *command, "retrieve", "--query", "an-kla", "--budget", "60000",
            "--freshness-profile", "computed-age/v1", "--stale-after-days", "30",
        ]).stdout)
        freshness = retrieve.get("freshness") or {}
        for key in ("evaluated", "not_evaluable", "unparseable", "stale"):
            if key not in freshness:
                raise SystemExit("beta16_upgrade_denominators_missing")

        # Fresh consumer initialized by the candidate: init surfaces the signal.
        fresh = temporary / "fresh"
        fresh.mkdir()
        init_out = json.loads(
            _run([str(cli), "--no-update-check", "--project-root", str(fresh), "init"]).stdout
        )
        if not init_out.get("context_diagnostics", {}).get("installed") is False:
            raise SystemExit("beta16_upgrade_init_signal_missing")

        # beta.17 features on the upgraded consumer: adopt-baseline + inventory.
        target = consumer / "AGENTS.md"
        target.write_text(
            target.read_text(encoding="utf-8") + "\nReferencias locales del proyecto.\n",
            encoding="utf-8",
        )
        adopted = json.loads(
            _run([str(cli), "--no-update-check", "--project-root", str(consumer),
                  "context", "adopt-baseline"]).stdout
        )
        result17 = adopted.get("result", {})
        if result17.get("schema") != "an-kla/context-baseline-adoption-result/v1" or result17.get("action") not in {"adopted", "noop"}:
            raise SystemExit("beta17_upgrade_adopt_baseline_missing")
        status_clean = json.loads(_run([*command, "context", "status"]).stdout)
        if "context_target_changed_outside_managed_block" in status_clean.get("warnings", []):
            raise SystemExit("beta17_upgrade_drift_not_resolved")
        verify_out = json.loads(_run([*command, "verify"]).stdout)
        inv = json.loads(
            _run([str(cli), "--no-update-check", "--project-root", str(consumer),
                  "inventory", "--revision", verify_out["revision"]]).stdout
        )
        if inv.get("schema") != "an-kla/inventory-v1":
            raise SystemExit("beta17_upgrade_inventory_missing")

    print(
        "check_beta16_upgrade: OK — revisión y contexto beta.16 preservados; "
        "denominadores, git/v1 declarado, integration status y señal de init "
        "presentes en wheel candidato 0.1.0b17"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
