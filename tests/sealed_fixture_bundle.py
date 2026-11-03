"""Synthetic sealed bundles for unkeyed structural tests (no encryption)."""
from __future__ import annotations
import base64
import json
from pathlib import Path
from an_kla.canonical import canonical_json, digest_bytes, digest_json
from an_kla.sealed import bundle as sb

def _synthetic_sealed_bundle(bundle: Path) -> dict:
    """Fabrica un bundle sellado cuya ESTRUCTURA verifica (unkeyed limpio).

    El ciphertext es relleno del tamaño exacto size+16: la estructura sin
    clave NO desencripta jamás (§8), así que el contenido no importa para
    este camino; el manifiesto es canónico v2 completo (seal con shape
    exacto, core con digest_json cuadrando).
    """

    payloads = {
        "anchor/project-identity.json": b'{"project":"synthetic"}',
        "anchor/memory/identity.json": b'{"store":"synthetic"}',
        "anchor/memory/refs/CURRENT": b"sha256:" + b"0" * 64,
        "anchor/memory/revisions/sha256/" + "1" * 64 + ".json": b"{}",
        "anchor/memory/checkpoints/sha256/" + "2" * 64 + ".json": b"{}",
    }
    entries = [
        {"path": path, "size": len(payload),
         "content_sha256": digest_bytes(payload)}
        for path, payload in sorted(
            payloads.items(), key=lambda item: item[0].encode("utf-8"))
    ]
    core = {
        "current_revision": payloads["anchor/memory/refs/CURRENT"].decode(),
        "project_identity_sha256": entries[0]["content_sha256"],
        "store_identity_sha256": entries[1]["content_sha256"],
        "entry_count": len(entries), "total_bytes": sum(
            item["size"] for item in entries),
        "entries": entries,
    }
    manifest = {
        "schema": "an-kla/export-manifest-v2",
        "profile": sb.SEALED_PROFILE,
        "seal": {
            "algorithm": "aes-256-gcm", "kdf": "hkdf-sha256",
            "adapter_id": "synthetic.adapter.v1",
            "wrapped_cek": base64.b64encode(b"s" * 48).decode("ascii"),
            "bundle_id": "ab" * 16, "manifest_mac": "cd" * 32,
        },
        "core": core,
        "manifest_sha256": digest_json(core),
    }
    bundle.mkdir(mode=0o700)
    entries_dir = bundle / "entries"
    entries_dir.mkdir(mode=0o700)
    for entry in entries:
        destination = entries_dir / entry["path"]
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Tamaño físico EXACTO size+16 (layout §6): la estructura sin clave
        # compara tamaños, jamás contenido.
        destination.write_bytes(b"\x00" * (entry["size"] + sb.GCM_TAG_BYTES))
    manifest_path = bundle / "manifest.json"
    manifest_path.write_bytes(canonical_json(manifest))
    manifest_path.chmod(0o600)
    return manifest


def _rewrite_manifest(bundle: Path, mutate, *, resync: bool = True) -> None:
    """Reescribe el manifiesto tras mutarlo. Con ``resync`` re-cuadra
    ``manifest_sha256`` contra el core mutado (mutaciones de SHAPE); sin
    ``resync`` deja el digest del mutador (mutaciones de CONSISTENCIA,
    p. ej. ``manifest_sha256`` descuadrado a propósito)."""
    manifest = json.loads((bundle / "manifest.json").read_bytes())
    manifest = mutate(manifest) or manifest
    if resync and "core" in manifest:
        manifest["manifest_sha256"] = digest_json(manifest["core"])
    (bundle / "manifest.json").write_bytes(canonical_json(manifest))
