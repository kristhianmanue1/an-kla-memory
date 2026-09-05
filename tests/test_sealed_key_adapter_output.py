"""test_sealed_key_adapter_output.py — partición de tests/test_sealed_key_adapter.py por unidad bajo prueba (beta.22, issue #106).

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


class _OutputContractBase(unittest.TestCase):
    """Base: adaptador ad-hoc cuyo STDOUT controlamos al byte."""

    def _run_wrap(self, stdout_body: str, exit_code: int = 0):
        adapter = _AdHocAdapter(
            self,
            f"""
            import sys
            sys.stdin.read(65536)
            sys.stdout.write({stdout_body!r})
            sys.stdout.flush()
            raise SystemExit({exit_code})
            """,
        )
        runner = adapter.runner()
        return runner.wrap_cek(os.urandom(32))

    def _run_unwrap(self, stdout_body: str, exit_code: int = 0):
        adapter = _AdHocAdapter(
            self,
            f"""
            import sys
            sys.stdin.read(65536)
            sys.stdout.write({stdout_body!r})
            sys.stdout.flush()
            raise SystemExit({exit_code})
            """,
        )
        runner = adapter.runner()
        return runner.unwrap_cek("A" * 88)


class TestOutputContractClosed(_OutputContractBase):
    """Clave extra/ausente/tipo incorrecto → sealing_adapter_error."""

    def test_extra_key_in_wrap_output(self):
        with self.assertRaises(SealingAdapterError):
            self._run_wrap(
                '{"adapter_id":"a.b","wrapped_cek":"QUFB","extra":1}'
            )

    def test_missing_key_in_wrap_output(self):
        with self.assertRaises(SealingAdapterError):
            self._run_wrap('{"adapter_id":"a.b"}')

    def test_missing_adapter_id_in_wrap_output(self):
        with self.assertRaises(SealingAdapterError):
            self._run_wrap('{"wrapped_cek":"QUFB"}')

    def test_wrong_type_wrapped_cek(self):
        with self.assertRaises(SealingAdapterError):
            self._run_wrap('{"adapter_id":"a.b","wrapped_cek":123}')

    def test_wrong_type_adapter_id(self):
        with self.assertRaises(SealingAdapterError):
            self._run_wrap('{"adapter_id":42,"wrapped_cek":"QUFB"}')

    def test_unwrap_output_with_extra_key(self):
        with self.assertRaises(SealingAdapterError):
            self._run_unwrap('{"cek_b64":"AAAA","op":"x"}')

    def test_unwrap_output_missing_key(self):
        with self.assertRaises(SealingAdapterError):
            self._run_unwrap("{}")

    def test_unwrap_output_not_an_object(self):
        with self.assertRaises(SealingAdapterError):
            self._run_unwrap('[1,2,3]')

    def test_unwrap_output_wrong_type(self):
        with self.assertRaises(SealingAdapterError):
            self._run_unwrap('{"cek_b64":null}')

    def test_stdout_garbage_not_json(self):
        with self.assertRaises(SealingAdapterError):
            self._run_wrap("this is not json at all <<>>")

    def test_stdout_binary_garbage(self):
        with self.assertRaises(SealingAdapterError):
            self._run_wrap("\x00\x01\x02\xff\xfe")

    def test_stdout_valid_json_but_truncated(self):
        with self.assertRaises(SealingAdapterError):
            self._run_wrap('{"cek_b64": "AAAA"')


class TestCekLengthContract(unittest.TestCase):
    """CEK decodificada ≠ 32 bytes → sealing_adapter_error (ADR §4)."""

    def _unwrap_returning(self, raw: bytes):
        import json as _json

        body = _json.dumps({"cek_b64": base64.b64encode(raw).decode("ascii")})
        adapter = _AdHocAdapter(
            self,
            f"""
            import sys
            sys.stdin.read(65536)
            sys.stdout.write({body!r})
            """,
        )
        return adapter.runner().unwrap_cek("A" * 88)

    def test_cek_31_bytes_rejected(self):
        with self.assertRaises(SealingAdapterError):
            self._unwrap_returning(b"x" * 31)

    def test_cek_33_bytes_rejected(self):
        with self.assertRaises(SealingAdapterError):
            self._unwrap_returning(b"x" * 33)

    def test_cek_empty_rejected(self):
        with self.assertRaises(SealingAdapterError):
            self._unwrap_returning(b"")

    def test_cek_missing_padding_rejected(self):
        """b64 sin padding (43 chars, '=' final omitido): decodifica a 32 B
        pero NO es canónico (padding obligatorio) → error."""
        import json as _json

        body = _json.dumps({"cek_b64": "A" * 43})
        adapter = _AdHocAdapter(
            self,
            f"""
            import sys
            sys.stdin.read(65536)
            sys.stdout.write({body!r})
            """,
        )
        with self.assertRaises(SealingAdapterError):
            adapter.runner().unwrap_cek("A" * 88)

    def test_cek_extra_padding_rejected(self):
        """b64 con padding sobrante (46 chars) → no canónico → error."""
        import json as _json

        body = _json.dumps({"cek_b64": "A" * 45 + "="})
        adapter = _AdHocAdapter(
            self,
            f"""
            import sys
            sys.stdin.read(65536)
            sys.stdout.write({body!r})
            """,
        )
        with self.assertRaises(SealingAdapterError):
            adapter.runner().unwrap_cek("A" * 88)

    def test_cek_urlsafe_alphabet_rejected(self):
        """Alfabeto URL-safe ('-' en vez de '+') no es canónico → error."""
        import json as _json

        body = _json.dumps({"cek_b64": "A" * 42 + "-AAA="})
        adapter = _AdHocAdapter(
            self,
            f"""
            import sys
            sys.stdin.read(65536)
            sys.stdout.write({body!r})
            """,
        )
        with self.assertRaises(SealingAdapterError):
            adapter.runner().unwrap_cek("A" * 88)

    def test_cek_valid_32_bytes_accepted(self):
        result = self._unwrap_returning(b"x" * 32)
        self.assertEqual(result.cek, b"x" * 32)


# ---------------------------------------------------------------------------
# 3. Exit != 0 con JSON válido → sealing_adapter_error
# ---------------------------------------------------------------------------


class TestExitStatusSemantics(unittest.TestCase):
    def test_exit_nonzero_with_valid_json_is_error(self):
        """Exit ≠ 0 = error AUNQUE el JSON de stdout sea válido (ADR §4)."""
        adapter = _AdHocAdapter(
            self,
            """
            import sys
            sys.stdin.read(65536)
            sys.stdout.write('{"cek_b64": "'
                + __import__("base64").b64encode(b"x" * 32).decode() + '"}')
            sys.stdout.flush()
            raise SystemExit(3)
            """,
        )
        with self.assertRaises(SealingAdapterError):
            adapter.runner().unwrap_cek("A" * 88)

    def test_exit_zero_with_valid_json_succeeds(self):
        adapter = _AdHocAdapter(
            self,
            """
            import base64, sys
            sys.stdin.read(65536)
            sys.stdout.write('{"cek_b64": "'
                + base64.b64encode(b"y" * 32).decode() + '"}')
            sys.stdout.flush()
            """,
        )
        result = adapter.runner().unwrap_cek("A" * 88)
        self.assertEqual(result.cek, b"y" * 32)

    def test_crashing_adapter_is_error(self):
        """Crashea (exit por excepción) con stderr ruidoso → error cerrado."""
        adapter = _AdHocAdapter(
            self,
            f"""
            import sys
            sys.stdin.read(65536)
            sys.stderr.write("{STDERR_CANARY} crash boom\\n")
            raise RuntimeError("adapter exploded")
            """,
        )
        with self.assertRaises(SealingAdapterError) as ctx:
            adapter.runner().unwrap_cek("A" * 88)
        self.assertNotIn(STDERR_CANARY, str(ctx.exception))


# ---------------------------------------------------------------------------
# 6. Timeout → sealing_adapter_error + árbol terminado
# ---------------------------------------------------------------------------


class TestTimeout(unittest.TestCase):
    def test_sleeping_adapter_times_out(self):
        """Adaptador que duerme → timeout → error; sin proceso residual."""
        marker = Path(
            tempfile.mkdtemp(prefix="ankla-t3-timeout-")
        ) / "alive.txt"
        self.addCleanup(lambda: marker.parent.exists() and _rmtree(marker.parent))
        adapter = _AdHocAdapter(
            self,
            f"""
            import sys, time
            sys.stdin.read(65536)
            sys.stdout.write("")  # nada: solo dormir
            sys.stdout.flush()
            time.sleep(120)
            """,
        )
        runner = adapter.runner(timeout_seconds=2.0)
        start = time.monotonic()
        with self.assertRaises(SealingAdapterError) as ctx:
            runner.unwrap_cek("A" * 88)
        elapsed = time.monotonic() - start
        # Terminó por timeout (~2 s), no por el sueño de 120 s ni por el
        # timeout por defecto de 30 s.
        self.assertLess(elapsed, 20.0)
        self.assertIn("timed out", str(ctx.exception))
        self.assertEqual(ctx.exception.ERROR_CODE, "sealing_adapter_error")

    def test_default_timeout_is_30_seconds(self):
        """La constante del runner es el tope del ADR §4: 30 s."""
        self.assertEqual(ADAPTER_TIMEOUT_SECONDS, 30.0)

    def test_tree_termination_kills_children(self):
        """TERM al GRUPO mata también al hijo (árbol, no solo el padre)."""
        adapter = _AdHocAdapter(
            self,
            """
            import subprocess, sys, time
            # Hijo que sobrevive al padre y escribe en stdout (bloquea el
            # pipe abierto): la señal al GRUPO debe alcanzarlo.
            subprocess.Popen([sys.executable, "-c",
                "import time; time.sleep(120)"])
            sys.stdin.read(65536)
            time.sleep(120)
            """,
        )
        runner = adapter.runner(timeout_seconds=1.5)
        start = time.monotonic()
        with self.assertRaises(SealingAdapterError):
            runner.unwrap_cek("A" * 88)
        elapsed = time.monotonic() - start
        # Si el hijo bloqueara el pipe para siempre sin killpg, el join(5)
        # del lector retrasaría ~5 s y el wait colgaría. Margen holgado.
        self.assertLess(elapsed, 25.0)


def _rmtree(path):
    import shutil

    shutil.rmtree(path, ignore_errors=True)


# ---------------------------------------------------------------------------
# 7. Límites I/O incrementales
# ---------------------------------------------------------------------------


class TestIOLimits(unittest.TestCase):
    def _adapter_emitting(self, stdout_bytes: int, stderr_bytes: int):
        return _AdHocAdapter(
            self,
            f"""
            import sys
            sys.stdin.read(65536)
            chunk = b"A" * 4096
            emitted = 0
            out_target = {stdout_bytes}
            err_target = {stderr_bytes}
            while emitted < out_target:
                n = min(4096, out_target - emitted)
                sys.stdout.buffer.write(chunk[:n])
                sys.stdout.buffer.flush()
                emitted += n
            emitted = 0
            while emitted < err_target:
                n = min(4096, err_target - emitted)
                sys.stderr.buffer.write(chunk[:n])
                sys.stderr.buffer.flush()
                emitted += n
            """,
        )

    def test_stdout_above_limit_is_error(self):
        adapter = self._adapter_emitting(ADAPTER_STDOUT_LIMIT + 4096, 0)
        with self.assertRaises(SealingAdapterError) as ctx:
            adapter.runner(timeout_seconds=20.0).unwrap_cek("A" * 88)
        self.assertEqual(ctx.exception.ERROR_CODE, "sealing_adapter_error")

    def test_stderr_above_limit_is_error(self):
        """Exceder 8 KiB de stderr también corta (límite del ADR §4)."""
        adapter = self._adapter_emitting(0, ADAPTER_STDERR_LIMIT + 4096)
        with self.assertRaises(SealingAdapterError):
            adapter.runner(timeout_seconds=20.0).unwrap_cek("A" * 88)

    def test_stdout_just_under_limit_succeeds(self):
        """64 KiB - 1 byte: dentro del límite, JSON válido al final."""
        import base64

        payload = '{"cek_b64": "%s"}' % base64.b64encode(b"z" * 32).decode()
        pad = ADAPTER_STDOUT_LIMIT - len(payload) - 1
        adapter = _AdHocAdapter(
            self,
            f"""
            import sys
            sys.stdin.read(65536)
            sys.stdout.write(" " * {pad})
            sys.stdout.write({payload!r})
            sys.stdout.flush()
            """,
        )
        result = adapter.runner(timeout_seconds=20.0).unwrap_cek("A" * 88)
        self.assertEqual(result.cek, b"z" * 32)

    def test_verbose_stderr_within_limit_is_discarded(self):
        """stderr dentro del límite: se descarta y NO rompe el contrato."""
        adapter = _AdHocAdapter(
            self,
            f"""
            import base64, sys
            sys.stdin.read(65536)
            sys.stderr.write("{STDERR_CANARY} " + "n" * 1000 + "\\n")
            sys.stdout.write('{{"cek_b64": "'
                + base64.b64encode(b"w" * 32).decode() + '"}}')
            sys.stdout.flush()
            """,
        )
        result = adapter.runner(timeout_seconds=20.0).unwrap_cek("A" * 88)
        self.assertEqual(result.cek, b"w" * 32)

    def test_limits_match_adr(self):
        """Límites congelados del ADR §4: 8 KiB / 64 KiB / 8 KiB."""
        self.assertEqual(ka.ADAPTER_STDIN_LIMIT, 8 * 1024)
        self.assertEqual(ADAPTER_STDOUT_LIMIT, 64 * 1024)
        self.assertEqual(ADAPTER_STDERR_LIMIT, 8 * 1024)


# ---------------------------------------------------------------------------
# 8. stderr NUNCA propagado a mensajes del core
# ---------------------------------------------------------------------------


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
