"""test_sealed_key_adapter_errors.py — partición de tests/test_sealed_key_adapter.py por unidad bajo prueba (beta.22, issue #106).

Casos y aserciones sin cambios; el prelude (imports y helpers de módulo) se
copia del archivo de origen para mantener cada archivo autocontenido.
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


class TestAdapterIdGrammar(unittest.TestCase):
    def _wrap_returning_id(self, adapter_id):
        literal = json.dumps({"adapter_id": adapter_id, "wrapped_cek": "QUFB"})  # b64(b"AAA")
        adapter = _AdHocAdapter(
            self,
            f"""
            import sys
            sys.stdin.read(65536)
            sys.stdout.write({literal!r})
            """,
        )
        return adapter.runner(timeout_seconds=10.0).wrap_cek(os.urandom(32))

    def test_valid_ids_accepted(self):
        for adapter_id in ("a", "A", "tests.file-key-adapter.v1", "x" * 64,
                           "Kms-Prod_eu1.2"):
            with self.subTest(adapter_id=adapter_id):
                result = self._wrap_returning_id(adapter_id)
                self.assertEqual(result.adapter_id, adapter_id)

    def test_dot_and_dotdot_rejected(self):
        for adapter_id in (".", ".."):
            with self.subTest(adapter_id=adapter_id):
                with self.assertRaises(SealingAdapterError):
                    self._wrap_returning_id(adapter_id)

    def test_leading_punctuation_rejected(self):
        for adapter_id in ("-x", ".x", "_x", ".tests"):
            with self.subTest(adapter_id=adapter_id):
                with self.assertRaises(SealingAdapterError):
                    self._wrap_returning_id(adapter_id)

    def test_out_of_alphabet_rejected(self):
        for adapter_id in ("a/b", "a\\b", "a:b", "a b", "aé", "a\x00b"):
            with self.subTest(adapter_id=adapter_id):
                with self.assertRaises(SealingAdapterError):
                    self._wrap_returning_id(adapter_id)

    def test_too_long_rejected(self):
        with self.assertRaises(SealingAdapterError):
            self._wrap_returning_id("x" * 65)

    def test_empty_rejected(self):
        with self.assertRaises(SealingAdapterError):
            self._wrap_returning_id("")


# ---------------------------------------------------------------------------
# Superficie canónica de códigos (ADR §5)
# ---------------------------------------------------------------------------


class TestCanonicalErrorCodes(unittest.TestCase):
    def test_codes_exact(self):
        self.assertEqual(
            ka.SEALING_ADAPTER_ERROR_CODE, "sealing_adapter_error"
        )
        self.assertEqual(
            ka.SEALING_ADAPTER_REQUIRED_CODE, "sealing_adapter_required"
        )
        self.assertEqual(
            SealingAdapterError.ERROR_CODE, "sealing_adapter_error"
        )
        self.assertEqual(
            SealingAdapterRequiredError.ERROR_CODE,
            "sealing_adapter_required",
        )

    def test_exported_from_package(self):
        import an_kla.sealed as sealed

        self.assertEqual(sealed.SEALING_ADAPTER_ERROR_CODE,
                         "sealing_adapter_error")
        self.assertEqual(sealed.SEALING_ADAPTER_REQUIRED_CODE,
                         "sealing_adapter_required")



# ---------------------------------------------------------------------------
# Attempt 2 — sondas del adversarial (H1, H2, H3)
# ---------------------------------------------------------------------------


class TestSetsidEscapeeBoundedTimeout(unittest.TestCase):
    """H1: escapee setsid con stdout abierto NO retiene la invocación.

    Sonda del revisor: el adaptador spawnea un hijo que hace ``os.setsid()``
    (escapa del kill de grupo, F8) HEREDANDO stdout abierto y duerme; el
    padre también duerme. El timeout debe lanzarse en <= timeout + gracia
    (TERM 2 s + margen), NO cuando el escapee muera (300 s).
    """

    def test_escapee_does_not_block_timeout_error(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        adapter_path = Path(tmp.name) / "escapee.py"
        adapter_path.write_text(
            textwrap.dedent(
                """
                import os, subprocess, sys, time
                subprocess.Popen([sys.executable, "-c",
                    "import os, time; os.setsid(); time.sleep(300)"])
                sys.stdin.read(65536)
                time.sleep(300)
                """
            ),
            encoding="utf-8",
        )
        runner = SealingAdapterRunner(
            [sys.executable, str(adapter_path)], timeout_seconds=2.0
        )
        start = time.monotonic()
        with self.assertRaises(SealingAdapterError) as ctx:
            runner.wrap_cek(b"k" * 32)
        elapsed = time.monotonic() - start
        # timeout (2 s) + gracia TERM (2 s) + margen de scheduler (2 s):
        # si el escapee retuviera el pipe, esto sería >= 60 s.
        self.assertLessEqual(elapsed, 6.0)
        self.assertIn("timed out", str(ctx.exception))

    def test_escapee_with_parent_exiting_also_bounded(self):
        """Variante: el padre muere rápido y SOLO el escapee sostiene stdout."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        adapter_path = Path(tmp.name) / "escapee_exit.py"
        adapter_path.write_text(
            textwrap.dedent(
                """
                import os, subprocess, sys
                subprocess.Popen([sys.executable, "-c",
                    "import os, time; os.setsid(); time.sleep(300)"])
                sys.stdin.read(65536)
                # padre sale YA; el escapee mantiene stdout sin EOF
                """
            ),
            encoding="utf-8",
        )
        runner = SealingAdapterRunner(
            [sys.executable, str(adapter_path)], timeout_seconds=2.0
        )
        start = time.monotonic()
        with self.assertRaises(SealingAdapterError):
            runner.wrap_cek(b"k" * 32)
        elapsed = time.monotonic() - start
        self.assertLessEqual(elapsed, 6.0)


class TestPartialOverflowImmediateDetection(unittest.TestCase):
    """H2: exceso NO múltiplo de 4096 con pipe ABIERTO se detecta YA.

    El bug: ``read(4096)`` bloqueaba hasta llenar el buffer — 64 KiB+1
    emitidos con el pipe abierto solo se detectaba a los 30 s (timeout).
    Con ``os.read`` crudo, el primer bloque parcial que cruza el límite
    dispara la terminación inmediata (< 1 s).
    """

    def test_stdout_overflow_nonmultiple_detected_immediately(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        target = ADAPTER_STDOUT_LIMIT + 1  # 65537 — NO múltiplo de 4096
        adapter_path = Path(tmp.name) / "overflow.py"
        adapter_path.write_text(
            textwrap.dedent(
                f"""
                import sys, time
                sys.stdin.read(65536)
                emitted = 0
                while emitted < {target}:
                    n = min(1000, {target} - emitted)
                    sys.stdout.buffer.write(b"A" * n)
                    sys.stdout.buffer.flush()
                    emitted += n
                time.sleep(60)  # mantiene el pipe abierto: sin exit, sin EOF
                """
            ),
            encoding="utf-8",
        )
        runner = SealingAdapterRunner(
            [sys.executable, str(adapter_path)], timeout_seconds=30.0
        )
        start = time.monotonic()
        with self.assertRaises(SealingAdapterError) as ctx:
            runner.wrap_cek(b"k" * 32)
        elapsed = time.monotonic() - start
        # Inmediato: no espera el timeout de 30 s ni bloques de 4096.
        self.assertLess(elapsed, 1.0)
        self.assertIn("i/o limits", str(ctx.exception))

    def test_stderr_overflow_partial_detected_immediately(self):
        """Ídem para stderr: exceso parcial + pipe abierto → inmediato."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        target = ADAPTER_STDERR_LIMIT + 1
        adapter_path = Path(tmp.name) / "overflow_err.py"
        adapter_path.write_text(
            textwrap.dedent(
                f"""
                import sys, time
                sys.stdin.read(65536)
                emitted = 0
                while emitted < {target}:
                    n = min(1000, {target} - emitted)
                    sys.stderr.buffer.write(b"E" * n)
                    sys.stderr.buffer.flush()
                    emitted += n
                time.sleep(60)
                """
            ),
            encoding="utf-8",
        )
        runner = SealingAdapterRunner(
            [sys.executable, str(adapter_path)], timeout_seconds=30.0
        )
        start = time.monotonic()
        with self.assertRaises(SealingAdapterError):
            runner.wrap_cek(b"k" * 32)
        self.assertLess(time.monotonic() - start, 1.0)


class TestWrappedCekCanonicalB64(unittest.TestCase):
    """H3: wrapped_cek (salida de wrap y entrada de unwrap) es base64
    canónico — el ADR §4 lo congela para cek_b64 Y wrapped_cek. Validar
    canonicidad NO es interpretar el blob (sigue opaco en contenido).
    """

    def _wrap_returning_blob(self, wrapped_cek: object):
        import json as _json

        literal = _json.dumps({"adapter_id": "a.b", "wrapped_cek": wrapped_cek})
        adapter = _AdHocAdapter(
            self,
            f"""
            import sys
            sys.stdin.read(65536)
            sys.stdout.write({literal!r})
            """,
        )
        return adapter.runner(timeout_seconds=10.0).wrap_cek(b"k" * 32)

    def test_non_b64_blob_rejected(self):
        with self.assertRaises(SealingAdapterError):
            self._wrap_returning_blob("!!!not-base64!!!")

    def test_urlsafe_alphabet_blob_rejected(self):
        with self.assertRaises(SealingAdapterError):
            self._wrap_returning_blob("AA-AA")

    def test_missing_padding_blob_rejected(self):
        # b64(b"AAAA") = "QUFBQQ==" — sin el '==' final no decodifica
        # con validate=True (padding obligatorio): rechazado.
        with self.assertRaises(SealingAdapterError):
            self._wrap_returning_blob("QUFBQQ")

    def test_valid_canonical_blob_accepted(self):
        import base64 as _b64

        blob = _b64.b64encode(b"whatever-opaque-bytes" + b"\x00" * 42).decode()
        result = self._wrap_returning_blob(blob)
        self.assertEqual(result.wrapped_cek, blob)

    def test_unwrap_input_non_b64_rejected_before_exec(self):
        """Entrada de unwrap no-b64: contrato violado PRE-vuelo (sin
        ejecutar el adaptador — el comando es inexistente y NO se lanza
        el error de ejecución sino el de forma)."""
        runner = SealingAdapterRunner(
            ["/nonexistent/ankla-t3-probe"], timeout_seconds=10.0
        )
        with self.assertRaises(SealingAdapterError) as ctx:
            runner.unwrap_cek("this-is-not-base64-at-all")
        # Mensaje cerrado genérico (forma), no el de ejecución con ruta.
        self.assertNotIn("nonexistent", str(ctx.exception))

    def test_reference_adapter_blob_is_canonical_b64(self):
        """El adaptador de referencia produce wrapped_cek b64 puro."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        key_file = _write_key_file(Path(tmp.name))
        os.environ[ENV_KEY_FILE] = str(key_file)
        self.addCleanup(os.environ.pop, ENV_KEY_FILE, None)
        runner = _reference_runner(key_file)
        result = runner.wrap_cek(os.urandom(32))
        # Canónico: re-codifica byte a byte idéntico.
        import base64 as _b64

        raw = _b64.b64decode(result.wrapped_cek, validate=True)
        self.assertEqual(_b64.b64encode(raw).decode("ascii"),
                         result.wrapped_cek)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
