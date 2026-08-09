"""Exercise a beta.8 managed-context migration using an isolated beta.11 wheel."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
TAG = "v0.1.0-beta.8"
TARGET = "v0.1.0-beta.11"


def _run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(command, capture_output=True, **kwargs)
    if result.returncode:
        sys.stderr.buffer.write(result.stdout)
        sys.stderr.buffer.write(result.stderr)
        raise SystemExit(result.returncode)
    return result


def _tag_bytes(relative: str) -> bytes:
    return _run(["git", "show", f"{TAG}:{relative}"], cwd=ROOT).stdout


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        wheel_dir = temporary / "wheel"
        wheel_dir.mkdir()
        _run(
            [
                sys.executable,
                "-m",
                "build",
                "--wheel",
                "--no-isolation",
                "--outdir",
                str(wheel_dir),
            ],
            cwd=ROOT,
        )
        wheels = list(wheel_dir.glob("*.whl"))
        if len(wheels) != 1:
            raise SystemExit("beta8_upgrade_invalid_artifact_count")

        environment_dir = temporary / "venv"
        _run([sys.executable, "-m", "venv", str(environment_dir)])
        scripts = environment_dir / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        cli = scripts / ("an-kla.exe" if os.name == "nt" else "an-kla")
        _run([str(python), "-m", "pip", "install", "--no-deps", str(wheels[0])])

        consumer = temporary / "consumer"
        consumer.mkdir()
        agents_before = _tag_bytes("AGENTS.md")
        contract_before = _tag_bytes("AN-KLA.md")
        (consumer / "AGENTS.md").write_bytes(agents_before)
        (consumer / "AN-KLA.md").write_bytes(contract_before)
        command = [str(cli), "--no-update-check", "--project-root", str(consumer)]

        legacy_builder = """\
import sys, uuid
from an_kla.initialization import initialize_locked
from an_kla.store import MemoryStore
store = MemoryStore(sys.argv[1])
store._make_layout()
with store.write_lock():
    revision, outcome = initialize_locked(store, transaction_id=str(uuid.uuid4()))
if revision is None or outcome.get("committed") is not True:
    raise SystemExit("legacy_fixture_failed")
"""
        _run([str(python), "-c", legacy_builder, str(consumer)])

        before = json.loads(_run([*command, "context", "status"]).stdout)
        if before.get("diagnostics") != ["context_template_outdated"]:
            raise SystemExit("beta8_upgrade_source_not_recognized")

        plan = json.loads(
            _run([*command, "upgrade", "inspect", "--target", TARGET]).stdout
        )
        plan_path = temporary / "upgrade-plan.json"
        plan_path.write_text(
            json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

        identity_before = json.loads(
            _run([*command, "identity", "status"]).stdout
        )
        if identity_before.get("identity_status") != "legacy_unadopted":
            raise SystemExit("beta8_upgrade_store_not_legacy")
        identity_plan = json.loads(
            _run([*command, "identity", "plan-adoption"]).stdout
        )
        identity_plan_path = temporary / "identity-plan.json"
        identity_plan_path.write_text(
            json.dumps(
                identity_plan,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        _run(
            [
                *command,
                "identity",
                "adopt",
                "--plan",
                str(identity_plan_path),
                "--expected-current",
                identity_plan["expected_current"],
            ]
        )
        identity_after = json.loads(
            _run([*command, "identity", "status"]).stdout
        )
        if identity_after.get("identity_status") != "complete":
            raise SystemExit("beta8_upgrade_identity_not_adopted")

        _run(
            [
                *command,
                "upgrade",
                "apply",
                plan["plan_fingerprint"],
                "--plan",
                str(plan_path),
            ]
        )
        verified = json.loads(
            _run([*command, "upgrade", "verify", "--target", TARGET]).stdout
        )
        if verified.get("ok") is not True:
            raise SystemExit("beta8_upgrade_verification_failed")
        after = json.loads(_run([*command, "context", "status"]).stdout)
        if after.get("ok") is not True or after.get("template_version") != "0.1.0-beta.11":
            raise SystemExit("beta8_upgrade_context_not_current")
        _run([*command, "verify"])

        prefix = agents_before.split(b"<!-- an-kla:managed-begin", 1)[0]
        if not (consumer / "AGENTS.md").read_bytes().startswith(prefix):
            raise SystemExit("beta8_upgrade_user_prefix_changed")

    print(
        "check_beta8_upgrade: OK — store legacy adoptado y contexto beta.8 "
        "migrado a beta.11 sin cambiar el prefijo del maintainer"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
