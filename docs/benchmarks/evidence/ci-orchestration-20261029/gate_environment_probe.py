"""Compare structural gates across two CI environments, with positive control."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
GATES = ("check_sizes.py", "check_plans.py", "check_adr_registry.py")


def probe() -> dict:
    observations = {}
    for mode in ("normal", "simulated"):
        env = dict(os.environ)
        for name in ("CI", "GITHUB_ACTIONS"):
            env.pop(name, None)
            if mode == "simulated":
                env[name] = "true"
        control = subprocess.run(
            [sys.executable, "-c", "import json,os; print(json.dumps({"
             "k:os.environ.get(k) for k in ('CI','GITHUB_ACTIONS')}))"],
            env=env, capture_output=True, text=True, timeout=20, check=True,
        )
        observations[mode] = {
            "control_child_environment": json.loads(control.stdout), "gates": {},
        }
        for gate in GATES:
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / gate)], cwd=ROOT,
                env=env, capture_output=True, text=True, timeout=20,
            )
            observations[mode]["gates"][gate] = {
                "rc": result.returncode, "stdout": result.stdout,
                "stderr": result.stderr,
            }
    assert observations["normal"]["control_child_environment"] == {
        "CI": None, "GITHUB_ACTIONS": None,
    }
    assert observations["simulated"]["control_child_environment"] == {
        "CI": "true", "GITHUB_ACTIONS": "true",
    }
    return {
        "python_version": sys.version, "executable": sys.executable,
        "scope": "same local tree/interpreter; CI/GITHUB_ACTIONS only",
        "observations": observations,
        "equal_gate_results": observations["normal"]["gates"]
        == observations["simulated"]["gates"],
    }


if __name__ == "__main__":
    result = probe()
    Path(__file__).with_name("gate-environment-probe.json").write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    )
    print("equal_gate_results:", result["equal_gate_results"])
    if not result["equal_gate_results"]:
        raise SystemExit(1)
