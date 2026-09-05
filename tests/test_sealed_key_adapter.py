"""Tests del runner seguro del adaptador externo de claves — T3 de #46.

Norma vinculante: ``docs/architecture/0042-sealed-export-v1.md`` §4
(ejecución segura congelada en Ronda 4) y §5 (superficie fail-closed).

Cubren la MATRIZ COMPLETA de la tarjeta sobre el runner
``an_kla.sealed.key_adapter`` usando el adaptador de referencia
archivo-llave (``tests/adapters/file_key_adapter.py`` — NO-producción)
y adaptadores ad-hoc (scripts Python de un solo archivo bajo un tmp dir)
para los casos de fallo.

La matriz (reglas congeladas del ADR §4 + §5):

1. Roundtrip completo vía runner: wrap → unwrap → CEK byte a byte
   idéntica (con el python3 de CLT cuando el test necesita cryptography,
   patrón T1/T2; aquí el adaptador de referencia es stdlib, así que el
   roundtrip corre en CUALQUIER intérprete — incluido el venv canónico
   SIN cryptography: el runner es stdlib pura).
2. Contrato JSON cerrado: clave extra/ausente/tipo incorrecto en la
   SALIDA del adaptador → ``sealing_adapter_error``.
3. Exit ≠ 0 con JSON válido en stdout → ``sealing_adapter_error``
   (el éxito exige exit 0 Y JSON cerrado válido).
4. Stdout basura (no JSON) → ``sealing_adapter_error``.
5. CEK decodificada ≠ 32 bytes → ``sealing_adapter_error``.
6. Timeout (adaptador que duerme) → ``sealing_adapter_error`` y árbol
   terminado (sin proceso residual gestionado).
7. Límites I/O: adaptador que emite > 64 KiB en stdout o > 8 KiB en
   stderr → ``sealing_adapter_error`` con terminación inmediata.
8. Stderr del adaptador NO aparece en NINGÚN mensaje de error del core
   (test explícito con contenido señuelo único).
9. Entorno mínimo con allowlist (F3): una variable NO-allowlisted del
   entorno padre NO llega al adaptador; una allowlisted SÍ llega.
10. ``sealing_adapter_required``: comando ausente / vacío / no-lista
    (borde caller, antes de ejecutar nada).
11. ``wrapped_cek`` opaco: el runner no interpreta el blob (solo techo
    pre-vuelo ≤ 4096 chars); CEK errónea en la entrada → ValueError de
    contrato del caller, no del adaptador.
12. Sin ``cryptography``: ``import an_kla.sealed`` exit 0; los errores
    del runner son INDEPENDIENTES del flag ``sealed_available``.
13. Higiene: argv estructurado JAMÁS pasa por shell (string → rechazo);
    el ejecutable inexistente es ``sealing_adapter_error``.
14. ``adapter_id``: gramática cerrada §6 — válido pasa; ``.``, ``..``,
    arranca con ``-``, carácter fuera de alfabeto, > 64 → error.

Particionado en beta.22 (issue #106, plan docs/plans/2026-09-01-deuda-tamanos-adopcion-skevi.md): parte del contenido vive ahora en tests/test_sealed_key_adapter_output.py, tests/test_sealed_key_adapter_behavior.py, tests/test_sealed_key_adapter_errors.py. Casos y aserciones sin cambios.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from an_kla.sealed import key_adapter as ka
from an_kla.sealed.key_adapter import (
    ADAPTER_STDERR_LIMIT,
    ADAPTER_STDOUT_LIMIT,
    ADAPTER_TIMEOUT_SECONDS,
    ADAPTER_WRAPPED_CEK_MAX_CHARS,
    SealingAdapterError,
    SealingAdapterRequiredError,
    SealingAdapterRunner,
)

TESTS_DIR = Path(__file__).resolve().parent
ADAPTERS_DIR = TESTS_DIR / "adapters"
REFERENCE_ADAPTER = ADAPTERS_DIR / "file_key_adapter.py"

ENV_KEY_FILE = "ANKLA_TEST_ADAPTER_KEY_FILE"
ENV_VERBOSE = "ANKLA_TEST_ADAPTER_VERBOSE"
ENV_PRINT_ENV = "ANKLA_TEST_ADAPTER_PRINT_ENV"

# Señuelo único: si ESTE texto aparece en un mensaje del core, stderr se
# propagó (violación directa del ADR §4).
STDERR_CANARY = "Zk7-canary-stderr-NEVER-propagate-9qXd"


def _cryptography_importable() -> bool:
    try:
        import cryptography  # noqa: F401
    except ImportError:
        return False
    return True


def _write_key_file(directory: Path) -> Path:
    """Archivo de llave del adaptador de referencia: 32 bytes hex."""
    path = directory / f"key-{secrets.token_hex(4)}.hex"
    path.write_bytes(secrets.token_hex(32).encode("ascii"))
    return path


def _reference_runner(key_file: Path, **kwargs) -> SealingAdapterRunner:
    kwargs.setdefault("env_allowlist", [ENV_KEY_FILE])
    return SealingAdapterRunner(
        [sys.executable, str(REFERENCE_ADAPTER)],
        **kwargs,
    )


class _AdHocAdapter:
    """Escribe un adaptador Python de un solo archivo en un tmp dir."""

    def __init__(self, testcase, body: str, *, argv_prefix=None):
        # TestCase.enterContext llegó en 3.11; el CLT python3 de la matriz
        # es 3.9 — compatibilidad explícita con addCleanup.
        tmp = tempfile.TemporaryDirectory()
        testcase.addCleanup(tmp.cleanup)
        base = tmp.name
        self.path = Path(base) / "adhoc_adapter.py"
        self.path.write_text(textwrap.dedent(body), encoding="utf-8")
        self.argv = list(argv_prefix or [sys.executable, str(self.path)])
        # hereda env del runner: none needed
        self.env_allowlist = []

    def runner(self, **kwargs) -> SealingAdapterRunner:
        return SealingAdapterRunner(self.argv, env_allowlist=self.env_allowlist, **kwargs)


# ---------------------------------------------------------------------------
# 1. Roundtrip completo vía runner (adaptador de referencia, stdlib)
# ---------------------------------------------------------------------------


class TestRoundtripReferenceAdapter(unittest.TestCase):
    """wrap por adaptador de referencia → unwrap → CEK byte a byte."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.key_file = _write_key_file(Path(self._tmp.name))
        os.environ[ENV_KEY_FILE] = str(self.key_file)
        self.addCleanup(os.environ.pop, ENV_KEY_FILE, None)

    def test_roundtrip_byte_exact(self):
        from an_kla.sealed.cek import generate_cek

        runner = _reference_runner(self.key_file)
        cek = generate_cek()
        result = runner.wrap_cek(cek)
        self.assertEqual(result.op, "wrap")
        # wrapped_cek: b64 puro (64 B estructurales → 88 chars)
        self.assertEqual(len(result.wrapped_cek), 88)
        self.assertEqual(result.adapter_id, "tests.file-key-adapter.v1")
        recovered = runner.unwrap_cek(result.wrapped_cek)
        self.assertEqual(recovered.cek, cek)  # byte a byte

    def test_roundtrip_fixed_cek(self):
        cek = bytes(range(32))
        runner = _reference_runner(self.key_file)
        result = runner.wrap_cek(cek)
        self.assertEqual(runner.unwrap_cek(result.wrapped_cek).cek, cek)

    def test_two_wraps_differ_but_both_unwrap(self):
        """El blob varía por wrap (nonce) y ambos recuperan la CEK."""
        from an_kla.sealed.cek import generate_cek

        runner = _reference_runner(self.key_file)
        cek = generate_cek()
        w1 = runner.wrap_cek(cek).wrapped_cek
        w2 = runner.wrap_cek(cek).wrapped_cek
        self.assertNotEqual(w1, w2)
        self.assertEqual(runner.unwrap_cek(w1).cek, cek)
        self.assertEqual(runner.unwrap_cek(w2).cek, cek)

    def test_wrong_key_file_fails_closed(self):
        """unwrap con OTRA llave falla — sin oráculo, sin degradación."""
        from an_kla.sealed.cek import generate_cek

        runner = _reference_runner(self.key_file)
        wrapped = runner.wrap_cek(generate_cek()).wrapped_cek

        other_key = _write_key_file(Path(self._tmp.name))
        os.environ[ENV_KEY_FILE] = str(other_key)
        with self.assertRaises(SealingAdapterError):
            runner.unwrap_cek(wrapped)
        os.environ[ENV_KEY_FILE] = str(self.key_file)

    def test_roundtrip_works_without_cryptography(self):
        """El camino runner+adaptador de referencia es stdlib pura.

        Corre en el venv canónico SIN cryptography (el runner no toca el
        extra; el adaptador de referencia tampoco). Skip imposible: si
        cryptography está presente el test igual corre (no depende de él).
        """
        runner = _reference_runner(self.key_file)
        cek = os.urandom(32)
        result = runner.wrap_cek(cek)
        self.assertEqual(runner.unwrap_cek(result.wrapped_cek).cek, cek)

    def test_crypto_roundtrip_with_cryptography_cek(self):
        """CEK generada por T2 + roundtrip vía runner (si hay extra).

        Con CLT python3 (cryptography 46.x) ejecuta; en el venv sin
        extra, skip honesto (patrón T1/T2).
        """
        if not _cryptography_importable():
            self.skipTest("cryptography no instalada (patron T1/T2)")
        from an_kla.sealed.cek import generate_cek
        from an_kla.sealed.kdf import derive_subkeys

        cek = generate_cek()
        runner = _reference_runner(self.key_file)
        result = runner.wrap_cek(cek)
        recovered = runner.unwrap_cek(result.wrapped_cek).cek
        self.assertEqual(recovered, cek)
        # La CEK recuperada por el adaptador produce las mismas subclaves.
        self.assertEqual(derive_subkeys(recovered), derive_subkeys(cek))


# ---------------------------------------------------------------------------
# 2-5. Contrato JSON cerrado en la SALIDA del adaptador
# ---------------------------------------------------------------------------


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
