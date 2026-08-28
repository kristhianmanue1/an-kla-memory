"""Tests de CEK efímera y wrap/unwrap — T2 de issue #46.

Verifican el contrato de ``an_kla.sealed.cek``:

1. ``generate_cek``: 32 bytes del CSPRNG del SO, sin extra requerido
   (generar no es cifrar), sin falsa unicidad (no repite con prob. alta).
2. **Roundtrip**: ``wrap(CEK, kek) → unwrap(wrapped, kek) == CEK`` byte a
   byte; el blob tiene la longitud estructural exacta (nonce 12 || cek 32
   || tag 16 = 60).
3. **Fail-closed sin degradación**: unwrap con KEK errónea/blob corrupto/
   tag inválido falla SIEMPRE con ``SealedCekUnwrapError`` — mismo
   mensaje uniforme, sin distinguir la causa (sin oráculo), y NUNCA
   devuelve la CEK en claro sin autenticar.
4. **F7**: CEK y blob ausentes de ``str``/``repr``/pickle/JSON de los
   objetos del módulo (``WrappedCek``).
5. KEK inyectable como parámetro: dos KEKs distintas → blobs distintos y
   unwrap cruzado falla.
6. **Imports perezosos**: ``an_kla.sealed.cek`` importable stdlib-only;
   operaciones fallan cerrado con ``SealedExtraNotInstalledError``
   (código ``sealing_extra_not_installed``) cuando ``cryptography``
   falta — independiente del flag por-proceso ``sealed_available``.

Entorno: la suite canónica corre SIN ``cryptography`` (skip honesto en los
tests criptográficos, igual que T1).
"""

from __future__ import annotations

import json
import os
import pathlib
import pickle
import subprocess
import sys
import unittest


def _cryptography_importable() -> bool:
    try:
        import cryptography  # noqa: F401
    except ImportError:
        return False
    return True


class TestGenerateCek(unittest.TestCase):
    """F1: 32 bytes del CSPRNG del SO, una por bundle."""

    def test_length_is_32(self):
        from an_kla.sealed.cek import generate_cek

        self.assertEqual(len(generate_cek()), 32)

    def test_returns_bytes(self):
        from an_kla.sealed.cek import generate_cek

        cek = generate_cek()
        self.assertIsInstance(cek, bytes)

    def test_fresh_cek_each_call(self):
        """Cada llamada da material nuevo: dos CEKs consecutivas difieren.

        (Probabilístico pero no flaky en la práctica: P(colisión de 32
        bytes aleatorios) ≈ 2^-256.)
        """
        from an_kla.sealed.cek import generate_cek

        seen = {generate_cek() for _ in range(16)}
        self.assertEqual(len(seen), 16)

    def test_generate_works_without_extra(self):
        """Generar la CEK es stdlib: no requiere cryptography.

        Se bloquea el import de cryptography: generate_cek debe funcionar.
        """
        code = (
            "import sys\n"
            "class _Block:\n"
            "    def find_spec(self, name, path=None, target=None):\n"
            "        if name == 'cryptography' or name.startswith("
            "'cryptography.'):\n"
            "            raise ImportError('blocked for test')\n"
            "        return None\n"
            "sys.meta_path.insert(0, _Block())\n"
            "from an_kla.sealed.cek import generate_cek, CEK_LENGTH\n"
            "cek = generate_cek()\n"
            "assert isinstance(cek, bytes) and len(cek) == CEK_LENGTH\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True,
            cwd=str(pathlib.Path(__file__).resolve().parents[1]),
        )
        self.assertEqual(result.returncode, 0,
                         msg=f"stderr: {result.stderr}\nstdout: {result.stdout}")


class TestWrapUnwrapRoundtrip(unittest.TestCase):
    def setUp(self):
        if not _cryptography_importable():
            self.skipTest("cryptography no instalada (extra [sealed] ausente); "
                          "test criptográfico no ejecutable en este intérprete")
        from an_kla.sealed import cek as cek_mod

        self.cek_mod = cek_mod

    def test_roundtrip_byte_exact(self):
        cek = self.cek_mod.generate_cek()
        kek = os.urandom(32)
        wrapped = self.cek_mod.wrap_cek(cek, kek)
        self.assertEqual(self.cek_mod.unwrap_cek(wrapped, kek), cek)

    def test_roundtrip_with_raw_bytes_blob(self):
        """unwrap acepta tanto WrappedCek como los bytes crudos del blob."""
        cek = self.cek_mod.generate_cek()
        kek = os.urandom(32)
        wrapped = self.cek_mod.wrap_cek(cek, kek)
        self.assertEqual(self.cek_mod.unwrap_cek(wrapped.blob, kek), cek)

    def test_wrapped_blob_structural_length(self):
        """Blob = nonce(12) || ciphertext(32) || tag(16) = 60 bytes exactos."""
        cek = self.cek_mod.generate_cek()
        kek = os.urandom(32)
        wrapped = self.cek_mod.wrap_cek(cek, kek)
        self.assertEqual(len(wrapped.blob), 60)
        self.assertEqual(len(wrapped.blob),
                         self.cek_mod.WRAPPED_CEK_BLOB_LENGTH)

    def test_wrap_is_randomized(self):
        """Nonce aleatorio por wrap: dos wraps de la misma CEK difieren."""
        cek = self.cek_mod.generate_cek()
        kek = os.urandom(32)
        w1 = self.cek_mod.wrap_cek(cek, kek)
        w2 = self.cek_mod.wrap_cek(cek, kek)
        self.assertNotEqual(w1.blob, w2.blob)
        # ...pero ambos desenrrollan a la misma CEK.
        self.assertEqual(self.cek_mod.unwrap_cek(w1, kek), cek)
        self.assertEqual(self.cek_mod.unwrap_cek(w2, kek), cek)

    def test_kek_is_injectable_parameter(self):
        """Contrato de función pura: la KEK entra como parámetro.

        Dos KEKs distintas envuelven a blobs distintos; unwrap cruzado
        falla (la KEK es la capacidad de custodia, T3 la moverá al
        adaptador).
        """
        cek = self.cek_mod.generate_cek()
        kek_a = os.urandom(32)
        kek_b = os.urandom(32)
        wrapped_a = self.cek_mod.wrap_cek(cek, kek_a)
        wrapped_b = self.cek_mod.wrap_cek(cek, kek_b)
        self.assertNotEqual(wrapped_a.blob, wrapped_b.blob)
        self.assertEqual(self.cek_mod.unwrap_cek(wrapped_a, kek_a), cek)
        with self.assertRaises(self.cek_mod.SealedCekUnwrapError):
            self.cek_mod.unwrap_cek(wrapped_a, kek_b)

    def test_roundtrip_fixed_cek_and_kek(self):
        """Vector determinista: CEK/KEK fijas → roundtrip exacto."""
        cek = bytes.fromhex("13" * 32)
        kek = bytes.fromhex("57" * 32)
        wrapped = self.cek_mod.wrap_cek(cek, kek)
        self.assertEqual(self.cek_mod.unwrap_cek(wrapped, kek), cek)


class TestUnwrapFailClosedNoDegradation(unittest.TestCase):
    def setUp(self):
        if not _cryptography_importable():
            self.skipTest("cryptography no instalada")
        from an_kla.sealed import cek as cek_mod

        self.cek_mod = cek_mod

    def _uniform(self, exc: Exception) -> None:
        """Mismo mensaje uniforme para toda causa: sin oráculo."""
        self.assertEqual(str(exc), "sealed cek unwrap failed (no further detail)")

    def test_wrong_kek_fails_closed(self):
        cek = self.cek_mod.generate_cek()
        wrapped = self.cek_mod.wrap_cek(cek, os.urandom(32))
        with self.assertRaises(self.cek_mod.SealedCekUnwrapError) as ctx:
            self.cek_mod.unwrap_cek(wrapped, os.urandom(32))
        self._uniform(ctx.exception)

    def test_corrupted_blob_fails_closed(self):
        """Cada byte del blob alterado → fallo cerrado (sin restauración parcial)."""
        cek = self.cek_mod.generate_cek()
        kek = os.urandom(32)
        blob = bytearray(self.cek_mod.wrap_cek(cek, kek).blob)
        for position in (0, 11, 12, 31, 40, 59):
            with self.subTest(position=position):
                corrupted = bytearray(blob)
                corrupted[position] ^= 0x01
                with self.assertRaises(self.cek_mod.SealedCekUnwrapError) as ctx:
                    self.cek_mod.unwrap_cek(bytes(corrupted), kek)
                self._uniform(ctx.exception)

    def test_error_message_leaks_no_material(self):
        """El mensaje de error no embebe blob, CEK ni KEK (F7 + sin oráculo)."""
        cek = self.cek_mod.generate_cek()
        kek = os.urandom(32)
        wrapped = self.cek_mod.wrap_cek(cek, kek)
        with self.assertRaises(self.cek_mod.SealedCekUnwrapError) as ctx:
            self.cek_mod.unwrap_cek(wrapped, os.urandom(32))
        message = str(ctx.exception)
        self.assertNotIn(cek.hex(), message)
        self.assertNotIn(kek.hex(), message)
        self.assertNotIn(wrapped.blob.hex(), message)

    def test_impossible_lengths_rejected(self):
        """Blobs de longitud imposible: rechazo uniforme ANTES del extra."""
        kek = os.urandom(32)
        for bad in (b"", b"x" * 59, b"x" * 61, b"x" * 12, b"x" * 128):
            with self.subTest(len=len(bad)):
                with self.assertRaises(self.cek_mod.SealedCekUnwrapError) as ctx:
                    self.cek_mod.unwrap_cek(bad, kek)
                self._uniform(ctx.exception)

    def test_never_returns_cleartext_on_failure(self):
        """La única salida exitosa de unwrap es la CEK autenticada: no hay
        ruta que devuelva material sin pasar el tag GCM (sin degradación)."""
        cek = self.cek_mod.generate_cek()
        kek = os.urandom(32)
        wrapped = self.cek_mod.wrap_cek(cek, kek)
        blob = bytearray(wrapped.blob)
        blob[-1] ^= 0x01  # tag corrupto
        try:
            result = self.cek_mod.unwrap_cek(bytes(blob), kek)
        except self.cek_mod.SealedCekUnwrapError:
            return  # camino esperado
        self.fail(f"unwrap degradó a claro: devolvió {result!r}")


class TestWrapInputContract(unittest.TestCase):
    def setUp(self):
        if not _cryptography_importable():
            self.skipTest("cryptography no instalada")
        from an_kla.sealed import cek as cek_mod

        self.cek_mod = cek_mod

    def test_cek_wrong_length_rejected(self):
        for bad in (b"", b"x" * 31, b"x" * 33):
            with self.subTest(len=len(bad)):
                with self.assertRaises(ValueError):
                    self.cek_mod.wrap_cek(bad, b"k" * 32)

    def test_kek_wrong_length_rejected(self):
        for bad in (b"", b"k" * 31, b"k" * 33):
            with self.subTest(len=len(bad)):
                with self.assertRaises(ValueError):
                    self.cek_mod.wrap_cek(b"x" * 32, bad)

    def test_non_bytes_rejected(self):
        with self.assertRaises(TypeError):
            self.cek_mod.wrap_cek("x" * 32, b"k" * 32)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            self.cek_mod.wrap_cek(b"x" * 32, "k" * 32)  # type: ignore[arg-type]

    def test_unwrap_kek_wrong_length_rejected(self):
        with self.assertRaises(ValueError):
            self.cek_mod.unwrap_cek(b"x" * 60, b"k" * 31)

    def test_wrappedcek_constructor_validates_length(self):
        with self.assertRaises(ValueError):
            self.cek_mod.WrappedCek(b"x" * 59)
        with self.assertRaises(ValueError):
            self.cek_mod.WrappedCek(b"x" * 61)
        with self.assertRaises(TypeError):
            self.cek_mod.WrappedCek("x" * 60)  # type: ignore[arg-type]


class TestWrappedCekF7(unittest.TestCase):
    """F7: ni la CEK ni el blob en str/repr/serializaciones."""

    def setUp(self):
        if not _cryptography_importable():
            self.skipTest("cryptography no instalada")
        from an_kla.sealed import cek as cek_mod

        cek = bytes.fromhex("ab" * 32)
        self.cek_hex = cek.hex()
        self.wrapped = cek_mod.wrap_cek(cek, bytes.fromhex("cd" * 32))
        self.cek_mod = cek_mod

    def test_repr_str_redacted(self):
        for text in (repr(self.wrapped), str(self.wrapped), f"{self.wrapped}"):
            self.assertNotIn(self.cek_hex, text)
            self.assertNotIn(self.wrapped.blob.hex(), text)
            # Tampoco prefijos parciales que delaten material.
            self.assertNotIn(self.wrapped.blob.hex()[:16], text)

    def test_pickle_refused(self):
        with self.assertRaises(TypeError):
            pickle.dumps(self.wrapped)

    def test_json_has_no_material(self):
        with self.assertRaises(TypeError):
            json.dumps(self.wrapped)
        with self.assertRaises(TypeError):
            json.dumps({"wrapped": self.wrapped})

    def test_no_dict_introspection(self):
        with self.assertRaises(TypeError):
            vars(self.wrapped)


class TestCekFailClosedWithoutExtra(unittest.TestCase):
    """Sin extra: wrap/unwrap fallan cerrado, sin acoplarse al flag."""

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

    def test_wrap_fails_closed_with_import_blocked(self):
        result = self._run_blocked(
            "import an_kla.sealed as s\n"
            "from an_kla.sealed import cek\n"
            "assert s.sealed_available is False\n"
            "try:\n"
            "    cek.wrap_cek(b'k' * 32, b'j' * 32)\n"
            "except s.SealedExtraNotInstalledError as e:\n"
            "    assert 'sealed' in str(e), str(e)\n"
            "else:\n"
            "    raise AssertionError('did not fail closed')\n"
        )
        self.assertEqual(result.returncode, 0,
                         msg=f"stderr: {result.stderr}\nstdout: {result.stdout}")

    def test_unwrap_fails_closed_with_import_blocked(self):
        result = self._run_blocked(
            "import an_kla.sealed as s\n"
            "from an_kla.sealed import cek\n"
            "try:\n"
            "    cek.unwrap_cek(b'x' * cek.WRAPPED_CEK_BLOB_LENGTH, b'j' * 32)\n"
            "except s.SealedExtraNotInstalledError:\n"
            "    pass\n"
            "else:\n"
            "    raise AssertionError('did not fail closed')\n"
        )
        self.assertEqual(result.returncode, 0,
                         msg=f"stderr: {result.stderr}\nstdout: {result.stdout}")

    def test_error_independent_of_availability_flag(self):
        """Con sealed_available mentido a True y sin cryptography real,
        wrap debe fallar igual: el flag por-proceso no enmascara nada."""
        result = self._run_blocked(
            "import an_kla.sealed as s\n"
            "from an_kla.sealed import cek\n"
            "s.sealed_available = True  # mentira deliberada (nota T1)\n"
            "try:\n"
            "    cek.wrap_cek(b'k' * 32, b'j' * 32)\n"
            "except s.SealedExtraNotInstalledError:\n"
            "    pass\n"
            "else:\n"
            "    raise AssertionError('flag enmascaro la ausencia real')\n"
        )
        self.assertEqual(result.returncode, 0,
                         msg=f"stderr: {result.stderr}\nstdout: {result.stdout}")

    def test_module_importable_without_extra(self):
        """an_kla.sealed.cek importable stdlib-only (promesa del core)."""
        result = self._run_blocked(
            "import sys\n"
            "from an_kla.sealed import cek\n"
            "assert 'cryptography' not in sys.modules\n"
            "assert cek.CEK_LENGTH == 32\n"
        )
        self.assertEqual(result.returncode, 0,
                         msg=f"stderr: {result.stderr}\nstdout: {result.stdout}")

    def test_canonical_error_codes_exported(self):
        """La superficie de error es estable y canónica (ADR §5)."""
        from an_kla.sealed import cek

        self.assertEqual(cek.SealedCekUnwrapError.ERROR_CODE,
                         "sealed_payload_auth_failed")


class TestIntegrationDeriveAndWrap(unittest.TestCase):
    """Integración mínima KDF↔CEK dentro del alcance T2 (sin bundle, T4)."""

    def test_generated_cek_usable_for_derivation_and_wrap(self):
        if not _cryptography_importable():
            self.skipTest("cryptography no instalada")
        from an_kla.sealed import cek as cek_mod
        from an_kla.sealed import kdf

        cek = cek_mod.generate_cek()
        # La CEK sirve como raíz de las subclaves...
        subkeys = kdf.derive_subkeys(cek)
        self.assertEqual(len(subkeys.aead_key), 32)
        # ...y como material envolvible bajo una KEK inyectada.
        kek = os.urandom(32)
        wrapped = cek_mod.wrap_cek(cek, kek)
        recovered = cek_mod.unwrap_cek(wrapped, kek)
        self.assertEqual(recovered, cek)
        # Las subclaves derivadas de la CEK recuperada son idénticas.
        self.assertEqual(kdf.derive_subkeys(recovered), subkeys)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
