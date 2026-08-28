"""Tests del bundle sellado (``sealed-export/v1``) — T4 de issue #46.

Cubren TODOS los checks DoD de la tarjeta (matriz §9 del ADR-0042):

- F1 (fila 1): recorrido COMPLETO 0..99999 → 100000 nonces distintos, todos
  de exactamente 12 bytes; además la construcción es la literal del ADR.
- Filas 2,3,4,5: ciphertext alterado 1 byte → ``sealed_payload_auth_failed``
  sin restauración parcial; CEK incorrecta → mismo error INDISTINGUIBLE;
  ``manifest_mac`` alterado con ``content_sha256`` cuadrando → fallo
  cerrado; entrada movida entre bundles (mismo store, CEKs distintas) →
  falla por AAD.
- Fila 7: roundtrip sellado byte-idéntico (CURRENT, snapshots, refutaciones
  como blobs del store).
- Fila 10b: entrada > 512 MiB con el tamaño MOCKEADO (sin materializar) →
  ``sealed_entry_too_large`` ANTES de cifrar, sin bundle parcial.
- Fila 10c (F5): tamaño físico size+15 / size+17 → autenticado
  ``sealed_payload_auth_failed``; borde EXACTO size+16 OK (lección T3-A2:
  bloques parciales y bordes, no solo casos felices alineados).
- Fila 12b: operación sellada sin extra → ``sealing_extra_not_installed``.
- Fila 13: re-sellado con CEK distinta → ``bundle_id`` distinto.
- Fila 16 (F7): CEK/subclaves (hex/b64 completos Y prefijos) ausentes de
  bundle, staging, resultados, warnings y mensajes de error.
- Extra §9-8/10c: verify sin clave jamás ``verified: true``; tamaño físico
  alterado sin clave → ``structure_verified: false`` +
  ``diagnostics: ["entry_size_mismatch"]``.

Entorno: la suite canónica corre SIN ``cryptography`` (skips honestos);
los tests criptográficos se ejecutan con el intérprete que sí la tiene.
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


class SealedBundleCryptoTests(unittest.TestCase):
    """Filas 2,3,4,5,7,10b,10c,13,16 — requieren ``cryptography``."""

    def setUp(self):
        if not _cryptography_importable():
            self.skipTest(
                "cryptography no instalada (extra [sealed] ausente); "
                "tests criptográficos del bundle no ejecutables aquí"
            )
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _sealed_with_cek(self, cek: bytes, name: str):
        """Bundle sellado con CEK FIJA (re-sellado determinista de prueba)."""
        store, _current = _make_store(self.root / f"source-{name}")
        adapter = FakeAdapter()
        with patch("an_kla.sealed.bundle.generate_cek", return_value=cek):
            created = sb.create_sealed_bundle(store, self.root / name, adapter)
        return store, created, self.root / name, adapter

    def _entry_file(self, bundle: Path, index: int = 0) -> Path:
        manifest = _manifest_of(bundle)
        return bundle / "entries" / manifest["core"]["entries"][index]["path"]

    # -- fila 7: roundtrip byte-idéntico ------------------------------------

    def test_row7_roundtrip_byte_identical(self):
        store, current, created, bundle, adapter = _create_sealed(self.root)
        cek = _cek_of(bundle, adapter)

        # El resultado expone el ancla fuera de línea (§Límites, H3).
        self.assertEqual(created["schema"], "an-kla/export-result-v2")
        self.assertRegex(created["bundle_id"], r"^[0-9a-f]{32}$")
        self.assertTrue(created["manifest_sha256"].startswith("sha256:"))
        self.assertEqual(created["warnings"], [sb.SEALED_WARNING])

        # verify autenticado (CEK inyectada y vía runner) → verified: true.
        keyed = sb.verify_sealed_bundle(bundle, cek=cek)
        self.assertTrue(keyed["verified"])
        self.assertTrue(keyed["structure_verified"])
        self.assertTrue(keyed["payloads_verified"])
        via_runner = sb.verify_sealed_bundle(bundle, runner=adapter)
        self.assertTrue(via_runner["verified"])

        # restore: el store restaurado es byte-idéntico archivo a archivo
        # (CURRENT, snapshots y todo blob durable del store incluidos).
        restored = self.root / "restored"
        result = sb.restore_sealed_bundle(bundle, restored, cek=cek)
        self.assertEqual(result["schema"], "an-kla/export-restore-result-v2")
        self.assertTrue(result["published"])
        self.assertEqual(MemoryStore(restored).read_current(), current)
        self.assertEqual(
            MemoryStore(restored).snapshot().records["facts"][0]["id"], "f-seal"
        )
        # Byte-idéntico ENTRADA A ENTRADA: cada entrada del manifiesto
        # (CURRENT, revisions, snapshots, transactions, segments…) existe
        # en el restaurado con los mismos bytes que en el origen.
        manifest = _manifest_of(bundle)
        for entry in manifest["core"]["entries"]:
            source_file = store.project_root / ".an-kla" / Path(
                entry["path"]
            ).relative_to("anchor")
            restored_file = restored / ".an-kla" / Path(
                entry["path"]
            ).relative_to("anchor")
            self.assertTrue(source_file.is_file(), entry["path"])
            self.assertTrue(restored_file.is_file(), entry["path"])
            self.assertEqual(
                restored_file.read_bytes(),
                source_file.read_bytes(),
                f"byte mismatch at {entry['path']}",
            )

        # Layout físico §6: ciphertext mide size+16; el nonce NO está en disco.
        manifest = _manifest_of(bundle)
        for entry in manifest["core"]["entries"]:
            physical = bundle / "entries" / entry["path"]
            self.assertEqual(physical.stat().st_size, entry["size"] + 16)
        blob = b"".join(
            (bundle / "entries" / e["path"]).read_bytes()
            for e in manifest["core"]["entries"]
        )
        self.assertNotIn(b"\x00" * 12, blob)  # sanity: nonce contador ausente

    def test_row7_roundtrip_via_runner(self):
        _store, _current, _created, bundle, adapter = _create_sealed(self.root)
        # Roundtrip completo vía runner: unwrap del wrapped_cek real.
        result = sb.restore_sealed_bundle(
            bundle, self.root / "restored", runner=adapter
        )
        self.assertTrue(result["published"])

    def test_manifest_v2_shape_core_exact_of_v1(self):
        _store, _current, _created, bundle, adapter = _create_sealed(self.root)
        manifest = _manifest_of(bundle)
        self.assertEqual(
            set(manifest), {"schema", "profile", "seal", "core", "manifest_sha256"}
        )
        self.assertEqual(manifest["schema"], "an-kla/export-manifest-v2")
        self.assertEqual(manifest["profile"], "sealed-export/v1")
        # core: shape EXACTO de v1 y manifest_sha256 = digest_json(core).
        self.assertEqual(
            set(manifest["core"]),
            {"current_revision", "project_identity_sha256", "store_identity_sha256",
             "entry_count", "total_bytes", "entries"},
        )
        self.assertEqual(manifest["manifest_sha256"], digest_json(manifest["core"]))
        # Manifest serializado como canonical JSON.
        self.assertEqual(
            (bundle / "manifest.json").read_bytes(), canonical_json(manifest)
        )
        # manifest_mac autentica el transcript completo (recalculado aquí).
        cek = _cek_of(bundle, adapter)
        subkeys = derive_subkeys(cek)
        self.assertEqual(subkeys.bundle_id_raw.hex(), manifest["seal"]["bundle_id"])
        seal_no_mac = {k: v for k, v in manifest["seal"].items() if k != "manifest_mac"}
        self.assertEqual(
            sb.compute_manifest_mac(
                subkeys.mac_key,
                sb.manifest_transcript(
                    seal_no_mac, manifest["core"], manifest["manifest_sha256"]
                ),
            ),
            manifest["seal"]["manifest_mac"],
        )

    # -- fila 2: ciphertext alterado 1 byte ----------------------------------

    def test_row2_tamper_one_byte_fails_closed_no_partial_restore(self):
        _store, _current, _created, bundle, _adapter = _create_sealed(self.root)
        target = self._entry_file(bundle, 0)
        data = bytearray(target.read_bytes())
        data[0] ^= 0x01
        target.write_bytes(bytes(data))
        with self.assertRaises(sb.SealedPayloadAuthFailedError) as ctx:
            sb.verify_sealed_bundle(bundle, runner=FakeAdapter())
        self.assertEqual(ctx.exception.ERROR_CODE, "sealed_payload_auth_failed")
        restored = self.root / "restored"
        with self.assertRaises(sb.SealedPayloadAuthFailedError):
            sb.restore_sealed_bundle(bundle, restored, runner=FakeAdapter())
        # Sin restauración parcial: el destino quedó vacío.
        self.assertFalse((restored / ".an-kla").exists())

    def test_row2_tamper_last_byte_tag(self):
        """Alterar el ÚLTIMO byte (el tag GCM) también falla cerrado."""
        _store, _current, _created, bundle, _adapter = _create_sealed(self.root)
        target = self._entry_file(bundle, 0)
        data = target.read_bytes()
        target.write_bytes(data[:-1] + bytes([data[-1] ^ 0xFF]))
        with self.assertRaises(sb.SealedPayloadAuthFailedError):
            sb.verify_sealed_bundle(bundle, runner=FakeAdapter())

    # -- fila 3: CEK incorrecta indistinguible --------------------------------

    def test_row3_wrong_cek_indistinguishable(self):
        _store, _current, created, bundle, adapter = _create_sealed(self.root)
        good_cek = _cek_of(bundle, adapter)
        wrong_cek = bytes(b ^ 0xFF for b in good_cek)
        # CEK incorrecta: MISMA excepción y MISMO mensaje que la corrupción
        # (fila 2) — sin oráculo que distinga clave mala de datos corruptos.
        with self.assertRaises(sb.SealedPayloadAuthFailedError) as wrong_ctx:
            sb.verify_sealed_bundle(bundle, cek=wrong_cek)
        target = self._entry_file(bundle, 0)
        data = bytearray(target.read_bytes())
        data[0] ^= 0x01
        target.write_bytes(bytes(data))
        with self.assertRaises(sb.SealedPayloadAuthFailedError) as corrupt_ctx:
            sb.verify_sealed_bundle(bundle, cek=good_cek)
        self.assertEqual(str(wrong_ctx.exception), str(corrupt_ctx.exception))

    # -- fila 4: manifest_mac alterado ---------------------------------------

    def test_row4_manifest_mac_altered_fails_closed(self):
        _store, _current, _created, bundle, _adapter = _create_sealed(self.root)
        manifest = _manifest_of(bundle)
        mac = manifest["seal"]["manifest_mac"]
        # Alterar el mac SIN tocar core: content_sha256 sigue cuadrando.
        flipped = ("0" if mac[0] != "0" else "1") + mac[1:]
        manifest["seal"]["manifest_mac"] = flipped
        (bundle / "manifest.json").write_bytes(canonical_json(manifest))
        self.assertEqual(digest_json(manifest["core"]), manifest["manifest_sha256"])
        with self.assertRaises(sb.SealedPayloadAuthFailedError):
            sb.verify_sealed_bundle(bundle, runner=FakeAdapter())
        # Caso límite: mayúsculas (hex bien formado pero NO canónico) es un
        # fallo de SHAPE del manifiesto (hex minúsculo normativo, §6) →
        # diagnóstico estructural export_manifest_invalid, también cerrado.
        manifest["seal"]["manifest_mac"] = mac.upper()
        (bundle / "manifest.json").write_bytes(canonical_json(manifest))
        with self.assertRaises(ExportIOError):
            sb.verify_sealed_bundle(bundle, runner=FakeAdapter())

    # -- fila 5: entrada movida entre bundles ---------------------------------

    def test_row5_entry_moved_between_bundles_fails_by_aad(self):
        cek_a = bytes.fromhex("11" * 32)
        cek_b = bytes.fromhex("22" * 32)
        _s1, _c1, bundle_a, _ad1 = self._sealed_with_cek(cek_a, "bundle-a")
        _s2, _c2, bundle_b, _ad2 = self._sealed_with_cek(cek_b, "bundle-b")
        manifest_a = _manifest_of(bundle_a)
        manifest_b = _manifest_of(bundle_b)
        self.assertNotEqual(
            manifest_a["seal"]["bundle_id"], manifest_b["seal"]["bundle_id"]
        )

        # Mover el ciphertext de una ruta compartida de A hacia B: el core y
        # el manifest de B quedan intactos (mismo store → mismo size+16); el
        # fallo es del AEAD por AAD (bundle_id de A ≠ bundle_id de B).
        paths_a = {e["path"] for e in manifest_a["core"]["entries"]}
        paths_b = {e["path"] for e in manifest_b["core"]["entries"]}
        victim = sorted(paths_a & paths_b)[0]
        (bundle_b / "entries" / victim).write_bytes(
            (bundle_a / "entries" / victim).read_bytes()
        )
        with self.assertRaises(sb.SealedPayloadAuthFailedError) as ctx:
            sb.verify_sealed_bundle(bundle_b, cek=cek_b)
        self.assertEqual(ctx.exception.ERROR_CODE, "sealed_payload_auth_failed")
        # Y la CEK de A contra B también falla: bundle_id recalculado (§6)
        # no coincide con el manifest de B — el manifiesto no se confía.
        with self.assertRaises(sb.SealedPayloadAuthFailedError):
            sb.verify_sealed_bundle(bundle_b, cek=cek_a)

    # -- fila 10b: entrada > max_entry_bytes (mock del tamaño) ----------------

    def test_row10b_entry_too_large_before_encrypting_no_partial_bundle(self):
        store, _current = _make_store(self.root / "source")

        # MOCK del tamaño (elección documentada): en lugar de materializar
        # 512 MiB reales, se parchea MAX_ENTRY_BYTES a un valor pequeño —
        # el borde estructural "entrada > techo" queda ejercitado igual por
        # entradas reales del store que exceden el techo parcheado.
        with patch("an_kla.sealed.bundle.MAX_ENTRY_BYTES", 8):
            with self.assertRaises(sb.SealedEntryTooLargeError) as ctx:
                sb.create_sealed_bundle(store, self.root / "big", FakeAdapter())
        self.assertEqual(ctx.exception.ERROR_CODE, "sealed_entry_too_large")
        # ANTES de cifrar: el adaptador jamás fue llamado y cero bundle/staging.
        self.assertFalse((self.root / "big").exists())
        self.assertEqual(
            [p.name for p in self.root.iterdir() if "staging" in p.name], []
        )

    def test_row10b_boundary_exact_limit_encrypts(self):
        """Borde EXACTO: entrada == max_entry_bytes SÍ se cifra (lección T3-A2)."""
        store, _current = _make_store(self.root / "source")
        biggest = max(
            (p for p in (store.project_root / ".an-kla").rglob("*") if p.is_file()),
            key=lambda p: p.stat().st_size,
        )
        size = biggest.stat().st_size
        with patch("an_kla.sealed.bundle.MAX_ENTRY_BYTES", size):
            created = sb.create_sealed_bundle(store, self.root / "exact", FakeAdapter())
        self.assertTrue(created["created"])

    def test_row10b_real_oversize_constant_is_512mib(self):
        self.assertEqual(sb.MAX_ENTRY_BYTES, 512 * 1024 * 1024)

    # -- fila 10c (F5): tamaño físico size+15 / size+17 ------------------------

    def test_row10c_physical_size_off_by_one_both_sides(self):
        _store, _current, _created, bundle, _adapter = _create_sealed(self.root)
        manifest = _manifest_of(bundle)
        entry = manifest["core"]["entries"][0]
        target = bundle / "entries" / entry["path"]
        original = target.read_bytes()
        self.assertEqual(len(original), entry["size"] + 16)  # borde exacto OK

        for label, payload in (
            ("size+17", original + b"\x00"),
            ("size+15", original[:-1]),
        ):
            with self.subTest(delta=label):
                target.write_bytes(payload)
                # Autenticado: sealed_payload_auth_failed SIN distinguir causa.
                with self.assertRaises(sb.SealedPayloadAuthFailedError):
                    sb.verify_sealed_bundle(bundle, runner=FakeAdapter())
                # Sin clave: structure_verified false + entry_size_mismatch,
                # JAMÁS desencripta ni afirma autenticidad.
                unkeyed = sb.verify_sealed_bundle(bundle)
                self.assertFalse(unkeyed["verified"])
                self.assertFalse(unkeyed["structure_verified"])
                self.assertIn("entry_size_mismatch", unkeyed["diagnostics"])
                self.assertEqual(
                    unkeyed["warnings"], ["sealed_payloads_unverified_without_key"]
                )
                target.write_bytes(original)  # restaurar para el siguiente caso

    def test_row10c_unkeyed_never_verified_true(self):
        """§9 fila 8: verify sin clave jamás devuelve verified: true."""
        _store, _current, _created, bundle, _adapter = _create_sealed(self.root)
        result = sb.verify_sealed_bundle(bundle)
        self.assertFalse(result["verified"])
        self.assertTrue(result["structure_verified"])
        self.assertFalse(result["payloads_verified"])
        self.assertEqual(
            result["warnings"], ["sealed_payloads_unverified_without_key"]
        )

    def test_row10c_unkeyed_detects_missing_and_extra_entries(self):
        _store, _current, _created, bundle, _adapter = _create_sealed(self.root)
        manifest = _manifest_of(bundle)
        victim = bundle / "entries" / manifest["core"]["entries"][0]["path"]
        saved = victim.read_bytes()
        victim.unlink()
        result = sb.verify_sealed_bundle(bundle)
        self.assertFalse(result["structure_verified"])
        self.assertIn("entry_missing", result["diagnostics"])
        victim.write_bytes(saved)
        extra = bundle / "entries" / "anchor/memory/refs/CURRENT.extra"
        extra.write_bytes(b"x")
        result = sb.verify_sealed_bundle(bundle)
        self.assertIn("entry_unexpected", result["diagnostics"])
        extra.unlink()
        # Manifiesto corrupto (JSON inválido) → manifest_invalid.
        raw = (bundle / "manifest.json").read_bytes()
        (bundle / "manifest.json").write_bytes(b"{not json")
        result = sb.verify_sealed_bundle(bundle)
        self.assertIn("manifest_invalid", result["diagnostics"])
        (bundle / "manifest.json").write_bytes(raw)

    # -- fila 12b: sin extra → sealing_extra_not_installed ---------------------

    def test_row12b_extra_not_installed_exact_code(self):
        """Operación sellada sin el extra falla con el código EXACTO (§9 12b).

        Se bloquea el import de ``cryptography`` (meta_path) en un proceso
        hijo: el cifrado del bundle DEBE fallar con
        ``SealedExtraNotInstalledError`` — código canónico exacto
        ``sealing_extra_not_installed`` — SIN degradarse a claro. La prueba
        es explícita (proceso hijo), no implícita en el entorno.
        """
        wrapper = (
            "import sys\n"
            "class _Block:\n"
            "    def find_spec(self, name, path=None, target=None):\n"
            "        if name == 'cryptography' or name.startswith("
            "'cryptography.'):\n"
            "            raise ImportError('blocked for test')\n"
            "        return None\n"
            "sys.meta_path.insert(0, _Block())\n"
            "[sys.modules.pop(m, None) for m in list(sys.modules)\n"
            " if m.startswith('cryptography')]\n"
        )
        code = wrapper + (
            "from an_kla.sealed import bundle as sb\n"
            "from an_kla.sealed import (SealedExtraNotInstalledError,\n"
            "                           SEALED_EXTRA_ERROR_CODE)\n"
            "assert SEALED_EXTRA_ERROR_CODE == 'sealing_extra_not_installed'\n"
            "assert SealedExtraNotInstalledError is not None\n"
            "try:\n"
            "    sb.encrypt_entry(b'k'*32, b'n'*12, b'p', b'aad')\n"
            "except SealedExtraNotInstalledError as e:\n"
            "    assert 'sealed' in str(e), str(e)\n"
            "else:\n"
            "    raise AssertionError('encrypt did not fail closed')\n"
            "try:\n"
            "    sb.decrypt_entry(b'k'*32, b'n'*12, b'c'*32, b'aad')\n"
            "except SealedExtraNotInstalledError:\n"
            "    pass\n"
            "else:\n"
            "    raise AssertionError('decrypt did not fail closed')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        self.assertEqual(
            result.returncode, 0,
            msg=f"stderr: {result.stderr}\nstdout: {result.stdout}",
        )

    # -- fila 13: re-sellado con CEK distinta → bundle_id distinto --------------

    def test_row13_reseal_different_cek_different_bundle_id(self):
        cek_a = bytes.fromhex("33" * 32)
        cek_b = bytes.fromhex("44" * 32)
        _s1, created_a, bundle_a, _ad1 = self._sealed_with_cek(cek_a, "a")
        _s2, created_b, bundle_b, _ad2 = self._sealed_with_cek(cek_b, "b")
        id_a, id_b = created_a["bundle_id"], created_b["bundle_id"]
        self.assertNotEqual(id_a, id_b)
        # Visible en result Y en manifiesto (ancla manual anti re-sellado).
        self.assertEqual(_manifest_of(bundle_a)["seal"]["bundle_id"], id_a)
        self.assertEqual(_manifest_of(bundle_b)["seal"]["bundle_id"], id_b)
        # bundle_id = HKDFExpand(CEK, b'bundle-id', 16) recalculado (§6).
        self.assertEqual(derive_subkeys(cek_a).bundle_id_raw.hex(), id_a)
        self.assertEqual(derive_subkeys(cek_b).bundle_id_raw.hex(), id_b)

    def test_row13_bundle_id_in_manifest_never_trusted(self):
        """El bundle_id del manifiesto se RECALCULA: alterarlo falla cerrado."""
        _store, _current, _created, bundle, _adapter = _create_sealed(self.root)
        raw = (bundle / "manifest.json").read_bytes()
        manifest = json.loads(raw)
        manifest["seal"]["bundle_id"] = (
            "0" if manifest["seal"]["bundle_id"][0] != "0" else "1"
        ) + manifest["seal"]["bundle_id"][1:]
        (bundle / "manifest.json").write_bytes(canonical_json(manifest))
        with self.assertRaises(sb.SealedPayloadAuthFailedError):
            sb.verify_sealed_bundle(bundle, runner=FakeAdapter())
        (bundle / "manifest.json").write_bytes(raw)

    # -- schema verify-result-v2: resultado KEYED REAL del código ---------------

    def test_verify_result_v2_schema_validates_real_keyed_result(self):
        """Attempt 2 (fix adversarial): el resultado KEYED REAL que produce
        ``verify_sealed_bundle`` con clave —no un ejemplo sintético— valida
        contra ``export-verify-result-v2`` (variante keyed del oneOf).
        """
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema no instalada (extra de test ausente)")
        _store, _current, _created, bundle, adapter = _create_sealed(self.root)
        cek = _cek_of(bundle, adapter)
        keyed = sb.verify_sealed_bundle(bundle, cek=cek)
        unkeyed = sb.verify_sealed_bundle(bundle)
        schema = json.loads(
            (Path(__file__).resolve().parents[1] / "docs" / "schemas"
             / "export-verify-result-v2.schema.json").read_text()
        )
        from jsonschema import Draft202012Validator

        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        self.assertTrue(keyed["verified"])
        self.assertTrue(keyed["payloads_verified"])
        self.assertEqual(keyed["warnings"], [sb.SEALED_WARNING])
        validator.validate(keyed)      # variante keyed con el dict REAL
        validator.validate(unkeyed)    # variante unkeyed con el dict REAL

    # -- fila 16 (F7): no-fuga de material secreto ------------------------------

    def test_row16_f7_no_secret_material_leak(self):
        """CEK/subclaves ausentes del bundle publicado y los resultados.

        El barrido usa un bundle creado con CEK FIJA (parche de
        ``generate_cek``) para conocer el material real: hex/b64 completos,
        prefijos y sufijos de los 4 materiales (CEK + 3 subclaves).
        """
        cek = bytes.fromhex("55" * 32)
        subkeys = derive_subkeys(cek)
        # NOTA F7 (ADR §1): ``bundle_id`` es un derivado NO secreto que
        # PERSISTE por diseño en el manifiesto y en export-result-v2
        # ("bundle_id y manifest_mac: valores derivados de la CEK que
        # también persisten, pero no son material secreto"). El barrido
        # sobre manifiesto/resultados cubre por tanto CEK/aead_key/mac_key;
        # bundle_id_raw se barre COMPLETO en los ciphertexts (donde ni
        # siquiera el derivado debería colar por error).
        secret_materials = [cek, subkeys.aead_key, subkeys.mac_key]
        all_materials = secret_materials + [subkeys.bundle_id_raw]

        def representations_of(material: bytes) -> list[str]:
            b64 = base64.b64encode(material).decode("ascii")
            return [
                material.hex(),          # hex completo
                b64,                     # b64 completo
                material.hex()[:16],     # prefijo hex
                material.hex()[-16:],    # sufijo hex
                b64[:12],                # prefijo b64
                b64[-12:],               # sufijo b64
            ]

        published_needles = [
            needle
            for material in secret_materials
            for needle in representations_of(material)
        ]
        result_needles = [
            needle
            for material in all_materials
            for needle in representations_of(material)
        ]

        _store, created, bundle, _ad = self._sealed_with_cek(cek, "f7")
        verify_keyed = sb.verify_sealed_bundle(bundle, cek=cek)
        verify_unkeyed = sb.verify_sealed_bundle(bundle)

        def sweep(label: str, text: str, needles: list[str]) -> None:
            for needle in needles:
                self.assertNotIn(needle, text, f"F7 leak in {label}")

        # 1. Bundle publicado: manifiesto y ciphertexts (texto y binario).
        for path in bundle.rglob("*"):
            if not path.is_file():
                continue
            blob = path.read_bytes()
            needles = result_needles if path.name != "manifest.json" else published_needles
            sweep(f"bundle file {path} (latin-1)", blob.decode("latin-1"), needles)
            for needle in needles:
                # Barrido binario de los hex completos (>=32 chars): el
                # material crudo tampoco puede viajar como bytes.
                if len(needle) >= 32 and all(
                    c in "0123456789abcdef" for c in needle
                ):
                    self.assertNotIn(
                        bytes.fromhex(needle), blob, f"F7 binary leak in {path}"
                    )
        # 2. Resultados (create/verify con y sin clave) y warnings.
        sweep("create result", json.dumps(created), published_needles)
        sweep("keyed verify result", json.dumps(verify_keyed), published_needles)
        sweep("unkeyed verify result", json.dumps(verify_unkeyed), published_needles)
        # 3. Staging: ningún residuo con el prefijo del staging.
        leftovers = [p.name for p in bundle.parent.iterdir() if "staging" in p.name]
        self.assertEqual(leftovers, [])
        # 4. bundle_id/manifest_mac (derivados NO secretos) SÍ están.
        self.assertIn(_manifest_of(bundle)["seal"]["bundle_id"], json.dumps(created))
        self.assertIn("manifest_mac", json.dumps(_manifest_of(bundle)))

    def test_row16_f7_no_leak_in_errors(self):
        """Los mensajes de error autenticado no distinguen ni embeben nada."""
        _store, _current, _created, bundle, _adapter = _create_sealed(self.root)
        target = self._entry_file(bundle, 0)
        data = target.read_bytes()
        target.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
        with self.assertRaises(sb.SealedPayloadAuthFailedError) as ctx:
            sb.verify_sealed_bundle(bundle, runner=FakeAdapter())
        message = str(ctx.exception)
        for word in ("cek", "key", "tag", "size", "aad", "mac"):
            self.assertNotIn(word, message.lower())

    # -- adapter_id (nota T3-N1 / §6) -------------------------------------------

    def test_adapter_id_invalid_rejected_at_manifest_write(self):
        for index, bad in enumerate(
            ("", ".", "..", "-lead", "has space", "áccent", "a" * 65, "a/b")
        ):
            with self.subTest(adapter_id=bad):
                store, _current = _make_store(self.root / f"source-bad-{index}")
                with self.assertRaises(sb.SealedAdapterIdInvalidError) as ctx:
                    sb.create_sealed_bundle(
                        store, self.root / "bad-id", FixedIdAdapter(bad)
                    )
                self.assertEqual(
                    ctx.exception.ERROR_CODE, "sealing_adapter_id_invalid"
                )
                self.assertFalse((self.root / "bad-id").exists())

    def test_adapter_id_grammar_edges_accepted(self):
        """Bordes VÁLIDOS de la gramática: 1 char, 64 chars, separadores."""
        for good in ("a", "a" * 64, "A.b_C-d0", "1"):
            with self.subTest(adapter_id=good):
                store, _current = _make_store(
                    self.root / f"source-ok-{abs(hash(good)) % 100000}"
                )
                created = sb.create_sealed_bundle(
                    store, self.root / f"ok-{abs(hash(good)) % 1000}",
                    FixedIdAdapter(good),
                )
                self.assertTrue(created["created"])

    # -- staging/destino: F6 ------------------------------------------------------

    def test_destination_exists_refused(self):
        _store, _current, _created, bundle, _adapter = _create_sealed(self.root)
        with self.assertRaises(ExportIOError) as ctx:
            sb.create_sealed_bundle(_store, bundle, FakeAdapter())
        self.assertEqual(str(ctx.exception), "export_destination_exists")

    def test_no_staging_residue_on_adapter_failure(self):
        """Adaptador que reviene en wrap: sin destino ni staging huérfano."""
        store, _current = _make_store(self.root / "source")

        class ExplodingAdapter(FakeAdapter):
            def wrap_cek(self, cek):
                raise RuntimeError("adapter exploded")

        with self.assertRaises(RuntimeError):
            sb.create_sealed_bundle(store, self.root / "boom", ExplodingAdapter())
        self.assertFalse((self.root / "boom").exists())
        self.assertEqual(
            [p.name for p in self.root.iterdir() if "staging" in p.name], []
        )

    def test_restore_refuses_existing_destination(self):
        _store, _current, _created, bundle, adapter = _create_sealed(self.root)
        restored = self.root / "restored"
        (restored / ".an-kla").mkdir(parents=True)
        with self.assertRaises(ExportIOError):
            sb.restore_sealed_bundle(bundle, restored, runner=adapter)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
