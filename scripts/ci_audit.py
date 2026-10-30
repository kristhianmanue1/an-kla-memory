"""Opt-in CI audit/development profiles. Does not replace ci_local.py yet."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.ci_baseline import compare_worker, coverage_gaps, load_baseline
from scripts.ci_plan import PROBE, make_plan, verify_worker
from scripts.ci_process import run_task
from scripts.ci_results import save


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("development", "audit"), default="audit")
    parser.add_argument("--principal", default=sys.executable)
    parser.add_argument("--plain-python")
    parser.add_argument("--sealed-python")
    parser.add_argument("--baseline", type=Path, help="Observed legacy evidence; enables transition comparison")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--budget", type=float, default=7200)
    parser.add_argument("--suite-timeout", type=float, default=900)
    args = parser.parse_args(argv)
    output = args.output or Path(tempfile.mkdtemp(prefix="ankla-ci-audit-"))
    output = output.resolve()
    if output == ROOT or ROOT in output.parents:
        parser.error("evidence must live outside the checked input tree")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        parser.error("output directory must be empty; no evidence overwrite")
    if args.budget <= 5 or args.suite_timeout <= 5:
        parser.error("budgets must include execution and cleanup")
    started = time.monotonic()
    deadline = started + args.budget
    report = {"schema": "ankla-ci/audit-v1", "profile": args.profile,
              "active_publication_gate": False, "complete": False, "tasks": [],
              "cells": [], "errors": [], "compatibility": {}, "budget_s": args.budget,
              "suite_timeout_s": args.suite_timeout, "transition_verified": False}
    path = output / "summary.json"
    env = dict(os.environ, AN_KLA_NO_UPDATE_CHECK="1")
    caller_mode = {k: env.get(k) for k in ("CI", "GITHUB_ACTIONS")}

    def persist():
        report["duration_s"] = time.monotonic() - started
        save(path, report)

    def task(name, command, limit, task_env=None):
        if report["errors"] or time.monotonic() >= deadline - 5:
            report["tasks"].append({"name": name, "status": "not_started"})
            raise RuntimeError("task_not_started:" + name)
        directory = output / (str(len(report["tasks"])) + "-" + name)
        result = run_task(command, cwd=ROOT, env=task_env or env, directory=directory,
                          deadline=deadline, timeout=limit)
        result.update(name=name, directory=str(directory))
        report["tasks"].append(result)
        persist()
        print(name + ": " + result["status"], flush=True)
        if result["status"] != "ok":
            raise RuntimeError("task_failed:" + name)
        return directory

    def probe(executable, name):
        directory = task("probe-" + name, [executable, "-c", PROBE], 15)
        runtime = json.loads((directory / "stdout.txt").read_text())
        runtime["launch"] = executable
        return runtime

    def signature(name):
        directory = task(name, [args.principal, str(ROOT / "scripts/ci_plan.py")], 60)
        return json.loads((directory / "stdout.txt").read_text())["signature"]

    persist()
    try:
        if os.name != "posix":
            raise RuntimeError("unsupported_process_containment: only POSIX verified")
        for escape in ("ANKLA_MATRIX_ROW15_ACTIVE", "AN_KLA_CI_LOCAL_MATRIX", "AN_KLA_CI_OBSERVER_DIR"):
            if (escape == "AN_KLA_CI_LOCAL_MATRIX" and env.get(escape) == "0") or (
                escape != "AN_KLA_CI_LOCAL_MATRIX" and env.get(escape)):
                raise RuntimeError("inherited_control_rejected:" + escape)
        principal = probe(args.principal, "principal")
        development = args.profile == "development"
        plain = principal if not args.plain_python else probe(args.plain_python, "plain")
        if development:
            sealed = principal
            baseline = []
        else:
            sealed_path = args.sealed_python or (args.principal if principal["crypto"] else None)
            if not sealed_path:
                raise RuntimeError("existing_sealed_python_required")
            sealed = principal if sealed_path == args.principal else probe(sealed_path, "sealed")
            baseline = load_baseline(args.baseline) if args.baseline else []
        compatibility = []
        if not development:
            for version in ("3.9", "3.12", "3.13"):
                candidate = shutil.which("python" + version)
                if not candidate:
                    report["compatibility"][version] = "optional_skip: unavailable in PATH"
                elif Path(candidate).resolve() == Path(args.principal).resolve():
                    # Legacy resolution covered this version via the principal. Do not claim venv equality.
                    report["compatibility"][version] = "version covered by principal; alternate prefix unproved"
                else:
                    compatibility.append(probe(candidate, "compat-" + version))
                    report["compatibility"][version] = "planned"
        cells = make_plan(principal, plain, sealed, compatibility, caller_mode, development)
        report["plan"] = cells
        before = signature("signature-before")
        report["input_signature"] = before
        if baseline and any(record["input_signature"] != before for record in baseline):
            raise RuntimeError("baseline_tree_does_not_match")
        for gate in ("check_sizes.py", "check_plans.py", "check_adr_registry.py"):
            task(gate, [args.principal, str(ROOT / "scripts" / gate)], 60)
        # Preserve mode variants until their equivalence has actually been established.
        for index, cell in enumerate(cells):
            runtime = cell["runtime"]
            gate_env = dict(env)
            for key, value in cell["mode"].items():
                gate_env.pop(key, None)
                if value is not None:
                    gate_env[key] = value
            task("import-" + str(index), [runtime["launch"], "-c",
                 "import an_kla; from pathlib import Path; assert Path(an_kla.__file__).resolve()==Path('an_kla/__init__.py').resolve()"], 15, gate_env)
            if not development:
                task("g3-" + str(index), [runtime["launch"], str(ROOT / "scripts/redteam_consistent_rewrite.py"), "--selftest"], 180, gate_env)
        policy = json.loads((ROOT / "scripts/ci_obligations.json").read_text())
        worker_reports = []
        for index, cell in enumerate(cells):
            cell_env = dict(env)
            for key, value in cell["mode"].items():
                cell_env.pop(key, None)
                if value is not None:
                    cell_env[key] = value
            result_path = output / ("cell-" + str(index) + ".json")
            directory = task("suite-" + str(index), [cell["runtime"]["launch"],
                             str(ROOT / "scripts/ci_worker.py"), "--result", str(result_path)],
                             args.suite_timeout, cell_env)
            observed = json.loads(result_path.read_text())
            failures = verify_worker(observed, cell["runtime"], policy["rows"], policy.get("conditional_subtest_skips", []))
            if observed["mode"] != cell["mode"] or any(
                observed[key] != cell["runtime"][key]
                for key in ("prefix", "real_executable", "crypto", "crypto_version", "platform", "flags", "export")
            ) or observed["version_info"] != cell["runtime"]["version"]:
                failures.append("worker_environment_mismatch")
            if baseline:
                failures.extend(compare_worker(observed, baseline))
                save(result_path, observed)
            report["cells"].append({"result": str(result_path), "failures": failures,
                                    "roles": cell["roles"], "duration_s": observed["duration_s"]})
            worker_reports.append(observed)
            if failures:
                raise RuntimeError("unproved_cell:" + str(index))
            persist()
        if baseline:
            gaps = coverage_gaps(worker_reports, baseline)
            if gaps:
                raise RuntimeError("lost_baseline_dimensions:" + repr(gaps))
        after = signature("signature-after")
        if before != after:
            raise RuntimeError("input_tree_changed")
        report["transition_verified"] = bool(baseline) and not development
        report["complete"] = True
    except (Exception, KeyboardInterrupt) as exc:
        report["errors"].append(type(exc).__name__ + ": " + str(exc))
    finally:
        for index, cell in enumerate(report.get("plan", [])):
            if index >= len(report["cells"]):
                started_cell = any(task.get("name") == "suite-" + str(index) for task in report["tasks"])
                report["cells"].append({"roles": cell["roles"],
                                        "status": "not_completed" if started_cell else "not_started"})
        persist()
        print("evidence: " + str(output), flush=True)
    return 0 if report["complete"] and not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
