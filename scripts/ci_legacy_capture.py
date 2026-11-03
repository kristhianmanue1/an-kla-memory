"""Declared observer of the unchanged legacy CI, for transition comparison only."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.ci_plan import PROBE
from scripts.ci_process import run_task
from scripts.ci_results import save, bootstrap_command

CLT = Path("/Library/Developer/CommandLineTools/usr/bin/python3")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output == ROOT or ROOT in output.parents:
        parser.error("output must be outside the source tree")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        parser.error("no baseline evidence overwrite")
    started = time.monotonic()
    deadline = started + 2000
    report = {"schema": "ankla-ci/legacy-capture-v1", "run_id": uuid.uuid4().hex,
              "status": "incomplete", "expected": [], "observer_files": {}, "tasks": []}
    env = dict(os.environ, AN_KLA_NO_UPDATE_CHECK="1")
    mode = {"CI": "true", "GITHUB_ACTIONS": "true"}

    def task(name, command, budget, task_env=env):
        directory = output / name
        result = run_task(command, cwd=ROOT, env=task_env, directory=directory,
                          deadline=deadline, timeout=budget)
        result["name"] = name
        report["tasks"].append(result)
        save(output / "legacy-run.json", report)
        if result["status"] != "ok":
            raise RuntimeError("legacy_capture_task_failed:" + name)
        return directory

    def signature(name):
        directory = task(name, [sys.executable, str(ROOT / "scripts/ci_plan.py")], 60)
        return json.loads((directory / "stdout.txt").read_text())["signature"]

    try:
        for key in ("ANKLA_MATRIX_ROW15_ACTIVE", "AN_KLA_CI_OBSERVER_DIR"):
            if env.get(key):
                raise RuntimeError("inherited_control:" + key)
        if env.get("AN_KLA_CI_LOCAL_MATRIX") == "0":
            raise RuntimeError("legacy_matrix_disabled")
        # Foreign matrix legs require a separately validated context inventory;
        # do not silently extend the diagnostic beyond its tested host setup.
        for version in ("3.9", "3.12", "3.13"):
            candidate = shutil.which("python" + version)
            if candidate and Path(candidate).resolve() != Path(sys.executable).resolve():
                raise RuntimeError("foreign_legacy_matrix_observer_not_supported:" + version)
        if not CLT.is_file():
            raise RuntimeError("legacy_crypto_profile_missing")
        for index, executable in enumerate((sys.executable, str(CLT))):
            directory = task("probe-" + str(index), [executable, "-c", PROBE], 15)
            runtime = json.loads((directory / "stdout.txt").read_text())
            if index == 1 and not runtime["crypto"]:
                raise RuntimeError("legacy_clt_does_not_have_crypto")
            collection_path = output / ("collection-" + str(index) + ".json")
            task("collect-" + str(index), [executable, str(ROOT / "scripts/ci_worker.py"),
                 "--collect-only", "--result", str(collection_path)], 30)
            collection = json.loads(collection_path.read_text())
            report["expected"].append(dict(runtime, version_info=runtime["version"],
                                            mode=mode, case_ids=sorted(collection["cases"])))
        observed_env = dict(env, AN_KLA_CI_OBSERVER_DIR=str(output),
                            AN_KLA_CI_OBSERVER_RUN_ID=report["run_id"])
        report["observer_context"] = "runpy bootstrap + Popen transport only for CI/unittest; original sitecustomize and PYTHONPATH preserved; no retroactive observation"
        report["input_signature"] = signature("signature-before")
        task("legacy-ci", bootstrap_command(sys.executable, [str(ROOT / "scripts/ci_local.py"), "--simulate-ci"]), 1800, observed_env)
        report["final_signature"] = signature("signature-after")
        for path in output.glob("*.json"):
            data = json.loads(path.read_text())
            if data.get("schema") == "ankla-ci/legacy-observer-v1":
                report["observer_files"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        report.update(status="ok", rc=0, cleanup="complete")
        save(output / "legacy-run.json", report)
        from scripts.ci_baseline import load_baseline
        load_baseline(output)  # Closed inventories and complete observations are mandatory.
    except (Exception, KeyboardInterrupt) as exc:
        report.update(status="incomplete", error=type(exc).__name__ + ": " + str(exc))
    report["duration_s"] = time.monotonic() - started
    save(output / "legacy-run.json", report)
    print(json.dumps({"status": report["status"], "output": str(output), "error": report.get("error")}), flush=True)
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
