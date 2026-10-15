"""Núcleo compartido de la batería P0 de escala (issue #149, Fase 0).

Sólo medición: no muta stores reales. Todos los stores viven en el workspace
efímero que la batería crea por corrida.
"""
from __future__ import annotations

import json
import os
import platform
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from an_kla.canonical import digest_json
from an_kla.store import MemoryStore

TEXT = "registro {i} sobre quetzal y memoria de trabajo del agente"
RARE_TERM = "xochimilco-xenicus-ferrovial"
DIGEST_B = "sha256:" + "b" * 64
REPO_ROOT = Path(__file__).resolve().parents[2]


def fts5_available() -> bool:
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE probe USING fts5(x)")
        conn.close()
        return True
    except Exception:
        return False


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT),
            capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() if out.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def env_fingerprint() -> dict[str, Any]:
    import an_kla

    return {
        "schema": "an-kla/scale-battery-env/v1",
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": sys.version,
        "interpreter": sys.executable,
        "machine": platform.machine(),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "sqlite": sqlite3.sqlite_version,
        "fts5": fts5_available(),
        "an_kla_version": getattr(an_kla, "__version__", None),
        "git_head": _git_sha(),
    }


def load_thresholds(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "an-kla/scale-battery-thresholds/v1":
        raise ValueError(f"umbrales con schema inesperado: {data.get('schema')}")
    return data


def make_store(ws: Path) -> tuple[MemoryStore, str]:
    store = MemoryStore(str(ws))
    return store, store.initialize()


def subject_refs(store: MemoryStore, count: int) -> list[str]:
    """Refs de sujeto válidas para el store (patrón de la sonda del #149)."""
    from an_kla.subject_ref import derive_namespace

    # store.root apunta a .an-kla/memory; la identidad vive un nivel arriba.
    ident = (Path(store.root).parent / "project-identity.json").read_bytes()
    ns = derive_namespace(ident)
    return [f"an-kla:subject:v1:service:{ns}:s{k}" for k in range(count)]


def build_proposal(
    base: str,
    record: dict[str, Any],
    *,
    operation: str = "add",
    supersedes: str | None = None,
) -> dict[str, Any]:
    proposal: dict[str, Any] = {
        "schema": "an-kla/write-proposal-v1",
        "base_revision": base,
        "stream": "facts",
        "operation": operation,
        "requested_representation": "summary",
        "record": record,
        "lineage": {"derived_from_retrieval": False, "refs": []},
    }
    if supersedes is not None:
        proposal["supersedes"] = supersedes
    return proposal


def build_authority(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "an-kla/write-authority-v1",
        "proposal_sha256": digest_json(candidate),
        "base_revision": candidate["base_revision"],
        "authority_class": "model_derived",
        "issuer": {
            "kind": "model",
            "id": "scale-battery-p0",
            "configuration_fingerprint": DIGEST_B,
        },
        "evidence": [],
        "scope": {
            "streams": [candidate["stream"]],
            "representations": [candidate["requested_representation"]],
            "operations": [candidate["operation"]],
        },
    }


def governed_write(
    store: MemoryStore,
    cur: str,
    record: dict[str, Any],
    *,
    operation: str = "add",
    supersedes: str | None = None,
) -> tuple[str, float, str]:
    """Una escritura por la vía gobernada pública; devuelve (rev, s, decisión)."""
    proposal = build_proposal(cur, record, operation=operation, supersedes=supersedes)
    authority = build_authority(proposal)
    t0 = time.perf_counter()
    planning = store.plan_write(proposal, authority)
    result = store.commit_write_plan(
        expected_current_hash=cur,
        proposal=proposal,
        authority=authority,
        decision=planning["decision"],
        plan=planning["plan"],
    )
    elapsed = time.perf_counter() - t0
    if not result.get("committed"):
        raise RuntimeError(f"commit no aplicado: {result}")
    return result["revision"], elapsed, planning["decision"]["decision"]


def internal_commit(
    store: MemoryStore, cur: str, facts: list[dict[str, Any]]
) -> str:
    return store.commit(expected_current_hash=cur, checkpoint_patch={}, facts=facts)


def timed(fn: Callable[[], Any], n: int = 1) -> float:
    best = float("inf")
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t0)
    return best


def stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    ordered = sorted(values)

    def pct(p: float) -> float:
        idx = min(len(ordered) - 1, int(round(p * (len(ordered) - 1))))
        return ordered[idx]

    return {
        "count": len(ordered),
        "min": ordered[0],
        "p50": pct(0.5),
        "p95": pct(0.95),
        "max": ordered[-1],
        "mean": sum(ordered) / len(ordered),
    }


def dir_size_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in Path(path).rglob("*") if p.is_file())


def cli(ws: Path, *args: str, timeout: int = 900) -> dict[str, Any]:
    """CLI público sobre el store del workspace; JSON de stdout o error."""
    cmd = [sys.executable, "-m", "an_kla", "--project-root", str(ws), *args]
    out = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "AN_KLA_NO_UPDATE_CHECK": "1"},
    )
    if out.returncode != 0:
        return {
            "ok": False,
            "returncode": out.returncode,
            "stderr_tail": out.stderr[-800:],
        }
    try:
        parsed = json.loads(out.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "returncode": 0, "stdout_tail": out.stdout[-800:]}
    if isinstance(parsed, dict):
        parsed.setdefault("ok", True)
    return parsed


def write_result(out_dir: Path, name: str, payload: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{name}.json"
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return target


def disk_guard(ws: Path, ceiling_bytes: int) -> dict[str, Any] | None:
    used = dir_size_bytes(ws)
    if used > ceiling_bytes:
        return {
            "abort_reason": "disk_ceiling",
            "store_bytes": used,
            "ceiling_bytes": ceiling_bytes,
        }
    return None
