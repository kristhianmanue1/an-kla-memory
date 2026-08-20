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
        if version.stdout.decode().strip() != "an-kla-memory 0.1.0b16":
            raise SystemExit("clean_wheel_wrong_version")
        help_result = _run([str(cli), "--no-update-check", "--help"])
        help_text = help_result.stdout.decode()
        if "{init,status,verify" not in help_text:
            raise SystemExit("clean_wheel_invalid_cli_help")
        public_commands = help_text.split("{", 1)[1].split("}", 1)[0].split(",")
        if "write" in public_commands:
            raise SystemExit("clean_wheel_legacy_write_exposed")
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
            "context-view-v1",
            "view-error-v1",
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

        consumer = temporary / "consumer"
        consumer.mkdir()
        consumer_command = [str(cli), "--no-update-check", "--project-root", str(consumer)]
        _run([*consumer_command, "init"])
        _run([*consumer_command, "context", "plan", "--operation", "install"])
        _run([*consumer_command, "context", "install"])
        context_status = json.loads(
            _run([*consumer_command, "context", "status"]).stdout
        )
        if context_status.get("ok") is not True or context_status.get(
            "template_version"
        ) != "0.1.0-beta.11":
            raise SystemExit("clean_wheel_context_not_current")
        identity_status = json.loads(
            _run([*consumer_command, "identity", "status"]).stdout
        )
        if identity_status.get("identity_status") != "complete":
            raise SystemExit("clean_wheel_identity_not_ready")
        verified = json.loads(_run([*consumer_command, "verify"]).stdout)
        revision = verified.get("revision")
        if not isinstance(revision, str):
            raise SystemExit("clean_wheel_missing_revision")
        capabilities_payload = json.loads(
            _run([str(cli), "--no-update-check", "capabilities"]).stdout
        )
        if capabilities_payload.get("view", {}).get("contract_version") != "g-view/v1":
            raise SystemExit("clean_wheel_missing_view_capability")
        view_result = _run(
            [*consumer_command, "view", "context", "--revision", revision]
        )
        try:
            view_payload = json.loads(view_result.stdout)
        except (UnicodeError, json.JSONDecodeError):
            raise SystemExit("clean_wheel_invalid_view_output") from None
        canonical_view = json.dumps(
            view_payload, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        if view_result.stdout != canonical_view:
            raise SystemExit("clean_wheel_noncanonical_view")
        if view_payload.get("schema") != "an-kla/context-view-v1":
            raise SystemExit("clean_wheel_wrong_view_schema")
        mcp_messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "an_kla_view_context", "arguments": {"revision": revision}}},
        ]
        mcp = _run(
            [str(python), "-m", "an_kla.mcp", "--project-root", str(consumer)],
            input="".join(json.dumps(item) + "\n" for item in mcp_messages).encode(),
        )
        replies = [json.loads(line) for line in mcp.stdout.splitlines()]
        tool_names = {item["name"] for item in replies[1]["result"]["tools"]}
        if "an_kla_view_context" not in tool_names:
            raise SystemExit("clean_wheel_missing_view_tool")
        mcp_result = replies[2]["result"]
        if mcp_result.get("isError") is not False:
            raise SystemExit("clean_wheel_view_tool_error")
        if mcp_result["content"][0]["text"].encode("utf-8") != canonical_view:
            raise SystemExit("clean_wheel_view_parity_mismatch")
    print(
        "check_clean_wheel: OK — instalación nueva, contexto, identidad, "
        "recursos y benchmark-reference "
        f"desde wheel aislado ({version.stdout.decode().strip()})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
