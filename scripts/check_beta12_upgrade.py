"""Exercise an offline beta.12 store with the candidate wheel."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_TAG = "v0.1.0-beta.12"
RECORD_ID = "f-beta12-upgrade"
RECORD_TEXT = "beta12 durable subject"


def _run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(command, capture_output=True, **kwargs)
    if result.returncode:
        sys.stderr.buffer.write(result.stdout)
        sys.stderr.buffer.write(result.stderr)
        raise SystemExit(result.returncode)
    return result


def _wheel(source: Path, destination: Path) -> Path:
    _run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(destination)],
        cwd=source,
    )
    wheels = list(destination.glob("*.whl"))
    if len(wheels) != 1:
        raise SystemExit("beta12_upgrade_invalid_wheel_count")
    return wheels[0]


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(_canonical(value))


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        archive = temporary / "beta12.zip"
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
                    raise SystemExit("beta12_upgrade_unsafe_archive")
            bundle.extractall(previous_source)

        previous_dir = temporary / "previous-wheel"
        candidate_dir = temporary / "candidate-wheel"
        previous_dir.mkdir()
        candidate_dir.mkdir()
        previous_wheel = _wheel(previous_source, previous_dir)
        candidate_wheel = _wheel(ROOT, candidate_dir)

        environment_dir = temporary / "venv"
        _run([sys.executable, "-m", "venv", str(environment_dir)])
        scripts = environment_dir / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        cli = scripts / ("an-kla.exe" if os.name == "nt" else "an-kla")
        _run([str(python), "-m", "pip", "install", "--no-deps", str(previous_wheel)])
        if _run([str(cli), "--version"]).stdout.decode().strip() != "an-kla-memory 0.1.0b12":
            raise SystemExit("beta12_upgrade_wrong_previous_version")

        consumer = temporary / "consumer"
        consumer.mkdir()
        command = [str(cli), "--no-update-check", "--project-root", str(consumer)]
        _run([*command, "init"])
        initial = json.loads(_run([*command, "verify"]).stdout)
        base_revision = initial.get("revision")
        namespace_result = json.loads(_run([*command, "subject", "namespace"]).stdout)
        namespace = namespace_result.get("namespace")
        if not isinstance(base_revision, str) or not isinstance(namespace, str):
            raise SystemExit("beta12_upgrade_subject_setup_failed")
        subject_ref = f"an-kla:subject:v1:service:{namespace}:upgrade"
        proposal = {
            "schema": "an-kla/write-proposal-v1",
            "base_revision": base_revision,
            "stream": "facts",
            "operation": "add",
            "requested_representation": "summary",
            "record": {
                "id": RECORD_ID,
                "subject_ref": subject_ref,
                "payload": {"text": RECORD_TEXT},
            },
            "lineage": {"derived_from_retrieval": False, "refs": []},
        }
        authority = {
            "schema": "an-kla/write-authority-v1",
            "proposal_sha256": _digest(proposal),
            "base_revision": base_revision,
            "authority_class": "model_derived",
            "issuer": {
                "kind": "model",
                "id": "beta12-upgrade-gate",
                "configuration_fingerprint": "sha256:" + "b" * 64,
            },
            "evidence": [],
            "scope": {
                "streams": ["facts"],
                "representations": ["summary"],
                "operations": ["add"],
            },
        }
        proposal_path = temporary / "proposal.json"
        authority_path = temporary / "authority.json"
        planning_path = temporary / "planning.json"
        _write_json(proposal_path, proposal)
        _write_json(authority_path, authority)
        planning = _run([
            *command, "plan-write", "--proposal", str(proposal_path),
            "--authority", str(authority_path),
        ]).stdout
        planning_path.write_bytes(planning)
        committed = json.loads(_run([
            *command, "commit-write-plan", "--expected-current", base_revision,
            "--proposal", str(proposal_path), "--authority", str(authority_path),
            "--planning-result", str(planning_path),
        ]).stdout)
        committed_revision = committed.get("revision")
        if not isinstance(committed_revision, str):
            raise SystemExit("beta12_upgrade_subject_commit_failed")
        before = json.loads(_run([*command, "verify"]).stdout)
        revision = before.get("revision")
        if revision != committed_revision:
            raise SystemExit("beta12_upgrade_missing_revision")

        _run([str(python), "-m", "pip", "install", "--no-deps", "--upgrade", str(candidate_wheel)])
        if _run([str(cli), "--version"]).stdout.decode().strip() != "an-kla-memory 0.1.0b13":
            raise SystemExit("beta12_upgrade_wrong_candidate_version")
        after = json.loads(_run([*command, "verify"]).stdout)
        if after.get("ok") is not True or after.get("revision") != revision:
            raise SystemExit("beta12_upgrade_revision_changed")
        view = json.loads(
            _run([
                *command, "view", "context", "--revision", revision,
                "--streams", "facts", "--subject", subject_ref,
            ]).stdout
        )
        if view.get("schema") != "an-kla/context-view-v1" or view.get("revision") != revision:
            raise SystemExit("beta12_upgrade_view_failed")
        subjects = view.get("subjects")
        if not isinstance(subjects, list) or len(subjects) != 1:
            raise SystemExit("beta12_upgrade_subject_missing")
        subject = subjects[0]
        alternatives = subject.get("alternatives") if isinstance(subject, dict) else None
        if (
            subject.get("subject_ref") != subject_ref
            or not isinstance(alternatives, list)
            or len(alternatives) != 1
            or alternatives[0].get("id") != RECORD_ID
            or alternatives[0].get("record_text") != RECORD_TEXT
        ):
            raise SystemExit("beta12_upgrade_subject_changed")
        with zipfile.ZipFile(candidate_wheel) as bundle:
            schema = json.loads(
                bundle.read("an_kla/schemas/context-view-v1.schema.json")
            )
        Draft202012Validator(schema).validate(view)

    print(
        "check_beta12_upgrade: OK — subject_ref, revisión, id y texto beta.12 "
        "preservados y servidos por G-VIEW válido desde wheel candidato 0.1.0b13"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
