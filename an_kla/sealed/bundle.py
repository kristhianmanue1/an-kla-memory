"""Cifrado del bundle sellado (``sealed-export/v1``) — T4 de issue #46.

Norma: ADR-0042 §2/§6/§9, cumplimiento LITERAL. SOLO la capa de bundle
(CLI/dispatcher dual/warnings son T5/T6). Reglas congeladas §6:
``entry_nonce(i) = i.to_bytes(12,"big")`` (contador 0-based del orden
canónico de ``core.entries``, NUNCA en disco); AAD = UTF8 del perfil ||
``bundle_id_raw`` (16 bytes crudos) || ``canonical_json(entry)``;
``manifest_mac = HMAC-SHA256(mac_key, canonical_json(T))``, T = {schema,
profile, seal_sin_manifest_mac, core, manifest_sha256}, hex minúsculo 64
chars, comparado con ``hmac.compare_digest`` (jamás ``==``); layout físico
``entries/<path>`` con tamaño ``entry.size + 16`` (tag GCM).

``create_sealed_bundle`` publica vía staging+renombrado atómico (F6);
``verify_sealed_bundle`` con clave verifica AEAD + ``manifest_mac`` +
``content_sha256`` del plano (sin clave SOLO estructura, jamás ``verified:
true``, §8); ``restore_sealed_bundle`` desencripta TODO antes de tocar
destino (semántica idéntica a v1, sin restauración parcial). En toda
verificación autenticada ``bundle_id`` se RECALCULA desde la CEK — el
manifiesto jamás se confía. F7: CEK/subclaves jamás en bundle, staging,
resultados ni errores; ``sealed_payload_auth_failed`` es código único sin
oráculo (§5). Sin ``cryptography`` falla cerrado con
``sealing_extra_not_installed``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
from typing import Any

from an_kla.canonical import canonical_json, digest_bytes, digest_json
from an_kla.export_io import (
    ExportIOError,
    normalize_and_sync_tree,
    rename_noreplace,
    safe_read,
)
# Política de enumeración/rutas de v1 reutilizada (fuente única; el camino
# sellado NO redefine qué exporta el store ni modifica nada del camino v1).
from an_kla.export_restore import _allowed, _files
from an_kla.identity import identity_lock
from an_kla.sealed.cek import generate_cek
from an_kla.sealed.kdf import BUNDLE_ID_RAW_LENGTH, derive_subkeys

__all__ = [
    "AAD_PREFIX", "GCM_TAG_BYTES", "MAX_ENTRY_BYTES", "NONCE_BYTES",
    "SEALED_PROFILE", "SEALED_WARNING", "UNKEYED_VERIFY_WARNING",
    "SealedAdapterIdInvalidError", "SealedEntryTooLargeError",
    "SealedPayloadAuthFailedError", "compute_manifest_mac",
    "create_sealed_bundle", "entry_aad", "entry_nonce", "manifest_transcript",
    "restore_sealed_bundle", "verify_manifest_mac", "verify_sealed_bundle",
]

#: Perfil sellado del ADR (enum cerrado de un elemento en la superficie CLI).
SEALED_PROFILE = "sealed-export/v1"

#: Advertencia sellada (§7): confidencialidad en reposo, NO veracidad.
#: La del verify sin clave (§8) jamás afirma autenticidad.
SEALED_WARNING = "sealed_export_untrusted_memory_data"
UNKEYED_VERIFY_WARNING = "sealed_payloads_unverified_without_key"

MANIFEST_SCHEMA = "an-kla/export-manifest-v2"  # schema del manifiesto v2 (§2)

#: AAD por entrada: UTF8("sealed-export/v1") (§6, congelado).
AAD_PREFIX: bytes = b"sealed-export/v1"

NONCE_BYTES = 12   # contador puro big-endian (§6, congelado al byte)
GCM_TAG_BYTES = 16  # tag GCM del layout físico (§6)
MAX_ENTRY_BYTES = 512 * 1024 * 1024  # techo por entrada (§6); sin chunking

#: Límites heredados de v1 (§6). Dominio del contador: 0 <= i < 2**96,
#: acotado por max_files.
MAX_FILES = 100000
MAX_BUNDLE_BYTES = 10 * 1024**3
_NONCE_DOMAIN = 1 << (8 * NONCE_BYTES)

_HEX32_RE = re.compile(r"^[0-9a-f]{32}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_B64_RE = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")

#: Keys exactas del manifiesto v2 (§2) — shape de seal y core.
_SEAL_KEYS = {
    "algorithm", "kdf", "adapter_id", "wrapped_cek",
    "bundle_id", "manifest_mac",
}
_CORE_KEYS = {
    "current_revision", "project_identity_sha256",
    "store_identity_sha256", "entry_count", "total_bytes", "entries",
}

#: Mensaje ÚNICO de fallo autenticado — sin oráculo (§5): tag, tamaño,
#: CEK incorrecta y corrupción son indistinguibles a propósito.
_AUTH_FAILED_MSG = "sealed payload authentication failed (no further detail)"
_WRAPPED_CEK_MAX_CHARS = 4096  # techo de wrapped_cek (§2/§4)

#: Diagnóstico estructural (§8) -> código ExportError del camino con clave
#: (los fallos estructurales conservan los diagnósticos de v1).
_DIAGNOSTIC_TO_EXPORT_ERROR = {
    "manifest_invalid": "export_manifest_invalid",
    "unsafe_path": "export_unsafe_path",
    "entry_missing": "export_extra_or_missing_entry",
    "entry_unexpected": "export_extra_or_missing_entry",
    "count_mismatch": "export_limits_exceeded",
}


class SealedPayloadAuthFailedError(RuntimeError):
    """Fallo autenticado — UN código/mensaje, sin oráculo (§5): tag, tamaño
    físico, CEK incorrecta, ``manifest_mac`` alterado o entrada injertada
    (AAD) producen este mismo error (§9 filas 2-5, 10c).
    """

    ERROR_CODE = "sealed_payload_auth_failed"


class SealedEntryTooLargeError(RuntimeError):
    """Entrada > ``max_entry_bytes`` (512 MiB) ANTES de cifrar (§6); sin
    chunking y sin bundle parcial."""

    ERROR_CODE = "sealed_entry_too_large"


class SealedAdapterIdInvalidError(RuntimeError):
    """``adapter_id`` fuera de la gramática ASCII (§6, F4), al escribir el
    manifiesto (nota T3-N1; el runner T3 ya la valida). Metadato público."""

    ERROR_CODE = "sealing_adapter_id_invalid"


# Funciones puras congeladas (§6)


def entry_nonce(index: int) -> bytes:
    """Nonce por entrada = contador puro ``i.to_bytes(12, "big")`` (§6).
    Índice 0-based del orden canónico de ``core.entries``; dominio acotado
    por ``MAX_FILES``; fuera de dominio, error de contrato (ValueError).
    """
    if not isinstance(index, int) or isinstance(index, bool):
        raise TypeError("index must be int")
    if not 0 <= index < _NONCE_DOMAIN or index >= MAX_FILES:
        raise ValueError(f"nonce index out of domain [0, {MAX_FILES})")
    return index.to_bytes(NONCE_BYTES, "big")


def entry_aad(bundle_id_raw: bytes, entry: dict[str, Any]) -> bytes:
    """AAD por entrada (§6, congelado): UTF8(perfil) || bundle_id_raw ||
    canonical_json(entry). Reordenar/intercambiar/injertar entradas falla al
    desencriptar — chequeo estructural del propio AEAD, no validación omisible.
    """
    if not isinstance(bundle_id_raw, (bytes, bytearray)):
        raise TypeError("bundle_id_raw must be bytes")
    if len(bundle_id_raw) != BUNDLE_ID_RAW_LENGTH:
        raise ValueError("bundle_id_raw must be exactly "
                         f"{BUNDLE_ID_RAW_LENGTH} bytes, got {len(bundle_id_raw)}")
    return AAD_PREFIX + bytes(bundle_id_raw) + canonical_json(entry)


def manifest_transcript(
    seal_without_mac: dict[str, Any],
    core: dict[str, Any],
    manifest_sha256: str,
) -> dict[str, Any]:
    """Transcript T del manifiesto (§6): autentica TODO el sello, no sólo core."""
    return {
        "schema": MANIFEST_SCHEMA, "profile": SEALED_PROFILE,
        "seal": seal_without_mac, "core": core,
        "manifest_sha256": manifest_sha256,
    }


def compute_manifest_mac(mac_key: bytes, transcript: dict[str, Any]) -> str:
    """``HMAC-SHA256(mac_key, canonical_json(T))`` — hex minúsculo 64 chars.

    ``mac_key`` de exactamente 32 bytes (error de contrato del caller).
    Stdlib pura (no requiere ``cryptography``).
    """
    if not isinstance(mac_key, (bytes, bytearray)):
        raise TypeError("mac_key must be bytes")
    if len(mac_key) != 32:
        raise ValueError(f"mac_key must be exactly 32 bytes, got {len(mac_key)}")
    return hmac.new(
        bytes(mac_key), canonical_json(transcript), hashlib.sha256
    ).hexdigest()


def verify_manifest_mac(
    mac_key: bytes, transcript: dict[str, Any], expected: object
) -> bool:
    """Compara el MAC con ``hmac.compare_digest`` — JAMÁS ``==`` (§6). Un
    ``expected`` que no sea hex minúsculo de 64 chars es fallo (False), no
    excepción: no se confía, se comprueba.
    """
    if not isinstance(expected, str) or not _HEX64_RE.fullmatch(expected):
        return False
    return hmac.compare_digest(
        compute_manifest_mac(mac_key, transcript), expected
    )


# Cifrado por entrada (AES-256-GCM, import perezoso del extra)


def _require_aesgcm():
    """Import perezoso y fail-closed de ``AESGCM`` (extra ``[sealed]``)."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:  # pragma: no cover - depende del entorno
        from an_kla.sealed import SealedExtraNotInstalledError

        raise SealedExtraNotInstalledError(
            "sealed profile unavailable: the 'sealed' extra is not installed "
            "(pip install 'an-kla-memory[sealed]'); refusing to degrade to "
            "cleartext"
        ) from exc
    return AESGCM


def _check_aead_contract(aead_key: bytes, nonce: bytes) -> None:
    if not isinstance(aead_key, (bytes, bytearray)) or len(aead_key) != 32:
        raise ValueError("aead_key must be bytes of exactly 32 bytes")
    if not isinstance(nonce, (bytes, bytearray)) or len(nonce) != NONCE_BYTES:
        raise ValueError(f"nonce must be bytes of exactly {NONCE_BYTES} bytes")


def encrypt_entry(
    aead_key: bytes, nonce: bytes, plaintext: bytes, aad: bytes
) -> bytes:
    """Cifra una entrada con AES-256-GCM → ``ciphertext || tag``.

    Errores de contrato del caller (longitudes) son ``ValueError``/
    ``TypeError`` ANTES del import del extra.
    """
    _check_aead_contract(aead_key, nonce)
    aesgcm_cls = _require_aesgcm()
    return aesgcm_cls(bytes(aead_key)).encrypt(
        bytes(nonce), bytes(plaintext), bytes(aad)
    )


def decrypt_entry(
    aead_key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes
) -> bytes:
    """Desencripta una entrada — fail-closed, SIN oráculo (§5): todo fallo
    (tag, AAD, clave, longitud) es ``SealedPayloadAuthFailedError`` uniforme.
    """
    _check_aead_contract(aead_key, nonce)
    if (
        not isinstance(ciphertext, (bytes, bytearray))
        or len(ciphertext) < GCM_TAG_BYTES
    ):
        # Longitud imposible = fallo autenticado, sin distinguir la causa.
        raise SealedPayloadAuthFailedError(_AUTH_FAILED_MSG)
    aesgcm_cls = _require_aesgcm()
    try:
        return aesgcm_cls(bytes(aead_key)).decrypt(
            bytes(nonce), bytes(ciphertext), bytes(aad)
        )
    except Exception as exc:
        raise SealedPayloadAuthFailedError(_AUTH_FAILED_MSG) from exc


# Validación de adapter_id al escribir el manifiesto (nota T3-N1)


def _validated_adapter_id(adapter_id: object) -> str:
    """Gramática cerrada §6 (F4) — reusa la validación de T3.

    Traduce el fallo a ``sealing_adapter_id_invalid`` al escribir el
    manifiesto (nota T3-N1). El mensaje NO embebe el valor recibido.
    """
    from an_kla.sealed.key_adapter import SealingAdapterError, validate_adapter_id

    try:
        return validate_adapter_id(adapter_id)
    except SealingAdapterError as exc:
        raise SealedAdapterIdInvalidError(
            "adapter_id violates the sealed-export/v1 grammar; "
            "manifest not written (sealing_adapter_id_invalid)"
        ) from exc


# Inspección estructural (sin clave) — enum cerrado de §8


def _manifest_structurally_invalid(manifest: object) -> bool:
    """Shape EXACTO del manifiesto v2 (§2): keys, consts, seal, core."""
    if not isinstance(manifest, dict):
        return True
    if set(manifest) != {"schema", "profile", "seal", "core", "manifest_sha256"}:
        return True
    if manifest["schema"] != MANIFEST_SCHEMA or manifest["profile"] != SEALED_PROFILE:
        return True
    seal = manifest["seal"]
    if not isinstance(seal, dict) or set(seal) != _SEAL_KEYS:
        return True
    if seal["algorithm"] != "aes-256-gcm" or seal["kdf"] != "hkdf-sha256":
        return True
    if not isinstance(seal["adapter_id"], str):
        return True
    wrapped = seal["wrapped_cek"]
    if not isinstance(wrapped, str) or len(wrapped) > _WRAPPED_CEK_MAX_CHARS:
        return True
    if not _B64_RE.fullmatch(wrapped):
        return True
    if not isinstance(seal["bundle_id"], str):
        return True
    if not _HEX32_RE.fullmatch(seal["bundle_id"]):
        return True
    if not isinstance(seal["manifest_mac"], str):
        return True
    if not _HEX64_RE.fullmatch(seal["manifest_mac"]):
        return True
    core = manifest["core"]
    if not isinstance(core, dict) or set(core) != _CORE_KEYS:
        return True
    if digest_json(core) != manifest["manifest_sha256"]:
        return True
    try:
        from an_kla.canonical import bare_digest

        for identifier in (
            manifest["manifest_sha256"], core["current_revision"],
            core["project_identity_sha256"], core["store_identity_sha256"],
        ):
            if not isinstance(identifier, str):
                raise ValueError("invalid_sha256_identifier")
            bare_digest(identifier)
    except (TypeError, ValueError):
        return True
    return False


def _walk_bundle_files(bundle: Path) -> tuple[set[str], set[str], list[str]]:
    """Enumera archivos/dirs reales; enlaces/especiales → ``unsafe_path``.

    Devuelve ``(files, dirs, diagnostics)``; nunca se sigue un link.
    """
    files: set[str] = set()
    dirs: set[str] = set()
    diagnostics: list[str] = []
    for base, dnames, fnames in os.walk(bundle, topdown=True, followlinks=False):
        base_path = Path(base)
        for name in [*dnames, *fnames]:
            path = base_path / name
            relative = path.relative_to(bundle).as_posix()
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                diagnostics.append("unsafe_path")
            elif stat.S_ISDIR(info.st_mode):
                dirs.add(relative)
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                files.add(relative)
            else:
                diagnostics.append("unsafe_path")
    return files, dirs, diagnostics


def _inspect_bundle(
    bundle: Path, max_files: int, max_bytes: int
) -> tuple[dict[str, Any] | None, dict[str, bytes], list[str]]:
    """Validación estructural sin desencriptar JAMÁS (§8, F5).

    ``(manifest, ciphertexts_by_path, diagnostics)``; vacíos = estructura
    válida. El tamaño físico se comprueba en los CALLERS (con clave
    ``sealed_payload_auth_failed``; sin clave ``entry_size_mismatch``).
    """
    _INV = ["manifest_invalid"]
    if bundle.is_symlink() or not bundle.is_dir():
        return None, {}, _INV
    try:
        raw = safe_read(bundle, "manifest.json")
        manifest = json.loads(raw)
    except (OSError, ExportIOError, json.JSONDecodeError, ValueError):
        return None, {}, _INV
    if not isinstance(manifest, dict) or canonical_json(manifest) != raw:
        return None, {}, _INV
    if _manifest_structurally_invalid(manifest):
        return None, {}, _INV

    core = manifest["core"]
    entries = core["entries"]
    diagnostics: list[str] = []
    if not isinstance(entries, list):
        return None, {}, _INV
    counts_ok = (
        type(core["entry_count"]) is int
        and core["entry_count"] == len(entries)
        and len(entries) <= max_files
        and type(core["total_bytes"]) is int
        and 0 <= core["total_bytes"] <= max_bytes
    )
    if not counts_ok:
        diagnostics.append("count_mismatch")
    for item in entries:
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "size", "content_sha256"}
            or not isinstance(item["path"], str)
            or type(item["size"]) is not int
            or item["size"] < 0
            or not isinstance(item["content_sha256"], str)
        ):
            return None, {}, _INV
        if not _allowed(item["path"]):
            diagnostics.append("unsafe_path")
    paths = [item["path"] for item in entries]
    folded = {p.casefold() for p in paths}
    canon = sorted(paths, key=lambda value: value.encode("utf-8"))
    if (
        len(set(paths)) != len(paths)
        or len(folded) != len(paths)
        or paths != canon
    ):
        return None, {}, _INV
    if any(diagnostics):
        return manifest, {}, diagnostics
    if sum(item["size"] for item in entries) != core["total_bytes"]:
        diagnostics.append("count_mismatch")

    expected = {"manifest.json"} | {"entries/" + path for path in paths}
    actual_files, actual_dirs, walk_diagnostics = _walk_bundle_files(bundle)
    diagnostics.extend(walk_diagnostics)
    if expected - actual_files:
        diagnostics.append("entry_missing")
    if actual_files - expected:
        diagnostics.append("entry_unexpected")
    allowed_dirs = {
        "/".join(path.split("/")[:index])
        for path in expected
        for index in range(1, len(path.split("/")))
    }
    if not actual_dirs.issubset(allowed_dirs):
        diagnostics.append("entry_unexpected")

    ciphertexts: dict[str, bytes] = {}
    if not any(diagnostics):
        for item in entries:
            try:
                ciphertexts[item["path"]] = safe_read(
                    bundle, "entries/" + item["path"])
            except (OSError, ExportIOError):
                diagnostics.append("unsafe_path")
                break
    return manifest, ciphertexts, diagnostics


# CEK y desencriptado autenticado


def _resolve_cek(cek: bytes | None, runner: object,
                 manifest: dict[str, Any]) -> bytes:
    """Obtiene la CEK: inyección directa o unwrap vía runner (T3). Longitud
    incorrecta = error de contrato (ValueError); CEK de 32 bytes pero
    equivocada = fallo autenticado al desencriptar (§5).
    """
    if cek is not None:
        if not isinstance(cek, (bytes, bytearray)) or len(cek) != 32:
            raise ValueError("cek must be bytes of exactly 32 bytes")
        return bytes(cek)
    if runner is not None:
        result = runner.unwrap_cek(manifest["seal"]["wrapped_cek"])
        cek = result.cek
        if not isinstance(cek, (bytes, bytearray)) or len(cek) != 32:
            raise SealedPayloadAuthFailedError(_AUTH_FAILED_MSG)
        return bytes(cek)
    raise ValueError("sealed operation requires cek or a key adapter runner")


def _decrypt_all(
    manifest: dict[str, Any], ciphertexts: dict[str, bytes], cek: bytes
) -> dict[str, bytes]:
    # Verificación autenticada completa (§8 con clave) — fail-closed.
    """Verificación autenticada completa (§8 con clave) — fail-closed:
    ``bundle_id`` RECALCULADO desde la CEK (compare_digest, §6);
    ``manifest_mac`` sobre el transcript canónico; por entrada tamaño físico
    ``size+16``, AEAD, ``size`` y ``content_sha256`` del plano. Todo fallo:
    un solo código (§5).
    """
    subkeys = derive_subkeys(cek)
    seal = manifest["seal"]
    if not hmac.compare_digest(subkeys.bundle_id_raw.hex(), seal["bundle_id"]):
        raise SealedPayloadAuthFailedError(_AUTH_FAILED_MSG)
    seal_without_mac = {
        key: value for key, value in seal.items() if key != "manifest_mac"
    }
    transcript = manifest_transcript(
        seal_without_mac, manifest["core"], manifest["manifest_sha256"]
    )
    if not verify_manifest_mac(subkeys.mac_key, transcript, seal["manifest_mac"]):
        raise SealedPayloadAuthFailedError(_AUTH_FAILED_MSG)
    payloads: dict[str, bytes] = {}
    for index, entry in enumerate(manifest["core"]["entries"]):
        ciphertext = ciphertexts[entry["path"]]
        if len(ciphertext) != entry["size"] + GCM_TAG_BYTES:
            raise SealedPayloadAuthFailedError(_AUTH_FAILED_MSG)
        plaintext = decrypt_entry(
            subkeys.aead_key, entry_nonce(index), ciphertext,
            entry_aad(subkeys.bundle_id_raw, entry),
        )
        sha = entry["content_sha256"]
        if len(plaintext) != entry["size"] or digest_bytes(plaintext) != sha:
            raise SealedPayloadAuthFailedError(_AUTH_FAILED_MSG)
        payloads[entry["path"]] = plaintext
    return payloads


def _identity_crosscheck(manifest: dict[str, Any], payloads: dict[str, bytes]) -> None:
    """Chequeos semánticos de v1 sobre el plano desencriptado."""
    core = manifest["core"]
    by_path = {item["path"]: item for item in core["entries"]}
    project_ok = (
        by_path.get("anchor/project-identity.json", {}).get("content_sha256")
        == core["project_identity_sha256"]
    )
    store_ok = (
        by_path.get("anchor/memory/identity.json", {}).get("content_sha256")
        == core["store_identity_sha256"]
    )
    if not (project_ok and store_ok):
        raise ExportIOError("export_identity_mismatch")
    current = payloads["anchor/memory/refs/CURRENT"].decode("ascii").strip()
    if current != core["current_revision"]:
        raise ExportIOError("export_current_mismatch")


# create sellado (staging + renombrado atómico — F6)


def create_sealed_bundle(store: Any, bundle: str | Path, runner: Any) -> dict:
    """Crea un bundle sellado ``sealed-export/v1`` (§2/§6, filas §9-7/13).

    CEK efímera (T2) + ``derive_subkeys``; nonce contador 0-based y AAD §6;
    ``size``/``content_sha256`` del PLANO (§3); techo ``MAX_ENTRY_BYTES``
    ANTES de cifrar (sin bundle parcial); ``wrapped_cek``/``adapter_id`` vía
    runner (T3) con gramática re-validada al escribir el manifiesto;
    publicación staging+renombrado atómico (F6); F7: material secreto sólo
    en memoria del proceso.
    """
    if not callable(getattr(runner, "wrap_cek", None)):
        raise ValueError("runner must provide wrap_cek(cek)")
    target = Path(bundle).resolve()
    if target.exists():
        raise ExportIOError("export_destination_exists")
    anchor = store.project_root / ".an-kla"
    if target == anchor or anchor in target.parents:
        raise ExportIOError("export_destination_inside_source")

    cek = generate_cek()
    subkeys = derive_subkeys(cek)
    with identity_lock(store):
        with store.write_lock():
            source_verify = store.verify()
            if source_verify["identity_status"] != "complete":
                raise ExportIOError("export_source_identity_incomplete")
            current = store.read_current()
            rows = _files(anchor)
            entries: list[dict[str, Any]] = []
            ciphertexts: list[bytes] = []
            for index, (relative, source) in enumerate(rows):
                if len(entries) >= MAX_FILES:
                    raise ExportIOError("export_limits_exceeded")
                rel_src = source.relative_to(store.project_root).as_posix()
                payload = safe_read(store.project_root, rel_src)
                if len(payload) > MAX_ENTRY_BYTES:
                    # Fail-closed ANTES de cifrar (§6): sin chunking.
                    raise SealedEntryTooLargeError(
                        f"sealed entry of {len(payload)} bytes exceeds "
                        f"max_entry_bytes ({MAX_ENTRY_BYTES}); refusing to "
                        "encrypt (sealed_entry_too_large)"
                    )
                entry = {
                    "path": relative, "size": len(payload),
                    "content_sha256": digest_bytes(payload),
                }
                ciphertexts.append(encrypt_entry(
                    subkeys.aead_key, entry_nonce(index), payload,
                    entry_aad(subkeys.bundle_id_raw, entry),
                ))
                entries.append(entry)
            if store.read_current() != current:
                raise ExportIOError("export_source_changed")
            if [item[0] for item in _files(anchor)] != [item[0] for item in rows]:
                raise ExportIOError("export_source_changed")
            final_verify = store.verify()
            stable = (
                final_verify["revision"] == current
                and final_verify["identity_status"] == "complete"
            )
            if not stable:
                raise ExportIOError("export_source_changed")

    total = sum(item["size"] for item in entries)
    if total > MAX_BUNDLE_BYTES:
        raise ExportIOError("export_limits_exceeded")
    by_path = {item["path"]: item for item in entries}
    prefixes = ("anchor/memory/revisions/", "anchor/memory/checkpoints/")
    for required in (
        "anchor/project-identity.json",
        "anchor/memory/identity.json",
        "anchor/memory/refs/CURRENT",
    ):
        if required not in by_path:
            raise ExportIOError("export_required_entry_missing")
    if not all(
        any(item["path"].startswith(p) for item in entries) for p in prefixes
    ):
        raise ExportIOError("export_required_entry_missing")

    core = {
        "current_revision": current,
        "project_identity_sha256": by_path["anchor/project-identity.json"][
            "content_sha256"],
        "store_identity_sha256": by_path["anchor/memory/identity.json"][
            "content_sha256"],
        "entry_count": len(entries),
        "total_bytes": total,
        "entries": entries,
    }
    manifest_sha256 = digest_json(core)

    wrapped = runner.wrap_cek(cek)
    wrapped_cek = wrapped.wrapped_cek
    if not isinstance(wrapped_cek, str) or len(wrapped_cek) > _WRAPPED_CEK_MAX_CHARS:
        raise ExportIOError("sealing_adapter_error")
    adapter_id = _validated_adapter_id(wrapped.adapter_id)

    seal_without_mac = {
        "algorithm": "aes-256-gcm", "kdf": "hkdf-sha256",
        "adapter_id": adapter_id, "wrapped_cek": wrapped_cek,
        "bundle_id": subkeys.bundle_id_raw.hex(),
    }
    manifest_mac = compute_manifest_mac(
        subkeys.mac_key,
        manifest_transcript(seal_without_mac, core, manifest_sha256),
    )
    manifest = {
        "schema": MANIFEST_SCHEMA, "profile": SEALED_PROFILE,
        "seal": {**seal_without_mac, "manifest_mac": manifest_mac},
        "core": core, "manifest_sha256": manifest_sha256,
    }

    staging = Path(tempfile.mkdtemp(
        prefix=f".{target.name}.seal-staging-", dir=target.parent))
    try:
        entries_dir = staging / "entries"
        entries_dir.mkdir(mode=0o700)
        for entry, ciphertext in zip(entries, ciphertexts):
            dest = entries_dir / entry["path"]
            dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            dest.write_bytes(ciphertext)
            dest.chmod(0o600)
        manifest_path = staging / "manifest.json"
        manifest_path.write_bytes(canonical_json(manifest))
        manifest_path.chmod(0o600)
        normalize_and_sync_tree(
            staging, [p for p in staging.rglob("*") if p.is_file()]
        )
        rename_noreplace(staging, target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "schema": "an-kla/export-result-v2", "created": True,
        "bundle": str(target.resolve()),
        "bundle_id": seal_without_mac["bundle_id"],
        "manifest_sha256": manifest_sha256, "current_revision": current,
        "warnings": [SEALED_WARNING],
    }


# verify sellado (§8: con clave / sin clave)


def verify_sealed_bundle(
    bundle: str | Path, *, cek: bytes | None = None, runner: Any = None,
    max_files: int = MAX_FILES, max_bytes: int = MAX_BUNDLE_BYTES) -> dict:
    """Verifica un bundle sellado (§8).

    Con clave (``cek`` o ``runner``): estructura + ``bundle_id`` recalculado
    + ``manifest_mac`` + AEAD por entrada + ``content_sha256`` del plano →
    ``verified: true``; todo fallo autenticado es
    ``SealedPayloadAuthFailedError`` (un código, sin oráculo). Sin clave:
    SOLO estructura (shape, conteos, presencia, tamaños físicos, tree) —
    ``verified`` JAMÁS ``true``, enum estructural cerrado en
    ``diagnostics``. No desencripta nada, nunca.
    """
    root = Path(bundle)
    keyed = cek is not None or runner is not None
    manifest, ciphertexts, diagnostics = _inspect_bundle(root, max_files, max_bytes)
    if keyed:
        if diagnostics:
            raise ExportIOError(_DIAGNOSTIC_TO_EXPORT_ERROR[diagnostics[0]])
        key = _resolve_cek(cek, runner, manifest)
        payloads = _decrypt_all(manifest, ciphertexts, key)
        _identity_crosscheck(manifest, payloads)
        return {
            "schema": "an-kla/export-verify-result-v2", "verified": True,
            "structure_verified": True, "payloads_verified": True,
            "manifest_sha256": manifest["manifest_sha256"],
            "current_revision": manifest["core"]["current_revision"],
            "bundle_id": manifest["seal"]["bundle_id"],
            "warnings": [SEALED_WARNING],
        }
    # Sin clave: tamaño físico entra al enum estructural (F5, §8).
    if manifest is not None and not diagnostics:
        for item in manifest["core"]["entries"]:
            phys = len(ciphertexts.get(item["path"], b""))
            if phys != item["size"] + GCM_TAG_BYTES:
                diagnostics.append("entry_size_mismatch")
                break
    result: dict = {
        "schema": "an-kla/export-verify-result-v2", "verified": False,
        "structure_verified": not diagnostics, "payloads_verified": False,
        "warnings": [UNKEYED_VERIFY_WARNING]}
    if diagnostics:
        result["diagnostics"] = diagnostics
    else:
        result.update({
            "manifest_sha256": manifest["manifest_sha256"],
            "current_revision": manifest["core"]["current_revision"],
            "bundle_id": manifest["seal"]["bundle_id"],
        })
    return result


# restore sellado (§3: semántica idéntica a v1 tras desencriptar)


def restore_sealed_bundle(
    bundle: str | Path, project_root: str | Path, *,
    cek: bytes | None = None, runner: Any = None,
) -> dict[str, Any]:
    """Restaura un bundle sellado — desencripta TODO antes de tocar destino.

    Fallo autenticado (tag/CEK/tamaño/mac/AAD) → ``SealedPayloadAuthFailedError``
    ANTES de crear staging (sin restauración parcial, §9 fila 2). Luego
    verificación semántica, ``no overwrite`` y ``no merge`` — idénticos a v1
    (§3).
    """
    manifest, ciphertexts, diagnostics = _inspect_bundle(
        Path(bundle), MAX_FILES, MAX_BUNDLE_BYTES
    )
    if diagnostics:
        raise ExportIOError(_DIAGNOSTIC_TO_EXPORT_ERROR[diagnostics[0]])
    key = _resolve_cek(cek, runner, manifest)
    payloads = _decrypt_all(manifest, ciphertexts, key)
    _identity_crosscheck(manifest, payloads)

    project = Path(project_root).resolve()
    project.mkdir(parents=True, exist_ok=True)
    destination = project / ".an-kla"
    if destination.exists():
        raise ExportIOError("restore_destination_conflict")
    staging = Path(tempfile.mkdtemp(
        prefix=".an-kla-sealed-restore-", dir=project))
    try:
        anchor = staging / ".an-kla"
        staged_files = []
        expected_sha = {i["path"]: i["content_sha256"]
                        for i in manifest["core"]["entries"]}
        for relative, payload in payloads.items():
            staged = anchor / Path(relative).relative_to("anchor")
            staged.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            staged.write_bytes(payload)
            staged_files.append(staged)
            if digest_bytes(staged.read_bytes()) != expected_sha[relative]:
                raise ExportIOError("restore_staging_mismatch")
        from an_kla.store import MemoryStore

        verified = MemoryStore(staging).verify()
        if verified["revision"] != manifest["core"]["current_revision"]:
            raise ExportIOError("export_semantic_mismatch")
        normalize_and_sync_tree(anchor, staged_files)
        rename_noreplace(anchor, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    from an_kla.storage_primitives import fsync_directory
    from an_kla.store import MemoryStore

    fsync_directory(project)
    final_verify = MemoryStore(project).verify()
    warnings = [SEALED_WARNING]
    if final_verify["root_relocated"]:
        warnings.append("root_relocated")
    return {
        "schema": "an-kla/export-restore-result-v2",
        "state": "published",
        "published": True,
        "current_revision": manifest["core"]["current_revision"],
        "manifest_sha256": manifest["manifest_sha256"],
        "warnings": warnings,
    }
