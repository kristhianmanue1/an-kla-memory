"""Per-case unittest evidence, also usable by a declared legacy observer."""
from __future__ import annotations

import hashlib
import inspect
import importlib.metadata
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RETIRED = {
    "test_sealed_matrix.MatrixReRunTests.test_rerun_source_modules_this_interpreter",
    "test_sealed_matrix.MatrixReRunTests.test_rerun_crypto_rows_with_clt_python",
    "test_sealed_matrix_rows.Row15SuiteBothProfilesTests.test_full_suite_this_interpreter",
    "test_sealed_matrix_rows.Row15SuiteBothProfilesTests.test_full_suite_with_extra_clt_python",
    "test_sealed_matrix_rows.Row15SuiteBothProfilesTests.test_ci_local_both_modes",
    "test_sealed_matrix_rows.Row11V1BundlesUnchangedTests.test_v1_suite_reruns_in_this_interpreter",
}


def leaves(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from leaves(item)
        else:
            yield item


def identity(test):
    cls = type(test)
    filename = Path(inspect.getfile(cls)).resolve()
    relative = filename.relative_to(ROOT).as_posix()
    # Resolve source first: aliases are not stripped without checking ownership.
    module = relative[:-3].replace("/", ".")
    if relative.startswith("tests/"):
        module = module.removeprefix("tests.") if hasattr(str, "removeprefix") else module[6:]
    return module + "." + cls.__qualname__ + "." + test._testMethodName


def collect(suite):
    cases = {}
    sources = {}
    for test in leaves(suite):
        key = identity(test)
        if key in cases:
            raise ValueError("duplicate_case:" + key)
        path = Path(inspect.getfile(type(test))).resolve()
        sources[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        cases[key] = {"raw_id": test.id(), "status": "not_run", "subtests": []}
    if not cases:
        raise ValueError("empty_suite")
    return cases, sources


def result_class(base, cases, on_event=lambda event: None):
    class Recorded(base):
        def _set(self, test, status, detail=None):
            try:
                key = identity(test)
            except (TypeError, ValueError, AttributeError):
                # Class/module setup skips do not produce startTest for each leaf.
                match = re.fullmatch(r"setUp(Class|Module) \((.+)\)", test.id())
                keys = []
                if match:
                    scope = match.group(2)
                    for candidate, record in cases.items():
                        raw = record["raw_id"]
                        if raw.startswith(scope + "."):
                            keys.append(candidate)
                if not keys:
                    key = "fixture:" + test.id()
                    cases.setdefault(key, {"raw_id": test.id(), "subtests": []})
                    keys = [key]
            else:
                keys = [key]
            for key in keys:
                record = cases[key]
                if status != "success" or record["status"] == "running":
                    record["status"] = status
                    if detail is not None:
                        record["detail"] = str(detail)
            on_event({"type": "case", "cases": {key: cases[key] for key in keys}})

        def startTest(self, test):
            self._set(test, "running")
            super().startTest(test)

        def addSuccess(self, test):
            self._set(test, "success")
            super().addSuccess(test)

        def addSkip(self, test, reason):
            parent = test.test_case if isinstance(test, unittest.case._SubTest) else None
            if parent is not None:
                key = identity(parent)
                cases[key]["subtests"].append({"id": key + test.id()[len(parent.id()):],
                                               "status": "skip", "detail": str(reason)})
                self._set(parent, "subtest_skip", reason)
            else:
                self._set(test, "skip", reason)
            super().addSkip(test, reason)

        def addFailure(self, test, err):
            self._set(test, "failure", self._exc_info_to_string(err, test))
            super().addFailure(test, err)

        def addError(self, test, err):
            self._set(test, "error", self._exc_info_to_string(err, test))
            super().addError(test, err)

        def addExpectedFailure(self, test, err):
            self._set(test, "expected_failure")
            super().addExpectedFailure(test, err)

        def addUnexpectedSuccess(self, test):
            self._set(test, "unexpected_success")
            super().addUnexpectedSuccess(test)

        def addSubTest(self, test, subtest, err):
            cases[identity(test)]["subtests"].append({
                "id": identity(test) + subtest.id()[len(test.id()):], "status": "success" if err is None else "failure",
            })
            if err is not None:
                self._set(test, "failure", self._exc_info_to_string(err, test))
            super().addSubTest(test, subtest, err)
            on_event({"type": "subtest", "case": identity(test), "record": cases[identity(test)]})
    return Recorded


def save(path, payload):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def bootstrap_command(executable, arguments):
    code = ("import sys,runpy,json;sys.path.insert(0," + repr(str(ROOT)) + ");"
            "from scripts.ci_results import observe;observe();sys.path.pop(0);"
            "args=json.loads(" + repr(json.dumps(list(arguments))) + ");")
    if arguments[0] == "-m":
        code += "sys.argv=args[1:];runpy.run_module(args[1],run_name='__main__',alter_sys=True)"
    else:
        code += ("from pathlib import Path;sys.path[0]=str(Path(args[0]).resolve().parent);"
                 "sys.argv=args;runpy.run_path(args[0],run_name='__main__')")
    return [executable, "-c", code]


def observed_command(arguments, cwd=None):
    if not isinstance(arguments, (list, tuple)) or len(arguments) < 2:
        return arguments
    if len(arguments) >= 3 and list(arguments[1:3]) == ["-m", "unittest"]:
        return bootstrap_command(arguments[0], arguments[1:])
    if not isinstance(arguments[1], (str, os.PathLike)):
        return arguments
    path = Path(arguments[1])
    if not path.is_absolute():
        path = Path(cwd or Path.cwd()) / path
    if path.resolve() == ROOT / "scripts/ci_local.py":
        return bootstrap_command(arguments[0], arguments[1:])
    return arguments


def observe():
    """Optional diagnostic; never enabled by the new audit runner itself."""
    destination = os.environ.get("AN_KLA_CI_OBSERVER_DIR")
    if not destination:
        return
    if getattr(unittest.TextTestRunner.run, "_ankla_observer", False):
        return
    original = unittest.TextTestRunner.run
    original_init = subprocess.Popen.__init__
    def observed_init(process, args, *positional, **kwargs):
        original_init(process, observed_command(args, kwargs.get("cwd")), *positional, **kwargs)
    subprocess.Popen.__init__ = observed_init
    active = False

    def run(runner, suite):
        nonlocal active
        if active:
            return original(runner, suite)
        active = True
        previous = runner.resultclass
        try:
            try:
                cases, sources = collect(suite)
            except ValueError as exc:
                # Diagnostic mini-suites outside this checkout are not baseline evidence.
                if str(exc).startswith(("duplicate_case:", "empty_suite")):
                    raise
                return original(runner, suite)
            path = Path(destination) / (str(os.getpid()) + "-" + str(time.time_ns()) + ".json")
            payload = {"schema": "ankla-ci/legacy-observer-v1", "complete": False, "cases": cases, "sources": sources,
                       "run_id": os.environ.get("AN_KLA_CI_OBSERVER_RUN_ID"),
                       "executable": sys.executable, "prefix": sys.prefix,
                       "version": sys.version, "version_info": list(sys.version_info[:3]),
                       "real_executable": str(Path(sys.executable).resolve()), "pid": os.getpid(),
                       "crypto": importlib.util.find_spec("cryptography") is not None,
                       "crypto_version": (importlib.metadata.version("cryptography")
                                          if importlib.util.find_spec("cryptography") is not None else None),
                       "platform": sys.platform, "flags": str(sys.flags),
                       "startup_customization": getattr(sys.modules.get("sitecustomize"), "__file__", None),
                       "export": bool(getattr(os, "O_NOFOLLOW", None) and getattr(os, "O_DIRECTORY", None)
                                      and os.open in os.supports_dir_fd),
                       "mode": {k: os.environ.get(k) for k in ("CI", "GITHUB_ACTIONS")}}
            save(path, payload)
            with path.with_suffix(".events.jsonl").open("x", encoding="utf-8") as events:
                def append(event):
                    events.write(json.dumps(event) + "\n")
                    events.flush()
                runner.resultclass = result_class(previous, cases, append)
                started = time.monotonic()
                result = original(runner, suite)
            payload.update(complete=True, duration_s=time.monotonic() - started,
                           successful=result.wasSuccessful(), tests_run=result.testsRun)
            save(path, payload)
            return result
        finally:
            runner.resultclass = previous
            active = False
    run._ankla_observer = True
    unittest.TextTestRunner.run = run
