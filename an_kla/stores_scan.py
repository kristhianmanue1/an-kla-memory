"""Read-only discovery of AN-KLA vaults under operator-named roots (ADR-0050).

``scan`` walks only the roots it is given, never follows symlinks, honours a
depth limit and classifies what it finds by identity bytes, never by path
names.  It writes nothing: no store object is opened for writing, ``verify``
is not called (its reader gate may create a lock file) and no result is
saved.  Paths appear only with ``show_paths``.
"""

from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

from .canonical import canonical_json, digest_bytes, digest_json
from .custody import BINDING_SCHEMA, POINTER_NAME, POINTER_SCHEMA
from .relocation_receipts import RelocationReceiptError, chain_head, load_relocation_receipt


SCHEMA = "an-kla/stores-scan-v1"
PRUNED = (".git", "node_modules")
CLASSES = (
    "active", "external_bound", "orphan_uncertain", "legacy_unadopted",
    "unreadable", "export_bundle", "pointer_only",
)
FLAGS = ("copy", "moved", "pointer_divergent", "pointer_target_out_of_scope")


class ScanError(ValueError):
    pass


class _Symlink(Exception):
    """A path component under the candidate root is a symlink."""


def _read(root: Path, *parts: str) -> bytes | None:
    """Read ``root/parts`` without following any symlinked component."""

    cursor = root
    for part in parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise _Symlink
    try:
        with cursor.open("rb") as handle:
            return handle.read()
    except OSError:
        return None


def _identity(root: Path) -> dict[str, Any]:
    """Identity facts of one custody root, read without any lock."""

    facts: dict[str, Any] = {"store_identity": None, "custody_fingerprint": None}
    try:
        current = _read(root, "memory", "refs", "CURRENT")
        project_bytes = _read(root, "project-identity.json")
        store_bytes = _read(root, "memory", "identity.json")
    except _Symlink:
        # Never read through a symlink: it could point outside the roots
        # the operator named (beta.30 release round, H-04).
        facts.update(state="unreadable", code="symlink_in_vault")
        return facts
    if project_bytes is None and store_bytes is None:
        facts["state"] = "legacy_unadopted" if current is not None else "absent"
        return facts
    try:
        project = json.loads(project_bytes or b"")
        identity = json.loads(store_bytes or b"")
        if (
            not isinstance(project, dict) or not isinstance(identity, dict)
            or canonical_json(project) != project_bytes
            or canonical_json(identity) != store_bytes
            or project.get("project_uuid") != identity.get("project_uuid")
            or identity.get("project_identity") != digest_bytes(project_bytes)
        ):
            raise ValueError
    except ValueError:
        facts.update(state="unreadable", code="store_identity_invalid")
        return facts
    if current is None or len(current) != 72 or not current.endswith(b"\n"):
        facts.update(state="unreadable", code="current_missing_or_invalid")
        return facts
    store_identity = digest_bytes(store_bytes)
    facts.update(
        state="complete",
        store_identity=store_identity,
        custody_fingerprint=digest_json({
            "schema": BINDING_SCHEMA,
            "project_uuid": identity["project_uuid"],
            "store_identity": store_identity,
        }),
        root_at_init=identity.get("canonical_project_root_at_init"),
    )
    view = SimpleNamespace(store_root=root, custody_walk_root=root.parent)
    try:
        head = chain_head(view, store_identity, "project_root")
        if head is not None:
            facts["root_at_init"] = load_relocation_receipt(view, head)["to_root_observed"]
    except RelocationReceiptError:
        facts.update(state="unreadable", code="relocation_receipt_chain_invalid")
    return facts


def _pointer(anchor: Path) -> dict[str, Any] | None:
    try:
        payload = _read(anchor, POINTER_NAME)
    except _Symlink:
        return {"store_root": None, "fingerprint": None}
    if payload is None:
        return None
    try:
        value = json.loads(payload)
        if value.get("schema") != POINTER_SCHEMA:
            raise ValueError
        return {"store_root": str(value["store_root"]), "fingerprint": value["custody_fingerprint"]}
    except (ValueError, TypeError, KeyError, AttributeError):
        return {"store_root": None, "fingerprint": None}


def _walk(root: Path, max_depth: int, counters: Counter) -> Iterable[tuple[str, Path]]:
    base = len(root.parts)

    def on_error(_exc: OSError) -> None:
        counters["walk_errors"] += 1

    for directory, subdirs, files in os.walk(root, followlinks=False, onerror=on_error):
        counters["directories_walked"] += 1
        here = Path(directory)
        depth = len(here.parts) - base
        kept = []
        for name in subdirs:
            if (here / name).is_symlink():
                counters["symlinks_not_followed"] += 1
            elif name in PRUNED:
                counters["pruned"] += 1
            else:
                kept.append(name)
        subdirs[:] = kept if depth < max_depth else []
        names = set(kept) | set(files)
        if ".an-kla" in names and not (here / ".an-kla").is_symlink():
            yield "anchor", here / ".an-kla"
        if "manifest.json" in files and (here / "entries" / "anchor").is_dir():
            yield "export_bundle", here
        elif (
            here.name != ".an-kla"
            and "project-identity.json" in files
            and (here / "memory" / "identity.json").exists()
            and here.parent.name != "entries"
        ):
            yield "external_root", here


def scan(roots: list[str | Path], *, max_depth: int = 4, show_paths: bool = False) -> dict[str, Any]:
    if not roots or max_depth < 0:
        raise ScanError("stores_scan_invalid_arguments")
    resolved = []
    for item in roots:
        path = Path(item)
        if not path.is_absolute() or not path.is_dir() or path.is_symlink():
            raise ScanError("stores_scan_root_invalid")
        resolved.append(path.resolve())
    counters: Counter = Counter()
    found: list[dict[str, Any]] = []
    for root in resolved:
        for kind, path in _walk(root, max_depth, counters):
            entry: dict[str, Any] = {"kind": kind, "path": path, "flags": []}
            if kind == "export_bundle":
                entry["class"] = "export_bundle"
                entry["custody_fingerprint"] = None
            else:
                entry.update(_identity(path))
                if kind == "anchor":
                    entry["pointer"] = _pointer(path)
            found.append(entry)
    vaults = [entry for entry in found if entry.get("state") == "complete"]
    locations = Counter(entry["store_identity"] for entry in vaults)
    by_location = {str(entry["path"]): entry for entry in found if entry["kind"] == "external_root"}
    pointed: set[str] = set()
    for entry in found:
        pointer = entry.get("pointer")
        if pointer is None:
            continue
        target = by_location.get(pointer["store_root"] or "")
        if target is None:
            entry["flags"].append("pointer_target_out_of_scope")
        elif target.get("custody_fingerprint") != pointer["fingerprint"]:
            entry["flags"].append("pointer_divergent")
        else:
            pointed.add(str(target["path"]))
    for entry in found:
        if entry["kind"] == "export_bundle":
            continue
        state = entry["state"]
        if state in {"unreadable", "legacy_unadopted"}:
            entry["class"] = state
            continue
        if state == "absent":
            entry["class"] = "pointer_only" if entry.get("pointer") else "unreadable"
            entry.setdefault("code", None if entry.get("pointer") else "anchor_empty")
            continue
        if entry["kind"] == "anchor":
            entry["class"] = "active"
            if entry.get("root_at_init") != str(entry["path"].parent):
                entry["flags"].append("moved")
        else:
            entry["class"] = "external_bound" if str(entry["path"]) in pointed else "orphan_uncertain"
        if locations[entry["store_identity"]] > 1:
            entry["flags"].append("copy")
    entries = []
    for entry in found:
        item = {
            "class": entry["class"],
            "flags": sorted(entry["flags"]),
            "custody_fingerprint": entry.get("custody_fingerprint"),
        }
        if entry.get("code"):
            item["code"] = entry["code"]
        if show_paths:
            item["path"] = str(entry["path"])
        entries.append(item)
    entries.sort(key=lambda item: (item["class"], item["custody_fingerprint"] or "", item.get("path", "")))
    return {
        "schema": SCHEMA,
        "roots": len(resolved),
        "max_depth": max_depth,
        "pruned_names": list(PRUNED),
        "directories_walked": counters["directories_walked"],
        "symlinks_not_followed": counters["symlinks_not_followed"],
        "walk_errors": counters["walk_errors"],
        "counts": {name: sum(1 for item in entries if item["class"] == name) for name in CLASSES},
        "flags": {name: sum(1 for item in entries if name in item["flags"]) for name in FLAGS},
        "verify_run": False,
        "paths_included": show_paths,
        "entries": entries,
    }


__all__ = ["CLASSES", "FLAGS", "SCHEMA", "ScanError", "scan"]
