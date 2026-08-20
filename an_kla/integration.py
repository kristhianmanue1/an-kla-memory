"""G1 (ADR-0039): observable integration status over existing axes."""

from __future__ import annotations

from typing import Any

from .context_package import context_status
from .startup import startup_diagnostic


INTEGRATION_SCHEMA = "an-kla/integration-status-v1"
SUPPORTED_PROFILES = ("agent-owned/v1", "host-managed/v1")
_CONTEXT_SCHEMA = "an-kla/context-status/v1"


def integration_status(store: Any, context_target: str = "AGENTS.md") -> dict[str, Any]:
    """Compose observable integration axes without creating anything.

    Read-only: ``store`` re-exposes ADR-0036 axes verbatim;
    ``managed_context`` re-exposes ``context-status/v1`` — when the
    context target cannot be observed (symlink, permissions), the axis
    reports ``presence: "unreadable"`` with a stable
    ``observation_error`` and exit stays 0: unreadability is a
    diagnosable state, and the error surface never leaks absolute
    paths (§11.1); ``integration`` declares what is observable and what
    is not (``unspecified`` / ``unverified``), never a fabricated
    composite state.
    """

    diagnostic = startup_diagnostic(store)
    try:
        context = context_status(str(store.project_root), context_target)
    except (OSError, ValueError) as exc:
        detail = str(exc) if isinstance(exc, ValueError) else ""
        code = detail or "context_target_unreadable"
        context = {
            "target": context_target,
            "installed": False,
            "template_version": None,
            "schema": _CONTEXT_SCHEMA,
            "ok": False,
            "diagnostics": [],
            "warnings": [],
            "_observation_error": code,
        }
    observation_error = context.pop("_observation_error", None)
    installed = bool(context.get("installed"))
    managed = {
        "target": context.get("target", context_target),
        "presence": "present" if installed else "absent",
        "template_version": context.get("template_version"),
        "context_schema": context.get("schema", _CONTEXT_SCHEMA),
        "ok": bool(context.get("ok")),
        "diagnostics": list(context.get("diagnostics", ())),
        "warnings": list(context.get("warnings", ())),
    }
    if observation_error is not None:
        managed["presence"] = "unreadable"
        managed["ok"] = False
        managed["observation_error"] = observation_error
    return {
        "schema": INTEGRATION_SCHEMA,
        "store": {
            "store_presence": diagnostic["store_presence"],
            "store_integrity": diagnostic["store_integrity"],
            "integrity_detail": diagnostic["integrity_detail"],
            "identity": diagnostic["identity"],
            "repo_context": diagnostic["repo_context"],
            "external_memory_evaluated": diagnostic["external_memory_evaluated"],
        },
        "managed_context": managed,
        "integration": {
            "supported_profiles": list(SUPPORTED_PROFILES),
            "observed_profile": "unspecified",
            "agent_binding": "unverified",
            "sharing_boundary": "filesystem-access/unverified",
            "host_hooks_evaluated": False,
        },
    }


__all__ = ["INTEGRATION_SCHEMA", "SUPPORTED_PROFILES", "integration_status"]
