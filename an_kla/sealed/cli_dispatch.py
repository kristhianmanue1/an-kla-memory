"""Dispatcher dual export/restore + flags CLI del perfil sellado — T5 de #46.

Norma vinculante: ADR-0042 ``docs/architecture/0042-sealed-export-v1.md``
§2 (gramática CLI congelada), §3 (dispatcher dual y nota de versión de
``unsupported_export_profile``), §5 (fail-closed, sin downgrade) y §8
(verify dual). Este módulo SOLO es WIRING: conecta la capa bundle de T4
(``an_kla.sealed.bundle``) y el runner de T3
(``an_kla.sealed.key_adapter``) con la superficie CLI existente. NO
reimplementa criptografía ni reescribe bundle/kdf/cek/key_adapter.

Reglas implementadas (cumplimiento LITERAL de la tarjeta):

- ``create`` sin ``--seal`` es EXACTAMENTE el camino ``export/v1``:
  delega en :func:`an_kla.export_restore.create_export` sin tocar nada
  (flags de adaptador ignorados — cambiar el camino v1 está prohibido).
  ``--seal sealed-export/v1`` (enum cerrado de un elemento) exige
  adaptador (``sealing_adapter_required``) y llama a
  :func:`an_kla.sealed.bundle.create_sealed_bundle`.
- ``--key-adapter`` argv estructurado SIN shell (§2/§4): ejecutable
  separado + ``--key-adapter-arg`` repetibles → ``argv = [bin, *args]``.
  PROHIBIDO aceptar un string con espacios y hacer split: el separador es
  estructural, no sintáctico → rechazo ``sealing_key_adapter_spaces_forbidden``.
- Dispatcher dual para verify/restore: elige camino por el ``profile`` del
  manifiesto. Manifiesto sellado presentado pidiendo camino v1 (o perfil
  desconocido) → ``unsupported_export_profile`` (§3: el código es del
  dispatcher dual nuevo; el lector beta.17 sin dispatcher responde
  ``export_manifest_invalid`` — ambos fallan cerrado). Manifiesto ilegible
  → camino v1, que emite su error canónico ``export_manifest_invalid``.
- Jamás hay degradación a claro (§5): restore sellado sin adaptador falla
  cerrado con ``sealing_adapter_required``; sin extra,
  ``sealing_extra_not_installed`` (lazy, dentro de la capa T4).
- verify dual (§8): sin ``--key-adapter`` la verificación de un bundle
  sellado es estructural — ``verified`` JAMÁS ``true``; con adaptador,
  autenticada (AEAD + ``manifest_mac`` + ``content_sha256`` del plano).
- Warnings §7 SIN cruce posible: cada camino produce los suyos (v1 conserva
  ``plaintext_export_contains_untrusted_memory_data`` intacto; sellado emite
  ``sealed_export_untrusted_memory_data``; verify sin clave
  ``sealed_payloads_unverified_without_key``). Este módulo jamás los altera.

Import stdlib-only: el paquete sigue siendo importable sin ``cryptography``;
los errores sellados son perezosos (los lanza la capa T4 al cifrar).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from an_kla.export_io import ExportIOError, safe_read
from an_kla.export_restore import (
    PROFILE as V1_PROFILE,
    create_export,
    restore_export,
    verify_export,
)
from an_kla.sealed.bundle import (
    SEALED_PROFILE,
    create_sealed_bundle,
    restore_sealed_bundle,
    verify_sealed_bundle,
)
from an_kla.sealed.key_adapter import (
    SealingAdapterRequiredError,
    SealingAdapterRunner,
)

__all__ = [
    "KEY_ADAPTER_SPACES_CODE", "SUPPORTED_PROFILES", "UNSUPPORTED_PROFILE_CODE",
    "adapter_runner", "dispatch_export_create", "dispatch_export_restore",
    "dispatch_export_verify",
]

#: Perfiles soportados por la superficie export/restore (§2).
SUPPORTED_PROFILES = (V1_PROFILE, SEALED_PROFILE)

#: Código del dispatcher dual ante downgrade o perfil desconocido (§3/§5).
UNSUPPORTED_PROFILE_CODE = "unsupported_export_profile"

#: Rechazo del string con espacios en ``--key-adapter`` (§2: prohibido el
#: split — el separador es estructural, no sintáctico).
KEY_ADAPTER_SPACES_CODE = "sealing_key_adapter_spaces_forbidden"

_ADAPTER_REQUIRED_MSG = (
    "sealing requires an external key adapter: no adapter command was specified"
)


def adapter_runner(
    key_adapter: str | None,
    key_adapter_args: "list[str] | tuple[str, ...] | None" = None,
    key_adapter_env: "list[str] | tuple[str, ...] | None" = None,
) -> SealingAdapterRunner:
    """Construye el runner desde los flags CLI (argv estructurado, §2/§4).

    - ``key_adapter`` ausente → ``SealingAdapterRequiredError``
      (``sealing_adapter_required``, §5: fail-closed, nunca claro).
    - ``key_adapter`` con espacios → ``ValueError``(
      ``sealing_key_adapter_spaces_forbidden``): PROHIBIDO el split; el
      separador es el flag repetible ``--key-adapter-arg``, no la sintaxis.
    - ``argv = [bin, *args]`` SIN shell; los args repetibles conservan sus
      espacios como UN elemento de argv (el runner T3 no usa shell jamás).
    - ``key_adapter_env``: allowlist de NOMBRES de variables (F3, §4).
    """

    if key_adapter is None:
        raise SealingAdapterRequiredError(_ADAPTER_REQUIRED_MSG)
    if not isinstance(key_adapter, str) or any(
        character.isspace() for character in key_adapter
    ):
        raise ValueError(KEY_ADAPTER_SPACES_CODE)
    args = list(key_adapter_args or ())
    if not all(isinstance(item, str) for item in args):
        raise ValueError(KEY_ADAPTER_SPACES_CODE)
    return SealingAdapterRunner(
        [key_adapter, *args], env_allowlist=list(key_adapter_env or ())
    )


def _peek_profile(bundle: str | Path) -> str | None:
    """Lee SOLO el ``profile`` del manifiesto (sin validarlo todo).

    ``None`` = manifiesto ilegible (el camino v1 emite entonces su error
    canónico ``export_manifest_invalid``); ``""`` = legible pero sin
    ``profile`` válido → perfil desconocido para el dispatcher dual.
    """

    try:
        raw = safe_read(Path(bundle), "manifest.json")
        manifest = json.loads(raw)
    except (OSError, ExportIOError, ValueError):
        return None
    if isinstance(manifest, dict):
        profile = manifest.get("profile")
        if isinstance(profile, str):
            return profile
    return ""


def _dispatch_profile(bundle: str | Path, seal_requested: str | None) -> str:
    """Perfil del camino a seguir (§3): por el manifiesto, salvo pedido
    explícito. Sellado pidiendo v1, v1 pidiendo sellado o perfil
    desconocido → ``unsupported_export_profile`` (downgrade estructuralmente
    imposible; ambos fallan cerrado)."""

    profile = _peek_profile(bundle)
    if profile is None:
        profile = V1_PROFILE
    if profile not in SUPPORTED_PROFILES:
        raise ExportIOError(UNSUPPORTED_PROFILE_CODE)
    if seal_requested is not None and seal_requested != profile:
        raise ExportIOError(UNSUPPORTED_PROFILE_CODE)
    return profile


def dispatch_export_create(
    store: Any,
    bundle: str | Path,
    *,
    seal: str | None = None,
    key_adapter: str | None = None,
    key_adapter_args: "list[str] | tuple[str, ...] | None" = None,
    key_adapter_env: "list[str] | tuple[str, ...] | None" = None,
    _runner_override: Any = None,
) -> dict[str, Any]:
    """``export create`` dual (§2): sin ``--seal`` EXACTAMENTE ``export/v1``.

    Con ``--seal sealed-export/v1``: exige adaptador (fail-closed §5) y
    delega en :func:`create_sealed_bundle` (resultado
    ``an-kla/export-result-v2`` con ``bundle_id`` + ``manifest_sha256``
    como anclas fuera de línea, §2/Límites; warnings §7 sellados).

    ``_runner_override`` es SOLO para tests: inyecta un runner/adaptador
    con la misma superficie (p. ej. en memoria); el camino CLI real
    construye el runner T3 desde los flags.
    """

    if seal is None:
        # Camino v1 EXACTO: los flags de adaptador no alteran nada aquí.
        return create_export(store, bundle)
    if seal == SEALED_PROFILE:
        runner = _runner_override if _runner_override is not None else (
            adapter_runner(key_adapter, key_adapter_args, key_adapter_env)
        )
        return create_sealed_bundle(store, bundle, runner)
    raise ExportIOError(UNSUPPORTED_PROFILE_CODE)


def dispatch_export_verify(
    bundle: str | Path,
    *,
    seal: str | None = None,
    key_adapter: str | None = None,
    key_adapter_args: "list[str] | tuple[str, ...] | None" = None,
    key_adapter_env: "list[str] | tuple[str, ...] | None" = None,
    _runner_override: Any = None,
) -> dict[str, Any]:
    """``export verify`` dual (§8).

    Bundle v1 → :func:`verify_export` sin cambios (warning v1 intacto).
    Bundle sellado: sin ``--key-adapter`` verificación ESTRUCTURAL —
    ``verified`` JAMÁS ``true``, enum cerrado de ``diagnostics`` §8; con
    adaptador, verificación autenticada (todo fallo =
    ``sealed_payload_auth_failed``, §5). ``_runner_override``: solo tests.
    """

    profile = _dispatch_profile(bundle, seal)
    if profile == V1_PROFILE:
        return verify_export(bundle)
    runner: Any = None
    if _runner_override is not None:
        runner = _runner_override
    elif key_adapter is not None:
        runner = adapter_runner(key_adapter, key_adapter_args, key_adapter_env)
    return verify_sealed_bundle(bundle, runner=runner)


def dispatch_export_restore(
    bundle: str | Path,
    project_root: str | Path,
    *,
    seal: str | None = None,
    key_adapter: str | None = None,
    key_adapter_args: "list[str] | tuple[str, ...] | None" = None,
    key_adapter_env: "list[str] | tuple[str, ...] | None" = None,
    _runner_override: Any = None,
) -> dict[str, Any]:
    """``export restore`` dual (§3): sellado JAMÁS restaurable por camino v1.

    Bundle v1 → :func:`restore_export` sin cambios. Bundle sellado: exige
    adaptador (``sealing_adapter_required``) y extra
    (``sealing_extra_not_installed``, lazy) — sin degradación a claro;
    tras desencriptar, semántica/no-overwrite/no-merge idénticos a v1 (T4).
    ``_runner_override``: solo tests.
    """

    profile = _dispatch_profile(bundle, seal)
    if profile == V1_PROFILE:
        return restore_export(bundle, project_root)
    runner = _runner_override if _runner_override is not None else (
        adapter_runner(key_adapter, key_adapter_args, key_adapter_env)
    )
    return restore_sealed_bundle(bundle, project_root, runner=runner)
