"""Governed, agent-facing project upgrade workflow.

Package installation remains the responsibility of an external package manager.
This module only plans and applies the context integration owned by AN-KLA.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .canonical import digest_json
from .context_package import (
    TEMPLATE_VERSION,
    apply_context_plan,
    context_status,
    plan_context_change,
)
from .store import MemoryStore
from .version import VERSION, normalized_release_tag


UPGRADE_PLAN_SCHEMA = "an-kla/upgrade-plan-v1"
UPGRADE_PLAN_SCHEMA_V2 = "an-kla/upgrade-plan-v2"
UPGRADE_RESULT_SCHEMA = "an-kla/upgrade-apply-result/v1"
UPGRADE_VERIFY_SCHEMA = "an-kla/upgrade-verify-result/v1"
UPGRADE_PROFILE = "project-context-upgrade/v1"

_PLAN_KEYS = {"schema", "core", "context_plan", "plan_fingerprint"}
_CORE_KEYS = {
    "profile",
    "target_release",
    "installed_version",
    "package_action",
    "context_operation",
    "context_target",
    "context_template_version",
    "context_plan_sha256",
}
# v2 adds an optional ``target_drift`` object to ``core``.  Both schemas are
# accepted on read so a v1 plan generated before beta.5 remains applicable.
_CORE_KEYS_V2 = _CORE_KEYS | {"target_drift"}


def _require_installed_target(target_release: str) -> None:
    try:
        target_version = normalized_release_tag(target_release)
    except ValueError:
        raise ValueError("unsupported_upgrade_target") from None
    if target_version != VERSION:
        raise ValueError("upgrade_target_not_installed")


def _detect_target_drift(
    project_root: str | Path, context_target: str
) -> dict[str, Any]:
    """Surface drift between the manifest baseline and the current target.

    A drift ``outside_managed_block`` exists when the bytes of the target on
    disk no longer match the ``target_sha256`` recorded in the local manifest
    (i.e. someone edited content outside the managed block since install).
    Without this signal the upgrade would absorb the drift silently when it
    rebuilds the manifest baseline; see ADR-0017.
    """

    from .context_package import (
        _load_manifest,
        _observed_sha,
        _project_root,
        _read_utf8,
        _target_path,
    )

    root = _project_root(project_root)
    target_path = _target_path(root, context_target)
    target_bytes, _ = _read_utf8(target_path)
    observed = _observed_sha(target_bytes)
    manifest = _load_manifest(root)
    if manifest is None:
        return {
            "outside_managed_block": False,
            "manifest_target_sha256_at_install": None,
            "observed_target_sha256": observed,
            "managed_content_sha256": None,
            "will_be_absorbed_by_apply": False,
        }
    manifest_target = manifest.get("target_sha256")
    drifted = (
        isinstance(manifest_target, str)
        and isinstance(observed, str)
        and manifest_target != observed
    )
    return {
        "outside_managed_block": bool(drifted),
        "manifest_target_sha256_at_install": manifest_target,
        "observed_target_sha256": observed,
        "managed_content_sha256": manifest.get("managed_content_sha256"),
        "will_be_absorbed_by_apply": bool(drifted),
    }


def inspect_upgrade(
    project_root: str | Path,
    target_release: str,
    context_target: str = "AGENTS.md",
) -> dict[str, Any]:
    """Build a deterministic, non-mutating plan for the installed release."""
    _require_installed_target(target_release)
    status = context_status(project_root, context_target)
    operation = "update" if status["installed"] else "install"
    context_plan = plan_context_change(project_root, operation, context_target)
    target_drift = _detect_target_drift(project_root, context_target)
    core = {
        "profile": UPGRADE_PROFILE,
        "target_release": target_release,
        "installed_version": VERSION,
        "package_action": "already_installed",
        "context_operation": operation,
        "context_target": context_target,
        "context_template_version": TEMPLATE_VERSION,
        "context_plan_sha256": digest_json(context_plan),
        "target_drift": target_drift,
    }
    return {
        "schema": UPGRADE_PLAN_SCHEMA_V2,
        "core": core,
        "context_plan": context_plan,
        "plan_fingerprint": digest_json(core),
    }


def _validate_plan(plan: Any, expected_fingerprint: str) -> dict[str, Any]:
    if not isinstance(plan, dict) or set(plan) != _PLAN_KEYS:
        raise ValueError("invalid_upgrade_plan")
    schema = plan.get("schema")
    core = plan.get("core")
    context_plan = plan.get("context_plan")
    fingerprint = plan.get("plan_fingerprint")
    if (
        schema not in {UPGRADE_PLAN_SCHEMA, UPGRADE_PLAN_SCHEMA_V2}
        or not isinstance(core, dict)
        or set(core) not in (_CORE_KEYS, _CORE_KEYS_V2)
        or not isinstance(context_plan, dict)
        or not isinstance(fingerprint, str)
        or fingerprint != expected_fingerprint
        or digest_json(core) != fingerprint
        or digest_json(context_plan) != core.get("context_plan_sha256")
        or core.get("profile") != UPGRADE_PROFILE
        or core.get("installed_version") != VERSION
        or core.get("package_action") != "already_installed"
        or context_plan.get("operation") != core.get("context_operation")
        or context_plan.get("target") != core.get("context_target")
        or context_plan.get("template_version")
        != core.get("context_template_version")
    ):
        raise ValueError("invalid_upgrade_plan")
    # When a v2 plan carries target_drift, the field must be well-formed.
    target_drift = core.get("target_drift")
    if target_drift is not None:
        if not isinstance(target_drift, dict) or set(target_drift) != {
            "outside_managed_block",
            "manifest_target_sha256_at_install",
            "observed_target_sha256",
            "managed_content_sha256",
            "will_be_absorbed_by_apply",
        }:
            raise ValueError("invalid_upgrade_plan")
        if not isinstance(target_drift["outside_managed_block"], bool) or not isinstance(
            target_drift["will_be_absorbed_by_apply"], bool
        ):
            raise ValueError("invalid_upgrade_plan")
    target_release = core.get("target_release")
    if not isinstance(target_release, str):
        raise ValueError("invalid_upgrade_plan")
    _require_installed_target(target_release)
    return plan


def verify_upgrade(
    project_root: str | Path,
    target_release: str,
    context_target: str = "AGENTS.md",
) -> dict[str, Any]:
    """Verify the installed release, managed context, and memory when present."""
    _require_installed_target(target_release)
    context = context_status(project_root, context_target)
    store = MemoryStore(project_root)
    if store.current_path.exists():
        memory: dict[str, Any] = {"status": "verified", "verification": store.verify()}
    else:
        memory = {"status": "not_initialized"}
    return {
        "schema": UPGRADE_VERIFY_SCHEMA,
        "profile": UPGRADE_PROFILE,
        "target_release": target_release,
        "installed_version": VERSION,
        "context": context,
        "memory": memory,
        "ok": context["ok"] and memory["status"] in {"verified", "not_initialized"},
    }


def apply_upgrade(
    project_root: str | Path,
    plan: Any,
    expected_fingerprint: str,
    *,
    confirm_target_drift: bool = False,
) -> dict[str, Any]:
    """Revalidate and apply the exact context plan under its existing lock.

    When the plan reports ``target_drift.outside_managed_block == true`` the
    apply fails closed unless the caller passes ``confirm_target_drift=True``.
    The successful result declares the absorbed baseline so the operator has
    an explicit record of what was promoted; see ADR-0017.
    """
    checked = _validate_plan(plan, expected_fingerprint)
    target_drift = checked["core"].get("target_drift")
    drift_detected = bool(target_drift and target_drift.get("outside_managed_block"))
    if drift_detected and not confirm_target_drift:
        raise ValueError("target_drift_requires_confirmation")
    pre_apply_drift = (
        deepcopy(target_drift) if target_drift is not None else None
    )
    result = apply_context_plan(project_root, checked["context_plan"])
    verification = verify_upgrade(
        project_root,
        checked["core"]["target_release"],
        checked["core"]["context_target"],
    )
    response: dict[str, Any] = {
        "schema": UPGRADE_RESULT_SCHEMA,
        "profile": UPGRADE_PROFILE,
        "plan_fingerprint": checked["plan_fingerprint"],
        "context_result": result,
        "verification": verification,
        "ok": verification["ok"],
    }
    if pre_apply_drift is not None:
        response["target_drift"] = pre_apply_drift
        if drift_detected:
            response["warnings"] = ["target_drift_absorbed_into_new_baseline"]
    return response


__all__ = [
    "UPGRADE_PLAN_SCHEMA",
    "UPGRADE_PLAN_SCHEMA_V2",
    "UPGRADE_PROFILE",
    "apply_upgrade",
    "inspect_upgrade",
    "verify_upgrade",
]
