"""Fail unless version and the documented adversarial release gate agree."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from an_kla.version import normalized_release_tag


def project_version(root: Path) -> str:
    payload = (root / "an_kla" / "version.py").read_text(encoding="utf-8")
    match = re.search(r'^VERSION = "([^"]+)"$', payload, re.MULTILINE)
    if not match:
        raise ValueError("missing_project_version")
    return match.group(1)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate_json_key")
        value[key] = item
    return value


def validate_release_gate(root: Path, tag: str) -> None:
    path = root / "docs" / "releases" / f"{tag}-adversarial.md"
    try:
        payload = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError("release_gate_document_missing") from exc
    marker_lines = [
        line for line in payload.splitlines() if "an-kla:release-gate" in line
    ]
    if not marker_lines:
        raise ValueError("release_gate_missing")
    if len(marker_lines) != 1:
        raise ValueError("release_gate_duplicated")
    match = re.fullmatch(
        r"<!-- an-kla:release-gate (\{.*\}) -->", marker_lines[0]
    )
    if not match:
        raise ValueError("release_gate_invalid")
    try:
        gate = json.loads(match.group(1), object_pairs_hook=_unique_object)
    except (TypeError, ValueError) as exc:
        raise ValueError("release_gate_invalid") from exc
    if not isinstance(gate, dict) or set(gate) != {"decision", "scope", "tag"}:
        raise ValueError("release_gate_invalid")
    if gate["tag"] != tag:
        raise ValueError("release_gate_tag_mismatch")
    if gate["scope"] != "release-candidate":
        raise ValueError("release_gate_scope_mismatch")
    if gate["decision"] != "proceed":
        raise ValueError("release_gate_not_proceed")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: check_release_tag.py <tag>")
    expected = normalized_release_tag(sys.argv[1])
    observed = project_version(ROOT)
    if expected != observed:
        raise SystemExit(f"release_version_mismatch:tag={expected}:project={observed}")
    try:
        validate_release_gate(ROOT, sys.argv[1])
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
