"""host_hooks.py — lectura y validación de la declaración de hooks del host.

Contrato: ADR-0047 §1 (`.an-kla/host-hooks.json`, host escribe, AN-KLA
sólo lee). Módulo puro: sin reloj, sin red, sin escritura, sin lock. La
degradación es diagnosticable y jamás lanza: ausencia, ilegibilidad o
malformación devuelven un eje `declaration` con códigos estables y sin
filtrar rutas (precedente ADR-0039:66-70).

Límites congelados (ADR-0047 §1): máximo 16 hooks; id 1-128 de
[A-Za-z0-9._-] y únicos; budget_bytes entero 1..1048576 (bool excluido);
fingerprint `^sha256:[0-9a-f]{64}$`; `required` sólo con sentido en
`checkpoint`; sin campos adicionales. La verificación cruzada de
`required` y los ids duplicados no son expresables en el schema JSON
publicado (`an-kla/host-hooks-v1`) y viven aquí.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

DECLARATION_SCHEMA = "an-kla/host-hooks-v1"
DECLARATION_FILE = "host-hooks.json"
DECLARED_PROFILE = "host-managed/v1"

MAX_HOOKS = 16
ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
FINGERPRINT_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
BUDGET_MIN = 1
BUDGET_MAX = 1048576

TRIGGERS = ("before_task", "material_close_or_handoff")
ACTIONS = ("assemble-context", "retrieve", "checkpoint", "status")

_ADAPTER_KEYS = ("name", "version", "configuration_fingerprint")
_HOOK_KEYS = ("id", "trigger", "action", "budget_bytes", "required")


def declaration_path(project_root) -> Path:
    return Path(project_root) / ".an-kla" / DECLARATION_FILE


def load_declaration(project_root) -> dict:
    """Lee y valida la declaración sin mutar nada ni lanzar.

    Devuelve un dict con eje `declaration` (`absent | invalid |
    well_formed`), `reason_codes` estables (sin rutas) y, en caso
    well_formed, `adapter`, `declared_profile` y `hooks` verbatim del
    archivo (dato no confiable; el caller nunca lo trata como autoridad).
    """
    path = declaration_path(project_root)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _status("absent", ["host_hooks_absent"])
    except UnicodeDecodeError:
        return _status("invalid", ["host_hooks_invalid_json"])
    except OSError:
        return _status("invalid", ["host_hooks_unreadable"])
    try:
        candidate = json.loads(raw)
    except json.JSONDecodeError:
        return _status("invalid", ["host_hooks_invalid_json"])
    codes = validate(candidate)
    if codes:
        return _status("invalid", codes)
    return {
        "declaration": "well_formed",
        "reason_codes": [],
        "adapter": candidate["adapter"],
        "declared_profile": candidate["declared_profile"],
        "hooks": candidate["hooks"],
    }


def validate(candidate) -> list:
    """Valida un candidato ya parseado; devuelve códigos estables vacíos
    si es bien formado. Nunca lanza ante tipos arbitrarios."""
    codes: list = []
    if not isinstance(candidate, dict):
        return ["host_hooks_not_an_object"]
    if candidate.get("schema") != DECLARATION_SCHEMA:
        codes.append("host_hooks_schema_unknown")

    adapter = candidate.get("adapter")
    if not isinstance(adapter, dict) or set(adapter) != set(_ADAPTER_KEYS):
        codes.append("host_hooks_adapter_invalid")
    else:
        if not _is_bounded_string(adapter["name"], 128):
            codes.append("host_hooks_adapter_name_invalid")
        if not _is_bounded_string(adapter["version"], 64):
            codes.append("host_hooks_adapter_version_invalid")
        if not isinstance(adapter["configuration_fingerprint"], str) or not (
            FINGERPRINT_PATTERN.match(adapter["configuration_fingerprint"])
        ):
            codes.append("host_hooks_adapter_fingerprint_invalid")

    if candidate.get("declared_profile") != DECLARED_PROFILE:
        codes.append("host_hooks_profile_unknown")

    hooks = candidate.get("hooks")
    if not isinstance(hooks, list):
        codes.append("host_hooks_hooks_invalid")
        return codes
    if len(hooks) > MAX_HOOKS:
        codes.append("host_hooks_hooks_count_exceeds_limit")

    seen_ids: set = set()
    for index, hook in enumerate(hooks):
        prefix = f"hook_{index}_"
        if not isinstance(hook, dict) or not set(_HOOK_KEYS) >= set(hook):
            codes.append(prefix + "shape_invalid")
            continue
        identifier = hook.get("id")
        if not isinstance(identifier, str) or not ID_PATTERN.match(identifier):
            codes.append(prefix + "id_invalid")
        elif identifier in seen_ids:
            codes.append("duplicate_hook_id")
        else:
            seen_ids.add(identifier)
        if hook.get("trigger") not in TRIGGERS:
            codes.append(prefix + "trigger_unknown")
        action = hook.get("action")
        if action not in ACTIONS:
            codes.append(prefix + "action_unknown")
        budget = hook.get("budget_bytes")
        if budget is not None and (
            isinstance(budget, bool)
            or not isinstance(budget, int)
            or not BUDGET_MIN <= budget <= BUDGET_MAX
        ):
            codes.append(prefix + "budget_bytes_out_of_range")
        required = hook.get("required")
        if required is not None:
            if not isinstance(required, bool):
                codes.append(prefix + "required_not_boolean")
            elif required and action != "checkpoint":
                codes.append(prefix + "required_on_non_checkpoint")
    return codes


def _status(declaration: str, reason_codes: list) -> dict:
    return {
        "declaration": declaration,
        "reason_codes": sorted(reason_codes),
        "adapter": None,
        "declared_profile": None,
        "hooks": [],
    }


def _is_bounded_string(value, max_length: int) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= max_length
        and value.strip() != ""
    )
