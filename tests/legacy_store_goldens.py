"""Cálculo de los goldens de compatibilidad del store `v0.1.0-beta.35`.

Lo usan `test_legacy_store_byte_identity.py` (compara) y su modo script
(`--write`, regenera `goldens.json`). El store del fixture se creó con el
código de la beta.35 (ver `GENERAR.md` en el fixture); aquí sólo se abre.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "store-v0.1.0-beta.35"
STORE_TAR = FIXTURE / "store.tar"
GOLDENS = FIXTURE / "goldens.json"
PLACEHOLDER = "<PROJECT_ROOT>"
BUNDLE_PLACEHOLDER = "<BUNDLE>"
MCP_PROTOCOL = "2025-06-18"
ENV = {**os.environ, "AN_KLA_NO_UPDATE_CHECK": "1", "PYTHONDONTWRITEBYTECODE": "1"}
FRESH_NOW = "2026-06-01T00:00:00Z"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def extract_store(project: Path) -> None:
    """Extrae `.an-kla/` del tar versionado; rechaza cualquier miembro que se salga de él."""
    with tarfile.open(STORE_TAR) as tar:
        for member in tar.getmembers():
            parts = Path(member.name).parts
            if not parts or parts[0] != ".an-kla" or ".." in parts or not (member.isfile() or member.isdir()):
                raise ValueError(f"store_tar_unsafe_member: {member.name}")
        try:
            tar.extractall(project, filter="data")
        except TypeError:  # Python < 3.12: sin `filter`; los miembros ya se validaron arriba
            tar.extractall(project)


def _normalize(text: str, *roots: Path) -> bytes:
    """Sustituye la ruta de trabajo (y su forma resuelta) por un marcador estable."""
    for root in roots:
        for form in {str(root), str(root.resolve())}:
            text = text.replace(form, PLACEHOLDER)
    return text.encode("utf-8")


def _cli(project: Path, *args: str) -> tuple[bytes, bytes]:
    """(material a hashear con rc y stderr, stdout normalizado)."""
    done = subprocess.run(
        [sys.executable, "-m", "an_kla", "--project-root", str(project), *args],
        capture_output=True, text=True, env=ENV, cwd=ROOT, timeout=120,
    )
    stdout = _normalize(done.stdout, project)
    return _normalize(f"rc={done.returncode}\n", project) + stdout + b"\n--stderr--\n" + \
        _normalize(done.stderr, project), stdout


def _mcp(project: Path, calls: list[tuple[str, dict]]) -> list[bytes]:
    """Una sesión stdio; devuelve la respuesta cruda de cada petición, normalizada."""
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": MCP_PROTOCOL}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    for offset, (name, arguments) in enumerate(calls, start=3):
        messages.append({"jsonrpc": "2.0", "id": offset, "method": "tools/call",
                         "params": {"name": name, "arguments": arguments}})
    done = subprocess.run(
        [sys.executable, "-m", "an_kla.mcp", "--project-root", str(project)],
        input="".join(json.dumps(m) + "\n" for m in messages),
        capture_output=True, text=True, env=ENV, cwd=ROOT, timeout=120, check=True,
    )
    return [_normalize(line, project) for line in done.stdout.splitlines()]


def _export_digests(project: Path, bundle: Path) -> dict[str, str]:
    """Manifest y digests de entradas del bundle; nunca la ruta del bundle."""
    done = subprocess.run(
        [sys.executable, "-m", "an_kla", "--project-root", str(project), "export", "create",
         "--bundle", str(bundle)],
        capture_output=True, text=True, env=ENV, cwd=ROOT, timeout=120, check=True,
    )
    result = json.loads(done.stdout)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    entries = [[e["path"], e["content_sha256"], e["size"]] for e in manifest["core"]["entries"]]
    return {
        "export.manifest_sha256": result["manifest_sha256"],
        "export.manifest_file_sha256": sha256_hex((bundle / "manifest.json").read_bytes()),
        "export.entries_sha256": sha256_hex(json.dumps(entries, sort_keys=True).encode("utf-8")),
        "export.entries_count": str(len(entries)),
    }


def compute(project: Path, scratch: Path) -> dict[str, str]:
    """Recalcula todos los goldens sobre un checkout del store ya extraído en `project`."""
    status = json.loads(_cli(project, "status")[1])
    revision = status["revision"]
    out: dict[str, str] = {"store.revision": revision}
    cli_cases = {
        "cli.status": ("status",),
        "cli.verify": ("verify",),
        "cli.inventory": ("inventory", "--revision", revision),
        "cli.retrieve": ("retrieve", "--query", "golden", "--budget", "400"),
        "cli.retrieve_streams": ("retrieve", "--query", "golden", "--budget", "400",
                                 "--streams", "facts,events,episodes"),
        "cli.retrieve_fresh": ("retrieve", "--query", "golden", "--budget", "400",
                               "--freshness-profile", "computed-age/v1", "--now", FRESH_NOW),
        "cli.resume": ("resume", "--budget", "4000", "--query", "golden"),
        "cli.assemble_context": ("assemble-context", "--query", "golden", "--budget", "800",
                                 "--new-information", "nota nueva"),
    }
    for name, args in cli_cases.items():
        out[name] = sha256_hex(_cli(project, *args)[0])
    proposal = scratch / "proposal.json"
    proposal.write_text(json.dumps({
        "schema": "an-kla/write-proposal-v1", "base_revision": revision, "stream": "facts",
        "operation": "add", "requested_representation": "summary",
        "lineage": {"derived_from_retrieval": False, "refs": []},
        "record": {"id": "f-golden-probe", "text": "probe", "summary": "probe",
                   "verified_at": "2026-01-06T00:00:00Z"},
    }))
    material, authority = _cli(project, "plan-write", "--proposal", str(proposal),
                               "--emit-authority-template")
    out["cli.plan_write_authority_template"] = sha256_hex(material)
    (scratch / "authority.json").write_bytes(authority)
    plan = json.loads(_cli(project, "plan-write", "--proposal", str(proposal), "--authority",
                           str(scratch / "authority.json"))[1])
    out["policy_fingerprint"] = plan["decision"]["policy_fingerprint"]
    out.update(_export_digests(project, scratch / "bundle"))
    mcp_calls = [
        ("an_kla_status", {}),
        ("an_kla_verify", {}),
        ("an_kla_doctor", {}),
        ("an_kla_get_checkpoint", {}),
        ("an_kla_retrieve", {"query": "golden", "budget_bytes": 400}),
        ("an_kla_assemble_context", {"query": "golden", "budget_bytes": 800}),
        ("an_kla_view_context", {"revision": revision}),
    ]
    replies = _mcp(project, mcp_calls)
    out["mcp.initialize"] = sha256_hex(replies[0])
    out["mcp.tools_list"] = sha256_hex(replies[1])
    for (name, _), reply in zip(mcp_calls, replies[2:]):
        out[f"mcp.{name}"] = sha256_hex(reply)
    return out


def compute_fresh() -> dict[str, str]:
    """Extrae el store en un directorio temporal nuevo y calcula los goldens."""
    with tempfile.TemporaryDirectory(prefix="legacy-store-") as tmp:
        base = Path(tmp)
        project = base / "project"
        project.mkdir()
        (base / "scratch").mkdir()
        extract_store(project)
        return compute(project, base / "scratch")


if __name__ == "__main__":
    if sys.argv[1:] != ["--write"]:
        raise SystemExit("uso: legacy_store_goldens.py --write")
    digest_tar = sha256_hex(STORE_TAR.read_bytes())
    document = {"store_tar_sha256": digest_tar, "goldens": compute_fresh()}
    GOLDENS.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"escrito {GOLDENS} ({len(document['goldens'])} goldens)")
