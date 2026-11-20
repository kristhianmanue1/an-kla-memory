"""A custodian adapter that is a real process (ADR-0071, acceptance 1 and 3): it answers what its scenario says or fails as it says.

    python custodian_adapter_fake.py --scenario <json> --log <file>

The scenario is ``{"mode": ..., ...}``: ``response`` (prints ``response``), ``exit_nonzero``, ``timeout`` (sleeps),
``bad_json``, ``bad_schema``, ``raw`` (prints ``raw`` as is), ``noisy_stderr`` (MiB on standard error, then ``response``), ``huge_stdout`` (more than the
8 MiB cap), ``grandchild`` (leaves a sleeping child in its process group and sleeps; its pid goes to ``pid_file``).
Every call writes to ``--log`` what it saw: its argv, its working directory, its environment and the request.
"""

import json
import os
import subprocess
import sys
import time


def main() -> int:
    args = sys.argv[1:]
    scenario = json.load(open(args[args.index("--scenario") + 1], encoding="utf-8"))
    request = json.loads(sys.stdin.read())
    with open(args[args.index("--log") + 1], "w", encoding="utf-8") as log:
        json.dump({"argv": sys.argv, "cwd": os.getcwd(), "env": dict(os.environ), "request": request}, log)
    mode = scenario["mode"]
    if mode == "exit_nonzero":
        sys.stderr.write("boom\n")
        return 3
    if mode == "timeout":
        time.sleep(60)
        return 0
    if mode == "raw":
        sys.stdout.write(scenario["raw"])
        return 0
    if mode == "bad_json":
        sys.stdout.write("esto no es JSON {")
        return 0
    if mode == "bad_schema":
        sys.stdout.write(json.dumps({"schema": "invalid", "error": "falló"}))
        return 0
    if mode == "huge_stdout":
        sys.stdout.write("x" * (9 * 1024 * 1024))
        return 0
    if mode == "grandchild":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdout=subprocess.DEVNULL)
        with open(scenario["pid_file"], "w", encoding="utf-8") as handle:
            handle.write(str(child.pid))
        time.sleep(60)
        return 0
    if mode == "noisy_stderr":
        chunk = "e" * 65536
        for _ in range(96):  # 6 MiB
            sys.stderr.write(chunk)
        sys.stderr.flush()
    sys.stdout.write(json.dumps(scenario["response"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
