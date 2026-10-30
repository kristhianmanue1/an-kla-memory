"""Static, bounded CI inventory; does not import or execute test modules."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SOURCES = (
    "scripts/ci_local.py",
    "tests/test_sealed_matrix.py",
    "tests/test_sealed_matrix_rows.py",
    "tests/test_ci_local_matriz.py",
    "tests/test_ci_metadata.py",
)


def inventory() -> dict:
    files = []
    definitions = {}
    for relative in SOURCES:
        raw = (ROOT / relative).read_bytes()
        tree = ast.parse(raw, filename=relative)
        calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                owner = node.func.value
                if isinstance(owner, ast.Name) and owner.id == "subprocess":
                    calls.append({"line": node.lineno, "call": ast.unparse(node)})
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                # AST locations/comments do not affect structural identity.
                digest = hashlib.sha256(ast.dump(node).encode()).hexdigest()
                definitions.setdefault(digest, []).append(
                    {"path": relative, "line": node.lineno, "name": node.name}
                )
        files.append({
            "path": relative,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "subprocess_sites": sorted(calls, key=lambda item: item["line"]),
        })
    source = ast.parse((ROOT / "tests/test_sealed_matrix.py").read_text())
    mapping = next(
        ast.literal_eval(node.value) for node in source.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name) and node.target.id == "_ROW_MODULES"
    )
    return {
        "scope": "static syntax only; no dynamic reachability or runtime count",
        "sources": files,
        "identical_top_level_definitions": [
            group for group in definitions.values() if len(group) > 1
        ],
        "declared_rows": len(mapping),
        "unique_rerun_modules": sorted({m for group in mapping.values() for m in group}),
    }


if __name__ == "__main__":
    destination = Path(__file__).with_name("inventory.json")
    destination.write_text(
        json.dumps(inventory(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    )
