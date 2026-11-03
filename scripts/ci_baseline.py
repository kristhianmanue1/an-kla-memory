"""Compare retained functional cases with observed legacy executions."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path

from scripts.ci_results import RETIRED


def load_baseline(directory):
    directory = Path(directory)
    manifest = json.loads((directory / "legacy-run.json").read_text())
    if manifest.get("schema") != "ankla-ci/legacy-capture-v1" or not manifest.get("run_id"):
        raise ValueError("closed_legacy_manifest_required")
    if manifest.get("status") != "ok" or manifest.get("rc") != 0 or manifest.get("cleanup") != "complete":
        raise ValueError("legacy_gate_not_complete")
    if not manifest.get("expected") or not manifest.get("observer_files") or not manifest.get("input_signature"):
        raise ValueError("legacy_inventory_missing")
    if manifest["input_signature"] != manifest.get("final_signature"):
        raise ValueError("legacy_tree_changed")
    from scripts.ci_worker import build_suite
    _, current_cases, _ = build_suite()
    if any(set(expected.get("case_ids", [])) != set(current_cases) for expected in manifest["expected"]):
        raise ValueError("legacy_inventory_does_not_match_functional_collection")
    records = []
    for name, digest in manifest["observer_files"].items():
        path = directory / name
        if path.parent != directory or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("legacy_observation_link_invalid")
        data = json.loads(path.read_text())
        if data.get("schema") != "ankla-ci/legacy-observer-v1":
            raise ValueError("legacy_observation_schema_invalid")
        if data.get("run_id") != manifest["run_id"]:
            raise ValueError("legacy_run_mismatch")
        if not data.get("complete") or not data.get("successful"):
            raise ValueError("legacy_observation_incomplete:" + path.name)
        if not data.get("cases"):
            raise ValueError("empty_legacy_observation")
        records.append(data)
    if not records:
        raise ValueError("legacy_observer_not_loaded")
    for expected in manifest["expected"]:
        candidates = [record for record in records if runtime_key(record) == runtime_key(expected)
                      and record["mode"] == expected["mode"]]
        required = set(expected["case_ids"])
        if not required or not any(set(record["cases"]) - RETIRED == required for record in candidates):
            raise ValueError("legacy_full_suite_inventory_incomplete")
    for record in records:
        record["input_signature"] = manifest["input_signature"]
    return records


def runtime_key(record):
    return (record["real_executable"], record["prefix"], tuple(record["version_info"]),
            record["crypto"], record["crypto_version"], record["platform"], record["flags"], record["export"])


def compare_worker(report, records):
    compatible = [record for record in records if runtime_key(record) == runtime_key(report)]
    if not compatible:
        return ["baseline_runtime_missing"]
    exact = [record for record in compatible if record["mode"] == report["mode"]]
    selected = exact or compatible
    errors = []
    compared = set()
    for record in selected:
        for key, previous in record["cases"].items():
            if key in RETIRED:
                continue
            if key.startswith("fixture:"):
                # Only a class setup skip is resolved by ci_results; other fixtures are invalid.
                errors.append("unresolved_legacy_fixture:" + key)
                continue
            if previous["status"] not in ("success", "skip", "subtest_skip"):
                errors.append("invalid_legacy_case:" + key)
                continue
            current = report["cases"].get(key)
            if current is None:
                errors.append("retained_case_missing:" + key)
                continue
            compared.add(key)
            if current["status"] != previous["status"]:
                errors.append("changed_case_outcome:" + key)
            if current["status"] == "skip" and current.get("detail") != previous.get("detail"):
                errors.append("changed_skip_reason:" + key)
            if current["status"] == "subtest_skip" and current.get("subtests") != previous.get("subtests"):
                errors.append("changed_subtest_skips:" + key)
        for path, digest in record["sources"].items():
            if path in report["sources"] and report["sources"][path] != digest:
                errors.append("source_changed_since_baseline:" + path)
    # An absent mode is new coverage, not measured same-mode equivalence.
    report["baseline_comparison"] = {"same_mode": bool(exact), "compared_cases": len(compared)}
    if not compared:
        errors.append("no_retained_cases_compared")
    return sorted(set(errors))


def coverage_gaps(reports, records):
    """No observed legacy runtime/mode may disappear from the new audit."""
    provided = {(runtime_key(r), tuple(sorted(r["mode"].items()))) for r in reports}
    required = {(runtime_key(r), tuple(sorted(r["mode"].items()))) for r in records
                if any(k not in RETIRED for k in r["cases"])}
    return [repr(item) for item in required - provided]
