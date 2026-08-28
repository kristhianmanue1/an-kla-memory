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


class TestStderrNeverPropagated(unittest.TestCase):
    def _stderr_canary_cases(self):
        return [
            ("exit-nonzero", "raise SystemExit(2)"),
            ("crash", "raise RuntimeError('boom')"),
            ("garbage", "import sys; sys.stdout.write('not-json')"),
        ]

    def test_stderr_canary_absent_from_all_error_messages(self):
        """El señuelo de stderr no aparece en NINGÚN mensaje de error."""
        for label, tail in self._stderr_canary_cases():
            with self.subTest(case=label):
                adapter = _AdHocAdapter(
                    self,
                    f"""
                    import sys
                    sys.stdin.read(65536)
                    sys.stderr.write("{STDERR_CANARY}\\n")
                    {tail}
                    """,
                )
                with self.assertRaises(SealingAdapterError) as ctx:
                    adapter.runner(timeout_seconds=15.0).unwrap_cek(
                        "A" * 88
                    )
                self.assertNotIn(STDERR_CANARY, str(ctx.exception))
                self.assertEqual(
                    ctx.exception.args[0],
                    "sealing key adapter failed (no further detail)",
                )

    def test_error_messages_are_closed_enum(self):
        """Los mensajes del runner son un conjunto cerrado, sin detalle."""
        allowed = {
            "sealing key adapter failed (no further detail)",
            "sealing key adapter timed out (no further detail)",
            "sealing key adapter exceeded i/o limits (no further detail)",
        }
        messages = {
            ka._ADAPTER_ERROR_MSG,
            ka._ADAPTER_TIMEOUT_MSG,
            ka._ADAPTER_IO_LIMIT_MSG,
        }
        self.assertLessEqual(messages, allowed)

    def test_reference_adapter_verbose_mode_clean(self):
        """Modo verbose del adaptador de referencia: contrato intacto."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        key_file = _write_key_file(Path(tmp.name))
        os.environ[ENV_KEY_FILE] = str(key_file)
        os.environ[ENV_VERBOSE] = "1"
        self.addCleanup(os.environ.pop, ENV_KEY_FILE, None)
        self.addCleanup(os.environ.pop, ENV_VERBOSE, None)
        runner = _reference_runner(key_file, env_allowlist=[ENV_KEY_FILE, ENV_VERBOSE])
        cek = os.urandom(32)
        wrapped = runner.wrap_cek(cek)
        self.assertEqual(runner.unwrap_cek(wrapped.wrapped_cek).cek, cek)


# ---------------------------------------------------------------------------
# 9. Entorno mínimo con allowlist (F3)
# ---------------------------------------------------------------------------


class TestEnvironmentAllowlist(unittest.TestCase):
    """Una NO-allowlisted NO llega; una allowlisted SÍ llega."""

    PARENT_SECRET = "ANKLA_T3_PARENT_SECRET"
    PARENT_ALLOWED = "ANKLA_T3_ALLOWED_TOKEN"
    CHILD_SEEN = "ANKLA_T3_CHILD_SAW"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.seen_path = Path(self._tmp.name) / "env_seen.json"

    def _env_probe_runner(self, env_allowlist):
        """Adaptador que vuelca su entorno a un ARCHIVO (el hecho observable
        fuera de stdio, porque stderr se descarta por diseño)."""
        target = str(self.seen_path)
        adapter = _AdHocAdapter(
            self,
            f"""
            import base64, json, os, sys
            sys.stdin.read(65536)
            raw = os.environ.get({self.PARENT_SECRET!r})
            raw2 = os.environ.get({self.PARENT_ALLOWED!r})
            with open({target!r}, "w") as fh:
                json.dump({{"secret_seen": raw is not None,
                            "allowed_seen": raw2 is not None,
                            "all_keys": sorted(os.environ)}}, fh)
            sys.stdout.write(json.dumps(
                {{"cek_b64": base64.b64encode(b"p" * 32).decode()}}))
            """,
        )
        return SealingAdapterRunner(
            adapter.argv, env_allowlist=env_allowlist, timeout_seconds=15.0
        )

    def test_parent_secret_does_not_reach_adapter(self):
        os.environ[self.PARENT_SECRET] = "super-secret-value-xyz"
        self.addCleanup(os.environ.pop, self.PARENT_SECRET, None)
        runner = self._env_probe_runner(env_allowlist=[])
        runner.unwrap_cek("A" * 88)
        seen = json.loads(self.seen_path.read_text())
        self.assertFalse(seen["secret_seen"])
        self.assertNotIn(self.PARENT_SECRET, seen["all_keys"])

    def test_allowlisted_variable_reaches_adapter(self):
        os.environ[self.PARENT_ALLOWED] = "allowed-value-123"
        os.environ[self.PARENT_SECRET] = "super-secret-value-xyz"
        self.addCleanup(os.environ.pop, self.PARENT_ALLOWED, None)
        self.addCleanup(os.environ.pop, self.PARENT_SECRET, None)
        runner = self._env_probe_runner(env_allowlist=[self.PARENT_ALLOWED])
        runner.unwrap_cek("A" * 88)
        seen = json.loads(self.seen_path.read_text())
        self.assertTrue(seen["allowed_seen"])
        # Y SOLO la allowlisted: la secreta sigue fuera.
        self.assertFalse(seen["secret_seen"])

    def test_no_allowlist_means_no_extra_vars(self):
        """Sin allowlist: sólo PATH/LANG/LC_ALL (mínimo del runner)."""
        os.environ[self.PARENT_SECRET] = "super-secret-value-xyz"
        os.environ[self.PARENT_ALLOWED] = "allowed-value-123"
        self.addCleanup(os.environ.pop, self.PARENT_SECRET, None)
        self.addCleanup(os.environ.pop, self.PARENT_ALLOWED, None)
        runner = self._env_probe_runner(env_allowlist=[])
        runner.unwrap_cek("A" * 88)
        seen = json.loads(self.seen_path.read_text())
        # Windows: el runner añade vars de runtime del SO (SystemRoot etc.)
        # para que el proceso hijo pueda inicializar — no son datos del host.
        platform_runtime = (
            {"SystemRoot", "SYSTEMROOT", "SystemDrive", "COMSPEC"}
            if os.name == "nt"
            else set()
        )
        self.assertLessEqual(
            set(seen["all_keys"]),
            {"PATH", "LANG", "LC_ALL", "TMPDIR", "HOME", "__CF_USER_TEXT_ENCODING"}
            | platform_runtime,
        )

    def test_allowlisted_missing_in_parent_is_absent(self):
        """Allowlisted que NO existe en el padre: no se crea de la nada."""
        runner = self._env_probe_runner(env_allowlist=["ANKLA_T3_NONEXISTENT"])
        runner.unwrap_cek("A" * 88)
        seen = json.loads(self.seen_path.read_text())
        self.assertNotIn("ANKLA_T3_NONEXISTENT", seen["all_keys"])

    def test_reference_adapter_requires_key_file_env(self):
        """El adaptador de referencia falla cerrado sin su env allowlisted.

        Sin env_allowlist, la variable no llega → error de contrato del
        adaptador → sealing_adapter_error en el core.
        """
        key_file = _write_key_file(Path(self._tmp.name))
        os.environ[ENV_KEY_FILE] = str(key_file)
        self.addCleanup(os.environ.pop, ENV_KEY_FILE, None)
        runner = SealingAdapterRunner(
            [sys.executable, str(REFERENCE_ADAPTER)], timeout_seconds=15.0
        )
        with self.assertRaises(SealingAdapterError):
            runner.wrap_cek(os.urandom(32))


# ---------------------------------------------------------------------------
# 10. sealing_adapter_required — borde caller
# ---------------------------------------------------------------------------


class TestAdapterRequired(unittest.TestCase):
    def test_none_command_raises_required(self):
        with self.assertRaises(SealingAdapterRequiredError):
            SealingAdapterRunner(None)

    def test_empty_list_raises_required(self):
        with self.assertRaises(SealingAdapterRequiredError):
            SealingAdapterRunner([])

    def test_string_command_rejected_not_shell(self):
        """Una línea de shell como string se RECHAZA: argv estructurado.

        Jamás ``sh -c``; aceptar una string sería invitar a interpolación.
        """
        with self.assertRaises(SealingAdapterRequiredError):
            SealingAdapterRunner("echo adapter")

    def test_non_string_elements_rejected(self):
        with self.assertRaises(SealingAdapterRequiredError):
            SealingAdapterRunner([sys.executable, 12345])

    def test_required_error_code_canonical(self):
        self.assertEqual(
            SealingAdapterRequiredError.ERROR_CODE, "sealing_adapter_required"
        )
        self.assertEqual(
            ka.SEALING_ADAPTER_REQUIRED_CODE, "sealing_adapter_required"
        )

    def test_nonexistent_executable_is_adapter_error(self):
        """Ejecutable inexistente: error del ADAPTADOR (se ejecutó el borde),
        no del caller — ADR §4: falla/crash → sealing_adapter_error."""
        runner = SealingAdapterRunner(
            ["/nonexistent/ankla-t3-adapter-binary"], timeout_seconds=10.0
        )
        with self.assertRaises(SealingAdapterError) as ctx:
            runner.wrap_cek(os.urandom(32))
        self.assertNotIn("/nonexistent", str(ctx.exception))


# ---------------------------------------------------------------------------
# 11. wrapped_cek opaco + pre-vuelo por schema
# ---------------------------------------------------------------------------


class TestWrappedCekOpacity(unittest.TestCase):
    def test_pre_flight_max_chars_enforced(self):
        self.assertEqual(ADAPTER_WRAPPED_CEK_MAX_CHARS, 4096)
        adapter = _AdHocAdapter(
            self,
            """
            import sys
            sys.stdin.read(65536)
            sys.stdout.write('{"cek_b64": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}')
            """,
        )
        runner = adapter.runner(timeout_seconds=10.0)
        # Entrada al unwrap mayor que el techo → error ANTES de ejecutar.
        too_long = "A" * (ADAPTER_WRAPPED_CEK_MAX_CHARS + 1)
        with self.assertRaises(SealingAdapterError):
            runner.unwrap_cek(too_long)

    def test_runner_does_not_interpret_blob(self):
        """El blob viaja tal cual; el adaptador decide su forma.

        Un adaptador ad-hoc acepta CUALQUIER blob opaco y devuelve CEK
        fija: el core no inspecciona el contenido del blob (solo techo).
        """
        adapter = _AdHocAdapter(
            self,
            """
            import base64, sys
            req = sys.stdin.read(65536)
            assert '"op": "unwrap"' in req or '"op":"unwrap"' in req
            sys.stdout.write('{"cek_b64": "'
                + base64.b64encode(b"k" * 32).decode() + '"}')
            """,
        )
        runner = adapter.runner(timeout_seconds=10.0)
        # b64 canónico de 32 bytes arbitrarios: canonicidad validada, pero
        # el CONTENIDO decodificado jamás se interpreta (opacidad intacta).
        import base64 as _b64

        opaque = _b64.b64encode(b"\x00\xffopaque-contents\xfe\x00" + b"Z" * 16).decode()
        result = runner.unwrap_cek(opaque)
        self.assertEqual(result.cek, b"k" * 32)

    def test_wrap_output_above_ceiling_rejected(self):
        adapter = _AdHocAdapter(
            self,
            """
            import sys
            sys.stdin.read(65536)
            sys.stdout.write('{"adapter_id": "a.b", "wrapped_cek": "'
                + "B" * 5000 + '"}')
            """,
        )
        with self.assertRaises(SealingAdapterError):
            adapter.runner(timeout_seconds=10.0).wrap_cek(os.urandom(32))

    def test_input_cek_must_be_32_bytes(self):
        """CEK de entrada con longitud errónea: ValueError de contrato del
        CALLER (pre-vuelo, sin ejecutar el adaptador)."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        key_file = _write_key_file(Path(tmp.name))
        runner = _reference_runner(key_file)
        with self.assertRaises(ValueError):
            runner.wrap_cek(b"short")
        with self.assertRaises(ValueError):
            runner.wrap_cek(b"x" * 33)
        with self.assertRaises(ValueError):
            runner.wrap_cek("not-bytes")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 12. Sin cryptography: import + independencia del flag
# ---------------------------------------------------------------------------


class TestNoCryptographyIndependence(unittest.TestCase):
    """El runner es stdlib pura: nada acopla a sealed_available."""

    def _run_blocked(self, code: str) -> subprocess.CompletedProcess:
        """Subproceso con cryptography BLOQUEADO vía meta-path."""
        blocker = textwrap.dedent(
            """
            import sys
            class _Block:
                def find_spec(self, name, path=None, target=None):
                    if name == 'cryptography' or name.startswith(
                            'cryptography.'):
                        raise ImportError('blocked for test')
                    return None
            sys.meta_path.insert(0, _Block())
            """
        )
        return subprocess.run(
            [sys.executable, "-c", blocker + textwrap.dedent(code)],
            capture_output=True,
            text=True,
            cwd=str(TESTS_DIR.parent),
        )

    def test_key_adapter_importable_without_extra(self):
        result = self._run_blocked(
            """
            import sys
            from an_kla.sealed import key_adapter
            assert 'cryptography' not in sys.modules
            assert key_adapter.SEALING_ADAPTER_ERROR_CODE == 'sealing_adapter_error'
            """
        )
        self.assertEqual(result.returncode, 0,
                         msg=f"stderr: {result.stderr}\nstdout: {result.stdout}")

    def test_runner_errors_independent_of_availability_flag(self):
        """Con sealed_available mentido a True y sin cryptography real,
        el runner sigue operando igual: el flag no acopla nada."""
        result = self._run_blocked(
            """
            import an_kla.sealed as s
            from an_kla.sealed import key_adapter
            s.sealed_available = True  # mentira deliberada (nota T1)
            r = key_adapter.SealingAdapterRunner(
                ['/nonexistent/ankla-t3-adapter'])
            try:
                r.wrap_cek(b'k' * 32)
            except key_adapter.SealingAdapterError:
                pass
            else:
                raise AssertionError('runner debio fallar cerrado')
            try:
                key_adapter.SealingAdapterRunner(None)
            except key_adapter.SealingAdapterRequiredError:
                pass
            else:
                raise AssertionError('required esperado')
            """
        )
        self.assertEqual(result.returncode, 0,
                         msg=f"stderr: {result.stderr}\nstdout: {result.stdout}")

    def test_sealed_package_importable_without_extra(self):
        """import an_kla.sealed (con el wiring T3) exit 0 sin cryptography."""
        result = self._run_blocked(
            """
            import sys
            import an_kla.sealed as s
            assert 'cryptography' not in sys.modules
            assert s.SEALING_ADAPTER_ERROR_CODE == 'sealing_adapter_error'
            assert s.SealingAdapterRunner is not None
            """
        )
        self.assertEqual(result.returncode, 0,
                         msg=f"stderr: {result.stderr}\nstdout: {result.stdout}")

    def test_no_cryptography_import_in_key_adapter(self):
        """grep estructural: key_adapter jamás importa cryptography."""
        source = ka.__file__
        text = Path(source).read_text(encoding="utf-8")
        self.assertNotIn("import cryptography", text)


# ---------------------------------------------------------------------------
# 13. Higiene: argv estructurado / sin shell
# ---------------------------------------------------------------------------


class TestNoShellExecution(unittest.TestCase):
    def test_no_shell_metacharacter_interpretation(self):
        """Metacaracteres de shell en un arg NO se interpretan JAMÁS.

        Si el runner usara shell, ``;`` ejecutaría el segundo comando y
        el archivo señuelo aparecería. Con argv estructurado, el archivo
        con nombre malicioso simplemente NO existe (OSError → error).
        """
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        canary = Path(tmp.name) / "canary.txt"
        evil = f"/usr/bin/touch;touch {canary}"
        runner = SealingAdapterRunner([evil], timeout_seconds=10.0)
        with self.assertRaises(SealingAdapterError):
            runner.wrap_cek(os.urandom(32))
        self.assertFalse(canary.exists())

    def test_arguments_passed_verbatim(self):
        """Args con espacios/comillas llegan ÍNTEGROS al adaptador."""
        magic = "arg with 'quotes' and $shell and \\backslash"
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        seen = Path(tmp.name) / "argv.json"
        adapter = _AdHocAdapter(
            self,
            f"""
            import base64, json, sys
            sys.stdin.read(65536)
            json.dump(sys.argv[1:], open({str(seen)!r}, "w"))
            sys.stdout.write(json.dumps(
                {{"cek_b64": base64.b64encode(b"p" * 32).decode()}}))
            """,
            argv_prefix=None,
        )
        runner = SealingAdapterRunner(
            [sys.executable, str(adapter.path), magic], timeout_seconds=10.0
        )
        runner.unwrap_cek("A" * 88)
        self.assertEqual(json.loads(seen.read_text()), [magic])

    def test_reference_adapter_documented_not_production(self):
        """El adaptador de referencia declara NO-producción en su fuente."""
        text = REFERENCE_ADAPTER.read_text(encoding="utf-8")
        self.assertIn("NO-producción".upper().replace("Ó", "O"), text.upper().replace("Ó", "O"))


# ---------------------------------------------------------------------------
# 14. adapter_id: gramática cerrada (ADR §6)
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
