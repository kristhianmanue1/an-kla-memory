"""Verifiable local export/backup and fail-closed restore (ADR-0027)."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

from .canonical import bare_digest, canonical_json, digest_bytes, digest_json
from .identity import identity_lock
from .export_io import (
    ExportIOError, normalize_and_sync_tree, rename_noreplace, safe_read,
    validate_tree,
)
from .storage_primitives import fsync_directory


PROFILE = "export/v1"
WARNING = "plaintext_export_contains_untrusted_memory_data"
_HEX = r"[0-9a-f]{64}"
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
_PATTERNS = tuple(re.compile(value) for value in (
    r"anchor/project-identity\.json", r"anchor/identity-intent\.json",
    rf"anchor/identity-(?:intents|receipts)/sha256/{_HEX}\.json",
    r"anchor/memory/identity\.json", rf"anchor/memory/identities/sha256/{_HEX}\.json",
    r"anchor/memory/refs/CURRENT", rf"anchor/memory/refs/ref-log/sha256/{_HEX}\.json",
    rf"anchor/memory/(?:revisions|checkpoints|refutations|authority-claims|authority-attestations)/sha256/{_HEX}\.json",
    rf"anchor/memory/segments/(?:facts|events|episodes)/sha256/{_HEX}\.jsonl",
    rf"anchor/memory/transactions/{_UUID}\.json",
    rf"anchor/memory/transactions/{_UUID}/(?:stages|receipts)/sha256/{_HEX}\.json",
    rf"anchor/memory/compaction/(?:catalogs|epochs|restore-proofs)/sha256/{_HEX}\.json",
    rf"anchor/receipts/receipts/sha256/{_HEX}\.json",
    rf"anchor/receipts/nonces/sha256/{_HEX}\.json",
    r"anchor/attest-whitelist\.json",
))


ExportError = ExportIOError


def _allowed(path: str) -> bool:
    return any(pattern.fullmatch(path) for pattern in _PATTERNS)


def _files(anchor: Path) -> list[tuple[str, Path]]:
    rows: list[tuple[str, Path]] = []
    for path in sorted(anchor.rglob("*")):
        relative = "anchor/" + path.relative_to(anchor).as_posix()
        if path.is_symlink():
            raise ExportError("export_unsafe_link")
        if path.is_dir():
            continue
        stat = path.lstat()
        if not path.is_file() or stat.st_nlink != 1:
            raise ExportError("export_unsafe_file")
        if _allowed(relative):
            rows.append((relative, path))
        elif relative not in {"anchor/.identity.lock", "anchor/memory/.write.lock", "anchor/memory/.reader-gate", "anchor/attest.key"} and not relative.startswith(("anchor/context/", "anchor/memory/indexes/", "anchor/memory/leases/", "anchor/memory/quarantine/")):
            raise ExportError("export_unrecognized_durable_path")
    return sorted(rows, key=lambda item: item[0].encode("utf-8"))


def _manifest(entries: list[dict[str, Any]], current: str, project_id: str, store_id: str) -> dict[str, Any]:
    core = {
        "current_revision": current,
        "project_identity_sha256": project_id,
        "store_identity_sha256": store_id,
        "entry_count": len(entries),
        "total_bytes": sum(item["size"] for item in entries),
        "entries": entries,
    }
    return {"schema": "an-kla/export-manifest-v1", "profile": PROFILE, "core": core, "manifest_sha256": digest_json(core)}


def create_export(store: Any, bundle: str | Path) -> dict[str, Any]:
    target = Path(bundle).resolve()
    if target.exists():
        raise ExportError("export_destination_exists")
    anchor = store.project_root / ".an-kla"
    if target == anchor or anchor in target.parents:
        raise ExportError("export_destination_inside_source")
    target.mkdir(mode=0o700, parents=False)
    try:
        entries_dir = target / "entries"
        entries_dir.mkdir(mode=0o700)
        with identity_lock(store):
            with store.write_lock():
                source_verify = store.verify()
                if source_verify["identity_status"] != "complete":
                    raise ExportError("export_source_identity_incomplete")
                current = store.read_current()
                rows = _files(anchor)
                entries = []
                for relative, source in rows:
                    relative_source = source.relative_to(store.project_root).as_posix()
                    payload = safe_read(store.project_root, relative_source)
                    destination = entries_dir / relative
                    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    destination.write_bytes(payload)
                    destination.chmod(0o600)
                    entries.append({"path": relative, "size": len(payload), "content_sha256": digest_bytes(payload)})
                if store.read_current() != current:
                    raise ExportError("export_source_changed")
                if [item[0] for item in _files(anchor)] != [item[0] for item in rows]:
                    raise ExportError("export_source_changed")
                final_verify = store.verify()
                if final_verify["revision"] != current or final_verify["identity_status"] != "complete":
                    raise ExportError("export_source_changed")
        by_path = {item["path"]: item for item in entries}
        for required in ("anchor/project-identity.json", "anchor/memory/identity.json", "anchor/memory/refs/CURRENT"):
            if required not in by_path:
                raise ExportError("export_required_entry_missing")
        if not any(item["path"].startswith("anchor/memory/revisions/") for item in entries) or not any(item["path"].startswith("anchor/memory/checkpoints/") for item in entries):
            raise ExportError("export_required_entry_missing")
        project_id = by_path["anchor/project-identity.json"]["content_sha256"]
        store_id = by_path["anchor/memory/identity.json"]["content_sha256"]
        manifest = _manifest(entries, current, project_id, store_id)
        (target / "manifest.json").write_bytes(canonical_json(manifest))
        (target / "manifest.json").chmod(0o600)
        normalize_and_sync_tree(target, [path for path in target.rglob("*") if path.is_file()])
        return {"schema": "an-kla/export-result-v1", "created": True, "bundle": str(target.resolve()), "manifest_sha256": manifest["manifest_sha256"], "current_revision": current, "warnings": [WARNING]}
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise


def _materialize(payloads: dict[str, bytes], manifest: dict[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as temporary:
        project = Path(temporary)
        for relative, payload in payloads.items():
            target = project / ".an-kla" / Path(relative).relative_to("anchor")
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            target.write_bytes(payload)
            target.chmod(0o600)
        from .store import MemoryStore

        verified = MemoryStore(project).verify()
        if verified["revision"] != manifest["core"]["current_revision"]:
            raise ExportError("export_semantic_mismatch")
        return verified


def _validated(bundle: Path, max_files: int, max_bytes: int) -> tuple[dict[str, Any], dict[str, bytes], dict[str, Any]]:
    if bundle.is_symlink() or not bundle.is_dir():
        raise ExportError("export_bundle_invalid")
    try:
        raw = safe_read(bundle, "manifest.json")
        manifest = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise ExportError("export_manifest_invalid") from exc
    if canonical_json(manifest) != raw or set(manifest) != {"schema", "profile", "core", "manifest_sha256"} or manifest["schema"] != "an-kla/export-manifest-v1" or manifest["profile"] != PROFILE:
        raise ExportError("export_manifest_invalid")
    core = manifest["core"]
    if not isinstance(core, dict) or set(core) != {"current_revision", "project_identity_sha256", "store_identity_sha256", "entry_count", "total_bytes", "entries"} or digest_json(core) != manifest["manifest_sha256"]:
        raise ExportError("export_manifest_invalid")
    try:
        for identifier in (
            manifest["manifest_sha256"], core["current_revision"],
            core["project_identity_sha256"], core["store_identity_sha256"],
        ):
            if not isinstance(identifier, str):
                raise ValueError("invalid_sha256_identifier")
            bare_digest(identifier)
    except (TypeError, ValueError) as exc:
        raise ExportError("export_manifest_invalid") from exc
    entries = core["entries"]
    if (
        not isinstance(entries, list)
        or type(core["entry_count"]) is not int
        or type(core["total_bytes"]) is not int
        or len(entries) > max_files
        or core["entry_count"] != len(entries)
        or not 0 <= core["total_bytes"] <= max_bytes
    ):
        raise ExportError("export_limits_exceeded")
    for item in entries:
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "size", "content_sha256"}
            or not isinstance(item["path"], str)
            or type(item["size"]) is not int
            or item["size"] < 0
            or not isinstance(item["content_sha256"], str)
        ):
            raise ExportError("export_entries_invalid")
        try:
            bare_digest(item["content_sha256"])
        except ValueError as exc:
            raise ExportError("export_entries_invalid") from exc
    paths = [item["path"] for item in entries]
    if len(paths) != len(entries) or paths != sorted(paths, key=lambda x: x.encode("utf-8")) or len(set(paths)) != len(paths) or len({str(path).casefold() for path in paths}) != len(paths):
        raise ExportError("export_entries_invalid")
    expected = {"manifest.json"}
    total = 0
    payloads: dict[str, bytes] = {}
    for item in entries:
        if set(item) != {"path", "size", "content_sha256"} or not _allowed(item["path"]):
            raise ExportError("export_entries_invalid")
        payload = safe_read(bundle, "entries/" + item["path"])
        if len(payload) != item["size"] or digest_bytes(payload) != item["content_sha256"]:
            raise ExportError("export_content_mismatch")
        total += len(payload)
        payloads[item["path"]] = payload
        expected.add("entries/" + item["path"])
    validate_tree(bundle, expected)
    if total != core["total_bytes"]:
        raise ExportError("export_extra_or_missing_entry")
    current = payloads["anchor/memory/refs/CURRENT"].decode("ascii").strip()
    if current != core["current_revision"]:
        raise ExportError("export_current_mismatch")
    by_path = {item["path"]: item for item in entries}
    if by_path.get("anchor/project-identity.json", {}).get("content_sha256") != core["project_identity_sha256"] or by_path.get("anchor/memory/identity.json", {}).get("content_sha256") != core["store_identity_sha256"]:
        raise ExportError("export_identity_mismatch")
    verified = _materialize(payloads, manifest)
    return deepcopy(manifest), payloads, verified


def verify_export(bundle: str | Path, *, max_files: int = 100000, max_bytes: int = 10 * 1024**3) -> dict[str, Any]:
    manifest, _payloads, _verified = _validated(Path(bundle), max_files, max_bytes)
    return {"schema": "an-kla/export-verify-result-v1", "verified": True, "manifest_sha256": manifest["manifest_sha256"], "current_revision": manifest["core"]["current_revision"], "warnings": [WARNING]}


def _destination_matches(destination: Path, payloads: dict[str, bytes]) -> bool:
    try:
        expected = {
            Path(relative).relative_to("anchor").as_posix()
            for relative in payloads
        }
        # Semantic verification creates the permanent reader gate required by
        # ADR-0028.  It is runtime coordination state, not exported content.
        gate = destination / "memory" / ".reader-gate"
        if gate.exists():
            expected.add("memory/.reader-gate")
        validate_tree(destination, expected)
        return all(
            safe_read(destination, Path(relative).relative_to("anchor").as_posix())
            == payload
            for relative, payload in payloads.items()
        )
    except Exception:
        return False


def restore_export(bundle: str | Path, project_root: str | Path) -> dict[str, Any]:
    source = Path(bundle)
    manifest, payloads, _bundle_verified = _validated(source, 100000, 10 * 1024**3)
    project = Path(project_root).resolve()
    project.mkdir(parents=True, exist_ok=True)
    destination = project / ".an-kla"
    if destination.exists():
        raise ExportError("restore_destination_conflict")
    try:
        staging = Path(tempfile.mkdtemp(prefix=".an-kla-restore-", dir=project))
    except OSError as exc:
        return {"schema": "an-kla/restore-result-v1", "state": "not_published", "published": False, "current_revision": manifest["core"]["current_revision"], "manifest_sha256": manifest["manifest_sha256"], "warnings": [WARNING, f"restore_error:{exc}"]}
    published = False
    durability_complete = False
    try:
        anchor = staging / ".an-kla"
        staged_files = []
        for relative, payload in payloads.items():
            staged = anchor / Path(relative).relative_to("anchor")
            staged.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            staged.write_bytes(payload)
            staged_files.append(staged)
            if digest_bytes(staged.read_bytes()) != next(item["content_sha256"] for item in manifest["core"]["entries"] if item["path"] == relative):
                raise ExportError("restore_staging_mismatch")
        from .store import MemoryStore

        MemoryStore(staging).verify()
        normalize_and_sync_tree(anchor, staged_files)
        for relative, payload in payloads.items():
            staged = anchor / Path(relative).relative_to("anchor")
            if digest_bytes(staged.read_bytes()) != digest_bytes(payload):
                raise ExportError("restore_staging_mismatch")
        rename_noreplace(anchor, destination)
        published = True
        fsync_directory(project)
        durability_complete = True
        final_verify = MemoryStore(project).verify()
        warnings = [WARNING]
        if final_verify["root_relocated"]:
            warnings.append("root_relocated")
        return {"schema": "an-kla/restore-result-v1", "state": "published", "published": True, "current_revision": manifest["core"]["current_revision"], "manifest_sha256": manifest["manifest_sha256"], "warnings": warnings}
    except Exception as exc:
        conflict = str(exc) == "restore_destination_conflict"
        if not published and not conflict and destination.exists() and _destination_matches(destination, payloads):
            published = True
        if not published:
            state = (
                "not_published"
                if conflict
                or not destination.exists()
                else "outcome_unknown"
            )
            if state == "outcome_unknown":
                published = True
        elif durability_complete:
            state = "outcome_unknown"
        else:
            state = "published_durability_incomplete"
        return {"schema": "an-kla/restore-result-v1", "state": state, "published": published, "current_revision": manifest["core"]["current_revision"], "manifest_sha256": manifest["manifest_sha256"], "warnings": [WARNING, f"restore_error:{exc}"]}
    finally:
        shutil.rmtree(staging, ignore_errors=True)


__all__ = ["ExportError", "create_export", "restore_export", "verify_export"]
