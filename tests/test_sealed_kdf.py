"""Tests del KDF sellado (HKDF-SHA256 solo Expand) — T2 de issue #46.

Verifican el contrato criptográfico de ``an_kla.sealed.kdf``:

1. **Vectores independientes**: HKDFExpand sobre CEKs fijas produce los
   valores esperados calculados en el PROPIO test con ``hashlib``/``hmac``
   puros de la stdlib (RFC 5869 §2.3, T(N) = HMAC(PRK, T(N-1) | info | N)
   desde T(0) = vacío), SIN usar ``cryptography``. Esto valida la
   implementación (que SÍ usa ``cryptography``) contra una segunda
   implementación independiente.
2. Los vectores satisfacen además RFC 5869 Test Case 1 (PRK OKM de 42
   bytes): prueba de la primitiva contra el RFC usando HKDFExpand directo
   (la PRK de ese vector es uniforme, exactamente el régimen de este
   módulo).
3. **Separación de dominio**: las 3 subclaves del ADR §1 son distintas
   entre sí, deterministas y de longitud exacta.
4. **Contrato de entrada**: CEK != 32 bytes, info no-bytes y length
   inválido rechazados ANTES del import del extra (errores independientes
   del entorno).
5. **F7**: ``str``/``repr``/pickle/JSON de ``SealedSubkeys`` sin material.
6. **Fail-closed sin extra**: operaciones con import roto fallan con
   ``SealedExtraNotInstalledError`` (código
   ``sealing_extra_not_installed``), INDEPENDIENTEMENTE del flag
   por-proceso ``sealed_available`` (nota del adversarial T1).
7. Igualdad por ``hmac.compare_digest`` y desigualdad real entre subclaves.

Entorno: la suite canónica corre SIN ``cryptography`` (extra ``[sealed]``
declarado, no instalado). Los tests criptográficos se saltan con skip
honesto cuando el intérprete no tiene la librería — igual que T1.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import subprocess
import pathlib
import sys
import unittest


def _cryptography_importable() -> bool:
    try:
        import cryptography  # noqa: F401
    except ImportError:
        return False
    return True


# --- Implementación de referencia independiente (stdlib pura) ----------------


def _hkdf_expand_reference(prk: bytes, info: bytes, length: int) -> bytes:
    """HKDF-Expand (RFC 5869 §2.3) implementado aquí con hashlib/hmac puros.

    Segunda implementación independiente de la del módulo (que usa
    ``cryptography``): T(N) = HMAC(PRK, T(N-1) || info || N), T(0) = vacío.
    """
    okm = b""
    block = b""
    counter = 1
    while len(okm) < length:
        block = hmac.new(prk, block + info + bytes([counter]),
                         hashlib.sha256).digest()
        okm += block
        counter += 1
    return okm[:length]


# --- Vectores ----------------------------------------------------------------
# RFC 5869 Appendix A, Test Case 1 — satisfecho por la primitiva HKDFExpand
# directa cuando la PRK ya es el valor uniforme del vector.
_RFC5869_TC1 = {
    "prk": bytes.fromhex(
        "077709362c2e32df0ddc3f0dc47bba6390b6c73bb50f9c3122ec844ad7c2b3e5"),
    "info": bytes.fromhex("f0f1f2f3f4f5f6f7f8f9"),
    "length": 42,
    "okm": bytes.fromhex(
        "3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf"
        "34007208d5b887185865"),
}

# CEKs fijas arbitrarias para los vectores de las 3 subclaves del ADR §1.
# Los OKM esperados NO están hardcodeados: se calculan en el test con la
# referencia stdlib, de modo que la validación sea independiente.
_TEST_CEKS = [
    bytes.fromhex("00" * 32),
    bytes.fromhex(
        "3afb141faf8ee010b48584c0b896b9a8e33a2c1e1f6c1a9ddafab7f3b0f0a041"),
    bytes.fromhex(
        "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"),
]


class TestHkdfExpandIndependentVectors(unittest.TestCase):
    """La implementación del módulo coincide con la referencia stdlib pura."""

    def test_matches_reference_on_adr_infos(self):
        """HKDFExpand == referencia para las 3 info del ADR en CEKs fijas."""
        if not _cryptography_importable():
            self.skipTest("cryptography no instalada (extra [sealed] ausente); "
                          "vector criptográfico no ejecutable en este intérprete")
        from an_kla.sealed import kdf

        for cek in _TEST_CEKS:
            for info, length in (
                (kdf.INFO_AEAD_KEY, 32),
                (kdf.INFO_BUNDLE_ID, 16),
                (kdf.INFO_MANIFEST_MAC, 32),
            ):
                with self.subTest(cek=cek.hex()[:8], info=info, length=length):
                    self.assertEqual(
                        kdf.hkdf_expand(cek, info, length),
                        _hkdf_expand_reference(cek, info, length))

    def test_matches_reference_various_lengths(self):
        """Longitudes varias (1, 31, 32, 33, 64, 100) también coinciden."""
        if not _cryptography_importable():
            self.skipTest("cryptography no instalada; "
                          "vector criptográfico no ejecutable en este intérprete")
        from an_kla.sealed import kdf

        prk = _TEST_CEKS[1]
        for length in (1, 31, 32, 33, 64, 100):
            with self.subTest(length=length):
                self.assertEqual(
                    kdf.hkdf_expand(prk, b"domain-sep-test", length),
                    _hkdf_expand_reference(prk, b"domain-sep-test", length))

    def test_rfc5869_test_case_1(self):
        """Primitiva HKDFExpand directa satisface RFC 5869 Test Case 1."""
        if not _cryptography_importable():
            self.skipTest("cryptography no instalada; "
                          "vector RFC 5869 no ejecutable en este intérprete")
        from an_kla.sealed import kdf

        self.assertEqual(
            kdf.hkdf_expand(_RFC5869_TC1["prk"],
                            _RFC5869_TC1["info"],
                            _RFC5869_TC1["length"]),
            _RFC5869_TC1["okm"])
        # La referencia stdlib del test también lo satisface (sanity del vector).
        self.assertEqual(
            _hkdf_expand_reference(_RFC5869_TC1["prk"],
                                   _RFC5869_TC1["info"],
                                   _RFC5869_TC1["length"]),
            _RFC5869_TC1["okm"])

    def test_deterministic(self):
        """Misma CEK + info → mismos bytes, siempre (dos llamadas)."""
        if not _cryptography_importable():
            self.skipTest("cryptography no instalada")
        from an_kla.sealed import kdf

        cek = _TEST_CEKS[1]
        self.assertEqual(kdf.hkdf_expand(cek, kdf.INFO_AEAD_KEY, 32),
                         kdf.hkdf_expand(cek, kdf.INFO_AEAD_KEY, 32))


class TestDeriveSubkeys(unittest.TestCase):
    """Las TRES subclaves exactas del ADR §1, con separación de dominio."""

    def test_exact_lengths_and_infos(self):
        """aead 32 / bundle_id_raw 16 / mac 32, derivadas con las info literales."""
        if not _cryptography_importable():
            self.skipTest("cryptography no instalada")
        from an_kla.sealed import kdf

        cek = _TEST_CEKS[1]
        sk = kdf.derive_subkeys(cek)
        self.assertEqual(sk.aead_key,
                         _hkdf_expand_reference(cek, b"aead-key", 32))
        self.assertEqual(sk.bundle_id_raw,
                         _hkdf_expand_reference(cek, b"bundle-id", 16))
        self.assertEqual(sk.mac_key,
                         _hkdf_expand_reference(cek, b"manifest-mac", 32))

    def test_info_literals_frozen(self):
        """Las info strings del ADR §1 son exactamente estas, sin variantes."""
        from an_kla.sealed import kdf

        self.assertEqual(kdf.INFO_AEAD_KEY, b"aead-key")
        self.assertEqual(kdf.INFO_BUNDLE_ID, b"bundle-id")
        self.assertEqual(kdf.INFO_MANIFEST_MAC, b"manifest-mac")

    def test_domain_separation_keys_differ(self):
        """Las 3 subclaves son distintas entre sí (info diferentes → K distintas)."""
        if not _cryptography_importable():
            self.skipTest("cryptography no instalada")
        from an_kla.sealed import kdf

        sk = kdf.derive_subkeys(_TEST_CEKS[0])
        self.assertNotEqual(sk.aead_key, sk.mac_key)
        self.assertNotEqual(sk.aead_key, sk.bundle_id_raw)
        self.assertNotEqual(sk.bundle_id_raw, sk.mac_key)

    def test_never_the_cek_itself(self):
        """La CEK raíz nunca es subclave ni clave AES directa (ADR §1)."""
        if not _cryptography_importable():
            self.skipTest("cryptography no instalada")
        from an_kla.sealed import kdf

        cek = _TEST_CEKS[0]
        sk = kdf.derive_subkeys(cek)
        self.assertNotEqual(sk.aead_key, cek)
        self.assertNotEqual(sk.mac_key, cek)
        self.assertNotEqual(sk.bundle_id_raw, cek[:16])

    def test_different_ceks_different_subkeys(self):
        """CEK distinta → las 3 subclaves cambian (una CEK nueva por bundle)."""
        if not _cryptography_importable():
            self.skipTest("cryptography no instalada")
        from an_kla.sealed import kdf

        sk0 = kdf.derive_subkeys(_TEST_CEKS[0])
        sk1 = kdf.derive_subkeys(_TEST_CEKS[1])
        self.assertNotEqual(sk0.aead_key, sk1.aead_key)
        self.assertNotEqual(sk0.bundle_id_raw, sk1.bundle_id_raw)
        self.assertNotEqual(sk0.mac_key, sk1.mac_key)
        self.assertNotEqual(sk0, sk1)


class TestKdfInputContract(unittest.TestCase):
    """Errores de contrato del caller — independientes del extra (pre-import)."""

    def test_cek_wrong_length_rejected(self):
        """CEK de 31/33/0 bytes rechazada con ValueError ANTES del import."""
        from an_kla.sealed import kdf

        for bad in (b"", b"x" * 31, b"x" * 33):
            with self.subTest(len=len(bad)):
                with self.assertRaises(ValueError):
                    kdf.derive_subkeys(bad)

    def test_cek_non_bytes_rejected(self):
        from an_kla.sealed import kdf

        for bad in ("x" * 32, None, 32, [1] * 32):
            with self.subTest(bad=type(bad).__name__):
                with self.assertRaises(TypeError):
                    kdf.derive_subkeys(bad)

    def test_hkdf_expand_length_contract(self):
        from an_kla.sealed import kdf

        for bad in (0, -1):
            with self.subTest(length=bad):
                with self.assertRaises(ValueError):
                    kdf.hkdf_expand(b"k" * 32, b"info", bad)
        with self.assertRaises(TypeError):
            kdf.hkdf_expand(b"k" * 32, b"info", "32")
        with self.assertRaises(ValueError):
            kdf.hkdf_expand(b"k" * 32, b"info", 255 * 32 + 1)

    def test_hkdf_expand_non_bytes_rejected(self):
        from an_kla.sealed import kdf

        with self.assertRaises(TypeError):
            kdf.hkdf_expand("k" * 32, b"info", 32)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            kdf.hkdf_expand(b"k" * 32, "info", 32)  # type: ignore[arg-type]

    def test_memoryview_accepted(self):
        """Los buffers de lectura (memoryview) son entrada válida."""
        if not _cryptography_importable():
            self.skipTest("cryptography no instalada")
        from an_kla.sealed import kdf

        cek = memoryview(_TEST_CEKS[1])
        sk = kdf.derive_subkeys(cek)
        self.assertEqual(sk.aead_key,
                         _hkdf_expand_reference(_TEST_CEKS[1], b"aead-key", 32))


class TestSealedSubkeysF7(unittest.TestCase):
    """INVARIANTE F7: jamás material clave en str/repr/serializaciones."""

    def _make(self):
        if not _cryptography_importable():
            self.skipTest("cryptography no instalada")
        from an_kla.sealed import kdf

        return kdf.derive_subkeys(_TEST_CEKS[1])

    def test_repr_str_redacted(self):
        sk = self._make()
        for text in (repr(sk), str(sk), f"{sk}", format(sk)):
            self.assertNotIn(sk.aead_key.hex(), text)
            self.assertNotIn(sk.bundle_id_raw.hex(), text)
            self.assertNotIn(sk.mac_key.hex(), text)
            for material in (sk.aead_key, sk.bundle_id_raw, sk.mac_key):
                # Ningún byte crudo representable aparece.
                self.assertNotIn(repr(material), text)
            self.assertNotIn(sk.aead_key.hex()[:16], text)

    def test_pickle_refused(self):
        import pickle

        sk = self._make()
        with self.assertRaises(TypeError):
            pickle.dumps(sk)

    def test_json_serialization_has_no_material(self):
        """json.dumps por defecto RECHAZA el objeto (bytes no serializables)."""
        sk = self._make()
        with self.assertRaises(TypeError):
            json.dumps(sk)
        # Ni el default=… lo saca: no hay __dict__ ni protocolo dict.
        with self.assertRaises(TypeError):
            json.dumps({"subkeys": sk})

    def test_no_dict_introspection(self):
        """Sin __dict__: las slots privadas no se exfiltran por vars()."""
        sk = self._make()
        with self.assertRaises(TypeError):
            vars(sk)


class TestKdfFailClosedWithoutExtra(unittest.TestCase):
    """Sin el extra, las operaciones KDF fallan cerrado — sin acoplarse al flag."""

    def _run_blocked(self, code: str):
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
        return subprocess.run(
            [sys.executable, "-c", wrapper + code],
            capture_output=True, text=True,
            cwd=str(pathlib.Path(__file__).resolve().parents[1]),
        )

    def test_hkdf_expand_fails_closed_with_import_blocked(self):
        result = self._run_blocked(
            "import an_kla.sealed as s\n"
            "from an_kla.sealed import kdf\n"
            "assert s.sealed_available is False\n"
            "try:\n"
            "    kdf.hkdf_expand(b'k' * 32, b'info', 32)\n"
            "except s.SealedExtraNotInstalledError as e:\n"
            "    assert 'sealed' in str(e), str(e)\n"
            "else:\n"
            "    raise AssertionError('did not fail closed')\n"
        )
        self.assertEqual(result.returncode, 0,
                         msg=f"stderr: {result.stderr}\nstdout: {result.stdout}")

    def test_derive_subkeys_fails_closed_with_import_blocked(self):
        result = self._run_blocked(
            "import an_kla.sealed as s\n"
            "from an_kla.sealed import kdf\n"
            "try:\n"
            "    kdf.derive_subkeys(b'k' * 32)\n"
            "except s.SealedExtraNotInstalledError:\n"
            "    pass\n"
            "else:\n"
            "    raise AssertionError('did not fail closed')\n"
        )
        self.assertEqual(result.returncode, 0,
                         msg=f"stderr: {result.stderr}\nstdout: {result.stdout}")

    def test_input_errors_precede_extra_error(self):
        """CEK de longitud mala NO exige el extra: ValueError del contrato."""
        result = self._run_blocked(
            "from an_kla.sealed import kdf\n"
            "try:\n"
            "    kdf.derive_subkeys(b'short')\n"
            "except ValueError:\n"
            "    pass\n"
            "else:\n"
            "    raise AssertionError('expected ValueError before extra check')\n"
        )
        self.assertEqual(result.returncode, 0,
                         msg=f"stderr: {result.stderr}\nstdout: {result.stdout}")

    def test_error_independent_of_availability_flag(self):
        """KDF/CEK no consultan sealed_available: su error es del import real.

        Se fuerza sealed_available=True (monkeyup) con el import roto: la
        operación DEBE fallar igual con SealedExtraNotInstalledError — el
        flag por-proceso jamás enmascara la ausencia real del extra.
        """
        result = self._run_blocked(
            "import an_kla.sealed as s\n"
            "from an_kla.sealed import kdf\n"
            "s.sealed_available = True  # mentira deliberada (nota T1)\n"
            "try:\n"
            "    kdf.hkdf_expand(b'k' * 32, b'info', 32)\n"
            "except s.SealedExtraNotInstalledError:\n"
            "    pass\n"
            "else:\n"
            "    raise AssertionError('flag enmascaro la ausencia real')\n"
        )
        self.assertEqual(result.returncode, 0,
                         msg=f"stderr: {result.stderr}\nstdout: {result.stdout}")


class TestSealedSubkeysEquality(unittest.TestCase):
    def test_equal_for_same_cek(self):
        if not _cryptography_importable():
            self.skipTest("cryptography no instalada")
        from an_kla.sealed import kdf

        self.assertEqual(kdf.derive_subkeys(_TEST_CEKS[1]),
                         kdf.derive_subkeys(_TEST_CEKS[1]))

    def test_not_equal_to_non_subkeys(self):
        if not _cryptography_importable():
            self.skipTest("cryptography no instalada")
        from an_kla.sealed import kdf

        sk = kdf.derive_subkeys(_TEST_CEKS[1])
        self.assertNotEqual(sk, "not-a-subkeys")
        self.assertFalse(sk == 42)

    def test_constructor_validates_material(self):
        from an_kla.sealed import kdf

        with self.assertRaises(ValueError):
            kdf.SealedSubkeys(b"a" * 31, b"b" * 16, b"c" * 32)
        with self.assertRaises(ValueError):
            kdf.SealedSubkeys(b"a" * 32, b"b" * 15, b"c" * 32)
        with self.assertRaises(ValueError):
            kdf.SealedSubkeys(b"a" * 32, b"b" * 16, b"c" * 33)
        with self.assertRaises(TypeError):
            kdf.SealedSubkeys("a" * 32, b"b" * 16, b"c" * 32)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
