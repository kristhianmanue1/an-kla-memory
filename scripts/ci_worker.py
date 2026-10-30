"""Functional worker: no CI entrypoint and no nested discovery execution."""
from __future__ import annotations

import argparse
import json
import importlib.metadata
import importlib.util
import os
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.ci_results import RETIRED, collect, identity, leaves, result_class, save


def build_suite():
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    cases, sources = collect(suite)
    absent = RETIRED - cases.keys()
    if absent:
        raise ValueError("retired_orchestration_missing:" + repr(sorted(absent)))
    selected = unittest.TestSuite(test for test in leaves(suite) if identity(test) not in RETIRED)
    for key in RETIRED:
        del cases[key]
    return selected, cases, sources


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--collect-only", action="store_true")
    args = parser.parse_args()
    suite, cases, sources = build_suite()
    payload = {"schema": "ankla-ci/functional-evidence-v1", "complete": False,
               "cases": cases, "sources": sources, "executable": sys.executable,
               "prefix": sys.prefix, "version": sys.version,
               "version_info": list(sys.version_info[:3]),
               "real_executable": str(Path(sys.executable).resolve()),
               "mode": {k: os.environ.get(k) for k in ("CI", "GITHUB_ACTIONS")},
               "crypto": importlib.util.find_spec("cryptography") is not None,
               "crypto_version": (importlib.metadata.version("cryptography")
                                  if importlib.util.find_spec("cryptography") is not None else None),
               "platform": sys.platform, "flags": str(sys.flags),
               "export": bool(getattr(os, "O_NOFOLLOW", None) and getattr(os, "O_DIRECTORY", None)
                              and os.open in os.supports_dir_fd),
               "retired_orchestration": sorted(RETIRED)}
    save(args.result, payload)
    if args.collect_only:
        return 0
    started = time.monotonic()
    with args.result.with_suffix(".events.jsonl").open("x", encoding="utf-8") as events:
        def append(event):
            events.write(json.dumps(event) + "\n")
            events.flush()
        runner = unittest.TextTestRunner(verbosity=1, resultclass=result_class(unittest.TextTestResult, cases, append))
        result = runner.run(suite)
    payload.update(complete=True, successful=result.wasSuccessful(),
                   duration_s=time.monotonic() - started, tests_run=result.testsRun)
    save(args.result, payload)
    invalid = any(item["status"] not in ("success", "skip", "subtest_skip") for item in cases.values())
    return 0 if result.wasSuccessful() and not invalid else 1


if __name__ == "__main__":
    raise SystemExit(main())
