"""test_sealed_bundle_units.py — partición de tests/test_sealed_bundle.py por unidad bajo prueba (beta.22, issue #106).

TestNonceCounterF1 (fila 1, F1) y TestPureFunctions: casos y aserciones
sin cambios; el prelude se copia del archivo de origen.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from an_kla.canonical import canonical_json, digest_json
from an_kla.export_io import ExportIOError
from an_kla.sealed import bundle as sb
from an_kla.sealed.kdf import derive_subkeys
from an_kla.store import MemoryStore


def _cryptography_importable() -> bool:
    try:
        import cryptography  # noqa: F401
    except ImportError:
        return False
    return True


# ---------------------------------------------------------------------------
# Adaptador de prueba determinístico (in-memory, sin proceso)
# ---------------------------------------------------------------------------


class FakeAdapter:
    """Adaptador con la MISMA superficie que ``SealingAdapterRunner`` (T3).

    Determinístico: wrap/unwrap con la MISMA KEK simétrica. Permite
    inyectar CEKs arbitrarias y materializar ``wrapped_cek`` opaco sin
    proceso externo (los límites del runner real ya se probaron en T3).
    """

    ADAPTER_ID = "test-adapter-v1"

    def __init__(self) -> None:
        self.ceks: dict[str, bytes] = {}
        self.counter = 0
        self.wrap_calls = 0

    @staticmethod
    def _kek() -> bytes:
        return b"k" * 32

    def wrap_cek(self, cek: bytes):
        from an_kla.sealed.cek import wrap_cek

        self.counter += 1
        self.wrap_calls += 1
        token = f"blob-{self.counter}"
        self.ceks[token] = bytes(cek)
        blob = token.encode("ascii") + b":" + wrap_cek(cek, self._kek()).blob
        return types.SimpleNamespace(
            wrapped_cek=base64.b64encode(blob).decode("ascii"),
            adapter_id=self.ADAPTER_ID,
        )

    def unwrap_cek(self, wrapped_cek: str):
        from an_kla.sealed.cek import unwrap_cek

        try:
            token, blob = base64.b64decode(wrapped_cek, validate=True).split(
                b":", 1
            )
            cek = unwrap_cek(blob, self._kek())
        except Exception as exc:
            raise sb.SealedPayloadAuthFailedError(
                "sealed payload authentication failed (no further detail)"
            ) from exc
        if token.decode("ascii") not in self.ceks:
            raise sb.SealedPayloadAuthFailedError(
                "sealed payload authentication failed (no further detail)"
            )
        return types.SimpleNamespace(cek=cek)


class FixedIdAdapter(FakeAdapter):
    """Adapter_id arbitrario (para gramática §6 al escribir el manifiesto)."""

    def __init__(self, adapter_id: str) -> None:
        super().__init__()
        self._id = adapter_id

    def wrap_cek(self, cek: bytes):
        result = super().wrap_cek(cek)
        result.adapter_id = self._id
        return result


def _make_store(root: Path) -> tuple[MemoryStore, str]:
    store = MemoryStore(root)
    initial = store.initialize()
    current = store.commit(
        expected_current_hash=initial,
        checkpoint_patch={},
        facts=[{"id": "f-seal", "payload": {"text": "sealed-backup"}}],
        events=[{"id": "e-seal", "payload": {"text": "event"}}],
    )
    return store, current


def _create_sealed(root: Path, name: str = "sealed-bundle"):
    """Bundle sellado con adaptador fresco. Devuelve (store, current, result, bundle, adapter)."""
    store, current = _make_store(root / "source")
    adapter = FakeAdapter()
    created = sb.create_sealed_bundle(store, root / name, adapter)
    return store, current, created, root / name, adapter


def _cek_of(bundle: Path, adapter: FakeAdapter) -> bytes:
    """CEK de un bundle creado por ``adapter`` (token del wrapped_cek)."""
    manifest = json.loads((bundle / "manifest.json").read_text())
    raw = base64.b64decode(manifest["seal"]["wrapped_cek"], validate=True)
    token = raw.split(b":", 1)[0].decode("ascii")
    return adapter.ceks[token]


def _manifest_of(bundle: Path) -> dict:
    return json.loads((bundle / "manifest.json").read_text())


# ---------------------------------------------------------------------------
# F1 — inyectividad del contador de nonces (fila §9-1)
# ---------------------------------------------------------------------------


class TestNonceCounterF1(unittest.TestCase):
    """Recorrido COMPLETO del dominio 0..99999 (elección documentada).

    El DoD permite lote/muestreo "si el recorrido completo tarda"; aquí el
    recorrido completo cuesta <1 s (100000 ``to_bytes``), así que se hace
    COMPLETO: no hay razón estadística para muestrear.
    """

    def test_100000_distinct_nonces_all_exactly_12_bytes(self):
        seen = set()
        for index in range(100000):
            nonce = sb.entry_nonce(index)
            self.assertEqual(len(nonce), 12)
            seen.add(nonce)
        self.assertEqual(len(seen), 100000)

    def test_construction_is_the_adr_literal(self):
        """``i.to_bytes(12, 'big')`` byte a byte en los bordes del dominio."""
        for index in (0, 1, 255, 256, 65535, 65536, 99999):
            self.assertEqual(sb.entry_nonce(index), index.to_bytes(12, "big"))
        self.assertEqual(sb.entry_nonce(0), b"\x00" * 12)
        self.assertEqual(sb.entry_nonce(1)[11:], b"\x01")

    def test_index_out_of_domain_rejected(self):
        for bad in (-1, 100000, 2**96):
            with self.subTest(index=bad):
                with self.assertRaises(ValueError):
                    sb.entry_nonce(bad)
        with self.assertRaises(TypeError):
            sb.entry_nonce(True)  # bool es int pero no índice legítimo


# ---------------------------------------------------------------------------
# Funciones puras: AAD, transcript, manifest_mac
# ---------------------------------------------------------------------------


class TestPureFunctions(unittest.TestCase):
    def test_aad_construction_literal(self):
        """AAD = UTF8('sealed-export/v1') || bundle_id_raw || canonical_json."""
        bundle_id_raw = bytes.fromhex("00" * 15 + "ff")
        entry = {"path": "anchor/memory/refs/CURRENT", "size": 71,
                 "content_sha256": "sha256:" + "a" * 64}
        expected = b"sealed-export/v1" + bundle_id_raw + canonical_json(entry)
        self.assertEqual(sb.entry_aad(bundle_id_raw, entry), expected)

    def test_aad_binds_entry_and_bundle(self):
        bundle_id_raw = bytes(range(16))
        entry = {"path": "p", "size": 1, "content_sha256": "sha256:" + "b" * 64}
        other_id = bytes(range(16))[::-1]
        other_entry = dict(entry, size=2)
        base = sb.entry_aad(bundle_id_raw, entry)
        self.assertNotEqual(base, sb.entry_aad(other_id, entry))
        self.assertNotEqual(base, sb.entry_aad(bundle_id_raw, other_entry))

    def test_aad_contract_errors(self):
        with self.assertRaises(ValueError):
            sb.entry_aad(b"short", {})
        with self.assertRaises(TypeError):
            sb.entry_aad("not-bytes", {})

    def test_transcript_shape_and_order_independence(self):
        """T = {schema, profile, seal, core, manifest_sha256} — sin campos extra."""
        seal = {"algorithm": "aes-256-gcm", "kdf": "hkdf-sha256", "adapter_id": "a1",
                "wrapped_cek": "QkxPQg==", "bundle_id": "ab" * 16}
        core = {"entries": []}
        transcript = sb.manifest_transcript(seal, core, "sha256:" + "c" * 64)
        self.assertEqual(set(transcript),
                         {"schema", "profile", "seal", "core", "manifest_sha256"})
        self.assertEqual(transcript["schema"], "an-kla/export-manifest-v2")
        self.assertEqual(transcript["profile"], "sealed-export/v1")
        # canonical_json reordena: el transcript es estable bajo permutación.
        permuted = dict(reversed(list(seal.items())))
        self.assertEqual(
            sb.manifest_transcript(permuted, core, "sha256:" + "c" * 64),
            transcript,
        )

    def test_manifest_mac_is_lowercase_hex_64(self):
        import hashlib
        import hmac

        key = b"m" * 32
        transcript = sb.manifest_transcript({}, {}, "sha256:" + "0" * 64)
        mac = sb.compute_manifest_mac(key, transcript)
        self.assertEqual(len(mac), 64)
        self.assertEqual(mac, mac.lower())
        expected = hmac.new(key, canonical_json(transcript), hashlib.sha256).hexdigest()
        self.assertEqual(mac, expected)

    def test_manifest_mac_contract_errors(self):
        with self.assertRaises(ValueError):
            sb.compute_manifest_mac(b"short", {})
        with self.assertRaises(TypeError):
            sb.compute_manifest_mac("key", {})

    def test_verify_manifest_mac_constant_time_compare_and_formats(self):
        key = b"m" * 32
        transcript = sb.manifest_transcript({}, {}, "sha256:" + "0" * 64)
        good = sb.compute_manifest_mac(key, transcript)
        self.assertTrue(sb.verify_manifest_mac(key, transcript, good))
        # Hex mayúsculas / 63 chars / 65 chars / no-str → False (no excepción).
        self.assertFalse(sb.verify_manifest_mac(key, transcript, good.upper()))
        self.assertFalse(sb.verify_manifest_mac(key, transcript, good[:63]))
        self.assertFalse(sb.verify_manifest_mac(key, transcript, good + "0"))
        self.assertFalse(sb.verify_manifest_mac(key, transcript, None))
        self.assertFalse(sb.verify_manifest_mac(key, transcript, 42))
        # Clave distinta → False.
        self.assertFalse(sb.verify_manifest_mac(b"n" * 32, transcript, good))


# ---------------------------------------------------------------------------
# Criptografía del bundle — TODAS las filas §9 de esta tarjeta
# ---------------------------------------------------------------------------


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
