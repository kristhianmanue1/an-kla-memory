"""Cooperative test-fixture ownership, without changing product argv/env or Popen."""
from __future__ import annotations

import ast
import json
import os
import re
import secrets
import signal
import subprocess
import time
from pathlib import Path

_REFERENCES = {}


def register_script(path, testcase=None, member_token=None):
    directory = os.environ.get("AN_KLA_CI_SPAWN_REGISTRY")
    if not directory:
        return path
    path = Path(path).absolute()
    source_root = Path(__file__).resolve().parents[1]
    if path == source_root or source_root in path.parents:
        raise ValueError("fixture instrumentation must not modify the source tree")
    registry = Path(directory)
    intents = registry / "intents"
    intents.mkdir(mode=0o700, exist_ok=True)
    processes = registry / "processes"
    processes.mkdir(mode=0o700, exist_ok=True)
    token = secrets.token_hex(20)
    intent = intents / (token + ".json")
    intent.write_text(json.dumps({"script": str(path), "token": token, "member_token": member_token}))
    source = path.read_text()
    tree = ast.parse(source)
    insertion = 0
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            insertion = node.end_lineno
        elif isinstance(node, ast.ImportFrom) and node.module == "__future__":
            insertion = node.end_lineno
        else:
            break
    prelude = f'''
def __ankla_ci_register_fixture__():
    import json, os, pathlib
    registry = pathlib.Path({str(registry)!r})
    if (registry / 'closed').exists() or (registry / {token + '.closed'!r}).exists():
        raise SystemExit(99)
    record = registry / 'processes' / ({token!r} + '-' + str(os.getpid()) + '.json')
    temporary = record.with_suffix('.tmp')
    temporary.write_text(json.dumps({{'pid':os.getpid(), 'pgid':os.getpgrp(),
        'script':{str(path)!r}, 'token':{token!r}}}))
    temporary.replace(record)
    if (registry / 'closed').exists() or (registry / {token + '.closed'!r}).exists():
        raise SystemExit(99)
__ankla_ci_register_fixture__()
del __ankla_ci_register_fixture__
'''
    lines = source.splitlines(keepends=True)
    lines[insertion:insertion] = [prelude]
    path.write_text("".join(lines))
    if testcase is not None:
        def cleanup():
            pending = cleanup_scripts(registry, time.monotonic() + 2, token)
            testcase.assertEqual(pending, [], "fixture cleanup incomplete")
        testcase.addCleanup(cleanup)
    return path


def reference_adapter_path(source):
    directory = os.environ.get("AN_KLA_CI_SPAWN_REGISTRY")
    if not directory:
        return source
    key = (directory, str(source))
    if key not in _REFERENCES:
        destination = Path(directory) / ("reference-" + secrets.token_hex(10) + ".py")
        destination.write_bytes(Path(source).read_bytes())
        _REFERENCES[key] = register_script(destination)
    return _REFERENCES[key]


def cleanup_scripts(registry, deadline, only_token=None, observed_live=None):
    registry = Path(registry)
    pending = []
    intents = list((registry / "intents").glob("*.json"))
    for intent in intents:
        if time.monotonic() >= deadline:
            return pending + ["fixture_registry_scan_incomplete"]
        info = json.loads(intent.read_text())
        token, script = info["token"], info["script"]
        if not re.fullmatch(r"[0-9a-f]{40}", token) or intent.name != token + ".json" or not Path(script).is_absolute():
            raise ValueError("invalid_fixture_intent")
        if info.get("member_token") is not None and not re.fullmatch(r"[0-9a-f]{40}", info["member_token"]):
            raise ValueError("invalid_fixture_member_token")
        if only_token and token != only_token:
            continue
        (registry / (token + ".closed")).touch()
        records = list((registry / "processes").glob(token + "-*.json"))
        owners = [json.loads(record.read_text()) for record in records]
        if any(not isinstance(owner.get("pid"), int) or owner["pid"] <= 1 or
               not isinstance(owner.get("pgid"), int) or owner["pgid"] <= 1 or
               owner.get("script") != script or owner.get("token") != token for owner in owners):
            raise ValueError("invalid_fixture_owner")
        # Intents precede Popen: find a process even before its Python prelude runs.
        probe = subprocess.run(["pgrep", "-f", re.escape(script)], capture_output=True,
                               text=True, timeout=max(.001, min(.25, deadline - time.monotonic())))
        if probe.returncode not in (0, 1):
            pending.append(token)
            continue
        for line in probe.stdout.splitlines():
            pid = int(line)
            if pid != os.getpid() and all(owner["pid"] != pid for owner in owners):
                try:
                    group = os.getpgid(pid)
                except ProcessLookupError:
                    continue
                owners.append({"pid": pid, "pgid": group, "script": script, "token": token})
        for owner in owners:
            if time.monotonic() >= deadline:
                return pending + [token]
            pid, group = owner["pid"], owner["pgid"]
            command = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True,
                                     text=True, timeout=max(.001, min(.25, deadline - time.monotonic())))
            if command.returncode == 0 and not re.search(r"(?:^| )" + re.escape(script) + r"(?: |$)", command.stdout):
                pending.append(token)  # Reused PID or an unverifiable argument: never signal it.
                continue
            if command.returncode not in (0, 1):
                pending.append(token)
                continue
            # A recorded private-fixture group can retain children after its leader exits.
            target = -group if group == pid else pid
            try:
                os.kill(target, 0)
            except ProcessLookupError:
                continue
            if command.returncode == 1:
                member_token = info.get("member_token")
                if not member_token:
                    pending.append(token)
                    continue
                members = subprocess.run(["pgrep", "-f", member_token], capture_output=True, text=True,
                                         timeout=max(.001, min(.25, deadline - time.monotonic())))
                owned_member = False
                for candidate in members.stdout.splitlines():
                    try:
                        if int(candidate) != os.getpid() and os.getpgid(int(candidate)) == group:
                            owned_member = True
                    except ProcessLookupError:
                        continue
                if not owned_member:
                    pending.append(token)
                    continue
            if observed_live is not None:
                observed_live.append(pid)
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.kill(target, sig)
                except ProcessLookupError:
                    break
                if sig == signal.SIGTERM:
                    time.sleep(min(.01, max(0, deadline - time.monotonic())))
            while time.monotonic() < deadline:
                try:
                    os.kill(target, 0)
                except ProcessLookupError:
                    break
                time.sleep(.01)
            else:
                pending.append(token)
        if token not in pending:
            intent.unlink(missing_ok=True)
            for record in records:
                record.unlink(missing_ok=True)
    return pending
