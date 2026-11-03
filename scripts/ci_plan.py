"""Pure audit planning and bounded-probe payloads (ADR-0062)."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = """
import importlib.util, json, os, sys
crypto = importlib.util.find_spec('cryptography')
crypto_version = None
if crypto is not None:
    import cryptography
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    AESGCM.generate_key(bit_length=128)
    crypto_version = cryptography.__version__
print(json.dumps({'executable':sys.executable,'real_executable':os.path.realpath(sys.executable),'prefix':sys.prefix,
 'version':list(sys.version_info[:3]), 'crypto':crypto is not None,
 'crypto_version':crypto_version, 'platform':sys.platform,
 'flags':str(sys.flags), 'export':bool(getattr(os,'O_NOFOLLOW',None)
 and getattr(os,'O_DIRECTORY',None) and os.open in os.supports_dir_fd)}))
"""


def environment_key(runtime):
    # Keep launch identity and venv prefix: realpath alone merges distinct venvs.
    return tuple(runtime[k] if not isinstance(runtime[k], list) else tuple(runtime[k])
                 for k in ("real_executable", "prefix", "version", "crypto_version", "platform", "flags"))


def make_plan(principal, plain, sealed, compatibility, caller_mode, development=False):
    version = principal["version"]
    if not (version[0] == 3 and 12 <= version[1] < 14):
        raise ValueError("principal_requires_supported_python_312_plus")
    wanted = [(principal, caller_mode, "development")] if development else [
        (plain, {"CI": None, "GITHUB_ACTIONS": None}, "plain-normal"),
        (plain, {"CI": "true", "GITHUB_ACTIONS": "true"}, "plain-simulated"),
        (sealed, {"CI": None, "GITHUB_ACTIONS": None}, "sealed-normal"),
        (sealed, {"CI": "true", "GITHUB_ACTIONS": "true"}, "sealed-simulated"),
    ]
    if not development:
        if plain["crypto"] or not sealed["crypto"] or plain["version"][:2] < [3, 12]:
            raise ValueError("required_dependency_profile_missing")
        wanted.extend((runtime, caller_mode, "compatibility") for runtime in compatibility)
    cells = []
    seen = set()
    for runtime, mode, role in wanted:
        if runtime["version"][0] != 3 or not 9 <= runtime["version"][1] < 14:
            raise ValueError("unsupported_worker_python")
        key = (environment_key(runtime), tuple(sorted(mode.items())))
        if key in seen:
            next(c for c in cells if c["key"] == repr(key))["roles"].append(role)
            continue
        seen.add(key)
        cells.append({"key": repr(key), "runtime": runtime, "mode": mode, "roles": [role]})
    return cells


def signature():
    """Conservative superset of gate inputs, including untracked paths/directories."""
    skipped = {".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
    digest = hashlib.sha256()
    for directory, dirs, files in os.walk(ROOT, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in skipped)
        relative = Path(directory).relative_to(ROOT).as_posix()
        digest.update(("dir:" + relative + "\0").encode())
        for name in sorted(files):
            if name.endswith((".pyc", ".pyo")):
                continue
            path = Path(directory) / name
            digest.update((path.relative_to(ROOT).as_posix() + "\0").encode())
            if path.is_symlink():
                digest.update(("link:" + os.readlink(path)).encode())
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def verify_worker(report, runtime, policy, conditional_subtest_skips=()):
    failures = []
    if not report.get("complete") or not report.get("successful"):
        failures.append("incomplete_or_unsuccessful_suite")
    cases = report.get("cases", {})
    if not cases:
        failures.append("empty_suite")
    for key, item in cases.items():
        allowed_partial = False
        for rule in conditional_subtest_skips:
            if rule["id"] == key and rule["when"] == "crypto" and runtime["crypto"]:
                expected = {key + suffix for suffix in rule["subtest_suffixes"]}
                actual = item.get("subtests", [])
                allowed_partial = (item["status"] == "subtest_skip" and len(actual) == len(expected)
                    and {sub["id"] for sub in actual} == expected
                    and all(sub["status"] == "skip" and sub.get("detail") == rule["reason"] for sub in actual))
        if item["status"] not in ("success", "skip") and not allowed_partial:
            failures.append("invalid_case_result:" + key)
        if not allowed_partial and any(sub["status"] != "success" for sub in item.get("subtests", [])):
            failures.append("subtest_not_successful:" + key)
    for row in policy:
        for obligation in row["cases"]:
            predicate = obligation["when"]
            applies = {"always": True, "crypto": runtime["crypto"], "plain": not runtime["crypto"],
                       "export": runtime["export"], "crypto_export": runtime["crypto"] and runtime["export"]}[predicate]
            key = obligation["id"]
            if key not in cases:
                failures.append("missing_obligation:" + row["row"] + ":" + key)
            elif applies and cases[key]["status"] != "success":
                failures.append("unproved_obligation:" + row["row"] + ":" + key)
    return failures


if __name__ == "__main__":
    print(json.dumps({"signature": signature()}))
