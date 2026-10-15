"""Batería P0 de escala del store (issue #149, Fase 0) — CLI.

Uso (desde la raíz del repo, Python 3.12+):

    python -m benchmarks.scale.battery --scenario all
    python -m benchmarks.scale.battery --scenario ingest-governed --smoke

Umbrales normativos: `benchmarks/scale/thresholds-v1.json`, commiteado antes
de cualquier corrida oficial. Los abortos por umbral son resultados, no
fallos: la batería termina `ok` si se ejecutó y registró, aunque una celda
aborte. El presupuesto total detiene el lanzamiento de escenarios restantes.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from benchmarks.scale.core import (
    REPO_ROOT,
    env_fingerprint,
    load_thresholds,
    write_result,
)

SCENARIOS = (
    "ingest-governed",
    "reads-diagnostic",
    "concurrency",
    "crash",
    "compaction",
)

SMOKE_OVERRIDES: dict[str, dict[str, Any]] = {
    "ingest-governed": {"n_target": 6, "read_points": [3, 6]},
    "reads-diagnostic": {"records_points": [50], "batch": 25},
    "concurrency": {
        "writers": 2,
        "readers": 2,
        "duration_s": 3,
        "preload_records": 40,
    },
    "crash": {
        "attempts": 2,
        "preload_records": 10,
        "kill_delay_min_s": 0.3,
        "kill_delay_max_s": 0.6,
    },
    "compaction": {"target_revisions": 12},
}


def _run_one(
    name: str, ws: Path, th: dict[str, Any], overrides: dict[str, Any] | None
) -> dict[str, Any]:
    if name == "ingest-governed":
        from benchmarks.scale.scenarios_ingest import run_ingest_governed

        return run_ingest_governed(ws, th, overrides)
    if name == "reads-diagnostic":
        from benchmarks.scale.scenarios_diagnostic import run_reads_diagnostic

        return run_reads_diagnostic(ws, th, overrides)
    if name == "concurrency":
        from benchmarks.scale.scenarios_ops import run_concurrency

        return run_concurrency(ws, th, overrides)
    if name == "crash":
        from benchmarks.scale.scenarios_ops import run_crash

        return run_crash(ws, th, overrides)
    if name == "compaction":
        from benchmarks.scale.scenarios_ops import run_compaction

        return run_compaction(ws, th, overrides)
    raise ValueError(f"escenario desconocido: {name}")


def _summary_md(
    results: dict[str, dict[str, Any]], env: dict[str, Any]
) -> str:
    lines = [
        "# Batería P0 de escala — corrida (issue #149)",
        "",
        f"- Huella de entorno: Python `{env['python'].split()[0]}` sobre "
        f"`{env['platform']}` ({env['machine']}), SQLite {env['sqlite']}, "
        f"FTS5={env['fts5']}, git `{env['git_head'][:12]}`.",
        "- Umbrales: `benchmarks/scale/thresholds-v1.json` (aprobados por el "
        "maintainer antes de correr; copia exacta en `thresholds-used.json`).",
        "",
        "| Escenario | ok | wall s | Nota |",
        "|---|---|---:|---|",
    ]
    for name, payload in results.items():
        note = ""
        if name == "ingest-governed":
            aborts = [
                f"{c['scenario']}: {c['abort']['abort_reason']}@{c['abort']['at_n']}"
                for c in payload.get("cells", [])
                if c.get("abort")
            ]
            note = "; ".join(aborts) or "sin abortos"
        elif name == "reads-diagnostic":
            note = "columna interna (commit), etiquetada"
        lines.append(
            f"| {name} | {payload.get('ok')} | "
            f"{float(payload.get('wall_s', 0) or 0):.1f} | {note} |"
        )
    lines += [
        "",
        "Los abortos por umbral son resultados falsables, no fallos de la",
        "batería. Los números absolutos dependen de la máquina: la forma de",
        "la curva es el hallazgo (frontera de confianza del informe origen).",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Batería P0 de escala (#149).")
    parser.add_argument(
        "--scenario", default="all", choices=[*SCENARIOS, "all", "fingerprint"]
    )
    parser.add_argument(
        "--thresholds",
        default=str(REPO_ROOT / "benchmarks/scale/thresholds-v1.json"),
    )
    parser.add_argument(
        "--workspace", default=None, help="dir de trabajo (temporal si se omite)"
    )
    parser.add_argument(
        "--out",
        default=None,
        help="dir de resultados (bajo benchmarks/scale/results/ si se omite "
        "en corrida oficial; temporal con --smoke)",
    )
    parser.add_argument(
        "--smoke", action="store_true", help="escala diminuta para tests"
    )
    args = parser.parse_args(argv)

    th = load_thresholds(Path(args.thresholds))
    env = env_fingerprint()
    if args.scenario == "fingerprint":
        print(env)
        return 0

    ws_own = args.workspace is None
    if ws_own:
        ws = Path(tempfile.mkdtemp(prefix="ankla-p0-"))
    else:
        ws = Path(args.workspace)
    if args.out:
        out = Path(args.out)
    elif args.smoke:
        out = Path(tempfile.mkdtemp(prefix="ankla-p0-out-"))
    else:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out = REPO_ROOT / "benchmarks/scale/results" / stamp
    out.mkdir(parents=True, exist_ok=True)

    names = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    results: dict[str, dict[str, Any]] = {}
    t_all = time.perf_counter()
    budget = th["battery"]["total_budget_wall_s"]
    failed = False
    try:
        for name in names:
            if time.perf_counter() - t_all > budget:
                results[name] = {"ok": False, "skipped": "total_budget_exceeded"}
                write_result(out, name, results[name])
                continue
            overrides = SMOKE_OVERRIDES.get(name) if args.smoke else None
            try:
                print(f"==> {name}", flush=True)
                results[name] = _run_one(name, ws, th, overrides)
            except Exception as exc:  # se registra, no se silencia
                failed = True
                results[name] = {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            # Persistencia inmediata: la muerte del padre no pierde lo corrido.
            write_result(out, name, results[name])
    finally:
        write_result(out, "env", env)
        write_result(out, "summary", results)
        shutil.copyfile(args.thresholds, out / "thresholds-used.json")
        (out / "battery-report.md").write_text(
            _summary_md(results, env), encoding="utf-8"
        )
        if ws_own:
            shutil.rmtree(ws, ignore_errors=True)
    print(f"resultados: {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
