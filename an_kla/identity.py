"""Project/store identity bootstrap, adoption, and verification (ADR-0022)."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import time
import uuid
from typing import Any, Iterator, Mapping

from .canonical import bare_digest, canonical_json, digest_bytes, digest_json
from .identity_evidence import (
    IdentityEvidenceError,
    valid_identity_receipt,
    validate_bound_descendants,
    write_identity_receipt,
)
from .storage_primitives import atomic_write, fsync_directory, write_immutable
from .version import VERSION


PROJECT_SCHEMA = "an-kla/project-identity-v1"
STORE_SCHEMA = "an-kla/store-identity-v1"
INTENT_SCHEMA = "an-kla/identity-intent-v1"
PLAN_SCHEMA = "an-kla/identity-adoption-plan-v1"
RESULT_SCHEMA = "an-kla/identity-operation-result-v1"


class IdentityError(RuntimeError):
    pass


def _uuid(value: Any) -> str:
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, ValueError) as exc:
        raise IdentityError("identity_uuid_invalid") from exc
    if str(parsed) != value or parsed.version not in {1, 2, 3, 4, 5}:
        raise IdentityError("identity_uuid_invalid")
    return value


def _transaction_uuid(value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, ValueError) as exc:
        raise IdentityError("invalid_transaction_id") from exc
    if (
        str(parsed) != value
        or parsed.version not in {1, 2, 3, 4, 5}
        or parsed.variant != uuid.RFC_4122
    ):
        raise IdentityError("invalid_transaction_id")
    return value


def _paths(store: Any) -> dict[str, Path]:
    anchor = store.project_root / ".an-kla"
    return {
        "anchor": anchor,
        "project": anchor / "project-identity.json",
        "store": store.root / "identity.json",
        "intent": anchor / "identity-intent.json",
        "lock": anchor / ".identity.lock",
        "immutable_intents": anchor / "identity-intents" / "sha256",
        "receipts": anchor / "identity-receipts" / "sha256",
    }


def _reject_symlink_path(path: Path, root: Path) -> None:
    cursor = path
    while cursor != root:
        if cursor.is_symlink():
            raise IdentityError("store_identity_invalid")
        if root not in cursor.parents:
            raise IdentityError("store_identity_invalid")
        cursor = cursor.parent


def _read_canonical(path: Path, missing: str, invalid: str) -> tuple[dict[str, Any], bytes]:
    try:
        payload = path.read_bytes()
    except FileNotFoundError as exc:
        raise IdentityError(missing) from exc
    try:
        value = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise IdentityError(invalid) from exc
    if not isinstance(value, dict) or canonical_json(value) != payload:
        raise IdentityError(invalid)
    return value, payload


def _validate_project(value: Mapping[str, Any]) -> None:
    if set(value) != {"schema", "project_uuid", "created_by_version"}:
        raise IdentityError("project_identity_invalid")
    if value["schema"] != PROJECT_SCHEMA or not isinstance(value["created_by_version"], str):
        raise IdentityError("project_identity_invalid")
    _uuid(value["project_uuid"])


def _validate_store(value: Mapping[str, Any]) -> None:
    if set(value) != {
        "schema",
        "store_uuid",
        "project_uuid",
        "project_identity",
        "canonical_project_root_at_init",
        "created_by_version",
    }:
        raise IdentityError("store_identity_invalid")
    if (
        value["schema"] != STORE_SCHEMA
        or not isinstance(value["canonical_project_root_at_init"], str)
        or not isinstance(value["created_by_version"], str)
    ):
        raise IdentityError("store_identity_invalid")
    _uuid(value["store_uuid"])
    _uuid(value["project_uuid"])
    try:
        bare_digest(value["project_identity"])
    except (TypeError, ValueError) as exc:
        raise IdentityError("store_identity_invalid") from exc


def _validate_pair(project: Mapping[str, Any], identity: Mapping[str, Any]) -> None:
    _validate_project(project)
    _validate_store(identity)
    if (
        identity["project_uuid"] != project["project_uuid"]
        or identity["project_identity"] != digest_json(project)
    ):
        raise IdentityError("project_identity_mismatch")


def read_binding(store: Any) -> dict[str, Any]:
    """Read and bind the two live identity files without mutating."""

    paths = _paths(store)
    _reject_symlink_path(paths["project"], store.project_root)
    _reject_symlink_path(paths["store"], store.project_root)
    project, project_bytes = _read_canonical(
        paths["project"], "project_identity_missing", "project_identity_invalid"
    )
    identity, store_bytes = _read_canonical(
        paths["store"], "store_identity_missing", "store_identity_invalid"
    )
    _validate_pair(project, identity)
    project_digest = digest_bytes(project_bytes)
    if identity["project_uuid"] != project["project_uuid"]:
        raise IdentityError("project_identity_mismatch")
    if identity["project_identity"] != project_digest:
        raise IdentityError("project_identity_mismatch")
    identity_digest = digest_bytes(store_bytes)
    _reject_symlink_path(
        store._path_for("identities", identity_digest), store.project_root
    )
    immutable = store._read_json_object("identities", identity_digest)
    if dict(immutable) != identity:
        raise IdentityError("store_identity_invalid")
    return {
        "project": project,
        "store": identity,
        "project_bytes": project_bytes,
        "store_bytes": store_bytes,
        "store_identity": identity_digest,
        "root_relocated": str(store.project_root) != identity["canonical_project_root_at_init"],
    }


def assert_unchanged(store: Any, before: Mapping[str, Any], parent: str) -> str:
    """Re-read identity under the store lock and enforce parent lineage."""

    paths = _paths(store)
    try:
        project_bytes = paths["project"].read_bytes()
        store_bytes = paths["store"].read_bytes()
    except OSError as exc:
        raise IdentityError("store_identity_changed") from exc
    if project_bytes != before["project_bytes"] or store_bytes != before["store_bytes"]:
        raise IdentityError("store_identity_changed")
    after = read_binding(store)
    manifest = store._read_json_object("revisions", parent)
    linked = manifest.get("store_identity")
    if linked is not None and linked != after["store_identity"]:
        raise IdentityError("store_identity_lineage_mismatch")
    if linked is None and not _completed_adoption_matches(store, parent):
        raise IdentityError("legacy_store_identity_adoption_required")
    return str(after["store_identity"])


def verify_current_binding(store: Any, manifest: Mapping[str, Any], current: str) -> dict[str, Any]:
    binding = read_binding(store)
    linked = manifest.get("store_identity")
    if linked == binding["store_identity"]:
        return binding
    if linked is None and _completed_adoption_matches(store, current):
        return binding
    raise IdentityError("store_identity_lineage_mismatch")


def verify_manifest_link(store: Any, manifest: Mapping[str, Any]) -> None:
    linked = manifest.get("store_identity")
    if linked is None:
        return
    try:
        bare_digest(linked)
        value = store._read_json_object("identities", linked)
        _validate_store(value)
    except IdentityError:
        raise
    except Exception as exc:
        raise IdentityError("store_identity_invalid") from exc


@contextmanager
def identity_lock(store: Any) -> Iterator[None]:
    paths = _paths(store)
    _reject_symlink_path(paths["lock"], store.project_root)
    paths["anchor"].mkdir(parents=True, exist_ok=True)
    with paths["lock"].open("a+b") as handle:
        try:
            import fcntl  # type: ignore
        except ImportError:
            try:
                import msvcrt  # type: ignore
            except ImportError as exc:
                raise IdentityError("identity_lock_unsupported") from exc
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            deadline = time.monotonic() + 10.0
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise IdentityError("identity_lock_busy") from exc
                    time.sleep(0.05)
            try:
                yield
            finally:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            return
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass


def _write_create_or_match(path: Path, payload: bytes, root: Path) -> None:
    _reject_symlink_path(path, root)
    def conflict(_target: Path) -> None:
        raise IdentityError("identity_bootstrap_conflict")

    write_immutable(path, payload, conflict=conflict, fsync_directory=fsync_directory)


def _new_objects(store: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    project = {
        "schema": PROJECT_SCHEMA,
        "project_uuid": str(uuid.uuid4()),
        "created_by_version": VERSION,
    }
    identity = {
        "schema": STORE_SCHEMA,
        "store_uuid": str(uuid.uuid4()),
        "project_uuid": project["project_uuid"],
        "project_identity": digest_json(project),
        "canonical_project_root_at_init": str(store.project_root),
        "created_by_version": VERSION,
    }
    return project, identity


def _intent_core(
    operation: str,
    project: Mapping[str, Any],
    identity: Mapping[str, Any],
    current: str | None,
    transaction_id: str | None,
) -> dict[str, Any]:
    core = {
        "schema": INTENT_SCHEMA,
        "operation": operation,
        "project_identity": deepcopy(dict(project)),
        "store_identity": deepcopy(dict(identity)),
        "current_observed": current,
        "transaction_id": transaction_id,
    }
    return core


def _read_intent(store: Any) -> dict[str, Any] | None:
    path = _paths(store)["intent"]
    if not path.exists():
        return None
    _reject_symlink_path(path, store.project_root)
    value, _payload = _read_canonical(path, "identity_intent_missing", "identity_bootstrap_conflict")
    if set(value) != {"schema", "operation", "project_identity", "store_identity", "current_observed", "transaction_id", "intent_sha256", "stage"}:
        raise IdentityError("identity_bootstrap_conflict")
    core = {key: value[key] for key in value if key not in {"intent_sha256", "stage"}}
    if value["schema"] != INTENT_SCHEMA or digest_json(core) != value["intent_sha256"]:
        raise IdentityError("identity_bootstrap_conflict")
    _validate_pair(value["project_identity"], value["store_identity"])
    if value["operation"] == "initialize":
        if value["current_observed"] is not None or not isinstance(
            value["transaction_id"], str
        ):
            raise IdentityError("identity_bootstrap_conflict")
        _transaction_uuid(value["transaction_id"])
    elif value["operation"] == "adopt":
        if value["transaction_id"] is not None or not isinstance(
            value["current_observed"], str
        ):
            raise IdentityError("identity_bootstrap_conflict")
        try:
            bare_digest(value["current_observed"])
        except ValueError as exc:
            raise IdentityError("identity_bootstrap_conflict") from exc
    else:
        raise IdentityError("identity_bootstrap_conflict")
    return value


def _publish_intent(store: Any, core: Mapping[str, Any], stage: str) -> dict[str, Any]:
    paths = _paths(store)
    identifier = digest_json(core)
    immutable = paths["immutable_intents"] / (identifier.removeprefix("sha256:") + ".json")
    value = {**deepcopy(dict(core)), "intent_sha256": identifier, "stage": stage}
    if paths["intent"].exists():
        atomic_write(paths["intent"], canonical_json(value), fsync_directory=fsync_directory)
    else:
        _write_create_or_match(paths["intent"], canonical_json(value), store.project_root)
    _write_create_or_match(immutable, canonical_json(core), store.project_root)
    return value


def _write_identities(store: Any, intent: Mapping[str, Any]) -> str:
    paths = _paths(store)
    _validate_pair(intent["project_identity"], intent["store_identity"])
    store._make_layout()
    paths["immutable_intents"].mkdir(parents=True, exist_ok=True)
    paths["receipts"].mkdir(parents=True, exist_ok=True)
    project_bytes = canonical_json(intent["project_identity"])
    store_bytes = canonical_json(intent["store_identity"])
    identity_digest = digest_bytes(store_bytes)
    _write_create_or_match(store._path_for("identities", identity_digest), store_bytes, store.project_root)
    _write_create_or_match(paths["store"], store_bytes, store.project_root)
    _write_create_or_match(paths["project"], project_bytes, store.project_root)
    binding = read_binding(store)
    if binding["store_identity"] != identity_digest:
        raise IdentityError("identity_bootstrap_conflict")
    return identity_digest


def _result(operation: str, intent: Mapping[str, Any], current: str | None, receipt: str | None, error: str | None = None) -> dict[str, Any]:
    return {
        "schema": RESULT_SCHEMA,
        "operation": operation,
        "intent_sha256": intent["intent_sha256"],
        "identity_state": intent["stage"],
        "current_observed": current,
        "durability_state": "complete" if receipt is not None else "incomplete",
        "receipt": receipt,
        "error_code": error,
    }


def bootstrap_initialize(store: Any, transaction_id: str | None = None) -> dict[str, Any]:
    """Create/reconcile identity and root under identity→store lock order."""

    from .initialization import existing_initialization, initialize_locked

    if transaction_id is not None:
        _transaction_uuid(transaction_id)
    status = identity_status(store)
    if status["identity_status"] == "legacy_unadopted":
        raise IdentityError("legacy_store_identity_adoption_required")
    if status["identity_status"] == "complete":
        existing = existing_initialization(store, transaction_id)
        if existing is None:
            raise IdentityError("identity_bootstrap_conflict")
        receipt = valid_identity_receipt(store, _read_intent(store), existing["revision"])
        return {
            **existing,
            "identity": _result(
                "initialize",
                _read_intent(store),
                existing["revision"],
                receipt,
            ),
        }
    with identity_lock(store):
        intent = _read_intent(store)
        if intent is not None and intent["stage"] == "complete" and store.current_path.exists():
            existing = existing_initialization(store, transaction_id)
            if existing is None:
                raise IdentityError("identity_bootstrap_conflict")
            receipt = valid_identity_receipt(store, intent, existing["revision"])
            return {
                **existing,
                "identity": _result(
                    "initialize", intent, existing["revision"], receipt
                ),
            }
        if intent is None:
            project, identity = _new_objects(store)
            txid = transaction_id or str(uuid.uuid4())
            core = _intent_core("initialize", project, identity, None, txid)
            intent = _publish_intent(store, core, "intent_only")
        elif intent["operation"] != "initialize":
            raise IdentityError("identity_bootstrap_conflict")
        identity_digest = _write_identities(store, intent)
        intent = _publish_intent(store, {key: intent[key] for key in intent if key not in {"intent_sha256", "stage"}}, "identities_ready_root_pending")
        with store.write_lock():
            if store.current_path.exists():
                _validate_initialize_current(store, intent, identity_digest)
            existing = existing_initialization(store, intent["transaction_id"])
            if existing is None:
                revision, outcome = initialize_locked(store, transaction_id=intent["transaction_id"], store_identity=identity_digest)
            else:
                revision, outcome = existing["revision"], existing["outcome"]
            if revision is None or (outcome is not None and outcome.get("committed") is not True):
                return {"revision": revision, "outcome": outcome, "identity": _result("initialize", intent, revision, None, "root_incomplete")}
            receipt = write_identity_receipt(store, intent, "initialize", revision)
            intent = _publish_intent(store, {key: intent[key] for key in intent if key not in {"intent_sha256", "stage"}}, "complete")
        if transaction_id is not None and transaction_id != intent["transaction_id"]:
            outcome = None
        return {"revision": revision, "outcome": outcome, "identity": _result("initialize", intent, revision, receipt)}


def plan_adoption(store: Any) -> dict[str, Any]:
    if identity_status(store)["identity_status"] != "legacy_unadopted":
        raise IdentityError("identity_adoption_plan_invalid")
    current = store.read_current()
    project, identity = _new_objects(store)
    core = {
        "schema": PLAN_SCHEMA,
        "expected_current": current,
        "canonical_project_root_observed": str(store.project_root),
        "project_identity": project,
        "store_identity": identity,
    }
    return {**core, "plan_fingerprint": digest_json(core)}


def _validate_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, dict) or set(plan) != {"schema", "expected_current", "canonical_project_root_observed", "project_identity", "store_identity", "plan_fingerprint"}:
        raise IdentityError("identity_adoption_plan_invalid")
    core = {key: plan[key] for key in plan if key != "plan_fingerprint"}
    if plan["schema"] != PLAN_SCHEMA or digest_json(core) != plan["plan_fingerprint"]:
        raise IdentityError("identity_adoption_plan_invalid")
    try:
        _validate_pair(plan["project_identity"], plan["store_identity"])
    except IdentityError as exc:
        raise IdentityError("identity_adoption_plan_invalid")
    return deepcopy(dict(plan))


def adopt(store: Any, plan: Mapping[str, Any], expected_current: str) -> dict[str, Any]:
    checked = _validate_plan(plan)
    if (
        checked["expected_current"] != expected_current
        or checked["canonical_project_root_observed"] != str(store.project_root)
        or checked["store_identity"]["canonical_project_root_at_init"]
        != str(store.project_root)
    ):
        raise IdentityError("identity_adoption_base_changed")
    with identity_lock(store):
        with store.write_lock():
            if store.read_current() != expected_current:
                raise IdentityError("identity_adoption_base_changed")
            status = identity_status(store)["identity_status"]
            intent = _read_intent(store)
            if intent is None:
                if status != "legacy_unadopted":
                    raise IdentityError("identity_adoption_plan_invalid")
                core = _intent_core("adopt", checked["project_identity"], checked["store_identity"], expected_current, None)
                intent = _publish_intent(store, core, "intent_only")
            elif (
                intent["operation"] != "adopt"
                or intent["current_observed"] != expected_current
                or intent["project_identity"] != checked["project_identity"]
                or intent["store_identity"] != checked["store_identity"]
            ):
                raise IdentityError("identity_bootstrap_conflict")
            _write_identities(store, intent)
            receipt = write_identity_receipt(store, intent, "adopt", expected_current)
            intent = _publish_intent(store, {key: intent[key] for key in intent if key not in {"intent_sha256", "stage"}}, "complete")
            return _result("adopt", intent, expected_current, receipt)


def repair(store: Any, supplied_intent: Mapping[str, Any]) -> dict[str, Any]:
    """Resume only the exact bootstrap/adoption intent supplied by the caller."""

    checked = deepcopy(dict(supplied_intent)) if isinstance(supplied_intent, dict) else {}
    with identity_lock(store):
        intent = _read_intent(store)
        if intent is None or checked != intent:
            raise IdentityError("identity_bootstrap_conflict")
        operation = intent["operation"]
        if operation not in {"initialize", "adopt"}:
            raise IdentityError("identity_bootstrap_conflict")
        identity_digest = _write_identities(store, intent)
        with store.write_lock():
            if operation == "initialize" and not store.current_path.exists():
                from .initialization import initialize_locked

                revision, outcome = initialize_locked(
                    store,
                    transaction_id=intent["transaction_id"],
                    store_identity=identity_digest,
                )
                if revision is None or outcome.get("committed") is not True:
                    return _result("repair", intent, revision, None, "root_incomplete")
            else:
                revision = store.read_current()
                if operation == "initialize":
                    captured = _initialize_root(store, intent, identity_digest)
                    _require_bound_descendants(
                        store, revision, captured, identity_digest
                    )
                elif operation == "adopt":
                    captured = intent["current_observed"]
                    _require_bound_descendants(
                        store,
                        revision,
                        captured,
                        identity_digest,
                        allow_captured_legacy=True,
                    )
            receipt = write_identity_receipt(store, intent, "repair", revision)
            intent = _publish_intent(
                store,
                {key: intent[key] for key in intent if key not in {"intent_sha256", "stage"}},
                "complete",
            )
            return _result("repair", intent, revision, receipt)


def _validate_initialize_current(
    store: Any, intent: Mapping[str, Any], identity_digest: str
) -> None:
    try:
        current = store.read_current()
        manifest = store._read_json_object("revisions", current)
    except Exception as exc:
        raise IdentityError("identity_bootstrap_conflict") from exc
    if (
        manifest.get("parent") is not None
        or manifest.get("transaction_id") != intent["transaction_id"]
        or manifest.get("store_identity") != identity_digest
    ):
        raise IdentityError("identity_bootstrap_conflict")


def _initialize_root(
    store: Any, intent: Mapping[str, Any], identity_digest: str
) -> str:
    matches: list[str] = []
    for path in sorted((store.root / "revisions" / "sha256").glob("*.json")):
        try:
            identifier = "sha256:" + path.stem
            manifest = store._read_json_object("revisions", identifier)
        except Exception:
            continue
        if (
            manifest.get("parent") is None
            and manifest.get("transaction_id") == intent["transaction_id"]
            and manifest.get("store_identity") == identity_digest
        ):
            matches.append(identifier)
    if len(matches) != 1:
        raise IdentityError("identity_bootstrap_conflict")
    return matches[0]


def _require_bound_descendants(*args: Any, **kwargs: Any) -> None:
    try:
        validate_bound_descendants(*args, **kwargs)
    except IdentityEvidenceError as exc:
        raise IdentityError(str(exc)) from exc


def _completed_adoption_matches(store: Any, parent: str) -> bool:
    try:
        intent = _read_intent(store)
    except IdentityError:
        return False
    return bool(
        intent
        and intent["operation"] == "adopt"
        and intent["stage"] == "complete"
        and intent["current_observed"] == parent
        and valid_identity_receipt(store, intent, parent) is not None
    )


def mutation_preflight(store: Any) -> dict[str, Any]:
    status = identity_status(store)["identity_status"]
    if status == "legacy_unadopted":
        raise IdentityError("legacy_store_identity_adoption_required")
    if status != "complete":
        raise IdentityError("store_identity_invalid")
    return read_binding(store)


def identity_status(store: Any, include_ids: bool = False) -> dict[str, Any]:
    paths = _paths(store)
    current_exists = store.current_path.exists()
    project_exists = paths["project"].exists()
    store_exists = paths["store"].exists()
    intent_exists = paths["intent"].exists()
    status = "absent"
    error = None
    binding = None
    if current_exists and not project_exists and not store_exists and not intent_exists:
        status = "legacy_unadopted"
    elif intent_exists and not project_exists and not store_exists:
        status = "intent_only"
    elif store_exists and not project_exists:
        status = "store_only"
    elif project_exists and not store_exists:
        status = "project_only"
    elif project_exists and store_exists:
        try:
            binding = read_binding(store)
            intent = _read_intent(store)
            current = store.read_current() if current_exists else None
            receipt = (
                valid_identity_receipt(store, intent, current)
                if current is not None and intent is not None
                else None
            )
            if current is not None:
                current_manifest = store._read_json_object("revisions", current)
                linked = current_manifest.get("store_identity")
                adopted_legacy_current = bool(
                    linked is None
                    and intent
                    and intent["operation"] == "adopt"
                    and intent["current_observed"] == current
                    and receipt is not None
                )
                if linked != binding["store_identity"] and not adopted_legacy_current:
                    raise IdentityError("store_identity_lineage_mismatch")
                compacted_identity = False
                if (
                    linked == binding["store_identity"]
                    and current_manifest.get("schema") == "an-kla/revision-v3"
                ):
                    try:
                        from .revision_validation import (
                            validate_manifest, validate_revision_chain,
                        )

                        validate_manifest(current_manifest, IdentityError)
                        validate_revision_chain(
                            store, current, current_manifest, IdentityError
                        )
                        compacted_identity = True
                    except Exception as exc:
                        raise IdentityError("store_identity_lineage_mismatch") from exc
                elif linked == binding["store_identity"]:
                    # A v3 descendant reaches its root through the normal chain.
                    try:
                        cursor_manifest = current_manifest
                        cursor = current
                        while cursor_manifest.get("parent") is not None:
                            cursor = str(cursor_manifest["parent"])
                            cursor_manifest = store._read_json_object("revisions", cursor)
                        if cursor_manifest.get("schema") == "an-kla/revision-v3":
                            from .revision_validation import (
                                validate_manifest, validate_revision_chain,
                            )

                            validate_manifest(current_manifest, IdentityError)
                            validate_revision_chain(
                                store, current, current_manifest, IdentityError
                            )
                            compacted_identity = True
                    except Exception as exc:
                        raise IdentityError("store_identity_lineage_mismatch") from exc
            else:
                compacted_identity = False
            if (
                current is not None
                and (
                    (
                        intent
                        and intent["stage"] == "complete"
                        and receipt is not None
                    )
                    or compacted_identity
                )
            ):
                status = "complete"
            elif current_exists:
                status = "partial_consistent"
            else:
                status = "identities_ready_root_pending"
        except IdentityError as exc:
            status, error = "conflict", str(exc)
    result = {
        "schema": "an-kla/identity-status-v1",
        "identity_status": status,
        "root_relocated": binding["root_relocated"] if binding else None,
        "error_code": error,
    }
    if include_ids and binding:
        result.update({"project_uuid": binding["project"]["project_uuid"], "store_uuid": binding["store"]["store_uuid"], "store_identity": binding["store_identity"]})
    return result


__all__ = ["IdentityError", "adopt", "assert_unchanged", "bootstrap_initialize", "identity_status", "mutation_preflight", "plan_adoption", "read_binding", "repair", "verify_current_binding", "verify_manifest_link"]
