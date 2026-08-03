"""Governed, agent-facing project upgrade workflow.

Package installation remains the responsibility of an external package manager.
This module only plans and applies the context integration owned by AN-KLA.
"""

from __future__ import annotations

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


def _require_installed_target(target_release: str) -> None:
    try:
        target_version = normalized_release_tag(target_release)
    except ValueError:
        raise ValueError("unsupported_upgrade_target") from None
    if target_version != VERSION:
        raise ValueError("upgrade_target_not_installed")


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
    core = {
        "profile": UPGRADE_PROFILE,
        "target_release": target_release,
        "installed_version": VERSION,
        "package_action": "already_installed",
        "context_operation": operation,
        "context_target": context_target,
        "context_template_version": TEMPLATE_VERSION,
        "context_plan_sha256": digest_json(context_plan),
    }
    return {
        "schema": UPGRADE_PLAN_SCHEMA,
        "core": core,
        "context_plan": context_plan,
        "plan_fingerprint": digest_json(core),
    }


def _validate_plan(plan: Any, expected_fingerprint: str) -> dict[str, Any]:
    if not isinstance(plan, dict) or set(plan) != _PLAN_KEYS:
        raise ValueError("invalid_upgrade_plan")
    core = plan.get("core")
    context_plan = plan.get("context_plan")
    fingerprint = plan.get("plan_fingerprint")
    if (
        plan.get("schema") != UPGRADE_PLAN_SCHEMA
        or not isinstance(core, dict)
        or set(core) != _CORE_KEYS
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
) -> dict[str, Any]:
    """Revalidate and apply the exact context plan under its existing lock."""
    checked = _validate_plan(plan, expected_fingerprint)
    result = apply_context_plan(project_root, checked["context_plan"])
    verification = verify_upgrade(
        project_root,
        checked["core"]["target_release"],
        checked["core"]["context_target"],
    )
    return {
        "schema": UPGRADE_RESULT_SCHEMA,
        "profile": UPGRADE_PROFILE,
        "plan_fingerprint": checked["plan_fingerprint"],
        "context_result": result,
        "verification": verification,
        "ok": verification["ok"],
    }


__all__ = [
    "UPGRADE_PLAN_SCHEMA",
    "UPGRADE_PROFILE",
    "apply_upgrade",
    "inspect_upgrade",
    "verify_upgrade",
]
