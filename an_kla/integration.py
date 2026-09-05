"""G1 (ADR-0039): observable integration status over existing axes.

G2 (ADR-0047 §5): `integration-status-v2` añade el bloque `host_hooks`
y computa `observed_profile` con la declaración del host. v1 permanece
byte-idéntico y es la emisión por defecto (los goldens legacy y los
scripts de upgrade con wheels pinneadas siguen verificando v1); v2 es
opt-in vía `--schema-version v2`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .context_package import context_status
from .host_hooks import load_declaration
from .startup import startup_diagnostic


INTEGRATION_SCHEMA = "an-kla/integration-status-v1"
INTEGRATION_SCHEMA_V2 = "an-kla/integration-status-v2"
SUPPORTED_PROFILES = ("agent-owned/v1", "host-managed/v1")
OBSERVED_PROFILES_V2 = (
    "unspecified",
    "declared-not-invoked",
    "host-managed/v1",
)
HOOK_RECENCY_HOURS = 24
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


def integration_status_v2(
    store: Any,
    context_target: str = "AGENTS.md",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compose `integration-status-v2` (ADR-0047 §5), read-only.

    Re-expone los bloques `store`/`managed_context` de v1 verbatim y
    añade `host_hooks`. El perfil observado se calcula, jamás se
    persiste: sin declaración bien formada -> `unspecified`; con ella y
    sin evidencia de invocación verificada -> `declared-not-invoked`
    (F3-C añadirá la lectura de `.an-kla/hook-runs/`; hasta entonces la
    evidencia no puede existir porque no hay escritor). `now` inyecta el
    reloj para la recencia (HOOK_RECENCY_HOURS); nunca `datetime.now`
    escondido.
    """
    base = integration_status(store, context_target)
    del now  # recencia: se aplica cuando F3-C aporte la lectura de runs
    declaration = load_declaration(store.project_root)
    if declaration["declaration"] == "well_formed":
        observed_profile = "declared-not-invoked"
        pending = (
            "required"
            if any(
                hook.get("required") is True
                and hook.get("trigger") == "material_close_or_handoff"
                for hook in declaration["hooks"]
            )
            else "none"
        )
    else:
        observed_profile = "unspecified"
        pending = "none"
    return {
        "schema": INTEGRATION_SCHEMA_V2,
        "store": base["store"],
        "managed_context": base["managed_context"],
        "integration": {
            "supported_profiles": list(SUPPORTED_PROFILES),
            "observed_profile": observed_profile,
            "agent_binding": "unverified",
            "sharing_boundary": "filesystem-access/unverified",
            "host_hooks_evaluated": True,
        },
        "host_hooks": {
            "declaration": declaration["declaration"],
            "reason_codes": declaration["reason_codes"],
            "hook_declared": [
                hook["id"] for hook in declaration["hooks"]
            ],
            "hook_invoked": [],
            "unknown_hooks": [],
            "pending_continuity": pending,
            "degraded_codes": [],
        },
    }


__all__ = [
    "HOOK_RECENCY_HOURS",
    "INTEGRATION_SCHEMA",
    "INTEGRATION_SCHEMA_V2",
    "OBSERVED_PROFILES_V2",
    "SUPPORTED_PROFILES",
    "integration_status",
    "integration_status_v2",
]
