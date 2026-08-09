"""Build and exercise an isolated wheel without network or publication."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
RESOURCE_NAMES = {
    "an_kla/resources/retrieval-benchmark-v2/queries.jsonl",
    "an_kla/resources/retrieval-benchmark-v2/provenance.json",
}


def _run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(command, capture_output=True, **kwargs)
    if result.returncode:
        sys.stderr.buffer.write(result.stdout)
        sys.stderr.buffer.write(result.stderr)
        raise SystemExit(result.returncode)
    return result


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        wheel_dir = temporary / "wheel"
        wheel_dir.mkdir()
        _run(
            [
                sys.executable, "-m", "build", "--wheel", "--no-isolation",
                "--outdir", str(wheel_dir),
            ],
            cwd=ROOT,
        )
        wheels = list(wheel_dir.glob("*.whl"))
        if len(wheels) != 1:
            raise SystemExit("clean_wheel_invalid_artifact_count")
        with zipfile.ZipFile(wheels[0]) as archive:
            missing = RESOURCE_NAMES - set(archive.namelist())
        if missing:
            raise SystemExit("clean_wheel_missing_benchmark_resources")

        environment_dir = temporary / "venv"
        _run([sys.executable, "-m", "venv", str(environment_dir)])
        scripts = environment_dir / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        cli = scripts / ("an-kla.exe" if os.name == "nt" else "an-kla")
        _run([str(python), "-m", "pip", "install", "--no-deps", str(wheels[0])])
        version = _run([str(cli), "--version"])
        schema_list = _run(
            [str(cli), "--no-update-check", "schema", "list"],
            env={**os.environ, "AN_KLA_NO_UPDATE_CHECK": "1"},
        )
        try:
            installed_schemas = {
                item["name"] for item in json.loads(schema_list.stdout)["schemas"]
            }
        except (KeyError, TypeError, UnicodeError, json.JSONDecodeError):
            raise SystemExit("clean_wheel_invalid_schema_catalog") from None
        required_compaction = {
            "compaction-planning-result-v1",
            "compaction-result-v1",
            "compaction-tombstone-catalog-v1",
            "revision-v3",
            "transaction-archived-v1",
            "verify-revision-v1",
        }
        if not required_compaction.issubset(installed_schemas):
            raise SystemExit("clean_wheel_missing_compaction_schemas")
        benchmark = _run(
            [str(cli), "--no-update-check", "benchmark-reference"],
            env={**os.environ, "AN_KLA_NO_UPDATE_CHECK": "1"},
        )
        try:
            payload = json.loads(benchmark.stdout)
        except (UnicodeError, json.JSONDecodeError):
            raise SystemExit("clean_wheel_invalid_benchmark_output") from None
        if payload.get("schema") != "an-kla/reference-benchmark-v1":
            raise SystemExit("clean_wheel_wrong_benchmark_schema")
        if payload.get("conclusion") != {
            "ranking_change_authorized": False,
            "reason": "metrics_require_future_adr",
        }:
            raise SystemExit("clean_wheel_unsafe_benchmark_conclusion")
    print(
        "check_clean_wheel: OK — entrypoint, recursos y benchmark-reference "
        f"desde wheel aislado ({version.stdout.decode().strip()})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
