"""Batería de escala del store — CLI.

Fase 0 (#149): `SCENARIOS` (columna gobernada, columna diagnóstica interna,
operaciones). Fase v2 (#167): `SCENARIOS_V2` (ingesta por CLI, concurrencia
4×8 con tasa de LockBusyError, término raro índice sí/no, crash mid-commit
en store grande, compactación a ~20k revisiones).

Uso (desde la raíz del repo, Python 3.12+):

    python -m benchmarks.scale.battery --scenario all
    python -m benchmarks.scale.battery --scenario all-v2
    python -m benchmarks.scale.battery --scenario ingest-governed --smoke

Umbrales normativos: `benchmarks/scale/thresholds-v2.json` (incluye las
secciones v1 verbatim), commiteado antes de cualquier corrida oficial. Los
abortos por umbral son resultados, no fallos: la batería termina `ok` si se
ejecutó y registró, aunque una celda aborte. El presupuesto total detiene el
lanzamiento de escenarios restantes.
"""
from __future__ import annotations

import argparse
import json
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
    "ingest-batch",
    "reads-diagnostic",
    "concurrency",
    "crash",
    "compaction",
)

SCENARIOS_V2 = (
    "ingest-cli",
    "concurrency-v2",
    "rare-query-index",
    "crash-mid-commit",
    "compaction-large",
)

SCENARIO_CHOICES = (*SCENARIOS, *SCENARIOS_V2, "all", "all-v2", "fingerprint")

SMOKE_OVERRIDES: dict[str, dict[str, Any]] = {
    "ingest-governed": {"n_target": 6, "read_points": [3, 6]},
    "ingest-batch": {"n_target": 6, "batch_size": 2},
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
    "ingest-cli": {"n_target": 4},
    "concurrency-v2": {
        "writers": 2,
        "readers": 2,
        "duration_s": 3,
        "preload_records": 40,
    },
    "rare-query-index": {"records": 250, "batch": 125, "rare_every": 50},
    "crash-mid-commit": {
        "attempts": 2,
        "preload_records": 30,
        "preload_batch": 30,
    },
    "compaction-large": {"target_revisions": 12, "probe_delay_s": 0.3},
}


def _run_one(
    name: str, ws: Path, th: dict[str, Any], overrides: dict[str, Any] | None
) -> dict[str, Any]:
    if name == "ingest-governed":
        from benchmarks.scale.scenarios_ingest import run_ingest_governed

        return run_ingest_governed(ws, th, overrides)
    if name == "ingest-batch":
        from benchmarks.scale.scenarios_ingest import run_ingest_batch

        return run_ingest_batch(ws, th, overrides)
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
    if name == "ingest-cli":
        from benchmarks.scale.scenarios_ingest_cli import run_ingest_cli

        return run_ingest_cli(ws, th, overrides)
    if name == "concurrency-v2":
        from benchmarks.scale.scenarios_concurrency import run_concurrency_v2

        return run_concurrency_v2(ws, th, overrides)
    if name == "rare-query-index":
        from benchmarks.scale.scenarios_concurrency import run_rare_query_index

        return run_rare_query_index(ws, th, overrides)
    if name == "crash-mid-commit":
        from benchmarks.scale.scenarios_durability import run_crash_mid_commit

        return run_crash_mid_commit(ws, th, overrides)
    if name == "compaction-large":
        from benchmarks.scale.scenarios_durability import run_compaction_large

        return run_compaction_large(ws, th, overrides)
    raise ValueError(f"escenario desconocido: {name}")


def _summary_md(
    results: dict[str, dict[str, Any]],
    env: dict[str, Any],
    thresholds_path: Path | None = None,
) -> str:
    th_name = (
        thresholds_path.name if thresholds_path is not None else "thresholds-v1.json"
    )
    try:
        thresholds_path.resolve().relative_to(REPO_ROOT)
        th_ref = f"`benchmarks/scale/{th_name}`"
    except (ValueError, OSError, TypeError):
        th_ref = f"copia externa `{th_name}` (exacta en `thresholds-used.json`)"
    lines = [
        "# Batería de escala — corrida",
        "",
        f"- Huella de entorno: Python `{env['python'].split()[0]}` sobre "
        f"`{env['platform']}` ({env['machine']}), SQLite {env['sqlite']}, "
        f"FTS5={env['fts5']}, git `{env['git_head'][:12]}`.",
        f"- Umbrales: {th_ref}. v1 aprobados por el maintainer (sesión "
        "2026-10-14); v2 (#167) pendientes de aprobación para corrida oficial.",
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
        elif name == "ingest-cli":
            abort = payload.get("abort")
            note = (
                f"abort {abort['abort_reason']}@{abort['at_n']}"
                if abort
                else f"n={payload.get('n_written')} por CLI público"
            )
        elif name == "concurrency-v2":
            totals = payload.get("totals", {})
            rate = totals.get("lock_busy_rate")
            note = (
                "tasa LockBusyError "
                + (f"{rate:.4f}" if isinstance(rate, (int, float)) else "n/d")
                + f", deadline {payload.get('params', {}).get('lock_deadline_s')} s"
            )
        elif name == "rare-query-index":
            phases = {
                p.get("phase"): p for p in payload.get("phases", [])
            }
            con = phases.get("con_indice", {})
            note = (
                f"índice sí/no: sin={phases.get('sin_indice', {}).get('rare_profile')} "
                f"con={con.get('rare_profile')}"
            )
        elif name == "crash-mid-commit":
            kills = payload.get("attempts", [])
            mid = sum(1 for k in kills if k.get("mid_commit_evidence"))
            note = (
                f"{len(kills)} kills, {mid} con evidencia mid-commit, "
                f"post-crash ok={payload.get('post_crash', {}).get('committed')}"
            )
        elif name == "compaction-large":
            timings = payload.get("timings_s", {})
            window = payload.get("unavailability_window_s")
            note = (
                f"revs={payload.get('params', {}).get('target_revisions')}, "
                f"commit {timings.get('compact_commit', 0):.1f} s, "
                + (
                    f"ventana {window:.1f} s"
                    if isinstance(window, (int, float))
                    else "ventana n/d"
                )
            )
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
    parser = argparse.ArgumentParser(
        description="Batería de escala (#149 Fase 0 + #167 v2)."
    )
    parser.add_argument("--scenario", default="all", choices=SCENARIO_CHOICES)
    parser.add_argument(
        "--thresholds",
        default=str(REPO_ROOT / "benchmarks/scale/thresholds-v2.json"),
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

    names: list[str]
    if args.scenario == "all":
        names = [*SCENARIOS, *SCENARIOS_V2]
    elif args.scenario == "all-v2":
        names = list(SCENARIOS_V2)
    else:
        names = [args.scenario]
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
        # Fusión con escenarios ya persistidos en el dir de salida: permite
        # re-corridas parciales sin fragmentar la corrida oficial.
        merged: dict[str, dict[str, Any]] = {}
        for existing in sorted(out.glob("*.json")):
            name = existing.stem
            if name in ("summary", "env", "thresholds-used"):
                continue
            try:
                merged[name] = json.loads(existing.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
        merged.update(results)
        write_result(out, "env", env)
        write_result(out, "summary", merged)
        shutil.copyfile(args.thresholds, out / "thresholds-used.json")
        (out / "battery-report.md").write_text(
            _summary_md(merged, env, Path(args.thresholds)), encoding="utf-8"
        )
        if ws_own:
            shutil.rmtree(ws, ignore_errors=True)
    print(f"resultados: {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
