"""Tests CLI del dispatcher dual export/restore sellado — T5 de issue #46.

Superficie bajo prueba: ``an_kla.sealed.cli_dispatch`` (wiring) + flags
``--seal/--key-adapter/--key-adapter-arg/--key-adapter-env`` en
``cli_parser``/``__main__`` sobre la capa bundle T4 intacta.

Cobertura = TODOS los checks DoD de la tarjeta:

1. ``export create --seal sealed-export/v1 --key-adapter ...`` produce
   bundle sellado verificable (roundtrip completo por superficie CLI).
2. ``export verify`` SIN clave sobre bundle sellado: verified:false,
   structure/payloads, warning ``sealed_payloads_unverified_without_key`` —
   y CADA una de las 6 categorías de corrupción estructural §8 →
   ``diagnostics`` correctos del enum (manifest_invalid, entry_size_mismatch,
   entry_missing, entry_unexpected, unsafe_path, count_mismatch).
3. verify CON clave: verified:true + warning
   ``sealed_export_untrusted_memory_data``.
4. Downgrade: sellado pidiendo v1 → ``unsupported_export_profile``; perfil
   desconocido → ``unsupported_export_profile``; sellado sin adaptador →
   fail-closed ``sealing_adapter_required`` (nunca claro).
5. Sin ``--seal``: camino export/v1 EXACTO (schema v1, warning v1 intacto).
6. ``--key-adapter`` con espacios → rechazo (sin split); flags repetibles
   construyen argv sin shell (espacios en un arg preservados).
7. Taxonomía warnings §7 SIN cruce: sellado jamás emite
   ``plaintext_export_contains_untrusted_memory_data`` y viceversa.
8. ``export-result-v2`` con ``bundle_id`` + ``manifest_sha256`` accesibles.

Entornos (lección A3 + T4-N2): el dispatcher/flags/downgrade/sin-clave
corren SIN ``cryptography`` en la suite canónica .venv (el unkeyed es
stdlib pura); sólo lo criptográfico (create/verify-keyed con AEAD) se
ejercita con CLT python3 (skips honestos, patrón T4). Los tests que no
necesitan criptografía usan un bundle sellado sintético válido en
estructura (manifiesto v2 canónico + ciphertexts con tamaño size+16)
para cubrir el unkeyed REAL, no un stub.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest

from an_kla.canonical import canonical_json, digest_bytes, digest_json
from an_kla.export_restore import ExportError, PROFILE as V1_PROFILE
from an_kla.sealed import bundle as sb
from an_kla.sealed.cli_dispatch import (
    KEY_ADAPTER_SPACES_CODE,
    UNSUPPORTED_PROFILE_CODE,
    adapter_runner,
    dispatch_export_create,
    dispatch_export_restore,
    dispatch_export_verify,
)
from an_kla.sealed.key_adapter import SealingAdapterRequiredError
from an_kla.store import MemoryStore

ROOT = Path(__file__).resolve().parents[1]

PLAINTEXT_WARNING = "plaintext_export_contains_untrusted_memory_data"
SEALED_WARNING = "sealed_export_untrusted_memory_data"
UNKEYED_WARNING = "sealed_payloads_unverified_without_key"

DIAGNOSTIC_ENUM = {
    "manifest_invalid", "entry_size_mismatch", "entry_missing",
    "entry_unexpected", "unsafe_path", "count_mismatch",
}


def _cryptography_importable() -> bool:
    try:
        import cryptography  # noqa: F401
    except ImportError:
        return False
    return True


# ---------------------------------------------------------------------------
# Fixture: store v1 + adaptador en memoria (superficie runner de T3)
# ---------------------------------------------------------------------------


def _make_store(root: Path) -> MemoryStore:
    source = root / "source"
    source.mkdir()
    store = MemoryStore(source)
    initial = store.initialize()
    store.commit(
        expected_current_hash=initial, checkpoint_patch={},
        facts=[{"id": "f-cli-seal", "payload": {"text": "seal"}}],
    )
    return store


class FakeAdapter:
    """Adaptador determinístico en memoria (misma superficie del runner T3);
    usa el wrap/unwrap DOC de T2 (requiere cryptography SOLO al cifrar)."""

    ADAPTER_ID = "cli-test-adapter-v1"

    def __init__(self) -> None:
        self._ceks: dict[str, bytes] = {}
        self._counter = 0

    def wrap_cek(self, cek: bytes):
        from an_kla.sealed.cek import wrap_cek

        self._counter += 1
        token = f"cli-{self._counter}"
        self._ceks[token] = bytes(cek)
        blob = token.encode("ascii") + b":" + wrap_cek(cek, b"k" * 32).blob
        return types.SimpleNamespace(
            wrapped_cek=base64.b64encode(blob).decode("ascii"),
            adapter_id=self.ADAPTER_ID,
        )

    def unwrap_cek(self, wrapped_cek: str):
        from an_kla.sealed.cek import unwrap_cek

        try:
            token, blob = base64.b64decode(
                wrapped_cek, validate=True).split(b":", 1)
            cek = unwrap_cek(blob, b"k" * 32)
        except Exception as exc:
            raise sb.SealedPayloadAuthFailedError(
                "sealed payload authentication failed (no further detail)"
            ) from exc
        if token.decode("ascii") not in self._ceks:
            raise sb.SealedPayloadAuthFailedError(
                "sealed payload authentication failed (no further detail)"
            )
        return types.SimpleNamespace(cek=cek)


def _create_sealed(store: MemoryStore, bundle: Path) -> dict:
    return dispatch_export_create(
        store, bundle, seal=sb.SEALED_PROFILE, key_adapter="unused-bin",
        key_adapter_args=(),
        _runner_override=FakeAdapter(),
    )


def _keyed_verify(bundle: Path, adapter: "FakeAdapter | None" = None) -> dict:
    """Verify autenticado por la superficie de despacho (adaptador en
    memoria con la misma superficie del runner T3). El adaptador debe ser
    EL MISMO del create (la custodia del wrap vive en él, como en un
    adaptador real: el KEK/Keychain recuerda el blob)."""
    return dispatch_export_verify(
        bundle, key_adapter="x", key_adapter_args=(),
        _runner_override=adapter or FakeAdapter(),
    )


# ---------------------------------------------------------------------------
# Bundle sellado SINTÉTICO estructuralmente válido (sin cryptography):
# manifiesto v2 canónico + ciphertexts con tamaño size+16. Para cubrir el
# verify unkeyed REAL en la suite canónica .venv (lección A3/T4-N2).
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Sección criptográfica (CLT python3): roundtrip y verify CON clave
# ---------------------------------------------------------------------------


class SealedCliCryptoTests(unittest.TestCase):
    """Roundtrip completo por superficie CLI + verify autenticado (§8)."""

    def setUp(self) -> None:
        if not _cryptography_importable():
            self.skipTest(
                "cryptography no instalada (suite canónica .venv); "
                "estos tests corren con CLT python3"
            )

    def test_roundtrip_create_verify_keyed_restore_via_cli_surface(self):
        with tempfile.TemporaryDirectory() as root:
            store = _make_store(Path(root))
            bundle = Path(root) / "sealed.bundle"
            adapter = FakeAdapter()
            result = dispatch_export_create(
                store, bundle, seal=sb.SEALED_PROFILE, key_adapter="x",
                key_adapter_args=(), _runner_override=adapter,
            )
            # DoD: export-result-v2 con bundle_id + manifest_sha256 (anclas).
            self.assertEqual(result["schema"], "an-kla/export-result-v2")
            self.assertTrue(result["created"])
            self.assertRegex(result["bundle_id"], r"^[0-9a-f]{32}$")
            self.assertRegex(result["manifest_sha256"], r"^sha256:[0-9a-f]{64}$")
            self.assertEqual(result["warnings"], [SEALED_WARNING])
            self.assertNotIn(PLAINTEXT_WARNING, result["warnings"])
            manifest = json.loads((bundle / "manifest.json").read_bytes())
            self.assertEqual(manifest["profile"], sb.SEALED_PROFILE)
            self.assertEqual(manifest["seal"]["bundle_id"], result["bundle_id"])

            # DoD: verify SIN clave (estructura) + CON clave (autenticado).
            unkeyed = dispatch_export_verify(bundle)
            self.assertIs(unkeyed["verified"], False)
            self.assertIs(unkeyed["structure_verified"], True)
            self.assertIs(unkeyed["payloads_verified"], False)
            self.assertEqual(unkeyed["warnings"], [UNKEYED_WARNING])

            keyed = _keyed_verify(bundle, adapter)
            self.assertIs(keyed["verified"], True)
            self.assertIs(keyed["payloads_verified"], True)
            self.assertEqual(keyed["warnings"], [SEALED_WARNING])
            self.assertNotIn(PLAINTEXT_WARNING, keyed["warnings"])

            # Restore sellado por el dispatcher (semántica idéntica a v1).
            restored = Path(root) / "restored"
            outcome = dispatch_export_restore(
                bundle, restored, key_adapter="x", key_adapter_args=(),
                _runner_override=adapter)
            self.assertIs(outcome["published"], True)
            self.assertEqual(
                MemoryStore(restored).read_current(), store.read_current())

            # DoD: verify CON clave detecta reescritura (1 byte) — fail
            # cerrado sin oráculo (§5).
            entry = manifest["core"]["entries"][0]
            target = bundle / "entries" / entry["path"]
            target.write_bytes(target.read_bytes()[:-1] + b"\xff")
            with self.assertRaises(sb.SealedPayloadAuthFailedError):
                _keyed_verify(bundle)

    def test_roundtrip_via_subprocess_cli_real(self):
        """El CLI REAL (python -m an_kla) con flags repetibles y adaptador
        de archivo de tests (tests/adapters/file_key_adapter.py)."""
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            store = _make_store(root_path)
            key_file = root_path / "adapter.key"
            key_file.write_text("ab" * 32)
            bundle = root_path / "cli.bundle"
            adapter = ROOT / "tests" / "adapters" / "file_key_adapter.py"
            argv = [
                sys.executable, "-m", "an_kla", "--no-update-check",
                "--project-root", str(store.project_root),
                "export", "create", "--bundle", str(bundle),
                "--seal", "sealed-export/v1",
                "--key-adapter", sys.executable,
                "--key-adapter-arg", str(adapter),
                "--key-adapter-env", "ANKLA_TEST_ADAPTER_KEY_FILE",
            ]
            env = {"ANKLA_TEST_ADAPTER_KEY_FILE": str(key_file),
                   "PATH": "/usr/bin:/bin"}
            completed = subprocess.run(
                argv, cwd=ROOT, capture_output=True, text=True, env=env)
            self.assertEqual(
                completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(result["schema"], "an-kla/export-result-v2")
            self.assertEqual(result["warnings"], [SEALED_WARNING])

            keyed = subprocess.run([
                sys.executable, "-m", "an_kla", "--no-update-check",
                "export", "verify", "--bundle", str(bundle),
                "--key-adapter", sys.executable,
                "--key-adapter-arg", str(adapter),
                "--key-adapter-env", "ANKLA_TEST_ADAPTER_KEY_FILE",
            ], cwd=ROOT, capture_output=True, text=True, env=env)
            self.assertEqual(keyed.returncode, 0, keyed.stderr)
            self.assertIs(json.loads(keyed.stdout)["verified"], True)

    def test_create_seal_without_adapter_fails_closed_never_cleartext(self):
        with tempfile.TemporaryDirectory() as root:
            store = _make_store(Path(root))
            bundle = Path(root) / "nope.bundle"
            with self.assertRaises(SealingAdapterRequiredError):
                dispatch_export_create(store, bundle, seal=sb.SEALED_PROFILE)
            self.assertFalse(bundle.exists())  # nunca claro, nunca parcial


# ---------------------------------------------------------------------------
# Sección venv SIN cryptography: dispatcher, flags, downgrade, unkeyed
# ---------------------------------------------------------------------------


_EXPORT_CAPABLE = (
    getattr(os, "O_NOFOLLOW", None) is not None
    and getattr(os, "O_DIRECTORY", None) is not None
    and os.open in os.supports_dir_fd
)


@unittest.skipUnless(_EXPORT_CAPABLE, "plataforma sin export descriptor-relative (ADR-0027)")
class DispatcherDualTests(unittest.TestCase):
    """Dispatcher dual §3 + fail-closed §5 — SIN cryptography."""

    def test_verify_without_key_on_valid_structure_never_verified_true(self):
        with tempfile.TemporaryDirectory() as root:
            bundle = Path(root) / "sealed.bundle"
            _synthetic_sealed_bundle(bundle)
            result = dispatch_export_verify(bundle)
            self.assertEqual(
                result["schema"], "an-kla/export-verify-result-v2")
            self.assertIs(result["verified"], False)
            self.assertIs(result["structure_verified"], True)
            self.assertIs(result["payloads_verified"], False)
            self.assertEqual(result["warnings"], [UNKEYED_WARNING])
            self.assertNotIn("diagnostics", result)
            # Anclas presentes cuando la estructura cuadra.
            self.assertRegex(result["bundle_id"], r"^[0-9a-f]{32}$")

    def test_downgrade_sealed_bundle_asking_v1_unsupported_profile(self):
        with tempfile.TemporaryDirectory() as root:
            bundle = Path(root) / "sealed.bundle"
            _synthetic_sealed_bundle(bundle)
            # Sellado presentado PIDIENDO camino v1 (§3): el dispatcher dual
            # NUNCA deja pasar un v2 por el lector v1 — downgrade
            # estructuralmente imposible. La superficie de despacho acepta
            # el pedido v1 explícito (el enum CLI congela --seal a un
            # elemento, así que el pedido viaja por la API equivalente).
            with self.assertRaisesRegex(
                    ExportError, UNSUPPORTED_PROFILE_CODE):
                dispatch_export_verify(bundle, seal=V1_PROFILE)
            with self.assertRaisesRegex(
                    ExportError, UNSUPPORTED_PROFILE_CODE):
                dispatch_export_restore(
                    bundle, Path(root) / "r1", seal=V1_PROFILE)

    def test_unknown_profile_unsupported(self):
        with tempfile.TemporaryDirectory() as root:
            bundle = Path(root) / "weird.bundle"
            manifest = _synthetic_sealed_bundle(bundle)
            manifest["profile"] = "sealed-export/v99"
            (bundle / "manifest.json").write_bytes(canonical_json(manifest))
            with self.assertRaisesRegex(
                    ExportError, UNSUPPORTED_PROFILE_CODE):
                dispatch_export_verify(bundle)

    def test_create_with_unknown_seal_enum_rejected_by_parser(self):
        from an_kla.cli_parser import build_parser

        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([
                "export", "create", "--bundle", "x",
                "--seal", "sealed-export/v99",
            ])

    def test_v1_bundle_path_is_exact_v1(self):
        """Sin --seal el camino es EXACTAMENTE export/v1: schema v1,
        warning v1 intacto, verify v1 sin cambios."""
        with tempfile.TemporaryDirectory() as root:
            store = _make_store(Path(root))
            bundle = Path(root) / "plain.bundle"
            created = dispatch_export_create(store, bundle)
            self.assertEqual(created["schema"], "an-kla/export-result-v1")
            self.assertEqual(created["warnings"], [PLAINTEXT_WARNING])
            self.assertNotIn(SEALED_WARNING, created["warnings"])
            manifest = json.loads((bundle / "manifest.json").read_bytes())
            self.assertEqual(manifest["profile"], "export/v1")

            verified = dispatch_export_verify(bundle)
            self.assertEqual(verified["schema"], "an-kla/export-verify-result-v1")
            self.assertIs(verified["verified"], True)
            self.assertEqual(verified["warnings"], [PLAINTEXT_WARNING])
            self.assertNotIn(SEALED_WARNING, verified["warnings"])

            restored = Path(root) / "restored"
            outcome = dispatch_export_restore(bundle, restored)
            self.assertEqual(outcome["schema"], "an-kla/restore-result-v1")
            # El warning v1 va SIEMPRE; root_relocated es runtime-condition
            # (definido por verify v1, no por el dispatcher dual).
            self.assertIn(PLAINTEXT_WARNING, outcome["warnings"])
            self.assertTrue(
                set(outcome["warnings"]) <= {PLAINTEXT_WARNING, "root_relocated"})
            self.assertNotIn(SEALED_WARNING, outcome["warnings"])

    def test_v1_bundle_with_seal_flag_unsupported_profile(self):
        with tempfile.TemporaryDirectory() as root:
            store = _make_store(Path(root))
            bundle = Path(root) / "plain.bundle"
            dispatch_export_create(store, bundle)
            with self.assertRaisesRegex(
                    ExportError, UNSUPPORTED_PROFILE_CODE):
                dispatch_export_verify(bundle, seal=sb.SEALED_PROFILE)

    def test_restore_sealed_without_adapter_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            bundle = Path(root) / "sealed.bundle"
            _synthetic_sealed_bundle(bundle)
            with self.assertRaises(SealingAdapterRequiredError):
                dispatch_export_restore(bundle, Path(root) / "restored")
            self.assertFalse((Path(root) / "restored" / ".an-kla").exists())

    def test_illegible_manifest_falls_to_v1_canonical_error(self):
        with tempfile.TemporaryDirectory() as root:
            bundle = Path(root) / "junk.bundle"
            bundle.mkdir()
            (bundle / "manifest.json").write_bytes(b"not-json{")
            with self.assertRaisesRegex(ExportError, "export_manifest_invalid"):
                dispatch_export_verify(bundle)


@unittest.skipUnless(_EXPORT_CAPABLE, "plataforma sin export descriptor-relative (ADR-0027)")
class UnkeyedDiagnosticsTests(unittest.TestCase):
    """Las 6 categorías del enum estructural §8 — SIN cryptography, sobre
    bundles sellados reales en estructura (el unkeyed jamás desencripta)."""

    def _bundle(self, root: str) -> Path:
        bundle = Path(root) / "sealed.bundle"
        self.manifest = _synthetic_sealed_bundle(bundle)
        self.bundle = bundle
        return bundle

    def _verify(self) -> dict:
        return dispatch_export_verify(self.bundle)

    def test_manifest_invalid_shape(self):
        with tempfile.TemporaryDirectory() as root:
            self._bundle(root)
            # Shape de seal rota (falta una key) con perfil sellado intacto:
            # la estructura del manifiesto v2 es inválida (§8 manifest_invalid).
            def break_seal_shape(manifest):
                manifest["seal"].pop("bundle_id")

            _rewrite_manifest(self.bundle, break_seal_shape)
            result = self._verify()
            self.assertIs(result["structure_verified"], False)
            self.assertIn("manifest_invalid", result["diagnostics"])
            for code in result["diagnostics"]:
                self.assertIn(code, DIAGNOSTIC_ENUM)

    def test_manifest_invalid_manifest_sha256_mismatch(self):
        with tempfile.TemporaryDirectory() as root:
            self._bundle(root)
            _rewrite_manifest(
                self.bundle,
                lambda manifest: manifest.update(
                    manifest_sha256="sha256:" + "f" * 64) or manifest,
                resync=False,
            )
            result = self._verify()
            self.assertIn("manifest_invalid", result["diagnostics"])

    def test_manifest_invalid_non_canonical_bytes(self):
        with tempfile.TemporaryDirectory() as root:
            self._bundle(root)
            manifest = json.loads(
                (self.bundle / "manifest.json").read_bytes())
            # Bytes no canónicos (re-serializado con espacios).
            (self.bundle / "manifest.json").write_bytes(
                json.dumps(manifest, indent=1).encode())
            result = self._verify()
            self.assertIn("manifest_invalid", result["diagnostics"])

    def test_entry_size_mismatch_physical_size(self):
        with tempfile.TemporaryDirectory() as root:
            self._bundle(root)
            entry = self.manifest["core"]["entries"][0]
            target = self.bundle / "entries" / entry["path"]
            target.write_bytes(b"\x00" * (entry["size"] + 17))
            result = self._verify()
            self.assertIs(result["structure_verified"], False)
            self.assertEqual(result["diagnostics"], ["entry_size_mismatch"])

    def test_entry_missing_listed_file_absent(self):
        with tempfile.TemporaryDirectory() as root:
            self._bundle(root)
            entry = self.manifest["core"]["entries"][0]
            (self.bundle / "entries" / entry["path"]).unlink()
            result = self._verify()
            self.assertIn("entry_missing", result["diagnostics"])

    def test_entry_unexpected_extra_file(self):
        with tempfile.TemporaryDirectory() as root:
            self._bundle(root)
            (self.bundle / "entries" / "sneaky.json").write_bytes(b"x")
            result = self._verify()
            self.assertIn("entry_unexpected", result["diagnostics"])

    def test_unsafe_path_symlink_in_entries(self):
        with tempfile.TemporaryDirectory() as root:
            self._bundle(root)
            entry = self.manifest["core"]["entries"][0]
            target = self.bundle / "entries" / entry["path"]
            payload = target.read_bytes()
            target.unlink()
            target.symlink_to(Path(root) / "outside")
            (Path(root) / "outside").write_bytes(payload)
            result = self._verify()
            self.assertIn("unsafe_path", result["diagnostics"])

    def test_unsafe_path_disallowed_path_in_manifest(self):
        with tempfile.TemporaryDirectory() as root:
            self._bundle(root)

            def mutate(manifest):
                entry = manifest["core"]["entries"][0]
                entry["path"] = "anchor/../escape.json"
                return manifest

            _rewrite_manifest(self.bundle, mutate)
            result = self._verify()
            self.assertIn("unsafe_path", result["diagnostics"])

    def test_count_mismatch_totals(self):
        with tempfile.TemporaryDirectory() as root:
            self._bundle(root)

            def mutate(manifest):
                manifest["core"]["total_bytes"] += 1
                return manifest

            _rewrite_manifest(self.bundle, mutate)
            result = self._verify()
            self.assertIn("count_mismatch", result["diagnostics"])

    def test_count_mismatch_entry_count(self):
        with tempfile.TemporaryDirectory() as root:
            self._bundle(root)

            def mutate(manifest):
                manifest["core"]["entry_count"] += 1
                return manifest

            _rewrite_manifest(self.bundle, mutate)
            result = self._verify()
            self.assertIn("count_mismatch", result["diagnostics"])

    def test_diagnostics_enum_closed_and_never_verified_true(self):
        """Todo diagnóstico emitido pertenece al enum §8 cerrado y el
        resultado JAMÁS afirma verified/autenticidad."""
        with tempfile.TemporaryDirectory() as root:
            self._bundle(root)
            (self.bundle / "entries" / "sneaky.json").write_bytes(b"x")
            result = self._verify()
            self.assertIs(result["verified"], False)
            self.assertIs(result["payloads_verified"], False)
            for code in result["diagnostics"]:
                self.assertIn(code, DIAGNOSTIC_ENUM)
            self.assertEqual(result["warnings"], [UNKEYED_WARNING])


@unittest.skipUnless(_EXPORT_CAPABLE, "plataforma sin export descriptor-relative (ADR-0027)")
class KeyAdapterFlagsTests(unittest.TestCase):
    """--key-adapter: PROHIBIDO el split de string con espacios (§2);
    flags repetibles construyen argv sin shell."""

    def test_key_adapter_with_spaces_rejected_no_split(self):
        with self.assertRaises(ValueError) as caught:
            adapter_runner("bin --flag value")
        self.assertEqual(str(caught.exception), KEY_ADAPTER_SPACES_CODE)

    def test_key_adapter_with_tab_rejected(self):
        with self.assertRaises(ValueError):
            adapter_runner("bin\targ")

    def test_missing_adapter_required(self):
        with self.assertRaises(SealingAdapterRequiredError):
            adapter_runner(None)

    def test_repeated_flags_build_argv_without_shell(self):
        runner = adapter_runner(
            "/bin/echo", ["arg with spaces", "--flag", "value"])
        self.assertEqual(
            runner._argv, ["/bin/echo", "arg with spaces", "--flag", "value"])

    def test_repeated_flags_cli_surface_preserves_spaces(self):
        """El CLI REAL: --key-adapter-arg repetibles conservan espacios
        como UN elemento de argv (sin shell, sin split)."""
        from an_kla.cli_parser import build_parser

        parser = build_parser()
        args = parser.parse_args([
            "export", "create", "--bundle", "b",
            "--seal", "sealed-export/v1",
            "--key-adapter", "/bin/echo",
            "--key-adapter-arg", "first arg with spaces",
            "--key-adapter-arg=--second",  # forma '=': valor con prefijo --
        ])
        self.assertEqual(args.key_adapter, "/bin/echo")
        self.assertEqual(args.key_adapter_arg, [
            "first arg with spaces", "--second"])
        self.assertEqual(args.seal, "sealed-export/v1")

    def test_runner_executes_repeated_argv_without_shell(self):
        """End-to-end del argv estructurado: el runner ejecuta
        [bin, *args] sin shell (el adaptador de tests recibe los args)."""
        import os

        with tempfile.TemporaryDirectory() as root:
            key_file = Path(root) / "adapter.key"
            key_file.write_text("ab" * 32)
            adapter = ROOT / "tests" / "adapters" / "file_key_adapter.py"
            os.environ["ANKLA_TEST_ADAPTER_KEY_FILE"] = str(key_file)
            try:
                runner = adapter_runner(
                    sys.executable,
                    [str(adapter), "--ignored-with-spaces arg"],
                    key_adapter_env=["ANKLA_TEST_ADAPTER_KEY_FILE"],
                )
                result = runner.wrap_cek(b"k" * 32)
                self.assertEqual(
                    result.adapter_id, "tests.file-key-adapter.v1")
                self.assertTrue(result.wrapped_cek)
                back = runner.unwrap_cek(result.wrapped_cek)
                self.assertEqual(back.cek, b"k" * 32)
            finally:
                del os.environ["ANKLA_TEST_ADAPTER_KEY_FILE"]


if __name__ == "__main__":
    unittest.main()
